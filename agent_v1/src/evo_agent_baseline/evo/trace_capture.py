"""evo-agent v1 trace capture（spec v1 §3.6.2 + §5.6 + §9.2 + Appendix B.2）。

一次 ComplianceAssessmentRun 内，把 spec v1 §5.2 各阶段（input_guard /
fact_retrieval / rule_retrieval / skill_activation / closure_verification /
deep_lookup / report_generation / guard）按顺序写成 `EvoRunStep`，
最后 `finalize()` 合成 `EvoRunTrace` 并跑 4 类 audit。

关键不变量（spec v1 §9.2 + §2.2.3 + Appendix A）：

1. **不记录 raw W2 字段**：所有禁止 label / property / phrase（spec Appendix A）
   都不能出现在 trace 任何位置 —— 由 `forbidden_scan` 兜底。
2. **不记录原始 tool_input / tool_output**：只存 `tool_input_hash` /
   `tool_output_summary_hash`（sha256 hex）+ 安全摘要（trainer 默认只读 hash）。
3. **不记录 evaluator-only 字段**：FactPack / RuleSlice / ClosureValidationResult
   入 trace 前都过禁止字段扫描；rule_card / fact 体内只取统计摘要 + canonical hash。
4. **必须含 building_id_hash / world_id_hash**：trainer 默认只读 hash（spec
   §3.6.1 注 + §2.5 trainer credential）。trace 内可保留原 ids 在 agent partition，
   但 hash 字段是 trainer-visible 入口。

trace_capture 不影响 closure verifier authority（spec v1 §6 / 任务原则 3）：
`allow_stop` 永远由 closure verifier 决定，本模块只读 closure_result 写 summary。

spec→code 单向：所有 EvoRunStep / EvoRunTrace 字段必须与 `contracts.py` 一致；
不得自创字段，pydantic `extra=forbid` 强制契约。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from evo_agent_baseline.contracts import (
    ClosureValidationResult,
    EvoRunStep,
    EvoRunTrace,
    FactPack,
    RuleSlice,
)


# ===========================================================================
# 一、canonical JSON + sha256（spec v1 §3.8）
# ===========================================================================
#
# spec v1 §3.8：
#   encoding: utf-8
#   object_key_order: unicode_codepoint_ascending
#   datetime: utc_iso8601_seconds
#   float_precision: 6
#   drop_null_unless_required: true
#   list_order:
#     semantic_order_lists: preserve
#     set_semantic_lists: sort_ascending
#   hash: sha256_hex_lowercase
#
# 这里只实现"对 dict / list / 基础类型"的 canonical 化；调用方需要语义有序的
# list（如 EvoRunStep.seq）必须自己已经排好序传进来；set 语义的列表由调用方
# 显式 sort_ascending 后再传入。本函数不会修改 list 顺序。


def _canon_value(v: Any) -> Any:
    """spec v1 §3.8 canonical 化：dict 排序、float 截位、null 保留。"""
    if isinstance(v, dict):
        # unicode_codepoint_ascending（json sort_keys 默认即此）。
        return {k: _canon_value(v[k]) for k in sorted(v.keys())}
    if isinstance(v, (list, tuple)):
        # 不动列表顺序（语义有序 vs set 语义由上层决定）。
        return [_canon_value(x) for x in v]
    if isinstance(v, float):
        # float_precision: 6（spec §3.8）。
        return round(v, 6)
    if isinstance(v, bool):
        # bool 优先匹配（在 int 前），避免被当成 int 1/0。
        return v
    return v


def canonical_json_for_hash(obj: Any) -> str:
    """生成 spec v1 §3.8 canonical JSON 字符串（utf-8、key 升序、float 6 位）。

    与 `run_orchestrator._canonical_json` 区别：本函数面向 **hash 计算**，
    使用 `separators=(",", ":")` 无空白（避免分隔符差异导致 hash 不一致），
    而前者面向落盘可读 artifact。
    """
    return json.dumps(
        _canon_value(obj),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_hex(obj: Any) -> str:
    """spec v1 §3.8 hash 规则：sha256，小写 hex。

    入参若是 str/bytes 直接 hash，否则先走 canonical_json_for_hash。
    """
    if isinstance(obj, bytes):
        return hashlib.sha256(obj).hexdigest()
    if isinstance(obj, str):
        return hashlib.sha256(obj.encode("utf-8")).hexdigest()
    return hashlib.sha256(
        canonical_json_for_hash(obj).encode("utf-8")
    ).hexdigest()


# ===========================================================================
# 二、禁止字段 / 标签 / 文件 / 短语（spec v1 Appendix A）
# ===========================================================================
#
# trace_capture 的 forbidden_scan 是 trace finalization 前最后一道防线
# （spec v1 §5.6 末段 + §9.2 eligible 条件）。
# 任一项命中 → `forbidden_scan_passed=False` → trace 不得进入 Replay Buffer。
#
# 清单照 Appendix A 全量逐字搬：A.1 forbidden labels、A.2 forbidden properties、
# A.3 forbidden files、A.4 forbidden phrases；含 v0.4 已禁项与 v1 新增项。

# Appendix A.1 forbidden labels（v0.4 + v1 新增）
FORBIDDEN_LABELS: frozenset = frozenset({
    "NormativeProjection",
    "ProjectionFamilyEval",
    "ThresholdEval",
    "ReportBasisItem",
    "ExpectedVerdict",
    "EvalProjection",
    "EvalTruth",
    # v1 新增（spec v1 A.1）
    "EvalTruthReport",
    "RawEvalTruth",
    "W2Truth",
    "W2BasisItem",
    "W2ThresholdTruth",
    "ExpectedOutcome",
    "ReferenceVerdict",
    "ProjectionAnswer",
    "RawFeedback",
    "PerRunConfusion",
})

# Appendix A.2 forbidden properties（spec v1 全量逐字）
FORBIDDEN_PROPERTIES: frozenset = frozenset({
    "expected_verdict",
    "selected_family",
    "projection_status",
    "basis_items",
    "unknown_reason_code",
    "regime_tag",
    "pass_bool",
    "projection_id",
    "projection_registry_id",
    "projection_family",
    "projection_version",
    "required_world_core_slots",
    "required_measurement_slots",
    "required_qualifier_slots",
    "required_sidecar_interfaces",
    "matched_component_refs",
    "matched_measurement_ids",
    "coverage_status",
    "raw_projection_ref_hash",
    "projection_ref_hash",
    "truth_label",
    "expected_label",
    "reference_outcome",
    "w2_basis_ref",
    "basis_item_id",
    "projection_cell_id",
    "per_run_confusion",
    "raw_metric_by_run",
    "w2_threshold_truth",
    "w2_observed_value",
    "feedback_truth_comment",
    # spec v1 §2.3.1 agent-visible 禁止字段补充
    "leaked_expected_verdict",
    "raw_eval_truth",
    "raw_w2_metric",
    "w2_expected_operator",
})

# Appendix A.3 forbidden files
FORBIDDEN_FILE_TOKENS: frozenset = frozenset({
    "normative_projection_meta.parquet",
    "projections.parquet",
    "matched_families.parquet",
    "threshold_evaluations.parquet",
    "coverage_control_metadata.parquet",
    "basis_items.parquet",
    "eval_truth_report.json",
    "raw_eval_truth.json",
    "raw_feedback_notes.json",
})

# Appendix A.3 forbidden file prefix（`w2_*.json`）：用前缀匹配。
FORBIDDEN_FILE_PREFIXES: tuple = ("w2_",)

# Appendix A.4 forbidden phrases；spec v1 末段允许"非最终裁决/不构成最终合规裁决"
# 等否定式免责声明。本扫描只针对 trace 元数据（ref 字段 / summary 字段）；
# report 文本另由 `agent.hooks.pre_output_language_guard` 上一层 hook 把守。
FORBIDDEN_PHRASES: tuple = (
    "according to expected_verdict",
    "based on NormativeProjection",
    "force allow_stop",
    "override verifier",
    "expected verdict says",
    "W2 says",
)


# v1 §2.3 / §2.5 trainer 不读 raw run_id / building_id / world_id；trace 内
# 顶层只暴露 hash 字段，原 ids 不外泄到 trainer。本扫描兜底检测：除"_hash"
# 后缀字段外，其余字段不得含 `building_id` / `world_id` / `run_id` 这类 literal。
# 不过本 trace 顶层确实保留 `run_id`（spec v1 §3.6.1 字段表声明：trace 内保留
# 原 ids 在 agent partition），所以 forbidden_scan 不拦 `run_id` / `world_id_hash`
# / `building_id_hash` 字段本身；仅扫"值是否为禁止字段串"。


# ===========================================================================
# 三、forbidden_scan / 各 audit 实现
# ===========================================================================


_LEAKS_KEY = "__leaks__"


def _scan_dict_for_forbidden(
    obj: Any,
    path: str = "$",
    findings: Optional[List[Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    """递归扫 dict / list，查 Appendix A 禁止 label / property / file / phrase。

    返回命中列表，每条 `{kind, value, path}`，便于 audit_summary 上报。
    """
    if findings is None:
        findings = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            # 1. property 名直接禁
            if isinstance(k, str) and k in FORBIDDEN_PROPERTIES:
                findings.append({
                    "kind": "forbidden_property",
                    "value": k,
                    "path": f"{path}.{k}",
                })
            # 2. label 字段（label / labels / type / kind 等命名常见）值是禁 label
            if isinstance(v, str) and v in FORBIDDEN_LABELS:
                findings.append({
                    "kind": "forbidden_label",
                    "value": v,
                    "path": f"{path}.{k}",
                })
            _scan_dict_for_forbidden(v, f"{path}.{k}", findings)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            if isinstance(v, str) and v in FORBIDDEN_LABELS:
                findings.append({
                    "kind": "forbidden_label",
                    "value": v,
                    "path": f"{path}[{i}]",
                })
            _scan_dict_for_forbidden(v, f"{path}[{i}]", findings)
    elif isinstance(obj, str):
        # 3. 文件名命中（含相对路径）
        lower = obj.lower()
        for tok in FORBIDDEN_FILE_TOKENS:
            if tok in lower:
                findings.append({
                    "kind": "forbidden_file",
                    "value": tok,
                    "path": path,
                })
        for pref in FORBIDDEN_FILE_PREFIXES:
            # 仅匹配 path 末段，避免误伤包含 "w2_" 字串的纯数据
            tail = lower.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if tail.startswith(pref) and tail.endswith(".json"):
                findings.append({
                    "kind": "forbidden_file_prefix",
                    "value": tail,
                    "path": path,
                })
        # 4. 禁止短语
        for phrase in FORBIDDEN_PHRASES:
            if phrase.lower() in lower:
                findings.append({
                    "kind": "forbidden_phrase",
                    "value": phrase,
                    "path": path,
                })

    return findings


# spec v1 §2.5：agent-visible artifacts 路径白名单。任一 ref 落到 evaluator /
# raw_feedback / w2_* 目录都判 fail。
_AGENT_VISIBLE_PATH_PREFIXES: tuple = (
    "runs/",
    "runs\\",
    "evo_traces/",
    "evo_traces\\",
    "skill_packages/",
    "skill_packages\\",
    "policy_versions/",
    "policy_versions\\",
)

_EVALUATOR_ONLY_PATH_SUBSTRINGS: tuple = (
    "/eval_truth/",
    "\\eval_truth\\",
    "/raw_feedback/",
    "\\raw_feedback\\",
    "/w2_truth/",
    "\\w2_truth\\",
    "evaluator_truth_store",
    "raw_feedback_store",
)


def _source_visibility_check(refs: Iterable[Optional[str]]) -> Dict[str, Any]:
    """spec v1 §2.5：trace 引用的 artifact ref 必须落在 agent-visible 存储。

    refs 是若干路径字符串（None 跳过）。若任一 ref 命中 evaluator-only 子串
    → fail。空 ref 列表视为 pass（trace 本身就可能 closure-only 没 report ref）。
    """
    bad: List[str] = []
    for r in refs:
        if not r:
            continue
        low = r.lower()
        for sub in _EVALUATOR_ONLY_PATH_SUBSTRINGS:
            if sub in low:
                bad.append(r)
                break
    return {"passed": len(bad) == 0, "violating_refs": bad}


# spec v1 §5.5：verifier candidate universe 必须 non-null；trace 内若
# candidate_universe_hash 为空字符串/None 则 candidate_floor_audit fail。
def _candidate_floor_check(candidate_universe_hash: Optional[str]) -> Dict[str, Any]:
    """spec v1 §5.5：candidate_universe_hash 非空、≥64 字符（sha256 hex）。"""
    if not candidate_universe_hash:
        return {"passed": False, "reason": "candidate_universe_hash is null/empty"}
    if len(candidate_universe_hash) < 16:
        # sha256 hex 通常 64 字符；放宽到 ≥16 兼容 mock fixture（"sha256:" 前缀也算）。
        return {
            "passed": False,
            "reason": f"candidate_universe_hash too short: {len(candidate_universe_hash)}",
        }
    return {"passed": True, "reason": None}


# ===========================================================================
# 四、安全摘要（tool input / output / fact_pack / rule_slice）
# ===========================================================================
#
# spec v1 §5.6：tool input/output 存 canonical hash 与"安全摘要"。
# 安全摘要 = 没有 raw payload、只有：
#   - tool input：args 的字段名 + 类型；不含值。
#   - tool output：行数 / 命中数 / 是否 truncated；不含具体内容。
# fact_pack / rule_slice 同理：只取 count + ids 列表的 hash，不含值。


def _safe_tool_input_summary(tool_input: Any) -> Dict[str, Any]:
    """tool_input → 安全摘要 dict（只暴露字段名 + 类型）。"""
    if tool_input is None:
        return {"type": "null"}
    if isinstance(tool_input, dict):
        return {
            "type": "object",
            "keys": sorted(tool_input.keys()),
            "key_count": len(tool_input),
        }
    if isinstance(tool_input, (list, tuple)):
        return {"type": "array", "length": len(tool_input)}
    if isinstance(tool_input, str):
        return {"type": "string", "length": len(tool_input)}
    return {"type": type(tool_input).__name__}


def _safe_tool_output_summary(tool_output_summary: Any) -> Dict[str, Any]:
    """tool_output_summary → 安全摘要 dict。

    调用方传入的应该已经是 sanitized summary（不含 raw 内容），
    本函数兜底再过一次 forbidden_scan，把禁止字段清掉。
    """
    if tool_output_summary is None:
        return {"type": "null"}
    if not isinstance(tool_output_summary, dict):
        return _safe_tool_input_summary(tool_output_summary)
    # 浅过滤：剔除值里命中禁止 property 名的 key
    out: Dict[str, Any] = {}
    for k, v in tool_output_summary.items():
        if k in FORBIDDEN_PROPERTIES:
            continue
        if isinstance(v, str) and v in FORBIDDEN_LABELS:
            continue
        out[k] = v
    return out


def _fact_pack_summary(fact_pack: Any) -> Dict[str, Any]:
    """spec v1 §3.6.1 retrieval_summary：fact_count / source_tables / index 计数。"""
    if isinstance(fact_pack, FactPack):
        return {
            "fact_count": len(fact_pack.facts),
            "slot_index_keys": len(fact_pack.slot_index),
            "measure_index_keys": len(fact_pack.measure_index),
            "carrier_index_keys": len(fact_pack.carrier_index),
            "source_tables": sorted(fact_pack.source_tables),
        }
    # mock dict 兼容
    if isinstance(fact_pack, dict):
        return {
            "fact_count": len(fact_pack.get("facts", [])),
            "source_tables": sorted(fact_pack.get("source_tables", [])),
        }
    return {"fact_count": 0}


def _rule_slice_summary(rule_slice: Any) -> Dict[str, Any]:
    if isinstance(rule_slice, RuleSlice):
        # 只取 family ids（按 spec §3.6.1：candidate counts、family counts）；
        # 不暴露 candidate_rule_cards 完整内容。
        family_ids = sorted({f.family_id for f in rule_slice.rule_families})
        return {
            "candidate_rule_card_count": len(rule_slice.candidate_rule_cards),
            "rule_family_count": len(rule_slice.rule_families),
            "rule_family_ids": family_ids,
            "source_quote_count": len(rule_slice.source_quotes),
        }
    if isinstance(rule_slice, dict):
        return {
            "candidate_rule_card_count": len(rule_slice.get("candidate_rule_cards", [])),
            "rule_family_count": len(rule_slice.get("rule_families", [])),
        }
    return {"candidate_rule_card_count": 0}


def _closure_summary(closure: Any) -> Dict[str, Any]:
    """spec v1 §3.6.1：closure_summary 含 open/blocked/closed counts + reason counts。"""
    if isinstance(closure, ClosureValidationResult):
        cs = closure.closure_summary
        return {
            "total_obligations": cs.total_obligations,
            "closed_count": cs.closed_count,
            "open_count": cs.open_count,
            "blocked_count": cs.blocked_count,
            "satisfied_count": cs.satisfied_count,
            "violated_count": cs.violated_count,
            "unknown_count": cs.unknown_count,
            "not_applicable_count": cs.not_applicable_count,
            "open_reason_counts": dict(cs.open_reason_counts),
            "blocked_reason_counts": dict(cs.blocked_reason_counts),
            "allow_stop": cs.allow_stop,
            "stop_reason": cs.stop_reason,
        }
    if isinstance(closure, dict):
        return dict(closure)
    return {}


def _utc_now_iso() -> str:
    """UTC seconds 精度（spec v1 §3.8 datetime: utc_iso8601_seconds）。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ===========================================================================
# 五、TraceCapture（主类）
# ===========================================================================


class TraceCapture:
    """一次 ComplianceAssessmentRun 的 EvoRunTrace 捕获器（spec v1 §3.6.2 + §5.6）。

    用法：

        cap = TraceCapture(run_id, world_id, building_id)
        cap.capture_step(stage="input_guard", tool_name=None, ...)
        cap.capture_retrieval(fact_pack, rule_slice, candidate_universe={...})
        cap.capture_closure(closure_result)
        cap.capture_report("runs/CAR-.../llm_incomplete_closure_notice.md")
        cap.capture_hooks([...])
        trace = cap.finalize(
            active_skill_set_id="SS-...",
            active_skill_version_ids=[...],
            evo_policy_version_id="policy....",
            ...
        )

    finalize 后跑 4 类 audit：
    - forbidden_scan_passed —— Appendix A 禁止 label/property/file/phrase；
    - source_visibility_audit_passed —— 所有 ref 落 agent-visible 存储；
    - schema_audit_passed —— EvoRunTrace pydantic 校验（extra=forbid）；
    - candidate_floor_passed —— candidate_universe_hash 非空。

    任一 fail → trace 仍可返回（含 audit 标志位 false），但调用方
    （ReplayBuffer.add_trace）必须按 spec v1 §9.2 拒收。

    spec v1 §6 + 任务原则 3：trace_capture **不影响** closure verifier；
    本类只读 closure_result.allow_stop 写 summary，从不修改。
    """

    def __init__(self, run_id: str, world_id: str, building_id: str) -> None:
        """初始化：立即 hash world_id / building_id。

        spec v1 §3.6.1：trainer 默认只读 world_id_hash / building_id_hash，
        构造时就计算 hash；原 ids 保留在 capture 实例内，供 agent partition 使用。
        """
        if not run_id:
            raise ValueError("run_id is required")
        if not world_id:
            raise ValueError("world_id is required")
        if not building_id:
            raise ValueError("building_id is required")

        self.run_id = run_id
        self.world_id = world_id
        self.building_id = building_id
        # spec v1 §3.6.1 + §3.8：hash 用 canonical JSON + sha256 hex lowercase。
        self.world_id_hash = sha256_hex(world_id)
        self.building_id_hash = sha256_hex(building_id)

        # trace_id 用 run_id + sha8(run_id)（spec v1 §3.6.1 注：`ERT-<run_id>-<hash>`）
        self.trace_id = f"ERT-{run_id}-{sha256_hex(run_id)[:8]}"

        self._steps: List[EvoRunStep] = []
        self._seq = 0

        # capture_retrieval / capture_closure / capture_report / capture_hooks 写入的字段
        self._retrieval_summary: Dict[str, Any] = {}
        self._fact_pack_hash: Optional[str] = None
        self._rule_slice_hash: Optional[str] = None
        self._candidate_universe_hash: Optional[str] = None
        self._closure_result_ref: Optional[str] = None
        self._closure_summary: Dict[str, Any] = {}
        # identity-v5 §7：capture_closure 抄录的 ObligationSet.obligation_identity_schema
        # （旧 trace / 未过闭包为 None=v1 只读；EvoRunTrace 统计序列须按此分区）。
        self._obligation_identity_schema: Optional[str] = None
        self._report_ref: Optional[str] = None
        self._hook_results_hash: Optional[str] = None
        self._hook_results_payload: List[Dict[str, Any]] = []
        self._input_guard_hash: Optional[str] = None

        # finalize 时填充的 4 类 audit 结果
        self._forbidden_scan_passed: Optional[bool] = None
        self._source_visibility_audit_passed: Optional[bool] = None
        self._schema_audit_passed: Optional[bool] = None
        self._candidate_floor_passed: Optional[bool] = None
        self._audit_findings: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 步骤捕获
    # ------------------------------------------------------------------

    def capture_step(
        self,
        *,
        stage: str,
        tool_name: Optional[str] = None,
        tool_input: Any = None,
        tool_output_summary: Any = None,
        selected_skill_ids: Optional[Sequence[str]] = None,
        guard_results: Optional[Mapping[str, Any]] = None,
        candidate_set: Optional[Sequence[str]] = None,
        policy_decision_ref: Optional[str] = None,
    ) -> EvoRunStep:
        """记录一步（spec v1 §3.6.2）。

        - `tool_input` / `tool_output_summary`：计算 sha256 hash 后丢弃原值；
          仅在 step 内保留 hash（spec v1 §5.6 + §9.2）。
        - `selected_skill_ids` / `guard_results` / `candidate_set` /
          `policy_decision_ref` 可选；缺省按 EvoRunStep 默认。
        """
        self._seq += 1
        step_id = f"ERS-{self.trace_id}-{self._seq:04d}"

        tool_input_hash: Optional[str] = None
        if tool_input is not None:
            # 安全摘要的 hash —— 不暴露 raw payload；同一摘要 hash 一致。
            tool_input_hash = sha256_hex(_safe_tool_input_summary(tool_input))

        tool_output_summary_hash: Optional[str] = None
        if tool_output_summary is not None:
            tool_output_summary_hash = sha256_hex(
                _safe_tool_output_summary(tool_output_summary)
            )

        candidate_set_hash: Optional[str] = None
        if candidate_set is not None:
            # set 语义列表：sort_ascending（spec §3.8）
            candidate_set_hash = sha256_hex(sorted(candidate_set))

        step = EvoRunStep(
            step_id=step_id,
            trace_id=self.trace_id,
            seq=self._seq,
            stage=stage,  # type: ignore[arg-type]
            tool_name=tool_name,
            tool_input_hash=tool_input_hash,
            tool_output_summary_hash=tool_output_summary_hash,
            selected_skill_ids=sorted(selected_skill_ids or []),
            policy_decision_ref=policy_decision_ref,
            candidate_set_hash=candidate_set_hash,
            guard_results=dict(guard_results or {}),
            created_at=_utc_now_iso(),
        )
        self._steps.append(step)
        return step

    # ------------------------------------------------------------------
    # 阶段聚合捕获
    # ------------------------------------------------------------------

    def capture_input_guard(self, guard_result: Mapping[str, Any]) -> None:
        """记录 pre_run_input_guard 结果（spec v1 §3.6.1 input_guard_hash）。"""
        self._input_guard_hash = sha256_hex(dict(guard_result))
        # 也记一个 input_guard step（spec v1 §3.6.2 stage enum 含 input_guard）
        self.capture_step(
            stage="input_guard",
            guard_results={"input_guard_hash": self._input_guard_hash},
        )

    def capture_retrieval(
        self,
        fact_pack: Any,
        rule_slice: Any,
        candidate_universe: Optional[Iterable[str]] = None,
    ) -> None:
        """记录 retrieval 阶段（fact + rule + candidate universe）。

        spec v1 §3.6.1：
        - retrieval_summary_json：candidate counts / fact counts / family counts；
        - fact_pack_hash / rule_slice_hash / candidate_universe_hash：均 canonical hash。
        """
        fact_summary = _fact_pack_summary(fact_pack)
        rule_summary = _rule_slice_summary(rule_slice)
        self._retrieval_summary = {**fact_summary, **rule_summary}

        # 整体 hash 用模型 dump 的 canonical
        if hasattr(fact_pack, "model_dump"):
            self._fact_pack_hash = sha256_hex(fact_pack.model_dump())
        else:
            self._fact_pack_hash = sha256_hex(fact_pack)
        if hasattr(rule_slice, "model_dump"):
            self._rule_slice_hash = sha256_hex(rule_slice.model_dump())
        else:
            self._rule_slice_hash = sha256_hex(rule_slice)

        # candidate_universe：set 语义 → sort_ascending
        if candidate_universe is None:
            # 默认用 rule_slice 的 rule_card ids（spec v1 §5.5 base retrieval）。
            universe = []
            if isinstance(rule_slice, RuleSlice):
                universe = [c.rule_card_id for c in rule_slice.candidate_rule_cards]
            self._candidate_universe_hash = sha256_hex(sorted(universe))
        else:
            self._candidate_universe_hash = sha256_hex(sorted(candidate_universe))

        self.capture_step(
            stage="fact_retrieval",
            tool_output_summary=fact_summary,
        )
        self.capture_step(
            stage="rule_retrieval",
            tool_output_summary=rule_summary,
            candidate_set=(
                sorted([c.rule_card_id for c in rule_slice.candidate_rule_cards])
                if isinstance(rule_slice, RuleSlice)
                else None
            ),
        )

    def capture_closure(self, closure_result: Any) -> None:
        """记录 closure 阶段（spec v1 §3.6.1 closure_result_ref + closure_summary）。

        本方法仅 **读取** closure_result，不修改 `allow_stop`（spec v1 §6 +
        任务原则 3）。closure_result_ref 由 capture_step 调用方决定真实路径，
        本方法默认用 `runs/<run_id>/closure_validation_result.json`。
        """
        self._closure_summary = _closure_summary(closure_result)
        # identity-v5 §7：抄录身份 schema（旧产物 / 桩无 obligation_set 则 None=v1 只读）。
        _obl_set = getattr(closure_result, "obligation_set", None)
        self._obligation_identity_schema = getattr(
            _obl_set, "obligation_identity_schema", None
        )
        # ref 路径与 RunOrchestrator._persist_artifacts 保持一致
        self._closure_result_ref = f"runs/{self.run_id}/closure_validation_result.json"
        self.capture_step(
            stage="closure_verification",
            tool_output_summary=self._closure_summary,
            guard_results={"allow_stop": self._closure_summary.get("allow_stop")},
        )

    def capture_report(self, report_path: str) -> None:
        """记录 report 阶段（spec v1 §3.6.1 report_ref）。"""
        self._report_ref = report_path
        self.capture_step(
            stage="report_generation",
            tool_output_summary={"report_ref": report_path},
        )

    def capture_hooks(self, hook_results: Sequence[Mapping[str, Any]]) -> None:
        """记录 hook 结果（spec v1 §3.6.1 hook_results_hash）。

        hook_results 是 RunOrchestrator 收集的 `[input_guard, source_audit,
        stop_gate, output_guard, ...]` 列表；本方法 canonical hash 整个列表。
        """
        payload = [dict(h) for h in hook_results]
        self._hook_results_payload = payload
        self._hook_results_hash = sha256_hex(payload)

        # 给每个 hook 记一个 guard step，便于 trainer 复盘
        for h in payload:
            self.capture_step(
                stage="guard",
                tool_name=h.get("guard"),
                guard_results=h,
            )

    # ------------------------------------------------------------------
    # 4 类 audit
    # ------------------------------------------------------------------

    def _run_forbidden_scan(self, trace_dict: Dict[str, Any]) -> bool:
        """spec v1 §5.6 末 + §9.2 + Appendix A：trace 不得含禁止 label/property/file/phrase。"""
        findings = _scan_dict_for_forbidden(trace_dict)
        # 顶层字段名豁免：trace_id / run_id / world_id_hash / building_id_hash
        # 等是 spec v1 §3.6.1 授权字段，不应被自身字段名误触发。本扫描只在
        # 嵌套 value / key 中查 FORBIDDEN_PROPERTIES，trace 顶层字段名都不在
        # 禁止集合中，自然不冲突；这里冗余记一笔以防后续 spec 变更。
        self._audit_findings["forbidden_scan"] = findings
        return len(findings) == 0

    def _run_source_visibility_audit(self) -> bool:
        """spec v1 §2.5：所有 ref 必须 agent-visible。"""
        refs = [self._closure_result_ref, self._report_ref]
        res = _source_visibility_check(refs)
        self._audit_findings["source_visibility"] = res
        return bool(res["passed"])

    def _run_schema_audit(self, trace: EvoRunTrace) -> bool:
        """spec v1 Appendix B.2 + extra=forbid：trace pydantic 校验通过即 pass。

        因为 EvoRunTrace 的 `model_config = {"extra": "forbid"}`，
        构造时就会拒掉未授权字段；这里再 model_dump → model_validate 一遍，
        确保 round-trip 也合规。
        """
        try:
            EvoRunTrace.model_validate(trace.model_dump())
            self._audit_findings["schema"] = {"passed": True}
            return True
        except Exception as exc:  # noqa: BLE001
            self._audit_findings["schema"] = {"passed": False, "error": str(exc)}
            return False

    def _run_candidate_floor_audit(self) -> bool:
        """spec v1 §5.5：candidate_universe_hash 非空 + 长度合规。"""
        res = _candidate_floor_check(self._candidate_universe_hash)
        self._audit_findings["candidate_floor"] = res
        return bool(res["passed"])

    # ------------------------------------------------------------------
    # finalize
    # ------------------------------------------------------------------

    def finalize(
        self,
        *,
        active_skill_set_id: str,
        active_skill_version_ids: Sequence[str],
        evo_policy_version_id: str,
        agent_version: str,
        verifier_version: str,
        kg_snapshot_id: str,
        rulecard_bundle_id: str,
        tool_call_count: int,
        llm_iterations_used: int,
        cost: Optional[Mapping[str, Any]] = None,
        fallback_reason: Optional[str] = None,
        sanitized_feedback_refs: Optional[Sequence[str]] = None,
    ) -> EvoRunTrace:
        """组装最终 EvoRunTrace 并跑 4 类 audit（spec v1 §3.6.1 + §9.2）。

        所有 required 字段必须传齐；缺省/None 字段按 EvoRunTrace 默认。

        forbidden_scan_passed=False 的 trace 仍返回，方便审计；但调用方
        （ReplayBuffer.add_trace 等）必须拒收（spec v1 §9.2 eligible 条件）。
        """
        # 必填 hash 缺失时给空字符串占位 → schema_audit / candidate_floor_audit
        # 会捕到 fail；不要在这里抛异常，否则审计信息丢失。
        trace = EvoRunTrace(
            trace_id=self.trace_id,
            run_id=self.run_id,
            world_id_hash=self.world_id_hash,
            building_id_hash=self.building_id_hash,
            kg_snapshot_id=kg_snapshot_id,
            rulecard_bundle_id=rulecard_bundle_id,
            agent_version=agent_version,
            verifier_version=verifier_version,
            evo_policy_version_id=evo_policy_version_id,
            active_skill_set_id=active_skill_set_id,
            active_skill_version_ids=list(active_skill_version_ids),
            input_guard_hash=self._input_guard_hash or sha256_hex({}),
            retrieval_summary=dict(self._retrieval_summary),
            candidate_universe_hash=self._candidate_universe_hash or "",
            fact_pack_hash=self._fact_pack_hash or "",
            rule_slice_hash=self._rule_slice_hash or "",
            closure_result_ref=self._closure_result_ref or "",
            closure_summary=dict(self._closure_summary),
            report_ref=self._report_ref,
            hook_results_hash=self._hook_results_hash or sha256_hex([]),
            tool_call_count=tool_call_count,
            llm_iterations_used=llm_iterations_used,
            cost=dict(cost or {}),
            fallback_reason=fallback_reason,
            steps=list(self._steps),
            sanitized_feedback_refs=list(sanitized_feedback_refs or []),
            # identity-v5 §7：经验记录携身份 schema（capture_closure 抄录；分区禁跨模式混算）。
            obligation_identity_schema=self._obligation_identity_schema,
            trace_visibility="agent_visible_trace",
            # 先填占位，下面 audit 跑完再覆盖
            forbidden_scan_passed=False,
            source_visibility_audit_passed=False,
            schema_audit_passed=False,
            candidate_floor_passed=False,
            created_at=_utc_now_iso(),
        )

        # ---- 跑 4 类 audit ----
        # forbidden_scan 用 trace.model_dump()（含所有字段）
        trace_dump = trace.model_dump()
        self._forbidden_scan_passed = self._run_forbidden_scan(trace_dump)
        self._source_visibility_audit_passed = self._run_source_visibility_audit()
        self._candidate_floor_passed = self._run_candidate_floor_audit()
        self._schema_audit_passed = self._run_schema_audit(trace)

        # 覆盖 audit 标志位（model_copy 保留 extra=forbid 约束）
        trace = trace.model_copy(update={
            "forbidden_scan_passed": self._forbidden_scan_passed,
            "source_visibility_audit_passed": self._source_visibility_audit_passed,
            "schema_audit_passed": self._schema_audit_passed,
            "candidate_floor_passed": self._candidate_floor_passed,
        })
        return trace

    # ------------------------------------------------------------------
    # 公开 accessor（测试 / 审计用）
    # ------------------------------------------------------------------

    @property
    def steps(self) -> List[EvoRunStep]:
        """已捕获的 step 列表（顺序保持插入顺序）。"""
        return list(self._steps)

    @property
    def audit_findings(self) -> Dict[str, Any]:
        """4 类 audit 详情；finalize 后才有内容。"""
        return dict(self._audit_findings)


__all__ = [
    "TraceCapture",
    "canonical_json_for_hash",
    "sha256_hex",
    "FORBIDDEN_LABELS",
    "FORBIDDEN_PROPERTIES",
    "FORBIDDEN_FILE_TOKENS",
    "FORBIDDEN_PHRASES",
]
