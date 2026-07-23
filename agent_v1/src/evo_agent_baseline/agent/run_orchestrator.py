"""evo-agent baseline 运行编排（spec §5.2）。

把一次建筑评估串成 spec §5.2 的 11 步流程：

    1. validate input building_id / world_id
    2. create ComplianceAssessmentRun
    3. hook pre_run_guard
    4. retrieve building fact subgraph
    5. retrieve candidate rule families/cards
    6. assemble FactPack + RuleSlice
    7. deterministic closure verifier
    8. if allow_stop=false: 只出闭包未完成说明
       else:               出辅助审查报告
    9. hook pre_output_guard
    10. persist run artifacts
    11. evaluator later reads artifacts and W2 truth to score（不在 baseline 内）

设计要点（spec §1.0 原则 1、5；§7.1）：
- allow_stop 只能由确定性闭包验证器输出，编排器与 LLM 都不能覆盖
  （spec §7.3.5 post_verifier_stop_gate）。
- 检索（retrieval）与闭包验证（closure）由其他子模块实现，本编排器只按
  spec 接口签名调用：
  * retrieval 产 FactPack + RuleSlice；
  * closure 入口 validate_building_closure(rule_slice, fact_pack, config)
    -> ClosureValidationResult。
- 编排器不读取任何 W2 参考真值；五个 hard hook 在各时点拦截 blind 违规。

依赖注入：retrieval / closure 通过构造参数注入（callable），便于单测用
mock/stub，也便于真实集成时换成 retrieval.pack_builder / closure.validator。

spec→code 单向：流程步骤与产物清单照 spec §5.2 / §6.8，不自创。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from evo_agent_baseline.contracts import (
    ClosureValidationResult,
    ComplianceAssessmentRun,
    FactPack,
    RuleSlice,
)

from evo_agent_baseline.agent.hooks import (
    OutputGuardError,
    SecurityError,
    post_retrieval_source_audit,
    post_verifier_stop_gate,
    pre_output_language_guard,
    pre_run_input_guard,
)
from evo_agent_baseline.agent.llm_client import report_contract_mode
from evo_agent_baseline.agent.report_writer import write_report

# v1 trace capture（spec v1 §3.6.2 + §5.6）。evo_mode=False 时不 import 实例化路径；
# 顶层 import 是为了类型注解 + 单测可直接 from … import TraceCapture。
from evo_agent_baseline.evo.trace_capture import TraceCapture


# retrieval 入口签名（spec §5.5 / §5.6：检索产 FactPack + RuleSlice）。
# 入参 (world_id, building_id, run_id) → 返回 (FactPack, RuleSlice)。
RetrievalFn = Callable[[str, str, str], Tuple[FactPack, RuleSlice]]

# closure 入口签名（spec §6.6：validate_building_closure(rule_slice, fact_pack,
# config) -> ClosureValidationResult）。
ClosureFn = Callable[[RuleSlice, FactPack, Any], ClosureValidationResult]


# ---------------------------------------------------------------------------
# identity-v5 现网键切换：run catalog 接线（closure §5.2）
# ---------------------------------------------------------------------------
# 切键后真 `validate_building_closure` 要 keyword-only 必填 `identity_blueprint_catalog`
# （Decimal 读径 scope-aware 蓝图全集）；旧三参 `closure_fn(rule_slice, fact_pack, config)`
# 调用点会 TypeError。编排器不改注入契约、不碰 `llm_orchestrator`：在 run() 入口把注入的
# closure_fn 透明包一层——真 closure（声明该 keyword）→ 每次调用前从固定权威 bundle 建 run
# catalog 注入；注入桩（3 参签名，test_agent_control / LLM / evo 测试用）→ 原样透传、零回归。


def _closure_fn_expects_catalog(closure_fn: Any) -> bool:
    """closure_fn 是否声明 **keyword-only 必填** `identity_blueprint_catalog`。

    真 `validate_building_closure`（现网键切换后）把它声明为 keyword-only 且无默认；单测注入的
    3 参桩 `f(rule_slice, fact_pack, config)` 不声明它。签名不可解析（Mock / 内建等）→ 视作桩
    （False），保守走旧三参路径。

    必须校验 `kind == KEYWORD_ONLY`（而非仅"参数名存在"）：否则三**位置**参桩
    `f(a, b, identity_blueprint_catalog)` 会被误判为真 closure，包装后既把 `config` 当第三位置参
    （落到 `identity_blueprint_catalog` 形参）又传 keyword `identity_blueprint_catalog=` → 同名双传
    TypeError。叠加"无默认"要求，进一步排除把它声明成 keyword-only **可选**的伪 closure。
    """
    try:
        params = inspect.signature(closure_fn).parameters
    except (TypeError, ValueError):
        return False
    p = params.get("identity_blueprint_catalog")
    if p is None:
        return False
    return (
        p.kind == inspect.Parameter.KEYWORD_ONLY
        and p.default is inspect.Parameter.empty
    )


def _wrap_closure_fn_with_catalog(closure_fn: ClosureFn) -> ClosureFn:
    """把真 closure 包成 3 参 `ClosureFn`：每次调用前从**固定权威 bundle 路径**建 run catalog
    （closure §5.2）注入 keyword。注入桩原样返回（`build_run_catalog` 不被触碰 → 桩路径零回归）。

    catalog 每次调用重建（确定性支线每 run 一次；LLM 支线若多次调闭包则各按当次
    rule_slice/fact_pack 精确投影）。meta 由 `fact_pack` 派生（run_id/world_id/building_id），
    与影子对账 `run_shadow_closure` / 合成 fixture `catalog_for_slice` 同源，绝不 fail-open。
    """
    if not _closure_fn_expects_catalog(closure_fn):
        return closure_fn

    from evo_agent_baseline.closure.identity_blueprint_catalog import build_run_catalog

    def _closure_with_run_catalog(
        rule_slice: RuleSlice, fact_pack: FactPack, config: Any
    ) -> ClosureValidationResult:
        meta = {
            "run_id": fact_pack.run_id,
            "world_id": fact_pack.world_id,
            "building_id": fact_pack.building_id,
        }
        catalog = build_run_catalog(rule_slice, fact_pack, meta)
        return closure_fn(
            rule_slice, fact_pack, config, identity_blueprint_catalog=catalog
        )

    return _closure_with_run_catalog


# ===========================================================================
# 一、工具
# ===========================================================================


def _utc_now_iso() -> str:
    """当前 UTC 时间 ISO8601 字符串（带 Z 后缀），用于 requested_at 等时间戳。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_run_id(world_id: str, building_id: str, requested_at: str) -> str:
    """合成 run_id：CAR-<timestamp>-<hash>（spec §5.1.1 注释）。

    hash 取 (world_id, building_id, requested_at) 的 sha256 前 8 位，
    时间戳用紧凑数字串，保证同一请求可读且足够唯一。
    """
    ts = requested_at.replace("-", "").replace(":", "").replace("Z", "")
    raw = f"{world_id}|{building_id}|{requested_at}"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
    return f"CAR-{ts}-{h}"


def _canonical_json(obj: Any) -> str:
    """canonical JSON 序列化——排序键 + 无多余空白，保证可复现持久化。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def _model_dump(obj: Any) -> Any:
    """pydantic 模型 → dict；非模型原样返回。"""
    dump = getattr(obj, "model_dump", None)
    return dump() if callable(dump) else obj


def _strip_acceptance_only_audit(run_audit: Dict[str, Any]) -> None:
    """run 终态降为非 LLM 接纳时，清掉两阶段 advisory 审计与接纳指纹（bug6）。

    内层 `run_llm_orchestration` 一旦接纳，就把两阶段 advisory
    （`status_escalation_warning`，`advisory_only=true`）并入
    `submission_audit_events`，并落 `accepted_via` / `accepted_payload_sha256`
    / `accepted_point_count`。若外层 `post_verifier_stop_gate` / 输出检查 /
    持久化随后失败、run 终态被降为非接纳，这些接纳态残留会破坏原子接纳不变量
    （`llm_narrative_accepted=False` 却仍带 advisory + 接纳指纹）。

    此处只移除 `advisory_only` 的 `status_escalation_warning` 事件（保留
    `response_text_synthesized_submission` / `status_authority_ambiguous` /
    deprecated-tool / format 等其它事件），并把三个接纳指纹字段归 `None`，
    与非接纳终态一致。仅在 llm_mode run_audit 上调用（这些键此时必已初始化）。
    """
    events = run_audit.get("submission_audit_events")
    if events:
        kept = [
            event
            for event in events
            if not (
                event.get("event") == "status_escalation_warning"
                and event.get("advisory_only")
            )
        ]
        if kept:
            run_audit["submission_audit_events"] = kept
        else:
            # 与"本就无审计事件"的 run 形状一致：整键移除而非留空列表。
            run_audit.pop("submission_audit_events", None)
    run_audit["accepted_via"] = None
    run_audit["accepted_payload_sha256"] = None
    run_audit["accepted_point_count"] = None


# ===========================================================================
# 二、编排器
# ===========================================================================


class RunOrchestrator:
    """一次 ComplianceAssessmentRun 的编排器（spec §5.2）。

    用法：
        orch = RunOrchestrator(
            retrieval_fn=...,           # 产 (FactPack, RuleSlice)
            closure_fn=...,            # validate_building_closure
            runs_root="runs",
            agent_version="baseline_agent_v0.4",
            verifier_version="baseline_closure_v0.3",
            rulecard_bundle_id="...",
            kg_snapshot_id="KGS-...",
        )
        run = orch.run(world_id="W-1", building_id="B-1")
    """

    def __init__(
        self,
        *,
        retrieval_fn: RetrievalFn,
        closure_fn: ClosureFn,
        runs_root: str = "runs",
        agent_version: str = "baseline_agent_v0.4",
        verifier_version: str = "baseline_closure_v0.3",
        rulecard_bundle_id: str = "rule_card_v2",
        kg_snapshot_id: str = "",
        verifier_config: Optional[Any] = None,
        llm_mode: bool = False,
        llm_client: Optional[Any] = None,
        kg_client: Optional[Any] = None,
        evo_mode: bool = False,
        evo_trace_capture: Optional[TraceCapture] = None,
        evo_active_skill_set_id: str = "",
        evo_active_skill_version_ids: Optional[List[str]] = None,
        evo_policy_version_id: str = "",
        evo_replay_buffer: Optional[Any] = None,
    ) -> None:
        """构造编排器。

        入参：
        - retrieval_fn —— 检索入口，签名 (world_id, building_id, run_id)
          -> (FactPack, RuleSlice)。真实集成时由 retrieval 子模块提供；
          单测用 mock。
        - closure_fn —— 闭包验证入口，签名 (rule_slice, fact_pack, config)
          -> ClosureValidationResult（spec §6.6 validate_building_closure）。
        - runs_root —— run artifacts 持久化根目录（spec §6.8）。
        - agent_version / verifier_version / rulecard_bundle_id /
          kg_snapshot_id —— 写入 ComplianceAssessmentRun 的元数据。
        - verifier_config —— 透传给 closure_fn 的配置对象；None 时传一个
          最小 dict（closure 子模块自有 VerifierConfig，本编排器不定义它）。
        - llm_mode —— True 时步骤 4-8 交由 `llm_orchestrator.run_llm_orchestration`
          驱动（LLM 通过 tool use 编排检索 / 闭包 / 报告生成）；False（默认）
          走 spec §5.2 deterministic 11 步。allow_stop 在两种模式下都由
          deterministic verifier 决定（spec §1.0 原则 1）。
        - llm_client —— llm_mode=True 时注入的 LLM 客户端；None 时构造默认
          （Ollama 本机 `http://127.0.0.1:11434/v1`）。
        - evo_mode —— True 时启用 spec v1 §5.6 trace capture：各阶段调
          `evo_trace_capture.capture_*`，结束 finalize 后（若有 replay buffer）
          写入。evo_mode=False（默认）跟 v0.4 baseline 行为完全一致。
        - evo_trace_capture —— 已构造的 `TraceCapture` 实例；缺省时本编排器
          在 run() 开始时按 run_id / world_id / building_id 自动构造。
        - evo_active_skill_set_id / evo_active_skill_version_ids /
          evo_policy_version_id —— 写入 EvoRunTrace 的版本元数据（spec v1
          §3.6.1 必填字段）；evo_mode=False 时忽略。
        - evo_replay_buffer —— 可选 ReplayBuffer 实例（F 代理负责），需暴露
          `add_trace(trace) -> bool`；缺省时 finalize 后仅返回 trace 不入库。
        """
        self._retrieval_fn = retrieval_fn
        self._closure_fn = closure_fn
        self._runs_root = Path(runs_root)
        self._agent_version = agent_version
        self._verifier_version = verifier_version
        self._llm_mode = llm_mode
        self._llm_client = llm_client
        self._kg_client = kg_client
        self._rulecard_bundle_id = rulecard_bundle_id
        self._kg_snapshot_id = kg_snapshot_id
        self._verifier_config = verifier_config
        # --- evo v1 hook 状态（spec v1 §5.6）---
        self._evo_mode = evo_mode
        self._evo_trace_capture = evo_trace_capture
        self._evo_active_skill_set_id = evo_active_skill_set_id
        self._evo_active_skill_version_ids = list(evo_active_skill_version_ids or [])
        self._evo_policy_version_id = evo_policy_version_id
        self._evo_replay_buffer = evo_replay_buffer
        # 最近一次 run() 完成后 finalize 的 EvoRunTrace；evo_mode=False 时为 None。
        # 提供给 smoke 脚本 / 集成测试直接拿来 assert。
        self.last_evo_trace: Optional[Any] = None
        self.last_evo_audit_findings: Dict[str, Any] = {}
        self.last_replay_buffer_accepted: Optional[bool] = None
        # 最近一次 run() 完成后的 closure_result + rule_slice + retrieval summary;
        # paired ablation 跑批用来拿 closure_summary + 调 evaluator 跟 W2 真值对比。
        self.last_closure_result: Optional[Any] = None
        self.last_rule_slice: Optional[Any] = None
        self.last_retrieval_summary: Optional[Dict[str, Any]] = None

    # -- 主流程 -----------------------------------------------------------

    def run(
        self,
        *,
        world_id: str,
        building_id: str,
        run_input: Optional[Dict[str, Any]] = None,
        persist: bool = True,
    ) -> ComplianceAssessmentRun:
        """执行 spec §5.2 第 1-10 步，返回最终 ComplianceAssessmentRun。

        入参：
        - world_id / building_id —— 待评估建筑标识。
        - run_input —— 用户原始请求 dict（可含 raw_request 等自由文本），
          用于 pre_run_input_guard；缺省时按 world_id/building_id 合成。
        - persist —— 是否落盘 run artifacts（spec §6.8）；单测可关。

        返回：ComplianceAssessmentRun，status 终态为 report_ready / blocked /
        failed 之一；artifacts 路径写入 closure_result_ref / report_ref。

        blind 违规（SecurityError）不抛出到调用方，而是转成 status=blocked +
        notes 记录，与 spec §6.5.2 stop_reason=forbidden_reference_truth_detected
        语义一致。
        """
        requested_at = _utc_now_iso()
        run_id = _make_run_id(world_id, building_id, requested_at)
        run_input = dict(run_input or {})
        run_input.setdefault("world_id", world_id)
        run_input.setdefault("building_id", building_id)

        # --- evo v1 trace capture：每次 run() 开始重置实例属性 ---
        # 调用方可以预先注入一个 TraceCapture；否则按 run_id 自动构造。
        # evo_mode=False 时全部跳过，self._evo_trace_capture 保持为 None。
        if self._evo_mode:
            if self._evo_trace_capture is None:
                self._evo_trace_capture = TraceCapture(
                    run_id=run_id, world_id=world_id, building_id=building_id
                )
            # 即使预注入了 TraceCapture 也覆盖一下 run_id/world/building（一致性）。
        self.last_evo_trace = None
        self.last_evo_audit_findings = {}
        self.last_replay_buffer_accepted = None
        self.last_closure_result = None
        self.last_rule_slice = None
        self.last_retrieval_summary = None

        # --- 步骤 1 + 3：输入校验 + pre_run_input_guard（hard hook）---
        # spec §5.2 步骤 1 的 building_id/world_id 校验由 pre_run_input_guard
        # 内含（缺字段抛 ValueError）。
        try:
            input_guard_result = pre_run_input_guard(run_input)
        except (ValueError, SecurityError) as exc:
            # 输入阶段即违规 —— 不建正式 run，返回一个 blocked 占位 run。
            return self._make_blocked_run(
                run_id=run_id,
                world_id=world_id,
                building_id=building_id,
                requested_at=requested_at,
                status="blocked" if isinstance(exc, SecurityError) else "failed",
                input_guard_result={
                    "guard": "pre_run_input_guard",
                    "passed": False,
                    "error": str(exc),
                },
                note=f"pre_run_input_guard 拦截：{exc}",
            )

        # --- 步骤 2：create ComplianceAssessmentRun ---
        run = ComplianceAssessmentRun(
            run_id=run_id,
            run_type="baseline_building_review",
            world_id=world_id,
            building_id=building_id,
            requested_at=requested_at,
            status="created",
            kg_snapshot_id=self._kg_snapshot_id,
            agent_version=self._agent_version,
            verifier_version=self._verifier_version,
            rulecard_bundle_id=self._rulecard_bundle_id,
            input_guard_result=input_guard_result,
        )

        # evo trace：记录 input_guard 阶段
        if self._evo_mode and self._evo_trace_capture is not None:
            try:
                self._evo_trace_capture.capture_input_guard(input_guard_result)
            except Exception:  # noqa: BLE001 - trace capture 不影响主流程
                pass

        # run_audit 累积器（spec §8.2：run_audit.json 是 agent output 之一）。
        # 契约版本与产物形状成对：LLM 支线走 v2 程序骨架；确定性地板档仍走
        # v1 write_report 模板，必须标 v1，防跨版本混算。
        run_audit: Dict[str, Any] = {
            "run_id": run_id,
            "world_id": world_id,
            "building_id": building_id,
            "agent_version": self._agent_version,
            "verifier_version": self._verifier_version,
            # LLM 档初始版本按活动契约冻结（LLM 中途失败时审计不被误标 3）；
            # llm_result 出来后仍会回填（下方），二者按同一模式推导、恒一致。
            "report_contract_version": (
                (4 if report_contract_mode() == "v4" else 3) if self._llm_mode else 1
            ),
            "hook_results": [input_guard_result],
            "forbidden_sources_loaded": [],
            "status_trace": ["created"],
        }
        llm_state_holder: List[Any] = []
        if self._llm_mode:
            run_audit.update({
                "llm_narrative_accepted": False,
                "llm_narrative_attempts": 0,
                "llm_narrative_rejection_codes": [],
                "narrative_fallback_reason": None,
                "submission_format_attempts": 0,
                "submission_format_repairs_used": 0,
                "submission_format_events": [],
                "accepted_via": None,
                "accepted_point_count": None,
                "accepted_payload_sha256": None,
            })

        def _record_orchestrator_exception_narrative_audit() -> None:
            if not self._llm_mode:
                return
            state = llm_state_holder[-1] if llm_state_holder else None
            run_audit["llm_narrative_accepted"] = False
            run_audit["llm_narrative_attempts"] = int(
                getattr(state, "narrative_attempts", 0)
            )
            run_audit["llm_narrative_rejection_codes"] = list(
                getattr(state, "narrative_rejection_codes", [])
            )
            run_audit["narrative_fallback_reason"] = "orchestrator_exception"
            run_audit["submission_format_attempts"] = int(
                getattr(state, "submission_format_attempts", 0)
            )
            run_audit["submission_format_repairs_used"] = int(
                getattr(state, "submission_format_repairs_used", 0)
            )
            run_audit["submission_format_events"] = list(
                getattr(state, "submission_format_events", [])
            )
            # 原子接纳（bug6）：编排层异常收尾把 run 降为非接纳，必须同步清掉内层
            # 已并入的 advisory 审计与接纳指纹——否则 llm_narrative_accepted=False
            # 却残留 status_escalation_warning + accepted_via/sha，违反原子接纳。
            # 不能沿用 state.accepted_* 回填（那正是内层接纳留下的接纳态）。
            _strip_acceptance_only_audit(run_audit)

        try:
            # ---- 准备共享的 VerifierConfig（两种模式共用）----
            if self._verifier_config is not None:
                config = self._verifier_config
            else:
                from evo_agent_baseline.closure.schema import VerifierConfig
                config = VerifierConfig(
                    verifier_version=self._verifier_version,
                    guard_result=input_guard_result,
                )

            # ---- run catalog 接线（identity-v5 现网键切换，closure §5.2）----
            # 真 closure（要 keyword-only identity_blueprint_catalog）→ 透明包一层，每次调用
            # 前从固定权威 bundle 建 run catalog 注入；注入桩 → 原样透传（桩路径零回归）。
            # 确定性支线与 LLM 支线共用同一 3 参可调用体，`llm_orchestrator` 不受影响。
            closure_fn = _wrap_closure_fn_with_catalog(self._closure_fn)

            if self._llm_mode:
                # ---- LLM-as-brain：tool use 编排（spec §7）----
                # 但 deterministic backbone 不被 LLM 覆盖（spec §1.0 原则 1）：
                # allow_stop / closure 状态仍由 closure_fn 决定，LLM 只编排顺序
                # + 写自然语言报告。
                from evo_agent_baseline.agent.llm_orchestrator import (
                    run_llm_orchestration,
                )

                run.status = "llm_orchestrating"
                run_audit["status_trace"].append("llm_orchestrating")
                llm_result = run_llm_orchestration(
                    world_id=world_id,
                    building_id=building_id,
                    run_id=run_id,
                    retrieval_fn=self._retrieval_fn,
                    closure_fn=closure_fn,
                    llm_client=self._llm_client,
                    kg_client=self._kg_client,
                    verifier_config=config,
                    # 溯源元数据下传：确定性兜底模板与 write_report 路径产出同名
                    # 报告文件，资料范围 / 切片节必须同样完整（工单裁定 8）。
                    kg_snapshot_id=self._kg_snapshot_id,
                    rulecard_bundle_id=self._rulecard_bundle_id,
                    state_observer=llm_state_holder.append,
                )
                fact_pack = llm_result.state.fact_pack
                rule_slice = llm_result.state.rule_slice
                closure_result = llm_result.state.closure_result
                self._validate_retrieval_types(fact_pack, rule_slice)
                self._validate_closure_type(closure_result)
                run.retrieval_summary = self._summarize_retrieval(
                    fact_pack, rule_slice
                )
                # 暴露给 smoke / paired ablation 脚本——拿 closure_summary + 跑 evaluator
                self.last_closure_result = closure_result
                self.last_rule_slice = rule_slice
                self.last_retrieval_summary = run.retrieval_summary

                # 二次过 source audit（LLM orchestrator 已过一次，RunOrchestrator
                # 这里再过一次是双保险，hook 幂等）。
                audit_result = post_retrieval_source_audit(fact_pack, rule_slice)
                run_audit["hook_results"].append(audit_result)
                run_audit["forbidden_sources_loaded"] = audit_result.get(
                    "forbidden_sources_loaded", []
                )

                # --- evo trace：retrieval 阶段（spec v1 §5.6，LLM 路径对齐 deterministic 路径）---
                if self._evo_mode and self._evo_trace_capture is not None:
                    try:
                        self._evo_trace_capture.capture_retrieval(
                            fact_pack=fact_pack,
                            rule_slice=rule_slice,
                            candidate_universe=None,
                        )
                    except Exception:
                        pass
                run_audit["llm_turns"] = [
                    {
                        "iteration": t.iteration,
                        "response_chars": len(t.response_text),
                        "tool_call_count": len(t.tool_calls),
                        "finish_reason": t.finish_reason,
                        "prompt_tokens": t.prompt_tokens,
                        "completion_tokens": t.completion_tokens,
                    }
                    for t in llm_result.state.turns
                ]
                run_audit["llm_tool_log"] = llm_result.state.tool_log
                # llm_forced_finalize 保持原义（契约 v2 修订 5）：LLM 未在轮内
                # 调用提交工具（submit_analysis / finalize_report 别名视同）。
                # 不复用它表示叙述未过闸——那由下方四个叙述审计字段表达。
                run_audit["llm_forced_finalize"] = llm_result.forced_finalize
                run_audit["llm_iterations_used"] = llm_result.iterations_used
                run_audit["llm_tool_call_count"] = llm_result.tool_call_count
                # --- 报告契约 v2 叙述审计四新字段（契约 v2 修订 5）---
                run_audit["llm_narrative_accepted"] = (
                    llm_result.llm_narrative_accepted
                )
                run_audit["llm_narrative_attempts"] = (
                    llm_result.llm_narrative_attempts
                )
                run_audit["llm_narrative_rejection_codes"] = list(
                    llm_result.llm_narrative_rejection_codes
                )
                run_audit["narrative_fallback_reason"] = (
                    llm_result.narrative_fallback_reason
                )
                run_audit["submission_format_attempts"] = (
                    llm_result.submission_format_attempts
                )
                run_audit["submission_format_repairs_used"] = (
                    llm_result.submission_format_repairs_used
                )
                run_audit["submission_format_events"] = list(
                    llm_result.submission_format_events
                )
                run_audit["accepted_via"] = llm_result.accepted_via
                # 版本从 llm_result 回填（copilot 审出#3：原 run_audit 固定 3）。
                run_audit["report_contract_version"] = (
                    llm_result.report_contract_version
                )
                run_audit["accepted_point_count"] = (
                    llm_result.accepted_point_count
                )
                run_audit["accepted_payload_sha256"] = (
                    llm_result.accepted_payload_sha256
                )
                # 别名→真实 ID 单向映射落审计（契约 v2 修订 3）。
                if llm_result.state.evidence_pack is not None:
                    run_audit["narrative_alias_map"] = dict(
                        llm_result.state.evidence_pack.alias_map
                    )
                # 迁移期 finalize_report 别名命中的 deprecated-tool 审计事件
                # （契约 v2 兼容与迁移 3，便于统计并最终移除别名）。
                if llm_result.state.deprecated_tool_events:
                    run_audit["deprecated_tool_events"] = list(
                        llm_result.state.deprecated_tool_events
                    )
                if llm_result.state.submission_audit_events:
                    run_audit["submission_audit_events"] = list(
                        llm_result.state.submission_audit_events
                    )
                # 零计数断言闸 WARN（工单裁定 5：命中只记警告字段不拒绝）
                if llm_result.state.false_zero_count_warnings:
                    run_audit["false_zero_count_warnings"] = list(
                        llm_result.state.false_zero_count_warnings
                    )

                # allow_stop / stop_gate 仍由 deterministic 决定。
                stop_gate = post_verifier_stop_gate(closure_result)
                run_audit["hook_results"].append(stop_gate)
                run.allow_stop = stop_gate["allow_stop"]

                # --- evo trace：closure 阶段（LLM 路径对齐 deterministic 路径）---
                if self._evo_mode and self._evo_trace_capture is not None:
                    try:
                        self._evo_trace_capture.capture_closure(closure_result)
                    except Exception:
                        pass

                # --- 报告（契约 v2）---
                # v1 的三分支（deterministic_fallback / llm_authored /
                # output_guard_rejected 退化 write_report）已随契约 v2 收敛为
                # 单一组合终稿：程序骨架 + 已接纳的模型分析或确定性叙述模板，
                # 组合与守卫都在 run_llm_orchestration 内完成。文件名不再带
                # llm_ 前缀（成品不再由 LLM 整篇生成）；旧 fallback_reason 字段
                # 不再对 v2 run 写入（保持 v1 历史可读，叙述路径由
                # narrative_fallback_reason 表达）。
                report = {
                    "filename": (
                        "auxiliary_review_report.md"
                        if run.allow_stop
                        else "incomplete_closure_notice.md"
                    ),
                    "content": llm_result.report_markdown,
                    "kind": ("contract_v4_composed"
                             if llm_result.report_contract_version == 4
                             else "contract_v3_composed"),
                }
                if llm_result.state.llm_raw_response is not None:
                    # 未被接纳的最后一版叙述候选留痕（llm_raw_response.md）。
                    report["llm_raw_response"] = llm_result.state.llm_raw_response
                if llm_result.state.submission_format_rejected_raw_attempts:
                    # 格式失败原始载荷只落本地验尸文件；不进入模型回执，也不视为接纳内容。
                    report["submission_format_rejected_raw_attempts"] = list(
                        llm_result.state.submission_format_rejected_raw_attempts
                    )
                if llm_result.state.accepted_payload is not None:
                    # 接纳载荷审计产物（DEBT-054 观测补全）：规范化 {points:[...]}
                    # + sha 对账；用于离线回放的精确回放组身份锚。
                    report["accepted_payload"] = {
                        "payload": llm_result.state.accepted_payload,
                        "accepted_payload_sha256": (
                            llm_result.state.accepted_payload_sha256
                        ),
                    }

                # 复用内层组合守卫的权威结果（复审修正 P4）：内层已按"骨架
                # 默认白名单 + 模型槽位叙述前缀"拆半校验，外层若按默认语境
                # 整稿复检，会把叙述节合法豁免（如"尚未结案"）二次拒杀、
                # 拖垮整个 run。仅在结果缺失时才回退整稿复检。
                output_guard = getattr(
                    llm_result.state, "composed_guard_audit", None
                )
                if output_guard is None:
                    output_guard = pre_output_language_guard(report["content"])
                run_audit["hook_results"].append(output_guard)
            else:
                # ---- deterministic 11 步主流程（spec §5.2）----
                # --- 步骤 4 + 5 + 6：检索 + 组装 FactPack / RuleSlice ---
                run.status = "retrieving_facts"
                run_audit["status_trace"].append("retrieving_facts")
                fact_pack, rule_slice = self._retrieval_fn(
                    world_id, building_id, run_id
                )
                run.status = "retrieving_rules"
                run_audit["status_trace"].append("retrieving_rules")
                self._validate_retrieval_types(fact_pack, rule_slice)
                run.retrieval_summary = self._summarize_retrieval(
                    fact_pack, rule_slice
                )

                # --- post_retrieval_source_audit（hard hook）---
                audit_result = post_retrieval_source_audit(fact_pack, rule_slice)
                run_audit["hook_results"].append(audit_result)
                run_audit["forbidden_sources_loaded"] = audit_result.get(
                    "forbidden_sources_loaded", []
                )

                # --- evo trace：retrieval 阶段（spec v1 §5.6）---
                if self._evo_mode and self._evo_trace_capture is not None:
                    try:
                        self._evo_trace_capture.capture_retrieval(
                            fact_pack=fact_pack,
                            rule_slice=rule_slice,
                            candidate_universe=None,  # 默认用 rule_slice 的 rule_card ids
                        )
                    except Exception:
                        pass

                # --- 步骤 7：deterministic closure verifier ---
                run.status = "verifying_closure"
                run_audit["status_trace"].append("verifying_closure")
                closure_result = closure_fn(rule_slice, fact_pack, config)
                self._validate_closure_type(closure_result)
                # 暴露给 smoke / paired ablation 脚本——拿 closure_summary + 跑 evaluator
                self.last_closure_result = closure_result
                self.last_rule_slice = rule_slice
                self.last_retrieval_summary = run.retrieval_summary

                # --- post_verifier_stop_gate（hard hook）---
                stop_gate = post_verifier_stop_gate(closure_result)
                run_audit["hook_results"].append(stop_gate)
                run.allow_stop = stop_gate["allow_stop"]

                # --- evo trace：closure 阶段（任务原则 3：仅读不改 allow_stop）---
                if self._evo_mode and self._evo_trace_capture is not None:
                    try:
                        self._evo_trace_capture.capture_closure(closure_result)
                    except Exception:
                        pass

                # --- 步骤 8：按 allow_stop 出报告 ---
                report = write_report(
                    closure_result,
                    kg_snapshot_id=self._kg_snapshot_id,
                    rulecard_bundle_id=self._rulecard_bundle_id,
                    fact_source_tables=list(fact_pack.source_tables),
                    rule_families=self._rule_family_rows(rule_slice),
                )

                # --- 步骤 9：pre_output_language_guard（hard hook）---
                output_guard = pre_output_language_guard(report["content"])
                run_audit["hook_results"].append(output_guard)

            # --- 步骤 10：persist run artifacts（spec §6.8）---
            run.closure_result_ref = f"runs/{run_id}/closure_validation_result.json"
            run.report_ref = f"runs/{run_id}/{report['filename']}"
            run.status = "report_ready"
            run.completed_at = _utc_now_iso()
            run_audit["status_trace"].append("report_ready")
            run_audit["allow_stop"] = run.allow_stop
            run_audit["report_filename"] = report["filename"]

            # --- identity-v5 §7 原子版本传播 ---
            # ① 8 身份字段从 closure 的 machine_report.run_audit 透传进落盘 run_audit.json（真闭包
            #    必有；测试桩返回的 ClosureValidationResult 无该块则跳过，零回归）。
            # ② 会话载体抄录 obligation_identity_schema（旧产物 / 未过闭包=None 按 v1 只读；新 run 写
            #    v5），供 replay/eval 按身份 schema 分区。
            _mrr = getattr(closure_result, "machine_readable_report", None)
            _closure_run_audit = _mrr.get("run_audit") if isinstance(_mrr, dict) else None
            if isinstance(_closure_run_audit, dict):
                run_audit["identity_run_audit"] = dict(_closure_run_audit)
            run.obligation_identity_schema = getattr(
                closure_result.obligation_set, "obligation_identity_schema", None
            )

            if persist:
                self._persist_artifacts(
                    run=run,
                    fact_pack=fact_pack,
                    rule_slice=rule_slice,
                    closure_result=closure_result,
                    report=report,
                    run_audit=run_audit,
                )

            # --- evo trace finalize（spec v1 §3.6.1 + §9.2）---
            # 主成功路径 finalize（确定性 + LLM 路径同走）。
            # LLM 路径已在上方补齐 capture_retrieval + capture_closure，进 finalize
            # 时 tool_call_count / iterations 从 run_audit 取（默认值兜底）。
            if (
                self._evo_mode
                and self._evo_trace_capture is not None
            ):
                try:
                    # 先 capture_report + capture_hooks 收尾
                    if run.report_ref:
                        self._evo_trace_capture.capture_report(run.report_ref)
                    self._evo_trace_capture.capture_hooks(run_audit["hook_results"])

                    # tool_call_count：deterministic 模式按主流程固定 2 次（retrieval
                    # + closure）；spec v1 §3.6.1 这是统计字段，不要求精确还原 LLM
                    # 工具计数（llm_mode 由 E 代理处理）。
                    tool_call_count = run_audit.get("llm_tool_call_count", 2)
                    llm_iters = run_audit.get("llm_iterations_used", 0)

                    trace = self._evo_trace_capture.finalize(
                        active_skill_set_id=self._evo_active_skill_set_id
                        or "SS-baseline-empty",
                        active_skill_version_ids=self._evo_active_skill_version_ids,
                        evo_policy_version_id=self._evo_policy_version_id
                        or "policy.baseline.empty.v0",
                        agent_version=self._agent_version,
                        verifier_version=self._verifier_version,
                        kg_snapshot_id=self._kg_snapshot_id,
                        rulecard_bundle_id=self._rulecard_bundle_id,
                        tool_call_count=tool_call_count,
                        llm_iterations_used=llm_iters,
                        cost={"wall_ms": 0, "tool_calls": tool_call_count},
                        # EvoRunTrace 无通用 metadata/audit dict 且 extra=forbid；
                        # 不改 v1 DTO，只把 v2 叙述兜底信号映射到既有字段。
                        fallback_reason=(
                            run_audit.get("narrative_fallback_reason")
                            or run_audit.get("fallback_reason")
                        ),
                    )
                    self.last_evo_trace = trace
                    self.last_evo_audit_findings = (
                        self._evo_trace_capture.audit_findings
                    )

                    # 落 trace 文件到 runs/<run_id>/evo_run_trace.json，便于
                    # smoke / 集成测试断言（spec v1 §3.6.1 trace artifact）。
                    if persist:
                        run_dir = self._runs_root / run_id
                        run_dir.mkdir(parents=True, exist_ok=True)
                        (run_dir / "evo_run_trace.json").write_text(
                            _canonical_json(trace.model_dump()), encoding="utf-8"
                        )

                    # 写 ReplayBuffer（spec v1 §9.2）：forbidden_scan + 三 audit
                    # 全 pass 才入库。
                    if (
                        self._evo_replay_buffer is not None
                        and trace.forbidden_scan_passed
                        and trace.source_visibility_audit_passed
                        and trace.schema_audit_passed
                        and trace.candidate_floor_passed
                    ):
                        try:
                            accepted = self._evo_replay_buffer.add_trace(trace)
                            self.last_replay_buffer_accepted = bool(accepted)
                        except Exception:  # noqa: BLE001
                            self.last_replay_buffer_accepted = False
                    else:
                        # 任一 audit fail → spec v1 §9.2 拒收
                        self.last_replay_buffer_accepted = False
                except Exception as trace_exc:  # noqa: BLE001
                    # trace 失败不影响主 run 状态（任务原则 3）
                    run.notes.append(f"evo_trace_capture_error: {trace_exc}")
                    self.last_evo_trace = None
                    self.last_replay_buffer_accepted = False

            return run

        except SecurityError as exc:
            # blind 红线违规 —— run blocked，语义对齐 stop_reason
            # forbidden_reference_truth_detected（spec §6.5.2）。
            run.status = "blocked"
            run.completed_at = _utc_now_iso()
            run.notes.append(f"forbidden_reference_truth_detected: {exc}")
            run_audit["status_trace"].append("blocked")
            run_audit["blocked_reason"] = "forbidden_reference_truth_detected"
            run_audit["error"] = str(exc)
            _record_orchestrator_exception_narrative_audit()
            if persist:
                self._persist_failure(run, run_audit)
            return run

        except OutputGuardError as exc:
            # 输出含禁止话术 —— 报告生成阶段失败；run failed。
            run.status = "failed"
            run.completed_at = _utc_now_iso()
            run.notes.append(f"output_blocked_forbidden_phrase: {exc}")
            run_audit["status_trace"].append("failed")
            run_audit["error"] = str(exc)
            _record_orchestrator_exception_narrative_audit()
            if persist:
                self._persist_failure(run, run_audit)
            return run

        except Exception as exc:  # noqa: BLE001 - 编排层兜底
            run.status = "failed"
            run.completed_at = _utc_now_iso()
            run.notes.append(f"orchestrator_internal_error: {exc}")
            run_audit["status_trace"].append("failed")
            run_audit["error"] = str(exc)
            _record_orchestrator_exception_narrative_audit()
            if persist:
                self._persist_failure(run, run_audit)
            return run

    # -- 校验 -------------------------------------------------------------

    @staticmethod
    def _validate_retrieval_types(fact_pack: Any, rule_slice: Any) -> None:
        """检索返回值类型校验——必须是 FactPack / RuleSlice（spec §5.5 / §5.6）。"""
        if not isinstance(fact_pack, FactPack):
            raise TypeError(
                f"retrieval_fn 必须返回 FactPack，实得 {type(fact_pack).__name__}"
            )
        if not isinstance(rule_slice, RuleSlice):
            raise TypeError(
                f"retrieval_fn 必须返回 RuleSlice，实得 {type(rule_slice).__name__}"
            )

    @staticmethod
    def _validate_closure_type(closure_result: Any) -> None:
        """闭包返回值类型校验——必须是 ClosureValidationResult（spec §6.2.5）。"""
        if not isinstance(closure_result, ClosureValidationResult):
            raise TypeError(
                "closure_fn 必须返回 ClosureValidationResult，"
                f"实得 {type(closure_result).__name__}"
            )

    # -- 摘要 -------------------------------------------------------------

    @staticmethod
    def _summarize_retrieval(
        fact_pack: FactPack, rule_slice: RuleSlice
    ) -> Dict[str, Any]:
        """组装 ComplianceAssessmentRun.retrieval_summary。"""
        return {
            "fact_count": len(fact_pack.facts),
            "fact_source_tables": list(fact_pack.source_tables),
            "candidate_rule_card_count": len(rule_slice.candidate_rule_cards),
            "rule_family_count": len(rule_slice.rule_families),
            "source_quote_count": len(rule_slice.source_quotes),
        }

    @staticmethod
    def _rule_family_rows(rule_slice: RuleSlice) -> List[Dict[str, Any]]:
        """把 RuleSlice 的 family 信息整理成报告第 3 节所需的行。"""
        # 每个 family 下的 rule card 计数
        per_family: Dict[str, int] = {}
        for card in rule_slice.candidate_rule_cards:
            per_family[card.family_id] = per_family.get(card.family_id, 0) + 1
        rows: List[Dict[str, Any]] = []
        for fam in rule_slice.rule_families:
            rows.append(
                {
                    "family": fam.family_id,
                    "rule_card_count": per_family.get(fam.family_id, 0),
                    "source_clauses": fam.family_name or "—",
                }
            )
        return rows

    # -- 持久化 -----------------------------------------------------------

    def _persist_artifacts(
        self,
        *,
        run: ComplianceAssessmentRun,
        fact_pack: FactPack,
        rule_slice: RuleSlice,
        closure_result: ClosureValidationResult,
        report: Dict[str, Any],
        run_audit: Dict[str, Any],
    ) -> None:
        """落盘一次 run 的全部 artifacts（spec §6.8 + §8.2）。

        runs/<run_id>/
          fact_pack.json
          rule_slice.json
          obligation_set.json
          closure_validation_result.json
          run.json
          run_audit.json
          auxiliary_review_report.md   或   incomplete_closure_notice.md
          submission_format_rejected_raw_attempt_N.txt  （仅格式失败时；非接纳）
        """
        run_dir = self._runs_root / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        (run_dir / "fact_pack.json").write_text(
            _canonical_json(_model_dump(fact_pack)), encoding="utf-8"
        )
        (run_dir / "rule_slice.json").write_text(
            _canonical_json(_model_dump(rule_slice)), encoding="utf-8"
        )
        (run_dir / "obligation_set.json").write_text(
            _canonical_json(_model_dump(closure_result.obligation_set)),
            encoding="utf-8",
        )
        (run_dir / "closure_validation_result.json").write_text(
            _canonical_json(_model_dump(closure_result)), encoding="utf-8"
        )
        (run_dir / "run.json").write_text(
            _canonical_json(_model_dump(run)), encoding="utf-8"
        )
        (run_dir / "run_audit.json").write_text(
            _canonical_json(run_audit), encoding="utf-8"
        )
        (run_dir / report["filename"]).write_text(
            report["content"], encoding="utf-8"
        )
        if report.get("llm_raw_response") is not None:
            (run_dir / "llm_raw_response.md").write_text(
                report["llm_raw_response"], encoding="utf-8"
            )
        for rejected in report.get("submission_format_rejected_raw_attempts", []):
            attempt_index = int(rejected["attempt_index"])
            # 文件名显式标记 rejected_raw，防审计者把模型编造内容误当接纳产物。
            (run_dir / f"submission_format_rejected_raw_attempt_{attempt_index}.txt").write_bytes(
                str(rejected["raw"]).encode("utf-8")
            )
        # 接纳载荷落盘（DEBT-054 观测补全）：先无条件清残（复审 P2——同秒撞 ID
        # 复用 run_dir 时，非接纳 run 会遗留上次接纳文件，破坏"只在接纳时存在"
        # 与 SHA 对账不变量），再仅在本次接纳时写。
        (run_dir / "accepted_payload.json").unlink(missing_ok=True)
        if report.get("accepted_payload") is not None:
            # 规范化对象信封 + sha 对账字段，供离线回放精确回放组身份锚
            # （与 run_audit.accepted_payload_sha256 一致）。
            (run_dir / "accepted_payload.json").write_text(
                _canonical_json(report["accepted_payload"]), encoding="utf-8"
            )

    def _persist_failure(
        self, run: ComplianceAssessmentRun, run_audit: Dict[str, Any]
    ) -> None:
        """blocked / failed run 的最小持久化——只落 run.json + run_audit.json。"""
        run_dir = self._runs_root / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run.json").write_text(
            _canonical_json(_model_dump(run)), encoding="utf-8"
        )
        (run_dir / "run_audit.json").write_text(
            _canonical_json(run_audit), encoding="utf-8"
        )

    # -- 占位 run ---------------------------------------------------------

    def _make_blocked_run(
        self,
        *,
        run_id: str,
        world_id: str,
        building_id: str,
        requested_at: str,
        status: str,
        input_guard_result: Dict[str, Any],
        note: str,
    ) -> ComplianceAssessmentRun:
        """输入阶段即失败时返回的占位 run（status=blocked/failed）。

        world_id / building_id 可能为空（正是被拦截原因），用占位串补齐以满足
        ComplianceAssessmentRun 的非空约束。
        """
        return ComplianceAssessmentRun(
            run_id=run_id,
            run_type="baseline_building_review",
            world_id=world_id or "<missing>",
            building_id=building_id or "<missing>",
            requested_at=requested_at,
            completed_at=_utc_now_iso(),
            status=status,  # type: ignore[arg-type]
            kg_snapshot_id=self._kg_snapshot_id,
            agent_version=self._agent_version,
            verifier_version=self._verifier_version,
            rulecard_bundle_id=self._rulecard_bundle_id,
            input_guard_result=input_guard_result,
            notes=[note],
        )


__all__ = [
    "RunOrchestrator",
    "RetrievalFn",
    "ClosureFn",
]
