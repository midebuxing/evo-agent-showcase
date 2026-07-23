"""LLM-as-brain 编排器（spec §5.2 + §7；逐点提交契约 v3）。

LLM 只控制工具调度与结构化分析点列；allow_stop、closure_status 和
satisfaction_status 始终由 deterministic verifier 决定。v3 的真 tool call 与
纯文本合成路径共用 ``{"points":[{"text":...,"evidence_aliases":[...]}]}``
对象信封：格式错误走独立的一次修复预算，格式通过后才烧叙述预算；内容按点
校验、整篇原子接纳，随后由程序确定性转义、展开别名并渲染到唯一模型槽位。

报告骨架、权威计数、标题、闭包表格与人工复核节仍由程序渲染。模型槽位文本
使用 v3 三类叙述规则，程序骨架继续使用既有输出白名单，组合守卫按来源分区。
evo-agent blind 不变量保持：W2/evaluator 输入不进入 session、证据包或报告槽位。
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from evo_agent_baseline.agent.report_writer import (
    NarrativeEvidencePack,
    build_narrative_evidence_pack,
    extract_narrative_alias_tokens,
    render_contract_v2_report,
    render_deterministic_narrative,
    render_structured_narrative_points,
)
from evo_agent_baseline.agent.report_contract_v4 import (
    build_v4_model_payload,
    render_v4_points,
    validate_submission_payload_v4,
)

from evo_agent_baseline.contracts import (
    ClosureValidationResult,
    EvoPolicyVersion,
    FactPack,
    Obligation,
    RuleSlice,
    SkillJson,
)
from evo_agent_baseline.agent.hooks import (
    AGENT_FORBIDDEN_FILES,
    AGENT_FORBIDDEN_LABELS,
    AGENT_FORBIDDEN_PROPERTIES,
    OutputGuardError,
    post_retrieval_source_audit,
    pre_output_language_guard,
)
from evo_agent_baseline.agent.llm_client import (
    LLMClient,
    LLMTurn,
    load_system_prompt,
    report_contract_mode,
)

# 叙述节局部重试次数允许区间 + 默认值（报告契约 v2 修订 4：配置在 [1,2] 内，
# 默认 2；实现默认值对应草案开放问题 1）。
NARRATIVE_RETRY_LIMIT_RANGE = (1, 2)
DEFAULT_NARRATIVE_RETRY_LIMIT = 2


# ---------------------------------------------------------------------------
# Tools schema（OpenAI function calling 格式）
# ---------------------------------------------------------------------------
LLM_TOOLS: List[Dict[str, Any]] = [
    # ---- 主流程 5 个 tool（baseline 必需）----
    {
        "type": "function",
        "function": {
            "name": "retrieve_building_facts",
            "description": (
                "检索目标建筑的事实子图（World/Building/Component/Fragment/"
                "状态/Measurement/Sidecar）。每个评估必须先调一次，结果存 session。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_applicable_rules",
            "description": (
                "检索候选 rule_card 切片（候选规则卡 + family + 词表）。"
                "需先调 retrieve_building_facts。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_closure_verification",
            "description": (
                "对已检索的 fact + rule 跑确定性闭包验证器，返回义务汇总与 "
                "allow_stop。allow_stop 是唯一权威的'能否生成完整报告'判定。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_open_obligations",
            "description": (
                "从已跑的闭包结果中取前 N 个 open 义务详情（id 列表），"
                "帮助选哪些义务需深入查 inspect_obligation。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回义务数上限，默认 10",
                    }
                },
                "required": [],
            },
        },
    },
    # 契约 v3：两条路径共用同一对象信封；旧字符串入参只返回迁移回执。
    {
        "type": "function",
        "function": {
            "name": "submit_analysis",
            "description": (
                "提交报告契约 v3 JSON 点列。每一点只写事实限制、疑似风险、"
                "证据缺口或人工复核动作；证据通过 evidence_aliases 建立结构绑定，"
                "text 只能提及本点已绑定别名，且不得写真实 ID。报告骨架由程序渲染。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "points": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 24,
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "minLength": 1, "maxLength": 500},
                                "evidence_aliases": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": 8,
                                    "items": {"type": "string"},
                                    "uniqueItems": True,
                                },
                            },
                            "required": ["text", "evidence_aliases"],
                        },
                    }
                },
                "required": ["points"],
            },
        },
    },
    # ---- KG 检索深入 6 个 tool（真正用法规原文 + 节点细节，spec §5）----
    {
        "type": "function",
        "function": {
            "name": "inspect_obligation",
            "description": (
                "拿单条 obligation 的完整字段：kind / closure_status / "
                "satisfaction_status / threshold / observed_value / "
                "evidence_fact_ids / source_rule_card_id / source_clause_ids / "
                "source_quote_ids / open_reason_code / blocked_reason_code。"
                "用于 query_open_obligations / closure_summary 后深入单条义务的依据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "obligation_id": {
                        "type": "string",
                        "description": "前缀也可（首 12+ 字符即可匹配）",
                    }
                },
                "required": ["obligation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_clause",
            "description": (
                "按 clause_id 取一条法规章节的原文（heading + text 全文 markdown）。"
                "用于报告引用法规依据，避免脑补。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "clause_id": {
                        "type": "string",
                        "description": "RegulationClause.clause_id 完整值",
                    }
                },
                "required": ["clause_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_rule_card",
            "description": (
                "拿单张 rule_card 的核心字段 + 所有 source_quote 原文段落（含 "
                "page / language）+ source_clause_ids。用于解释某 rule_card "
                "实际要求是什么、法规根据在哪一条。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "rule_card_id": {
                        "type": "string",
                        "description": "RuleCard.rule_card_id 完整值",
                    }
                },
                "required": ["rule_card_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_regulation",
            "description": (
                "在法规全文里关键字搜索，返回 top-K 命中段落（含 clause_id + "
                "score + 前 300 字预览）。用于找特定主题的法规依据。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "全文搜索表达式（Lucene 语法，例如 'pull test'）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回条数上限，默认 5",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_fragment",
            "description": (
                "查单个 fragment 的完整状态画像：所属 component / location / "
                "driver / mechanism / condition / repair / specialized states / "
                "measurements 数量。用于深入分析某 fragment 为什么 open / blocked。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fragment_id": {
                        "type": "string",
                        "description": "Fragment.fragment_id 完整值",
                    }
                },
                "required": ["fragment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_facts_by_slot",
            "description": (
                "取目标建筑中某 slot_id 的具体 fact 值（value / unit / qualifiers / "
                "carrier）。用于回答'该建筑某个 slot 实际值是多少'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "slot_id": {
                        "type": "string",
                        "description": "目标 slot_id（canonical 形式）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回 fact 数上限，默认 10",
                    },
                },
                "required": ["slot_id"],
            },
        },
    },
]


# 报告契约 v4 的 submit_analysis 工具 schema（spec §7.4.5）：4 结构化字段、
# additionalProperties:false、无自由文本。其余工具与 v3 共用。
_V4_SUBMIT_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_analysis",
        "description": (
            "提交报告契约 v4 结构化点列。每点只含 obligation_alias/analysis_code/"
            "selected_fact_aliases/review_action_code 四字段，禁止任何自由文本；"
            "规则/状态/原因/最终句子全部由程序从权威对象生成，你只提交选择与分类。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "contract": {"type": "string", "enum": ["report_contract_v4"]},
                "points": {
                    "type": "array", "minItems": 1, "maxItems": 24,
                    "items": {
                        "type": "object",
                        "properties": {
                            "obligation_alias": {"type": "string"},
                            "analysis_code": {"type": "string"},
                            "selected_fact_aliases": {
                                "type": "array", "items": {"type": "string"}},
                            "review_action_code": {"type": "string"},
                        },
                        "required": ["obligation_alias", "analysis_code",
                                     "selected_fact_aliases", "review_action_code"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["contract", "points"],
            "additionalProperties": False,
        },
    },
}

LLM_TOOLS_V4: List[Dict[str, Any]] = [
    _V4_SUBMIT_TOOL if t.get("function", {}).get("name") == "submit_analysis" else t
    for t in LLM_TOOLS
]


def active_llm_tools(contract_version: Optional[int] = None) -> List[Dict[str, Any]]:
    """按报告契约版本选工具集：4 用 v4 submit schema，否则 v3（默认）。

    contract_version=None 时读进程环境（会话外场景）；会话内必须传
    state.contract_version 冻结值（copilot 终审五轮致命#1：运行中环境翻转）。
    """
    if contract_version is None:
        contract_version = 4 if report_contract_mode() == "v4" else 3
    return LLM_TOOLS_V4 if contract_version == 4 else LLM_TOOLS


def _pack_model_payload(pack: Any, contract_version: Optional[int] = None) -> Dict[str, Any]:
    """按报告契约版本选证据包 payload：4 带 suggested_analysis/allowed_actions 提示。

    contract_version 语义同 active_llm_tools：None 读环境，会话内传冻结值。
    """
    if contract_version is None:
        contract_version = 4 if report_contract_mode() == "v4" else 3
    if contract_version == 4:
        return build_v4_model_payload(pack)
    return pack.to_model_payload()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
@dataclass
class LLMSessionState:
    """LLM 编排过程的 Python-side 重对象 state。

    LLM 看不到全对象（防止 context 爆 + 信息泄漏风险），通过摘要驱动决策。
    `kg_client` 是 Neo4jClient 实例，用于深入查询工具（lookup_clause /
    lookup_rule_card / search_regulation / query_fragment）；None 时这些工具
    返回 'kg_client 未注入' 错误。

    evo-agent v1 新增字段（spec v1 §5.1 ComplianceAssessmentRunV1）：
    - `evo_policy_version_id` / `active_skill_version_ids`：active policy + skill set；
    - `skill_invocation_log`：本 session 内 Skill 触发 + 决策 + 结果列表，写入
      EvoRunTrace.steps（spec v1 §3.6.2）。

    evo_mode 关闭（policy 与 skills 均 None）时，session 行为与 v0.4 baseline 完全一致。
    """

    world_id: str
    building_id: str
    run_id: str
    # ---- 报告契约版本：会话创建时冻结,整条链唯一权威(也是唯一 env 读取点)。
    # copilot 终审五轮致命#1:各路径各自重读 report_contract_mode() 时,运行中
    # 环境翻转可让 v4 会话接纳 v3 自由文本而终稿仍标 v4——故冻进 state,
    # 提示词/工具 schema/回执/提交校验/渲染一律只读本字段。
    contract_version: int = field(
        default_factory=lambda: 4 if report_contract_mode() == "v4" else 3
    )
    fact_pack: Optional[FactPack] = None
    rule_slice: Optional[RuleSlice] = None
    closure_result: Optional[ClosureValidationResult] = None
    final_report: Optional[str] = None
    llm_raw_response: Optional[str] = None
    seen_date_tokens: set[str] = field(default_factory=set)
    # ---- 报告契约 v3 逐点提交与叙述状态 ----
    evidence_pack: Optional[NarrativeEvidencePack] = None
    accepted_payload: Optional[Dict[str, Any]] = None
    accepted_via: Optional[str] = None
    accepted_payload_sha256: Optional[str] = None
    submission_format_attempts: int = 0
    submission_format_repairs_used: int = 0
    submission_format_events: List[Dict[str, Any]] = field(default_factory=list)
    # 本地验尸专用：仅保存格式失败的原始提交，不进入模型侧回执或接纳载荷。
    submission_format_rejected_raw_attempts: List[Dict[str, Any]] = field(default_factory=list)
    submit_tool_called: bool = False  # llm_forced_finalize 原义：是否在轮内调过提交工具
    narrative_attempts: int = 0
    narrative_rejection_codes: List[str] = field(default_factory=list)
    narrative_fallback_reason: Optional[str] = None
    narrative_retry_limit: int = DEFAULT_NARRATIVE_RETRY_LIMIT
    deprecated_tool_events: List[Dict[str, Any]] = field(default_factory=list)
    submission_audit_events: List[Dict[str, Any]] = field(default_factory=list)
    # 两阶段接纳审计暂存（bug6）：内容层接纳时先写这里；组合终稿守卫全过、
    # 终局仍为 LLM 接纳后才并入权威 submission_audit_events。被撤销的稿由
    # _clear_final_acceptance 清空 pending，从而不落非接纳终稿的审计。
    pending_acceptance_audit_events: List[Dict[str, Any]] = field(default_factory=list)
    turns: List[LLMTurn] = field(default_factory=list)
    tool_log: List[Dict[str, Any]] = field(default_factory=list)
    kg_client: Optional[Any] = None  # Neo4jClient；type 用 Any 避免循环 import
    # 溯源元数据（RunOrchestrator 注入；确定性兜底模板渲染第 2/3 节用，工单裁定 8）
    kg_snapshot_id: str = ""
    rulecard_bundle_id: str = ""
    # 零计数断言闸 WARN 命中（工单裁定 5：只记警告不拒绝，落 run_audit）
    false_zero_count_warnings: List[Dict[str, Any]] = field(default_factory=list)
    # 组合终稿守卫的权威结果（复审修正 P4：内层拆半校验是唯一权威，外层
    # RunOrchestrator 必须复用本结果、不得按默认语境整稿复检——否则叙述节
    # 专属否定前缀放行的稿会在外层被二次拒杀整个 run）
    composed_guard_audit: Optional[Dict[str, Any]] = None
    # b 件（EXP-013 时序适配）：证据包首次就绪后的定向提交提示，每 run 只注入一次
    submit_directive_injected: bool = False
    # ---- v1 evo_mode 字段 ----
    evo_policy_version_id: Optional[str] = None
    active_skill_version_ids: List[str] = field(default_factory=list)
    skill_invocation_log: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Tool 执行
# ---------------------------------------------------------------------------
_SUBMIT_NEXT_ACTION = (
    "信息齐全后调 submit_analysis 提交分析（字段与形状按工具 schema，"
    "契约细节见系统提示词）；从证据包 key_items 选真实别名，每个重点项写一点。"
)


def _summarize_fact_pack(fp: FactPack) -> str:
    """LLM-readable FactPack 摘要（spec §5.5；不暴露完整对象）。

    `next_actions` 按 spec §7.5.3 "推荐 next-action hint" 给小模型推进流程。
    """
    by_carrier: Dict[str, int] = {}
    by_slot: Dict[str, int] = {}
    for f in fp.facts:
        by_carrier[f.carrier_type] = by_carrier.get(f.carrier_type, 0) + 1
        if f.slot_id:
            by_slot[f.slot_id] = by_slot.get(f.slot_id, 0) + 1
    top_slots = sorted(by_slot.items(), key=lambda x: -x[1])[:10]
    return json.dumps(
        {
            "fact_count": len(fp.facts),
            "by_carrier_type": by_carrier,
            "top_slots_by_fact_count": [{"slot_id": s, "count": c} for s, c in top_slots],
            "source_tables": list(fp.source_tables),
            "next_actions": [
                "调 retrieve_applicable_rules 拿候选 rule_card 切片（family / "
                "measure / artifact 注册表）",
                "若需查某 slot 的具体 fact 值，调 get_facts_by_slot(slot_id=...)",
                "fact + rule 都拿到后调 run_closure_verification 跑 deterministic"
                " 闭包验证，allow_stop 由此决定",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _summarize_rule_slice(rs: RuleSlice) -> str:
    """LLM-readable RuleSlice 摘要 + next-action hint（spec §7.5.3）。"""
    families: Dict[str, int] = {}
    for card in rs.candidate_rule_cards:
        families[card.family_id] = families.get(card.family_id, 0) + 1
    return json.dumps(
        {
            "rulecard_bundle_id": rs.rulecard_bundle_id,
            "candidate_rule_card_count": len(rs.candidate_rule_cards),
            "family_count": len(rs.rule_families),
            "candidate_cards_by_family": families,
            "semantic_slot_count": len(rs.semantic_slots),
            "measure_count": len(rs.measures),
            "artifact_count": len(rs.artifacts),
            "next_actions": [
                "调 run_closure_verification 跑 deterministic 闭包验证（必经；"
                "allow_stop 由此决定）",
                "对感兴趣的 rule_card_id 调 lookup_rule_card(rule_card_id=...)"
                " 取核心字段 + source_quote 原文",
                "对某主题不确定时调 search_regulation(query=...) 找命中条款",
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _summarize_closure(
    cr: ClosureValidationResult,
    evidence_pack: Optional[NarrativeEvidencePack] = None,
    contract_version: Optional[int] = None,
) -> str:
    """LLM-readable ClosureValidationResult 摘要 + 叙述证据包 + next-action hint。

    契约 v2 修订 3：在允许调用 submit_analysis 前，程序必须构造好
    NarrativeEvidencePack 并让模型可见（短别名 [O*]/[R*]/[F*]）。
    """
    summary = cr.closure_summary
    payload = {
        "total_obligations": summary.total_obligations,
        "closed_count": summary.closed_count,
        "open_count": summary.open_count,
        "blocked_count": summary.blocked_count,
        "satisfied_count": summary.satisfied_count,
        "violated_count": summary.violated_count,
        "unknown_count": summary.unknown_count,
        "not_applicable_count": summary.not_applicable_count,
        "open_reason_counts": summary.open_reason_counts,
        "blocked_reason_counts": summary.blocked_reason_counts,
        "rule_card_count": summary.rule_card_count,
        "family_count": summary.family_count,
        "allow_stop": cr.allow_stop,
        "allow_report_generation": cr.allow_report_generation,
        "high_risk_item_count": len(cr.high_risk_items),
    }
    if evidence_pack is not None:
        payload["narrative_evidence_pack"] = _pack_model_payload(
            evidence_pack, contract_version
        )
    if not cr.allow_stop:
        payload["next_actions"] = [
            "allow_stop=False: call query_open_obligations(limit=10) for top-10 open items; "
            "if open=0 and blocked>0, use the blocked summary and evidence pack",
            "如需细节可调 inspect_obligation / lookup_rule_card 深入查看",
            _SUBMIT_NEXT_ACTION,
        ]
    else:
        payload["next_actions"] = [
            _SUBMIT_NEXT_ACTION,
            "报告骨架与权威字段由程序渲染；只提交逐点实质分析。",
        ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _query_open_obligations_summary(closure_result: ClosureValidationResult, limit: int) -> str:
    """top-N 个 open obligation 给 LLM 看缺什么 + next-action hint。

    字段名跟 lookup_rule_card / inspect_obligation 入参一致（`rule_card_id` /
    `obligation_id`），LLM 复制粘贴即可调下一步 tool。
    """
    items: List[Dict[str, Any]] = []
    for o in closure_result.obligation_set.obligations:
        if o.closure_status != "open":
            continue
        items.append(
            {
                "obligation_id": o.obligation_id,  # 完整 id（inspect_obligation 接受完整或前缀）
                "rule_card_id": o.source_rule_card_id,  # 字段名跟 lookup_rule_card 入参一致
                "family_id": o.source_family_id,
                "kind": o.kind,
                "slots_needed": list(o.slot_ids)[:3],
                "measures_needed": list(o.measure_keys)[:3],
                "open_reason": o.open_reason_code,
            }
        )
        if len(items) >= limit:
            break
    payload = {
        "open_obligations": items,
        "next_actions": [
            "对感兴趣的 obligation 调 inspect_obligation(obligation_id=...)"
            " 拿完整字段（含 threshold / observed / evidence）",
            "对 rule_card_id 调 lookup_rule_card(rule_card_id=...) 拿法规 source_quote 真实原文",
            _SUBMIT_NEXT_ACTION,
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 报告契约 v3 逐点叙述闸常量
# ---------------------------------------------------------------------------
# 叙述节闸稳定拒绝码（run_audit.llm_narrative_rejection_codes 用）。
REJECT_UNRESOLVED_ALIAS = "unresolved_alias"
REJECT_FABRICATED_DATE = "fabricated_date"
REJECT_WRONG_BUILDING_ID = "wrong_building_id"
REJECT_FAKE_OBLIGATION_ID = "fake_obligation_id"
REJECT_FAKE_RULE_CARD_ID = "fake_rule_card_id"
REJECT_FAKE_FACT_ID = "fake_fact_id"
REJECT_RAW_EVIDENCE_ID = "raw_evidence_id"
REJECT_FORBIDDEN_PHRASE = "forbidden_phrase"
REJECT_BRANCH_INCONSISTENT = "branch_inconsistent"
REJECT_STATUS_ESCALATION = "status_escalation"

# 报告契约 v3 的格式错误稳定枚举。草案正文实际列出 19 项。
SUBMISSION_FORMAT_ERROR_CODES = (
    "invalid_json",
    "no_fence",
    "multi_fence",
    "bad_fence_language",
    "trailing_tokens",
    "duplicate_key",
    "root_not_object",
    "missing_points",
    "points_type",
    "empty_points",
    "too_many_points",
    "point_field_missing",
    "point_field_type",
    "text_too_long",
    "text_multiline",
    "alias_count",
    "alias_duplicate",
    "alias_in_text",
    "legacy_input_unsupported",
)
REJECT_META_COMMENTARY = "meta_commentary"

# 报告契约 v3 内容层稳定拒绝码（状态一致性闸加入后 10 -> 11）。顺序只用于
# 冻结/对账；实际回执仍按逐点检查的确定性发现顺序输出。
NARRATIVE_REJECTION_CODES = (
    REJECT_UNRESOLVED_ALIAS,
    REJECT_FABRICATED_DATE,
    REJECT_WRONG_BUILDING_ID,
    REJECT_FAKE_OBLIGATION_ID,
    REJECT_FAKE_RULE_CARD_ID,
    REJECT_FAKE_FACT_ID,
    REJECT_RAW_EVIDENCE_ID,
    REJECT_FORBIDDEN_PHRASE,
    REJECT_BRANCH_INCONSISTENT,
    REJECT_META_COMMENTARY,
    REJECT_STATUS_ESCALATION,
)

_BARE_V3_ALIAS_RE = re.compile(r"^[ORF][0-9]+$")
_CLAUSE_SPLIT_RE = re.compile(r"[。！？!?；;\r\n]+")
_TURN_BOUNDARY_RE = re.compile(r"(?:但是|然而|不过|可是|但|却|仍然|仍|而)")
_MODAL_SCOPE_CODEPOINTS = 12
_NEGATIVE_MODAL_TOKENS = (
    "尚不能",
    "尚无法",
    "并非",
    "不是",
    "不能",
    "无法",
    "不可",
    "不得",
    "尚未",
    "没有",
    "未",
    "无",
    "不",
    "非",
)
_POSITIVE_MODAL_TOKENS = (
    "已经",
    "可以",
    "能够",
    "确认",
    "认定",
    "判定",
    "足以",
    "允许",
    "已",
    "可",
    "能",
)
_UNCERTAIN_MODAL_TOKENS = (
    "需要人工",
    "尚待",
    "需由",
    "疑似",
    "可能",
    "或许",
    "是否",
    "建议",
    "待",
)
# 内容层第五检查（状态一致性闸）规则 A 已降为 advisory-only 探针：候选词命中
# 只在最终原子接纳后记 status_escalation_warning 审计事件，不产拒码、不烧叙述
# 预算、不触发确定性兜底（A 案；2026-07-13）。硬词 + 软词合并为单一候选表，
# 条件/否定/不确定/承认词不再作为消警豁免。规则 B（同质性）继续硬拒。
_OBLIGATION_NORMATIVE_OBJECTS = (
    "法定",
    "法规",
    "规范",
    "规定",
    "标准",
    "要求",
    "义务",
)
_OBLIGATION_VIOLATION_PREDICATES = (
    "缺失即违规",
    "构成违规",
    "未达标",
    "不达标",
    "不合格",
    "违反",
    "违背",
    "违规",
    "逾期",
    "超期",
)
_OBLIGATION_NORMATIVE_OBJECT_PATTERN = "|".join(
    re.escape(token) for token in _OBLIGATION_NORMATIVE_OBJECTS
)
_OBLIGATION_NONCONFORMITY_OBJECT_PATTERN = "|".join(
    re.escape(token)
    for token in _OBLIGATION_NORMATIVE_OBJECTS
    if token != "义务"
)
_OBLIGATION_SOFT_GAP_PREDICATES = (
    "无法满足",
    "缺失",
    "缺少",
    "尚缺",
    "欠缺",
    "未取得",
    "无法达到",
    "未满足",
    "不符合",
)
# 合并后的单一候选表：硬词（断言式违规）+ 软词（缺口）去重，保留硬词在前的
# 稳定顺序。规则 A 不再区分硬/软，全部候选只驱动 advisory 审计。
_OBLIGATION_STATUS_ESCALATION_CANDIDATES = tuple(
    dict.fromkeys(
        _OBLIGATION_VIOLATION_PREDICATES + _OBLIGATION_SOFT_GAP_PREDICATES
    )
)
# 规范宾语模式（未满足法定 / 不符合规范等）作为更长的替代排在候选前，finditer
# 从左到右取最长匹配，因而“未满足法定”整体成一个候选命中、裸“未满足”另计。
_OBLIGATION_STATUS_ESCALATION_PATTERN = re.compile(
    "|".join(
        [
            rf"未满足(?:{_OBLIGATION_NORMATIVE_OBJECT_PATTERN})",
            rf"不符合(?:{_OBLIGATION_NONCONFORMITY_OBJECT_PATTERN})",
        ]
        + [
            re.escape(token)
            for token in sorted(
                _OBLIGATION_STATUS_ESCALATION_CANDIDATES, key=len, reverse=True
            )
        ]
    )
)
_FINAL_STATUS_PREDICATES = (
    "做出最终裁决",
    "最终不合规",
    "最终合规",
    "最终裁决",
    "本建筑不合规",
    "本建筑已合规",
    "不合规",
    "合规",
    "结案",
)
_BRANCH_STATUS_PREDICATES = (
    "已生成完整辅助审查报告",
    "已形成完整辅助审查报告",
    "生成完整辅助审查报告",
    "形成完整辅助审查报告",
    "闭包验证通过",
    "闭包已通过",
    "闭包通过",
    "资料闭包完成",
    "闭包完成",
    "资料已齐全",
    "资料齐全",
)
_STATUS_SUBJECTS = (
    "本建筑",
    "该建筑",
    "本项目",
    "项目",
    "本报告",
    "报告",
    "闭包",
    "闭包验证",
    "资料",
)
_META_SELF_SUBJECTS = ("我", "模型", "本回答", "以下内容")
# "撰写/陈述"补自 2026-07-23 codex 审出的漏检："我会按要求撰写以下分析"有自指
# 主语却无行为词。不加"本文"作主语——它是"文本文件/样本文件"的子串,会误杀。
_META_OUTPUT_BEHAVIORS = ("输出", "使用", "提及", "避免", "遵循", "撰写", "陈述")
# 敏感状态词（最终裁决/合规判定类），shape2 与 shape3 共用，故前置定义。
_META_SENSITIVE_TERMS = tuple(dict.fromkeys(_FINAL_STATUS_PREDICATES + _BRANCH_STATUS_PREDICATES))
# shape2 的任务元语境锚点（2026-07-20 修，codex 决策门裁定"第四条路"）。
# 病：原 `_META_RULE_TERMS = (要求/提示词/规则/禁词/格式)` 与
# `_META_COMPLIANCE_BEHAVIORS = (按/不使用/避免/只能)` **任意共现**即判元评论。
# 但"要求/规则/格式"是合规正文高频词、"按"只是普通介词，二者共现在法规引述里
# 几乎必然发生 → 等于禁止模型引述法规内容。实证：某栋 24 点中 23 点合格，仅
# 因第 4 点写"违反 R4 规则要求修复工作须**按**《建筑物条例》标准执行"整篇退回。
# 修法：锚点必须是**明确指向本次任务/输出行为**的词，领域歧义词不得单独充当锚点。
# 为何不加自指主语约束（原方案②，被 codex 驳回）：汉语常省略主语，"须按提示词
# 格式输出""只能使用该格式"都是真元评论却无自指词，强加会确定性漏检。
_META_TASK_CONTEXT = (
    "提示词",
    # 2026-07-23 codex 审出后删"系统指令/系统提示"：楼宇设备语境撞车
    # （"设备只能遵循系统指令""按系统提示操作"是正常运维正文）。真元评论里
    # 这两词几乎总伴随"提示词/本回答/输出格式"等其它锚点,损失可承受。
    "禁词",
    "本回答",
    "本次回复",
    "点列",
    "信封",
    "字段说明",
    "正文措辞",
    "输出格式",
    "回复格式",
    "任务规则",
    "上述要求",
    # "上述指示"一族补自 2026-07-23 codex 审出的漏检("根据上述指示,本文仅
    # 陈述证据缺口"/"依照前述约束,下面直接给出分析"整句无锚点)。
    "上述指示",
    "前述指示",
    "前述约束",
    # 判定结论词本身即任务语境："避免提及最终裁决"这类是在谈本次输出该不该
    # 写某判定词，而非分析建筑。shape3 只覆盖"元语言式"（「合规」一词/措辞），
    # 此处补"行为式"。
    # ⚠️只收**明确表判定结论的长词**，不整表纳入 `_META_SENSITIVE_TERMS`——
    # 后者含裸"合规"，作子串会命中"符合规定/合规性"等正常合规正文
    # （实测："设备只能使用符合规定格式的记录"被误伤）。
    "最终裁决",
    "最终合规",
    "最终不合规",
    "做出最终裁决",
)
# 元行为词：须明确指向"生成/不生成某内容"。补 `不要出现`/`不得出现`/`不写`
# 一族（2026-07-20 实测漏检"正文中不要出现禁词"）；`依照/撰写/陈述`
# 补自 2026-07-23 codex 审出的漏检（与"上述指示"一族锚点配套）。
_META_COMPLIANCE_BEHAVIORS = (
    "按", "不使用", "避免", "只能", "遵循", "输出", "依照", "撰写", "陈述",
    "不要出现", "不得出现", "不要写", "不得写", "不写", "不要提及", "不得提及",
)
# 锚点的领域碰撞排除（2026-07-23 codex 审出）：锚点作无边界子串会命中的领域
# 长词，匹配前先抹除，防"监测点列表应按…"（含"点列"）、"建筑信封须按…"
# 被 shape2 整篇误杀。用占位符替换而非删除，防抹除后左右字符拼接出新锚点。
# "指示灯/约束条件"补自复核轮："上述指示灯应依照…""前述约束条件应依照…"
# 是正常设备/工程正文，却分别含"上述指示/前述约束"锚点。
_META_CONTEXT_EXCLUSIONS = ("点列表", "建筑信封", "指示灯", "约束条件")
# shape1 自指主语的领域碰撞排除（复核轮审出）："我方/我司"是当事方称谓不是
# 模型自指，却含"我"子串——"我方撰写的报告"会被误杀。
_META_SUBJECT_EXCLUSIONS = ("我方", "我司")
_META_MARKERS = ("一词", "措辞", "表述", "关键词", "引号内")
_SECURITY_LEAK_TOKENS = tuple(
    sorted(
        AGENT_FORBIDDEN_LABELS | AGENT_FORBIDDEN_PROPERTIES | AGENT_FORBIDDEN_FILES,
        key=lambda value: (-len(value), value),
    )
)

_FALLBACK_REASON_RANK = {
    None: -1,
    "submission_format_exhausted": 0,
    "no_analysis_submitted": 0,
    "narrative_rejected_no_retry": 0,
    "narrative_guard_exhausted": 0,
    "status_authority_ambiguous": 0,
    "combined_output_guard_rejected": 1,
    "composed_guard_degraded": 2,
    "orchestrator_exception": 3,
}

# 面向 run_audit 的冻结枚举；orchestrator_exception 是外围异常审计值，不属于
# 正常 v3 叙述状态机的 7 值枚举。
NARRATIVE_FALLBACK_REASONS = (
    "no_analysis_submitted",
    "narrative_rejected_no_retry",
    "narrative_guard_exhausted",
    "combined_output_guard_rejected",
    "composed_guard_degraded",
    "submission_format_exhausted",
    "status_authority_ambiguous",
)

# 中文邻接边界（工单裁定 2）：Python \b 视汉字为词字符——ID/日期/计数 token
# 紧贴汉字时 \b 不成立（「须于2031-01-02前」「open为0」漏杀），而字符类里的
# '-'/'.' 又给 \b 提供回退截断点（「编号BLD-HK-0001的」截成 'BLD-HK-' 误杀）。
# 候选正则不做边界回溯；由 `_bounded_tokens` 对完整 match 手工检查邻字符。
# 前界只排字母数字，允许中文及 ./- 邻接；后界按各 token 语法拒绝截断。
_DATE_PATTERN = re.compile(
    r"(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日)"
)
_BUILDING_ID_PATTERN = re.compile(r"B(?:LD)?-[A-Za-z0-9-]*[A-Za-z0-9]", re.I)
_OBL_ID_HEX_PATTERN = re.compile(r"[0-9a-fA-F]{12,40}")
_RULE_CARD_PATTERN = re.compile(r"rc\.[a-z0-9_.]*[a-z0-9_]")
_FACT_ID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9[])"
    r"(?:F(?:ACT)?-[A-Za-z0-9_.:-]+|[A-Za-z0-9_.-]+::[A-Za-z0-9_.:-]+)",
    re.I,
)
_ZERO_COUNT_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9./-])(open|blocked|violated)(?![A-Za-z0-9-])"
    r"([^0-9]{0,8})0(?![A-Za-z0-9-])"
)
_ZERO_COUNT_NEGATION_PATTERN = re.compile(r"不|非|\bnot\b|!=|≠|大于", re.I)
_NO_COUNT_PATTERNS = {
    "open": re.compile(r"无\s*(?:open|未闭合)(?:\s*义务)?", re.I),
    "blocked": re.compile(r"无\s*(?:blocked|阻塞)(?:\s*义务)?", re.I),
    "violated": re.compile(r"无\s*(?:violated|违规)(?:\s*义务)?", re.I),
}

_MARKDOWN_DELIMITER_RE = re.compile(r"[*_`~]+")
_DASH_TRANSLATION = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u2212": "-",
        "\ufe58": "-",
        "\ufe63": "-",
        "\uff0d": "-",
    }
)


def _safety_scan_view(text: str) -> str:
    """规则 1 的唯一扫描视图；展示/渲染仍保留原始文字。

    NFKC 与 casefold 先收拢全角和大小写变体，Cf 默认可忽略字符直接剥除；
    Markdown 定界符在文本与安全词元两侧同样折叠，因此不能用强调/代码样式
    拆开词元。Unicode 横线统一为 ASCII 连字符，供日期和 ID 形态扫描使用。
    """
    normalized = unicodedata.normalize("NFKC", text).casefold().translate(_DASH_TRANSLATION)
    visible = "".join(ch for ch in normalized if unicodedata.category(ch) != "Cf")
    return _MARKDOWN_DELIMITER_RE.sub("", visible)


def _bounded_tokens(
    pattern: re.Pattern[str],
    text: str,
    *,
    invalid_left: str = r"[A-Za-z0-9]",
    invalid_right: str,
    reject_hyphen_after_alnum: bool = False,
) -> List[str]:
    """Return full-boundary matches; reject a whole match instead of backtracking."""
    tokens: List[str] = []
    for match in pattern.finditer(text):
        left = text[match.start() - 1] if match.start() else ""
        right = text[match.end()] if match.end() < len(text) else ""
        if left and re.match(invalid_left, left):
            continue
        if (
            reject_hyphen_after_alnum
            and left == "-"
            and match.start() >= 2
            and re.match(r"[A-Za-z0-9]", text[match.start() - 2])
        ):
            continue
        if right and re.match(invalid_right, right):
            continue
        tokens.append(match.group(0))
    return tokens


def _date_tokens(text: str) -> List[str]:
    return _bounded_tokens(
        _DATE_PATTERN,
        _safety_scan_view(text),
        invalid_right=r"[A-Za-z0-9-]",
    )


def _report_has_dates_without_real_lookup(
    report_markdown: str, state: "LLMSessionState"
) -> List[str]:
    """返回模型可见工具文本与运行当天日期均不支持的日期 token。"""
    today = datetime.now().astimezone().date()
    allowed_today = {
        today.strftime("%Y-%m-%d"),
        today.strftime("%Y/%m/%d"),
        today.strftime("%Y.%m.%d"),
        f"{today.year}年{today.month}月{today.day}日",
        today.strftime("%Y年%m月%d日"),
    }
    return sorted(
        {
            token
            for token in _date_tokens(report_markdown)
            if token not in state.seen_date_tokens and token not in allowed_today
        }
    )


def _report_has_wrong_building_id(report_markdown: str, state: "LLMSessionState") -> List[str]:
    """返回既非当前 building_id 也非其前缀引用的建筑形态 token。

    工单裁定 3：允许自身 building_id 的至少 12 字符前缀引用；更短 token 不
    具有可靠指向性。此前的 world_id.startswith 是笔误——世界 ID 一律 'WB-' 开头，
    正则只能提取 'B-/BLD-' 形态 token，该子句对全部真实形态是死代码。
    """
    scan_text = _safety_scan_view(report_markdown)
    expected_id = _safety_scan_view(state.building_id)
    tokens = set(
        _bounded_tokens(
            _BUILDING_ID_PATTERN,
            scan_text,
            invalid_right=r"[A-Za-z0-9-]",
            reject_hyphen_after_alnum=True,
        )
    )
    return sorted(
        token
        for token in tokens
        if token != expected_id
        and (len(token) < 12 or not expected_id.startswith(token))
    )


def _report_has_fake_obligation_ids(report_markdown: str, state: "LLMSessionState") -> List[str]:
    """返回不是任一真实 obligation_id（或其前缀）的 12-40 位 hex token。

    与 inspect_obligation 的前缀契约一致：真实 ID 的首 12+ 字符按 startswith
    匹配；12-15 位未知 hex 前缀也必须进入闸门并被拒。
    """
    if state.closure_result is None:
        return []
    real_ids = {
        _safety_scan_view(o.obligation_id)
        for o in state.closure_result.obligation_set.obligations
    }
    hits = set(
        _bounded_tokens(
            _OBL_ID_HEX_PATTERN,
            _safety_scan_view(report_markdown),
            invalid_left=r"[A-Za-z0-9.]",
            invalid_right=r"[A-Za-z0-9-]",
        )
    )
    return sorted(token for token in hits if not any(rid.startswith(token) for rid in real_ids))


def _report_has_fake_rule_card_ids(report_markdown: str, state: "LLMSessionState") -> List[str]:
    """返回不在本次 RuleSlice 内的 rc.* token。"""
    if state.rule_slice is None:
        return []
    real_ids = {
        _safety_scan_view(card.rule_card_id)
        for card in state.rule_slice.candidate_rule_cards
    }
    hits = set(
        _bounded_tokens(
            _RULE_CARD_PATTERN,
            _safety_scan_view(report_markdown),
            invalid_right=r"[A-Za-z0-9-]",
        )
    )
    return sorted(hits - real_ids)


def _report_has_fake_fact_ids(report_markdown: str, state: "LLMSessionState") -> List[str]:
    """返回符合本项目 FactAtom ID 形态、但不在本次 FactPack 内的 token。"""
    if state.fact_pack is None:
        return []
    real_ids = {_safety_scan_view(fact.fact_id) for fact in state.fact_pack.facts}
    return sorted(set(_FACT_ID_PATTERN.findall(_safety_scan_view(report_markdown))) - real_ids)


def _report_has_raw_evidence_ids(report_markdown: str, state: "LLMSessionState") -> List[str]:
    """模型叙述只能用短别名；证据包内真实 ID 即使真实也不得直写。"""
    real_ids = set(state.evidence_pack.alias_map.values()) if state.evidence_pack else set()
    if state.fact_pack is not None:
        real_ids.update(fact.fact_id for fact in state.fact_pack.facts)
    if state.rule_slice is not None:
        real_ids.update(card.rule_card_id for card in state.rule_slice.candidate_rule_cards)
    if state.closure_result is not None:
        real_ids.update(ob.obligation_id for ob in state.closure_result.obligation_set.obligations)
    scan_text = _safety_scan_view(report_markdown)
    return sorted(
        {
            normalized_id
            for real_id in real_ids
            for normalized_id in (_safety_scan_view(real_id),)
            if re.search(
                rf"(?<![A-Za-z0-9.:-]){re.escape(normalized_id)}(?![A-Za-z0-9.:-])",
                scan_text,
            )
        }
    )


def _report_has_false_zero_count_assertions(
    report_markdown: str, state: "LLMSessionState"
) -> List[Dict[str, Any]]:
    """返回与 closure_summary 非零真值冲突的零计数断言。"""
    if state.closure_result is None:
        return []
    summary = state.closure_result.closure_summary
    actual = {
        "open": summary.open_count,
        "blocked": summary.blocked_count,
        "violated": summary.violated_count,
    }
    hits: List[Dict[str, Any]] = []
    for match in _ZERO_COUNT_PATTERN.finditer(report_markdown):
        key = match.group(1).lower()
        if _ZERO_COUNT_NEGATION_PATTERN.search(match.group(2)):
            continue
        if actual[key] > 0:
            hits.append({"token": match.group(0), "expected": actual[key]})
    for key, pattern in _NO_COUNT_PATTERNS.items():
        for match in pattern.finditer(report_markdown):
            # 工单裁定 5：「无 open/blocked/violated」断言同接否定排除——前置
            # 否定语境（「并非无 open 义务」等）实为断言计数非零，不算零断言。
            head = report_markdown[max(0, match.start() - 8) : match.start()]
            if _ZERO_COUNT_NEGATION_PATTERN.search(head):
                continue
            if actual[key] > 0:
                hits.append({"token": match.group(0), "expected": actual[key]})
    return hits


class _DuplicateKeyError(ValueError):
    pass


def _format_error(
    error_code: str, json_pointer: str, expected: Any, actual: Any, fix_hint: str
) -> Dict[str, Any]:
    return {
        "error_code": error_code,
        "json_pointer": json_pointer,
        "expected": expected,
        "actual": actual,
        "fix_hint": fix_hint,
    }


def _actual_shape(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return f"object(len={len(value)})"
    if isinstance(value, list):
        return f"array(len={len(value)})"
    if isinstance(value, str):
        return f"string(len={len(value)})"
    return type(value).__name__


def _strict_object_pairs(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    obj: Dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise _DuplicateKeyError(key)
        obj[key] = value
    return obj


def _strict_json_loads(text: str) -> Tuple[Any, List[Dict[str, Any]]]:
    try:
        return json.loads(text, object_pairs_hook=_strict_object_pairs), []
    except _DuplicateKeyError:
        return None, [
            _format_error(
                "duplicate_key",
                "",
                "unique object keys",
                _actual_shape(text),
                "删除重复对象键后重新提交。",
            )
        ]
    except json.JSONDecodeError as exc:
        code = "trailing_tokens" if exc.msg == "Extra data" else "invalid_json"
        hint = (
            "删除完整 JSON 值后的尾随 token。"
            if code == "trailing_tokens"
            else "提交一个可由标准 json.loads 严格解析的 JSON 值。"
        )
        return None, [
            _format_error(
                code,
                "",
                "one strict JSON value",
                _actual_shape(text),
                hint,
            )
        ]


def parse_synthesized_submission(text: Any) -> Tuple[Any, List[Dict[str, Any]]]:
    """按 v3 单围栏文法解析纯文本合成提交；不提取、不修补。"""
    if not isinstance(text, str):
        return None, [
            _format_error(
                "no_fence",
                "",
                "one closed JSON fence",
                _actual_shape(text),
                "只输出一个闭合的 JSON 代码围栏。",
            )
        ]
    fence_lines = re.findall(r"(?m)^[ \t]*```[^\r\n]*$", text)
    if len(fence_lines) > 2:
        return None, [
            _format_error(
                "multi_fence",
                "",
                "one closed JSON fence",
                f"fence_lines(len={len(fence_lines)})",
                "仅保留一个开围栏和一个闭围栏。",
            )
        ]
    match = re.fullmatch(r"\s*```([^`\r\n]*)\r?\n([\s\S]*?)\r?\n?```\s*", text)
    if match is None or len(fence_lines) != 2:
        return None, [
            _format_error(
                "no_fence",
                "",
                "one closed JSON fence",
                _actual_shape(text),
                "围栏外仅留空白，并提供恰好一个闭合围栏。",
            )
        ]
    language = match.group(1)
    if language not in ("", "json"):
        return None, [
            _format_error(
                "bad_fence_language",
                "",
                "json or empty",
                _actual_shape(language),
                "语言标记改为小写 json，或删除语言标记。",
            )
        ]
    return _strict_json_loads(match.group(2))


def validate_submission_payload(
    payload: Any,
) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """格式层校验；返回 trim 后规范信封或最多五项结构化错误。"""
    errors: List[Dict[str, Any]] = []

    def add(code: str, pointer: str, expected: Any, actual: Any, hint: str) -> None:
        if len(errors) < 5:
            errors.append(_format_error(code, pointer, expected, actual, hint))

    if not isinstance(payload, dict):
        add(
            "root_not_object",
            "",
            "object",
            _actual_shape(payload),
            '使用 {"points":[...]} 对象信封。',
        )
        return None, errors
    if "points" not in payload:
        add("missing_points", "/points", "array", "missing", "添加 points 数组。")
        return None, errors
    points = payload["points"]
    if not isinstance(points, list):
        add("points_type", "/points", "array", _actual_shape(points), "把 points 改为数组。")
        return None, errors
    if not points:
        add(
            "empty_points",
            "/points",
            1,
            _actual_shape(points),
            "从证据包重点项选真实别名、每个重点项写一点。",
        )
        return None, errors
    if len(points) > 24:
        add("too_many_points", "/points", 24, _actual_shape(points), "将点数减至 24 个以内。")
    normalized: List[Dict[str, Any]] = []
    for index, point in enumerate(points):
        pointer = f"/points/{index}"
        if not isinstance(point, dict):
            add("point_field_type", pointer, "object", _actual_shape(point), "每个点必须是对象。")
            continue
        missing = [name for name in ("text", "evidence_aliases") if name not in point]
        for name in missing:
            add("point_field_missing", f"{pointer}/{name}", name, "missing", f"添加 {name} 字段。")
        if missing:
            continue
        text_value = point["text"]
        aliases_value = point["evidence_aliases"]
        text_ok = isinstance(text_value, str)
        alias_ok = isinstance(aliases_value, list)
        trimmed = text_value.strip() if text_ok else ""
        if not text_ok or not trimmed:
            add(
                "point_field_type",
                f"{pointer}/text",
                "non-empty string",
                _actual_shape(text_value),
                "text 必须是 trim 后非空字符串。",
            )
            text_ok = False
        elif any(unicodedata.category(ch) == "Cf" for ch in text_value):
            add(
                "point_field_type",
                f"{pointer}/text",
                "visible string without Cf characters",
                _actual_shape(text_value),
                "text 含不可见字符（Unicode Cf）；删除不可见字符后重交。",
            )
            text_ok = False
        elif len(trimmed) > 500:
            add(
                "text_too_long",
                f"{pointer}/text",
                500,
                _actual_shape(trimmed),
                "将 text 缩短到 500 个 Unicode 码点以内。",
            )
        if text_ok and (
            len(text_value.splitlines()) != 1
            or any(
                unicodedata.category(ch) in {"Cc", "Zl", "Zp"}
                for ch in text_value
            )
        ):
            add(
                "text_multiline",
                f"{pointer}/text",
                "single-line string",
                _actual_shape(trimmed),
                "删除换行、行/段分隔符和控制字符。",
            )
        if not alias_ok:
            add(
                "point_field_type",
                f"{pointer}/evidence_aliases",
                "array",
                _actual_shape(aliases_value),
                "evidence_aliases 必须是数组。",
            )
        else:
            # 重复别名是纯噪声：同一别名列两遍不携带任何额外语义，要求模型手工
            # 去重考不出分析质量，只会白耗有限的格式修复预算（2026-07-20 实证：
            # 某栋两次尝试都卡在 alias_duplicate，内容其实在收敛）。故在校验前
            # **确定性去重**（保序），不再报 alias_duplicate。
            # 注意：这不是放宽叙述闸——数量超限（alias_count）仍拒绝，因为拆点
            # 是模型该做的语义判断，程序替它拆会改变分析结构。
            if all(isinstance(alias, str) for alias in aliases_value):
                deduped = list(dict.fromkeys(aliases_value))
                if len(deduped) != len(aliases_value):
                    point["evidence_aliases"] = deduped
                    aliases_value = deduped
            if not (1 <= len(aliases_value) <= 8):
                add(
                    "alias_count",
                    f"{pointer}/evidence_aliases",
                    "1..8",
                    _actual_shape(aliases_value),
                    "每点提交 1 至 8 个别名；条目多就拆成多个点。",
                )
            for alias_index, alias in enumerate(aliases_value):
                if not isinstance(alias, str) or _BARE_V3_ALIAS_RE.fullmatch(alias) is None:
                    add(
                        "point_field_type",
                        f"{pointer}/evidence_aliases/{alias_index}",
                        "bare alias string",
                        _actual_shape(alias),
                        "别名必须是 O1、R2 或 F3 形态的裸字符串。",
                    )
            if len(set(alias for alias in aliases_value if isinstance(alias, str))) != len(
                aliases_value
            ):
                add(
                    "alias_duplicate",
                    f"{pointer}/evidence_aliases",
                    "unique aliases",
                    _actual_shape(aliases_value),
                    "删除本点内重复别名。",
                )
        alias_tokens_in_text = (
            extract_narrative_alias_tokens(trimmed) if text_ok else []
        )
        bound_aliases = (
            {
                alias
                for alias in aliases_value
                if isinstance(alias, str)
                and _BARE_V3_ALIAS_RE.fullmatch(alias) is not None
            }
            if alias_ok
            else set()
        )
        unbound_text_aliases = [
            alias for alias in alias_tokens_in_text if alias not in bound_aliases
        ]
        if unbound_text_aliases:
            token_list = "、".join(unbound_text_aliases)
            # 回执同时报出本点当前绑定：实证(收官批 PODIUM-0043 点23)模型把相邻
            # 编号搞串(正文 O17、绑定 O24)后两次重试都没修对——旧回执只说"提及了
            # 未绑定的 O17"、不给它看自己绑了什么,模型无从判断该改正文还是改绑定。
            bound_list = "、".join(sorted(bound_aliases)) or "（空）"
            add(
                "alias_in_text",
                f"{pointer}/text",
                "text alias tokens subset of evidence_aliases",
                _actual_shape(trimmed),
                # 三择须完备(2026-07-23 codex 两轮审出):①补绑定须带语义归属
                # 条件——否则错编号恰为全局别名表另一条真实证据时,模型会机械
                # 追加过闸,形成跨点错误关联;②"删除"分支不可丢——编号既非
                # 写错又不属本点论据时,模型须有明确出路。
                f"text 提及了未绑定在本点的别名：{token_list}；"
                f"本点当前绑定：{bound_list}。请核对：若是 text 编号写错，"
                "改为绑定中的正确编号；仅当提及编号所指证据确属本点论据时，"
                "才把它加入 evidence_aliases，不得为通过校验而机械追加；"
                "二者皆非则从 text 中删去该编号。大小写变体须改正。",
            )
        if text_ok and alias_ok:
            normalized.append(
                {
                    "text": trimmed,
                    "evidence_aliases": list(aliases_value),
                }
            )
    if errors:
        return None, errors
    return {"points": normalized}, []


def _payload_sha256(payload: Dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _set_fallback_reason(state: "LLMSessionState", reason: str) -> None:
    if _FALLBACK_REASON_RANK.get(reason, 0) >= _FALLBACK_REASON_RANK.get(
        state.narrative_fallback_reason, -1
    ):
        state.narrative_fallback_reason = reason


def _format_failure_result(
    state: "LLMSessionState", via: str, errors: List[Dict[str, Any]]
) -> Tuple[str, bool]:
    event = {
        "attempt_index": state.submission_format_attempts,
        "via": via,
        "errors": errors[:5],
    }
    state.submission_format_events.append(event)
    pack_payload = (
        _pack_model_payload(state.evidence_pack, state.contract_version)
        if state.evidence_pack else None
    )
    # 顶层提示点名**具体失败位置 + 该点的修法**：泛泛一句"选真实别名"无法告诉
    # 模型第 7 点挂了 16 个别名要拆（2026-07-20 实证：模型能修一部分但漏掉未被
    # 点名的点，白耗修复预算）。逐错去重保序，最多列 5 条，避免提示过长。
    _specific: List[str] = []
    for error in errors:
        pointer_hint = error.get("json_pointer") or ""
        detail = error.get("fix_hint") or error.get("error_code") or ""
        line = f"{pointer_hint}：{detail}" if pointer_hint else str(detail)
        if line and line not in _specific:
            _specific.append(line)
    repair_hint = (
        "逐条修正以下位置后整篇重交：\n" + "\n".join(f"- {x}" for x in _specific[:5])
        if _specific
        else "从证据包重点项选真实别名、每个重点项写一点。"
    )
    # 空点列是模型先交出的格式自检模板：记格式失败与校验次数，但不占用本 run
    # 唯一一次“实质性格式修复”预算。主循环本身有迭代上限，不会因此无限重试。
    is_empty_points_template = bool(errors) and all(
        error.get("error_code") == "empty_points" for error in errors
    )
    # 格式层回执按**会话冻结契约**报版本与样例——v4 模式下报 3/给 v3 样例会教模型
    # 交错形状（终审四轮自查）；读环境而非冻结值会在运行中环境翻转时错版
    # （终审五轮致命#1）。
    _cv = state.contract_version
    if _cv == 4:
        _example = {
            "_note": "样例别名 O0/F0 不存在、不可照抄；用证据包 key_items 内真实别名",
            "contract": "report_contract_v4",
            "points": [
                {
                    "obligation_alias": "O0",
                    "analysis_code": "EVIDENCE_GAP",
                    "selected_fact_aliases": ["F0"],
                    "review_action_code": "OBTAIN_MISSING_EVIDENCE",
                }
            ],
        }
    else:
        _example = {
            "_note": "样例别名 O0 不存在、句子不可照抄；用证据包内真实别名写实质发现",
            "points": [
                {
                    "text": "此处写你自己的发现：某重点项缺什么资料、影响哪项复核。",
                    "evidence_aliases": ["O0"],
                }
            ],
        }
    if is_empty_points_template or state.submission_format_repairs_used == 0:
        repair_budget_consumed = not is_empty_points_template
        if repair_budget_consumed:
            state.submission_format_repairs_used = 1
        receipt = {
            "status": "submission_format_error",
            "error": "submission_format_error",
            "report_contract_version": _cv,
            "event": event,
            "repair_required": True,
            "repair_budget_consumed": repair_budget_consumed,
            "fix_hint": repair_hint,
            "narrative_evidence_pack": pack_payload,
            "example": _example,
        }
        return json.dumps(receipt, ensure_ascii=False), False
    _set_fallback_reason(state, "submission_format_exhausted")
    return json.dumps(
        {
            "status": "deterministic_narrative_fallback",
            "report_contract_version": _cv,
            "narrative_fallback_reason": "submission_format_exhausted",
            "event": event,
            "fix_hint": repair_hint,
            "narrative_evidence_pack": pack_payload,
        },
        ensure_ascii=False,
    ), True


def _key_items_submit_directive(
    pack: NarrativeEvidencePack, contract_version: Optional[int] = None
) -> str:
    """把本 run 的重点项压成最新用户消息里的内容锚，避免模型只交空信封。
    按契约版本给 v3/v4 各自的提交引导（copilot 审出#2：v4 模式下曾仍发 v3 指令）。
    contract_version=None 读环境（会话外场景）；会话内传 state 冻结值。"""
    if contract_version is None:
        contract_version = 4 if report_contract_mode() == "v4" else 3
    if contract_version == 4:
        payload = build_v4_model_payload(pack)
        key_items = payload.get("key_items", [])
        lines = [
            "下一条只输出 report_contract_v4 JSON（提交）：{\"contract\":\"report_contract_v4\","
            "\"points\":[{obligation_alias, analysis_code, selected_fact_aliases, review_action_code}]}。"
            "不要交空 points；每点只这 4 字段、禁任何自由文本。为你认为最该复核的义务各写一点。",
            "本次 key_items（含 suggested_analysis_code 与 allowed_review_actions）：",
        ]
        for item in key_items:
            fas = ",".join(str(v) for v in item.get("fact_aliases", [])) or "无"
            lines.append(
                "- "
                f"{item.get('alias', '未知')} | category={item.get('category') or '未知'}"
                f" | suggested_analysis_code={item.get('suggested_analysis_code')}"
                f" | allowed_review_actions={item.get('allowed_review_actions')}"
                f" | 可选 fact 别名={fas}"
            )
        lines.append(
            "analysis_code 填该义务的 suggested_analysis_code；review_action_code 从"
            " allowed_review_actions 选；selected_fact_aliases 只从该义务的可选 fact 别名选。"
        )
        return "\n".join(lines)
    key_items = pack.to_model_payload().get("key_items", [])
    lines = [
        "下一条只输出 JSON 点列（提交）。不要交空 points；先为每个重点项写一点再提交。"
        "每点最多绑 8 个别名，条目多就拆点。禁止把多张规则卡堆进同一个点；"
        "text 里若提别名，只能提该点 evidence_aliases 已绑定的（最稳妥是"
        "text 不提别名，证据关系交给 evidence_aliases 表达）。",
        "本次 key_items 别名与一行摘要清单：",
    ]
    for item in key_items:
        aliases = ",".join(str(value) for value in item.get("evidence_aliases", [])) or "无"
        slots = ",".join(str(value) for value in item.get("slots", [])) or "无"
        lines.append(
            "- "
            f"{item.get('alias', '未知')} | category={item.get('category') or '未知'}"
            f" | kind={item.get('kind') or '未知'} | reason={item.get('reason_code') or '无'}"
            f" | slots={slots} | 可绑定别名={aliases}"
        )
    lines.append(
        "每点 text 只写事实限制、疑似风险、证据缺口或人工复核动作；"
        "text 可自然提及别名，但提及 token 必须属于本点 evidence_aliases。"
    )
    return "\n".join(lines)


def _clauses(text: str) -> List[str]:
    normalized = unicodedata.normalize("NFKC", text)
    clauses: List[str] = []
    for sentence in _CLAUSE_SPLIT_RE.split(normalized):
        clauses.extend(part.strip() for part in _TURN_BOUNDARY_RE.split(sentence) if part.strip())
    return clauses


def _contains_any(text: str, values: Tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _strip_tokens(clause: str, tokens: Tuple[str, ...]) -> str:
    stripped = clause
    for token in tokens:
        stripped = stripped.replace(token, "□")
    return stripped


def _meta_task_context_hit(clause: str) -> bool:
    return _contains_any(
        _strip_tokens(clause, _META_CONTEXT_EXCLUSIONS), _META_TASK_CONTEXT
    )


def _meta_self_subject_hit(clause: str) -> bool:
    return _contains_any(
        _strip_tokens(clause, _META_SUBJECT_EXCLUSIONS), _META_SELF_SUBJECTS
    )


def _meta_commentary_hits(text: str) -> List[str]:
    hits: List[str] = []
    for clause in _clauses(text):
        shape1 = _meta_self_subject_hit(clause) and _contains_any(
            clause, _META_OUTPUT_BEHAVIORS
        )
        # shape2：省略主语的"输出规则说明"。锚点须是明确任务元语境词
        # （提示词/禁词/点列/输出格式…），不能是"规则/要求/格式"这类
        # 合规正文高频歧义词——后者与"按"共现在法规引述中几乎必然发生。
        shape2 = _meta_task_context_hit(clause) and _contains_any(
            clause, _META_COMPLIANCE_BEHAVIORS
        )
        shape3 = _contains_any(clause, _META_SENSITIVE_TERMS) and _contains_any(
            clause, _META_MARKERS
        )
        if shape1 or shape2 or shape3:
            hits.append("删除任务规则说明，只保留实质性分析")
    return hits


def _security_leak_hits(text: str) -> List[str]:
    scan_text = _safety_scan_view(text)
    return [
        token
        for token in _SECURITY_LEAK_TOKENS
        if _safety_scan_view(token) in scan_text
    ]


def _non_overlapping_token_count(text: str, tokens: Tuple[str, ...]) -> int:
    pattern = re.compile(
        "|".join(re.escape(token) for token in sorted(tokens, key=len, reverse=True))
    )
    return sum(1 for _ in pattern.finditer(text))


def _predicate_is_positive(clause: str, predicate_start: int) -> bool:
    head = clause[max(0, predicate_start - _MODAL_SCOPE_CODEPOINTS) : predicate_start]
    # 逗号不拆“分句”，但它隔开同分句内并列状态言语行为；极性窗口不得让前一
    # 次谓词的否定词支配后一谓词（如“尚未结案，现已结案”）。
    head = re.split(r"[，,：:、]", head)[-1]
    if _contains_any(head, _UNCERTAIN_MODAL_TOKENS):
        return False
    negations = _non_overlapping_token_count(head, _NEGATIVE_MODAL_TOKENS)
    if negations:
        return negations % 2 == 0
    if _contains_any(head, _POSITIVE_MODAL_TOKENS):
        return True
    return not head.strip() or _contains_any(head, _STATUS_SUBJECTS)


def _obligation_authority_status(obligation: Obligation) -> str:
    """Collapse closure/satisfaction into the authority status used by rule A/B."""
    if obligation.closure_status in {"open", "blocked"}:
        return str(obligation.closure_status)
    return str(obligation.satisfaction_status)


def _obligation_status_index(state: "LLMSessionState") -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = {}
    if state.closure_result is None:
        return index
    for obligation in state.closure_result.obligation_set.obligations:
        index.setdefault(str(obligation.obligation_id), []).append(
            _obligation_authority_status(obligation)
        )
    return index


def _obligation_reason_index(
    state: "LLMSessionState",
) -> Dict[str, Dict[str, List[str]]]:
    index: Dict[str, Dict[str, List[str]]] = {}
    if state.closure_result is None:
        return index
    for obligation in state.closure_result.obligation_set.obligations:
        item = index.setdefault(
            str(obligation.obligation_id),
            {"open_reason_codes": [], "blocked_reason_codes": []},
        )
        for field_name in ("open_reason_code", "blocked_reason_code"):
            value = getattr(obligation, field_name, None)
            if value is not None:
                item[f"{field_name}s"].append(str(value))
    return index


def _point_obligation_authorities(
    point: Dict[str, Any], state: "LLMSessionState"
) -> Dict[str, Dict[str, Any]]:
    """Resolve only directly bound O aliases; R/F aliases never carry status authority."""
    pack = state.evidence_pack
    alias_map = pack.alias_map if pack is not None else {}
    status_index = _obligation_status_index(state)
    reason_index = _obligation_reason_index(state)
    authorities: Dict[str, Dict[str, Any]] = {}
    for alias in point["evidence_aliases"]:
        if re.fullmatch(r"O[0-9]+", alias) is None or alias not in alias_map:
            continue
        obligation_id = str(alias_map[alias])
        reasons = reason_index.get(obligation_id, {})
        authorities[alias] = {
            "obligation_id": obligation_id,
            "statuses": sorted(set(status_index.get(obligation_id, []))),
            "open_reason_codes": sorted(
                set(reasons.get("open_reason_codes", []))
            ),
            "blocked_reason_codes": sorted(
                set(reasons.get("blocked_reason_codes", []))
            ),
        }
    return authorities


def _status_authority_ambiguities(
    payload: Dict[str, Any], state: "LLMSessionState"
) -> List[Dict[str, Any]]:
    """Return bound O ids whose duplicate instances disagree on authority status."""
    ambiguities: List[Dict[str, Any]] = []
    for point_index, point in enumerate(payload["points"]):
        authorities = _point_obligation_authorities(point, state)
        grouped: Dict[str, Dict[str, Any]] = {}
        for alias, authority in authorities.items():
            obligation_id = authority["obligation_id"]
            group = grouped.setdefault(
                obligation_id,
                {"aliases": [], "statuses": authority["statuses"]},
            )
            group["aliases"].append(alias)
        for obligation_id, group in grouped.items():
            if len(group["statuses"]) > 1:
                ambiguities.append(
                    {
                        "point_index": point_index,
                        "obligation_id": obligation_id,
                        "aliases": group["aliases"],
                        "statuses": group["statuses"],
                    }
                )
    return ambiguities


def _status_escalation_candidate_hits(text: str) -> List[str]:
    """Raw candidate-predicate matches for rule A's advisory probe.

    No polarity/condition/uncertainty filtering: rule A is advisory-only, so
    条件/否定/不确定/承认词 no longer whitewash a hit（they may at most annotate
    the audit event out of band）. Returns non-overlapping longest matches.
    """
    normalized = unicodedata.normalize("NFKC", text)
    return [
        match.group(0)
        for match in _OBLIGATION_STATUS_ESCALATION_PATTERN.finditer(normalized)
    ]


def _status_escalation_advisory_details(
    point: Dict[str, Any], point_index: int, state: "LLMSessionState"
) -> List[Dict[str, Any]]:
    """Rule A advisory probe (never rejects / burns budget / triggers fallback).

    Records a warning only after final atomic acceptance (two-phase, bug6):
    candidate predicate hit AND (no bound O, or bound O not all ``violated``).
    All-``violated`` bindings are the one case that legitimately asserts
    violation, so they raise no advisory. DEBT-054 status collisions are handled
    before this runs, so every bound authority carries exactly one status.
    """
    candidate_hits = _status_escalation_candidate_hits(point["text"])
    if not candidate_hits:
        return []
    authorities = _point_obligation_authorities(point, state)
    if authorities and all(
        item["statuses"] == ["violated"] for item in authorities.values()
    ):
        return []
    return [
        {
            "point_index": point_index,
            "subtype": "status_escalation_advisory",
            "advisory_only": True,
            "candidate_hits": candidate_hits,
            "obligation_statuses": {
                alias: item["statuses"] for alias, item in authorities.items()
            },
        }
    ]


def _status_consistency_details(
    point: Dict[str, Any], point_index: int, state: "LLMSessionState"
) -> List[Dict[str, Any]]:
    """Apply rule B only (homogeneous O bindings); rule A is now advisory-only.

    Rule A（词法违规谓词）no longer hard-rejects — it records an advisory audit
    event after acceptance via ``_status_escalation_advisory_details``. Rule B
    stays a hard reject because it keys off structured O-binding status, not
    Chinese syntax, so it is reliable.
    """
    authorities = _point_obligation_authorities(point, state)
    # DEBT-054 collisions are handled before narrative budget accounting; do not
    # mislabel the same authority failure as a model-authored status escalation.
    if any(len(item["statuses"]) > 1 for item in authorities.values()):
        return []

    details: List[Dict[str, Any]] = []
    if len(authorities) > 1:
        bound_statuses = {
            status
            for item in authorities.values()
            for status in item["statuses"]
        }
        if "satisfied" in bound_statuses and bound_statuses.intersection(
            {"violated", "open", "blocked", "not_applicable"}
        ):
            details.append(
                {
                    "point_index": point_index,
                    "subtype": "mixed_satisfied_binding",
                    "obligation_statuses": {
                        alias: item["statuses"] for alias, item in authorities.items()
                    },
                    "hint": "拆点或按状态分组绑定",
                }
            )
    return details


def _status_rule_hits(text: str, *, allow_stop: bool) -> Tuple[List[str], List[str]]:
    final_hits: List[str] = []
    branch_hits: List[str] = []
    for clause in _clauses(text):
        for predicate in _FINAL_STATUS_PREDICATES:
            for match in re.finditer(re.escape(predicate), clause):
                if _predicate_is_positive(clause, match.start()):
                    final_hits.append(predicate)
        if not allow_stop:
            for predicate in _BRANCH_STATUS_PREDICATES:
                for match in re.finditer(re.escape(predicate), clause):
                    if _predicate_is_positive(clause, match.start()):
                        branch_hits.append(predicate)
    return final_hits, branch_hits


# 覆盖上方 v2 Markdown 入口；v3 只接受已经过格式层的对象信封。
def narrative_guard(payload: Dict[str, Any], state: "LLMSessionState") -> List[Dict[str, Any]]:
    """逐点检查、整篇原子接纳；格式病不得进入本函数。"""
    rejections: List[Dict[str, Any]] = []
    status_details: List[Dict[str, Any]] = []
    pack = state.evidence_pack
    alias_map = pack.alias_map if pack is not None else {}
    unknown_aliases: List[str] = []
    for point in payload["points"]:
        unknown_aliases.extend(
            alias for alias in point["evidence_aliases"] if alias not in alias_map
        )
    if unknown_aliases:
        rejections.append(
            {
                "code": REJECT_UNRESOLVED_ALIAS,
                "detail": list(dict.fromkeys(unknown_aliases)),
            }
        )

    def add(code: str, detail: Any) -> None:
        if not any(item["code"] == code for item in rejections):
            rejections.append({"code": code, "detail": detail})

    for point_index, point in enumerate(payload["points"]):
        text = point["text"]
        fabricated_dates = _report_has_dates_without_real_lookup(text, state)
        if fabricated_dates:
            add(REJECT_FABRICATED_DATE, fabricated_dates)
        wrong_buildings = _report_has_wrong_building_id(text, state)
        if wrong_buildings:
            add(REJECT_WRONG_BUILDING_ID, wrong_buildings)
        fake_obligations = _report_has_fake_obligation_ids(text, state)
        if fake_obligations:
            add(REJECT_FAKE_OBLIGATION_ID, fake_obligations)
        fake_rule_cards = _report_has_fake_rule_card_ids(text, state)
        if fake_rule_cards:
            add(REJECT_FAKE_RULE_CARD_ID, fake_rule_cards)
        fake_facts = _report_has_fake_fact_ids(text, state)
        if fake_facts:
            add(REJECT_FAKE_FACT_ID, fake_facts)
        raw_ids = _report_has_raw_evidence_ids(text, state)
        if raw_ids:
            add(REJECT_RAW_EVIDENCE_ID, raw_ids)
        leak_hits = _security_leak_hits(text)
        if leak_hits:
            add(REJECT_FORBIDDEN_PHRASE, leak_hits)
        meta_hits = _meta_commentary_hits(text)
        if meta_hits:
            add(REJECT_META_COMMENTARY, meta_hits)
            continue
        status_details.extend(
            _status_consistency_details(point, point_index, state)
        )
        final_hits, branch_hits = _status_rule_hits(
            text,
            allow_stop=bool(state.closure_result and state.closure_result.allow_stop),
        )
        if final_hits:
            add(REJECT_FORBIDDEN_PHRASE, final_hits)
        if branch_hits:
            add(REJECT_BRANCH_INCONSISTENT, branch_hits)
    if status_details:
        add(REJECT_STATUS_ESCALATION, status_details)
    return rejections


def _ensure_evidence_pack(state: "LLMSessionState") -> Optional[NarrativeEvidencePack]:
    """构造（幂等）本次 run 的叙述证据包；证据包文本内的日期入模型可见白名单。

    证据包随 run_closure_verification 返回给模型（模型可见工具文本），其中
    rule card 引文 / fact 值可能含日期 token——预先记入 seen_date_tokens，
    确保引用证据包内容的叙述（含确定性模板）不被日期闸误杀。
    """
    if state.evidence_pack is None and state.closure_result is not None:
        state.evidence_pack = build_narrative_evidence_pack(
            state.closure_result, state.rule_slice, state.fact_pack
        )
        pack_text = json.dumps(
            _pack_model_payload(state.evidence_pack, state.contract_version),
            ensure_ascii=False,
        )
        state.seen_date_tokens.update(_date_tokens(pack_text))
    return state.evidence_pack


def _narrative_system_prompt(base_prompt: str, pack: Optional[NarrativeEvidencePack]) -> str:
    """返回原生 v3 提示词；证据包由工具结果/格式层回执携带。"""
    del pack
    return base_prompt.rstrip() + "\n"


# ---------------------------------------------------------------------------
# 主编排
# ---------------------------------------------------------------------------
@dataclass
class LLMOrchestratorResult:
    """LLM-driven 编排的最终交付（供 RunOrchestrator 持久化；契约 v2）。"""

    state: LLMSessionState
    report_markdown: str  # 组合终稿：程序骨架 + 已接纳分析/确定性叙述（别名已展开）
    report_passed_output_guard: bool
    tool_call_count: int
    iterations_used: int
    # llm_forced_finalize 原义（契约 v2 修订 5 明确保持）：LLM 在
    # max_tool_iterations 内未调用提交工具（submit_analysis；迁移期
    # finalize_report 别名视同调用）、由编排器强制结束。叙述被拒不算。
    forced_finalize: bool
    # ---- 报告契约 v3 格式/叙述审计 ----
    report_contract_version: int = 3
    llm_narrative_accepted: bool = False
    llm_narrative_attempts: int = 0
    llm_narrative_rejection_codes: List[str] = field(default_factory=list)
    narrative_fallback_reason: Optional[str] = None
    submission_format_attempts: int = 0
    submission_format_repairs_used: int = 0
    submission_format_events: List[Dict[str, Any]] = field(default_factory=list)
    accepted_via: Optional[str] = None
    accepted_point_count: Optional[int] = None
    accepted_payload_sha256: Optional[str] = None


def run_llm_orchestration(
    *,
    world_id: str,
    building_id: str,
    run_id: str,
    retrieval_fn: Callable[[str, str, str], Tuple[FactPack, RuleSlice]],
    closure_fn: Callable[[RuleSlice, FactPack, Any], ClosureValidationResult],
    llm_client: Optional[LLMClient] = None,
    kg_client: Any = None,
    verifier_config: Any = None,
    extra_user_directive: Optional[str] = None,
    evo_policy: Optional[EvoPolicyVersion] = None,
    active_skill_set: Optional[List[SkillJson]] = None,
    kg_snapshot_id: str = "",
    rulecard_bundle_id: str = "",
    narrative_retry_limit: int = DEFAULT_NARRATIVE_RETRY_LIMIT,
    state_observer: Optional[Callable[[LLMSessionState], None]] = None,
) -> LLMOrchestratorResult:
    """LLM-as-brain 主循环（spec §5.2 + §7；v1 §5.2 evo_mode hooks；契约 v2）。

    入参：
    - world_id / building_id / run_id：目标评估的标识；
    - retrieval_fn / closure_fn：跟 deterministic RunOrchestrator 同样的依赖注入入口；
    - llm_client：注入的 LLM 客户端；None 时构造默认（Ollama 本机）；
    - verifier_config：透传给 closure_fn 的配置；
    - extra_user_directive：第一轮 user 消息附加指令（默认即"请生成本建筑闭包评估"）。
    - evo_policy / active_skill_set：v1 evo_mode 参数；缺省时跟现行 baseline 一致。
      传入时 session state 记录 policy_version_id + active_skill_version_ids，
      并写 skill_invocation_log（spec v1 §5.1 ComplianceAssessmentRunV1）。
    - kg_snapshot_id / rulecard_bundle_id：run 溯源元数据（RunOrchestrator 持有），
      供 v2 程序骨架渲染完整的资料范围 / rule card 切片节（工单裁定 8）。
    - narrative_retry_limit：叙述节局部重试次数，clamp 到契约 v2 允许区间 [1,2]
      （默认 2）；重试只针对叙述节，不重跑检索 / 闭包。

    返回 `LLMOrchestratorResult`：
    - state.fact_pack / rule_slice / closure_result：deterministic 产物；
    - report_markdown：契约 v2 组合终稿（程序骨架 + 已接纳的模型分析或确定性
      叙述模板，别名已展开，已过输出守卫）；
    - report_passed_output_guard：组合终稿是否过守卫（确定性兜底稿按构造洁净，
      正常恒为 True）；
    - forced_finalize：True 表示 LLM 在循环上限内未调提交工具（原义不变）；
    - llm_narrative_* / narrative_fallback_reason：叙述审计四字段数据源。

    spec v1 §1 + §6 不变量：active_skill_set / evo_policy 不影响 allow_stop /
    closure_status / satisfaction_status；只影响 retrieval ranking + tool 顺序
    + report 结构。verifier 仍是唯一权威（spec v1 §6.3）。
    """
    client = llm_client or LLMClient()
    # 契约 v2：重试次数配置只允许 [1,2]，越界 clamp（不抛，防批跑配置事故）。
    retry_lo, retry_hi = NARRATIVE_RETRY_LIMIT_RANGE
    narrative_retry_limit = max(retry_lo, min(retry_hi, int(narrative_retry_limit)))
    state = LLMSessionState(
        world_id=world_id,
        building_id=building_id,
        run_id=run_id,
        kg_client=kg_client,
        kg_snapshot_id=kg_snapshot_id,
        rulecard_bundle_id=rulecard_bundle_id,
        narrative_retry_limit=narrative_retry_limit,
        evo_policy_version_id=(evo_policy.policy_version_id if evo_policy else None),
        active_skill_version_ids=sorted(s.skill_version_id for s in (active_skill_set or [])),
    )
    if state_observer is not None:
        state_observer(state)
    # 记录初始 skill_invocation_log（active set 注入即视为 baseline activation）
    if active_skill_set:
        state.skill_invocation_log.append(
            {
                "stage": "session_init",
                "active_skill_version_ids": list(state.active_skill_version_ids),
                "evo_policy_version_id": state.evo_policy_version_id,
            }
        )

    # 契约版本在 state 创建时已冻结（唯一 env 读取点，copilot 终审五轮致命#1：
    # 各路径各自重读环境会在运行中翻转时让 v4 会话接纳 v3 自由文本）。
    # 本函数与所有下游（提示词/工具 schema/回执/提交校验/渲染）只用这个冻结值。
    _cv = state.contract_version
    base_system_prompt = load_system_prompt(_cv)
    system_prompt = _narrative_system_prompt(base_system_prompt, None)
    if extra_user_directive:
        user_directive = extra_user_directive
    elif _cv == 4:
        user_directive = (
            f"请对 building_id={building_id} 跑一次完整 MBIS 合规闭包评估"
            f"（报告契约 v4）。\n\n"
            f"按 tool 的 next_actions 一步步走：retrieve_facts → retrieve_rules → "
            f"run_closure（返回闭包摘要 + narrative_evidence_pack，key_items 含 "
            f"suggested_analysis_code/allowed_review_actions）→ 可选深入 → submit_analysis "
            f"提交 report_contract_v4 结构化点列（每点只 obligation_alias/analysis_code/"
            f"selected_fact_aliases/review_action_code 四字段，禁自由文本）；"
            f"规则/状态/原因/句子全由程序权威渲染。"
        )
    else:
        user_directive = (
            f"请对 building_id={building_id} 跑一次完整 MBIS 合规闭包评估"
            f"（报告契约 v3）。\n\n"
            f"按 tool 的 next_actions 提示一步步走：retrieve_facts → retrieve_rules"
            f" → run_closure（返回权威闭包摘要 + 叙述证据包 narrative_evidence_pack）"
            f"→ 可选 query_open / inspect_obligation / lookup_rule_card 深入 → "
            f"submit_analysis 提交 JSON 点列。每点只写事实限制、疑似风险、"
            f"证据缺口或人工复核动作，text 与 evidence_aliases 分离；"
            f"完整报告骨架由程序确定性渲染。"
        )
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_directive},
    ]

    tool_call_count = 0
    # 契约 v2：循环里只等 submit_analysis 收档信号（接纳或叙述重试耗尽），
    # 组合终稿在循环外由程序渲染（state.accepted_payload / narrative_* 携带结果）。

    # 已经发过 submit_analysis 引导提示的次数，防无限引导。
    stuck_retry_count = 0
    MAX_STUCK_RETRIES = 2

    for iteration in range(client.config.max_tool_iterations):
        turn = client.chat(messages, tools=active_llm_tools(_cv), iteration=iteration)
        state.turns.append(turn)

        # LLM 既没调工具 又没给 content 文本 → "卡住"
        # 给一条 user 消息引导它用 submit_analysis；MAX_STUCK_RETRIES 次后放弃。
        if not turn.tool_calls and not turn.response_text.strip():
            if stuck_retry_count < MAX_STUCK_RETRIES and state.closure_result is not None:
                stuck_retry_count += 1
                messages.append({"role": "assistant", "content": ""})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "你已经拿到了 closure 验证结果，现在请直接用 "
                            "`submit_analysis` 工具提交分析（字段按工具 schema）。"
                            "只写实质性分析，不要再调其它工具。"
                        ),
                    }
                )
                continue
            break

        # LLM 没调工具但有文本 → 把 content 当分析节候选（少数模型
        # finish_reason=stop / length，直接吐 markdown 而不调 submit_analysis tool）。
        # 这条 fallback path 必须也过叙述节闸，否则 LLM 绕过 tool 直接出文本会
        # 越过所有防编造守卫（契约 v2 下同走 narrative_guard + 局部重试预算）。
        if not turn.tool_calls:
            candidate_analysis = turn.response_text.strip()
            synthesized_payload, synthesized_errors = parse_synthesized_submission(
                candidate_analysis
            )
            submit_tool_called_before_synthesis = state.submit_tool_called
            gate_text, gate_finalize_this = _execute_tool(
                tool_name="submit_analysis",
                args=synthesized_payload,
                state=state,
                retrieval_fn=retrieval_fn,
                closure_fn=closure_fn,
                verifier_config=verifier_config,
                submission_via="synthesized_json",
                submission_parse_errors=synthesized_errors,
                submission_raw_payload=turn.response_text,
            )
            if state.evidence_pack is not None:
                messages[0] = {
                    "role": "system",
                    "content": _narrative_system_prompt(base_system_prompt, state.evidence_pack),
                }
            # 编排器合成提交不等于 LLM 真调 submit_analysis；恢复原值，保持
            # llm_forced_finalize 字段的历史字面口径。
            state.submit_tool_called = submit_tool_called_before_synthesis
            state.submission_audit_events.append(
                {
                    "event": "response_text_synthesized_submission",
                    "iteration": iteration,
                    "accepted": state.accepted_via == "synthesized_json",
                }
            )
            state.tool_log.append(
                {
                    "iteration": iteration,
                    "tool": "submit_analysis",
                    "args": {"_via": "response_text_fallback"},
                    "result_preview": gate_text[:200],
                }
            )
            if gate_finalize_this:
                break
            # 未接纳且相应修复预算还有 → 把分层回执推给 LLM；格式病不得误称
            # 叙述闸拒绝，否则模型会按错误层级修稿并继续空点列循环。
            try:
                gate_body = json.loads(gate_text)
            except json.JSONDecodeError:  # pragma: no cover - tool 回执均由 json.dumps 生成
                gate_body = {}
            is_format_receipt = gate_body.get("status") == "submission_format_error"
            receipt_name = "格式层回执" if is_format_receipt else "内容层回执"
            messages.append({"role": "assistant", "content": turn.response_text or ""})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"你刚才直接输出的提交未接纳，以下是{receipt_name}。"
                        "请改用 `submit_analysis` 工具按回执修复提交信封（按当前契约字段）——"
                        "不要再以纯文本输出。\n\n"
                        f"回执：{gate_text}"
                    ),
                }
            )
            continue

        # 把 LLM 的 assistant message 加回（含 tool_calls，OpenAI 要求）
        assistant_msg: Dict[str, Any] = {
            "role": "assistant",
            "content": turn.response_text or "",
        }
        assistant_msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments_json"],
                },
            }
            for tc in turn.tool_calls
        ]
        messages.append(assistant_msg)

        # 处理本轮所有 tool_call
        finalize_called = False
        for tc in turn.tool_calls:
            tool_call_count += 1
            tool_name = tc["name"]
            submission_parse_errors: List[Dict[str, Any]] = []
            if tool_name in ("submit_analysis", "finalize_report"):
                args, submission_parse_errors = _strict_json_loads(tc["arguments_json"] or "{}")
            else:
                try:
                    args = json.loads(tc["arguments_json"] or "{}")
                except json.JSONDecodeError:
                    args = {}

            tool_result_text, finalize_this = _execute_tool(
                tool_name=tool_name,
                args=args,
                state=state,
                retrieval_fn=retrieval_fn,
                closure_fn=closure_fn,
                verifier_config=verifier_config,
                submission_parse_errors=submission_parse_errors,
                submission_raw_payload=(
                    tc["arguments_json"]
                    if tool_name in ("submit_analysis", "finalize_report")
                    else None
                ),
            )
            if state.evidence_pack is not None:
                messages[0] = {
                    "role": "system",
                    "content": _narrative_system_prompt(base_system_prompt, state.evidence_pack),
                }

            state.tool_log.append(
                {
                    "iteration": iteration,
                    "tool": tool_name,
                    "args": args,
                    "result_preview": tool_result_text[:200],
                }
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": tool_result_text,
                }
            )

            if finalize_this:
                finalize_called = True

        if finalize_called:
            break

        if state.evidence_pack is not None and not state.evidence_pack.alias_map:
            _set_fallback_reason(state, "no_analysis_submitted")
            break

        # ---- b 件（EXP-013 时序适配）：证据包首次就绪后追加一次定向提交
        # 提示——治 attempt-1 计划/元评论散文白烧（60/60 合成提交实证）。
        # 幂等：每 run 最多一次；只在同轮全部 tool result 入队之后追加，
        # 不插在并行 tool result 中间；重复调用 closure 不重复催交。
        if (
            state.evidence_pack is not None
            and not state.submit_directive_injected
            and state.accepted_payload is None
        ):
            state.submit_directive_injected = True
            messages.append(
                {
                    "role": "user",
                    "content": _key_items_submit_directive(
                        state.evidence_pack, state.contract_version
                    ),
                }
            )

    iterations_used = len(state.turns)
    # llm_forced_finalize 原义（契约 v2 修订 5）：LLM 在轮内未调提交工具
    # （submit_analysis / 迁移期 finalize_report 别名视同调用）。叙述被拒 /
    # 重试耗尽不算（那由 llm_narrative_* 四字段表达）。
    forced_finalize = not state.submit_tool_called

    # ----- 强制 backbone（spec §1.0 原则 1） -----
    # 无论 LLM 是否完成检索 / closure，最终交付前必须保证 deterministic 已跑过。
    # 叙述校验 / 局部重试 / fallback 均不触发闭包重算——这里只补"从未跑过"的缺口。
    if state.fact_pack is None or state.rule_slice is None:
        state.fact_pack, state.rule_slice = retrieval_fn(world_id, building_id, run_id)
    if state.closure_result is None:
        # 让 closure_fn 自己处理 None config 的兜底（每个实现可不同）
        state.closure_result = closure_fn(state.rule_slice, state.fact_pack, verifier_config)

    # ----- 契约 v2 组合终稿：程序骨架 + 唯一分析节槽位 -----
    pack = _ensure_evidence_pack(state)
    closure = state.closure_result
    allow_stop = closure.allow_stop

    llm_narrative_accepted = state.accepted_payload is not None
    if llm_narrative_accepted and (
        state.accepted_payload.get("contract") == "report_contract_v4"
    ):
        # 报告契约 v4：确定性组装（spec §7.4.5）。全篇预渲染已在接纳时验过必成功；
        # 保守起见此处 None 仍回退确定性模板（E-5.4③ fail-closed）。
        v4_lines = render_v4_points(pack, state.accepted_payload["points"])
        if v4_lines is None:
            llm_narrative_accepted = False
            state.narrative_fallback_reason = "narrative_rejected_no_retry"
            narrative = render_deterministic_narrative(pack)
        else:
            narrative = "\n".join(v4_lines)
    elif llm_narrative_accepted:
        narrative = render_structured_narrative_points(
            state.accepted_payload["points"], pack.alias_map
        )
    else:
        # 确定性叙述模板兜底；narrative_fallback_reason 给出明确原因
        # （提交但被拒且已耗尽的场景在 submit 分支已写 narrative_guard_exhausted）。
        if state.narrative_fallback_reason is None:
            state.narrative_fallback_reason = (
                "no_analysis_submitted"
                if state.narrative_attempts == 0
                else "narrative_rejected_no_retry"
            )
        narrative = render_deterministic_narrative(pack)

    def _compose(narrative_text: str) -> str:
        return render_contract_v2_report(
            closure,
            world_id=state.world_id,
            building_id=state.building_id,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            kg_snapshot_id=state.kg_snapshot_id,
            rulecard_bundle_id=state.rulecard_bundle_id,
            fact_source_tables=(list(state.fact_pack.source_tables) if state.fact_pack else None),
            rule_families=(_rule_family_rows(state.rule_slice) if state.rule_slice else None),
            evidence_pack=pack,
            analysis_markdown=narrative_text,
            analysis_is_llm=llm_narrative_accepted,
            # 版本按 run 开始时冻结的活动契约（_cv）定，不看是否接纳——v4 模式下
            # 回退稿也是 v4 模式的 run，标 v3 会误导审计/离线重渲染归档
            # （2026-07-23 copilot 终审四轮审出）。
            contract_version=_cv,
        )

    final_report = _compose(narrative)

    def _clear_final_acceptance() -> None:
        """终局未接纳时清空内容阶段的暂存接纳与暂存审计（含 pending，bug6）。"""
        nonlocal llm_narrative_accepted
        llm_narrative_accepted = False
        state.accepted_payload = None
        state.accepted_via = None
        state.accepted_payload_sha256 = None
        state.pending_acceptance_audit_events = []

    # ----- 组合终稿输出守卫（spec §7.3.6；契约 v2 修订 4）-----
    # 组合守卫失败不得回写或改变 verifier 结果；拒绝收档该稿，改用安全的
    # 确定性组合终稿（骨架 + 确定性叙述模板，按构造即守卫洁净）。
    passed_guard = True
    initial_guard_passed = True
    composed_guard_audit: Optional[Dict[str, Any]] = None
    try:
        skeleton_audit = pre_output_language_guard(_compose(""))
    except OutputGuardError:
        initial_guard_passed = False
    else:
        composed_guard_audit = {
            "guard": "pre_output_language_guard",
            "passed": True,
            "mode": ("composed_split_v4" if _cv == 4 else "composed_split_v3"),
            "skeleton": skeleton_audit,
            "narrative_slot": {
                # 按冻结契约标（终审五轮中#1：按接纳载荷倒推时 v4 回退稿会误标 v3 守卫）
                "guard": ("v4_structured_narrative_guard" if _cv == 4
                          else "v3_point_narrative_guard"),
                "passed": True,
            },
        }
    if not initial_guard_passed:
        _clear_final_acceptance()
        _set_fallback_reason(state, "combined_output_guard_rejected")
        final_report = _compose(render_deterministic_narrative(pack))
        try:
            composed_guard_audit = pre_output_language_guard(final_report)
        except OutputGuardError:
            # 数据携带内容（法规原文、fact value、notes 等）也可能命中禁话术。
            # 二次失败不得拖垮 run：保留骨架/权威计数，数据正文降为 ID 引用。
            _clear_final_acceptance()
            _set_fallback_reason(state, "composed_guard_degraded")
            final_report = render_contract_v2_report(
                closure,
                world_id=state.world_id,
                building_id=state.building_id,
                generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                kg_snapshot_id=state.kg_snapshot_id,
                rulecard_bundle_id=state.rulecard_bundle_id,
                fact_source_tables=(
                    list(state.fact_pack.source_tables) if state.fact_pack else None
                ),
                rule_families=(_rule_family_rows(state.rule_slice) if state.rule_slice else None),
                evidence_pack=pack,
                analysis_markdown=(
                    "### 守卫安全降级说明\n\n"
                    "- 数据正文未在本稿展开；请按下列 obligation / rule card / "
                    "fact ID 回查权威运行产物并由人工复核。"
                ),
                analysis_is_llm=False,
                guard_safe_data=True,
                # 降级稿同样按冻结契约标版本（终审五轮中#2：缺省落 3，
                # 正文横幅与审计/结果版本自相矛盾）。
                contract_version=_cv,
            )
            composed_guard_audit = pre_output_language_guard(final_report)

    state.composed_guard_audit = composed_guard_audit

    # 两阶段接纳审计并入（bug6）：只有组合守卫全过、终局仍为 LLM 接纳，才把内容
    # 层暂存的 advisory 审计并入权威 submission_audit_events。被降级/撤销的稿在
    # _clear_final_acceptance 已清空 pending，天然不落非接纳终稿的审计。
    if llm_narrative_accepted and state.pending_acceptance_audit_events:
        state.submission_audit_events.extend(state.pending_acceptance_audit_events)
        state.pending_acceptance_audit_events = []

    # ----- 组合终稿断言检查（迁移自 v1 标题闸 / 结构闸）-----
    # v1 的 missing_nonfinal_title / 结构闸随契约 v2 失效——骨架程序渲染后天然
    # 满足；此处只保留断言：标题必须与 allow_stop 分支一致。违规=程序 bug。
    expected_title = (
        "# MBIS 辅助审查报告（非最终裁决）" if allow_stop else "# MBIS 闭包未完成说明（非最终裁决）"
    )
    if not final_report.startswith(expected_title):
        raise RuntimeError(
            "report contract v3 invariant broken: 组合终稿标题与 allow_stop 分支不符"
        )

    # ----- tool 结果泄漏二次审计（spec §7.3.4） -----
    # 把 state 视为 facts+rules，过一次 source audit 防 W2 残留。
    if state.fact_pack and state.rule_slice:
        post_retrieval_source_audit(state.fact_pack, state.rule_slice)

    state.final_report = final_report

    if not llm_narrative_accepted and any(
        value is not None
        for value in (
            state.accepted_payload,
            state.accepted_via,
            state.accepted_payload_sha256,
        )
    ):
        raise RuntimeError(
            "report contract invariant broken: 终局未接纳但接纳审计字段未清空"
        )

    return LLMOrchestratorResult(
        state=state,
        report_markdown=final_report,
        report_passed_output_guard=passed_guard,
        tool_call_count=tool_call_count,
        iterations_used=iterations_used,
        forced_finalize=forced_finalize,
        # 版本按 run 开始时冻结的活动契约定（copilot 终审四轮审出：按接纳载荷定
        # 会把 v4 模式下的回退稿标成 v3，审计/kind/离线重渲染全被误归档）。
        report_contract_version=_cv,
        llm_narrative_accepted=llm_narrative_accepted,
        llm_narrative_attempts=state.narrative_attempts,
        llm_narrative_rejection_codes=list(state.narrative_rejection_codes),
        narrative_fallback_reason=state.narrative_fallback_reason,
        submission_format_attempts=state.submission_format_attempts,
        submission_format_repairs_used=state.submission_format_repairs_used,
        submission_format_events=list(state.submission_format_events),
        accepted_via=state.accepted_via,
        accepted_point_count=(
            len(state.accepted_payload["points"]) if state.accepted_payload is not None else None
        ),
        accepted_payload_sha256=state.accepted_payload_sha256,
    )


# ---------------------------------------------------------------------------
# Tool 执行 dispatcher
# ---------------------------------------------------------------------------
# 哨兵值：用于 _parse_int_arg 区分"调用方显式传 None 默认值"和"缺省参数"。
_PARSE_INT_FAIL = object()


def _parse_int_arg(
    args: Dict[str, Any],
    key: str,
    default: int,
    *,
    min_value: int,
    max_value: int,
) -> Any:
    """从 args 取 int 类型参数并 clamp 到 [min_value, max_value]。

    LLM tool 调用契约：所有数值边界异常都必须以 `{"error": ...}` JSON 形式
    返回给 LLM 重试，而非抛 Python 异常逃出 tool。本 helper 统一项目里 4 处
    `int(args.get(key) or default)` 的解析模式（query_open_obligations /
    search_regulation / get_facts_by_slot / 任何新增工具）。

    返回：
    - int：解析+clamp 成功
    - `_PARSE_INT_FAIL` 哨兵：解析失败（非 int 字面量），调用方应返回 JSON 错误

    注意：bool 是 int 子类，True/False 会被 Python `isinstance(x, int)` 通过
    并按 1/0 计算。本 helper 接受这个行为（与 Python int 语义一致）。
    """
    raw = args.get(key)
    if raw is None:
        return max(min_value, min(default, max_value))
    if isinstance(raw, bool):
        # bool 是 int 子类但语义上不是数字参数，单独拦
        return _PARSE_INT_FAIL
    if isinstance(raw, int):
        return max(min_value, min(raw, max_value))
    if isinstance(raw, float):
        if raw != raw or raw in (float("inf"), float("-inf")):
            return _PARSE_INT_FAIL
        return max(min_value, min(int(raw), max_value))
    if isinstance(raw, str):
        try:
            return max(min_value, min(int(raw.strip()), max_value))
        except (ValueError, TypeError):
            return _PARSE_INT_FAIL
    return _PARSE_INT_FAIL


def _int_arg_error(key: str, raw: Any, *, min_value: int, max_value: int) -> str:
    """`_parse_int_arg` 返回 _PARSE_INT_FAIL 时的 JSON 错误文本。"""
    return json.dumps(
        {
            "error": (
                f"参数 {key!r} 必须是 [{min_value}, {max_value}] 区间内的整数，"
                f"实得 {type(raw).__name__}={raw!r}"
            )
        },
        ensure_ascii=False,
    )


def _handle_submission(
    *,
    tool_name: str,
    args: Any,
    state: LLMSessionState,
    retrieval_fn: Callable[[str, str, str], Tuple[FactPack, RuleSlice]],
    closure_fn: Callable[[RuleSlice, FactPack, Any], ClosureValidationResult],
    verifier_config: Any,
    via: str,
    parse_errors: Optional[List[Dict[str, Any]]] = None,
    raw_submission: Optional[str] = None,
) -> Tuple[str, bool]:
    """v3 格式状态机 + 内容重试状态机的唯一提交入口。"""
    def format_failure(errors: List[Dict[str, Any]]) -> Tuple[str, bool]:
        if raw_submission is None:
            try:
                audit_raw = json.dumps(args, ensure_ascii=False)
            except (TypeError, ValueError):
                audit_raw = repr(args)
        else:
            audit_raw = raw_submission
        state.submission_format_rejected_raw_attempts.append(
            {
                "attempt_index": state.submission_format_attempts,
                "via": via,
                "raw": audit_raw,
            }
        )
        # 格式层回执必须给模型一条可修路径：即使它在检索前先交空点列，也先跑
        # 同一确定性 backbone 构造本 run 证据包，再把重点项和真实别名随回执返回。
        if state.fact_pack is None or state.rule_slice is None:
            state.fact_pack, state.rule_slice = retrieval_fn(
                state.world_id, state.building_id, state.run_id
            )
        if state.closure_result is None:
            state.closure_result = closure_fn(state.rule_slice, state.fact_pack, verifier_config)
        _ensure_evidence_pack(state)
        return _format_failure_result(state, via, errors)

    if via == "tool_call":
        state.submit_tool_called = True
    # 共享路径回执按**会话冻结契约**报版本（v4 模式下硬编码 3 会与系统提示词
    # 自相矛盾；读环境会在运行中翻转时错版——终审五轮致命#1）。
    _shared_cv = state.contract_version
    if state.accepted_payload is not None:
        return json.dumps(
            {
                "status": "analysis_already_accepted",
                "report_contract_version": _shared_cv,
            },
            ensure_ascii=False,
        ), True
    if state.narrative_fallback_reason in {
        "submission_format_exhausted",
        "narrative_guard_exhausted",
        "status_authority_ambiguous",
    }:
        return json.dumps(
            {
                "status": "deterministic_narrative_fallback",
                "report_contract_version": _shared_cv,
                "narrative_fallback_reason": state.narrative_fallback_reason,
            },
            ensure_ascii=False,
        ), True

    state.submission_format_attempts += 1
    legacy = tool_name == "finalize_report" or (
        isinstance(args, dict) and "analysis_markdown" in args
    )
    if legacy:
        state.deprecated_tool_events.append(
            {
                "event": "deprecated_submission_input",
                "tool": tool_name,
                "input": (
                    "report_markdown" if tool_name == "finalize_report" else "analysis_markdown"
                ),
            }
        )
        errors = [
            _format_error(
                "legacy_input_unsupported",
                "",
                "points envelope",
                _actual_shape(args),
                '改用 submit_analysis 工具提交分析（字段按工具 schema）。',
            )
        ]
        return format_failure(errors)
    if parse_errors:
        return format_failure(parse_errors)

    # --- 报告契约 v4 分派（spec §7.4.5 / E-5）：**按会话冻结契约绑定，不看提交里的
    # contract 字段**（终审首轮致命#1：按 payload.contract 分派，v4 模式下模型交 v3
    # 载荷会漏到 v3 路径、自由文本 gloss 重入），**也不重读环境**（终审五轮致命#1：
    # 运行中环境翻转同样让 v3 载荷漏进 v3 路径而终稿标 v4）。v4 会话下**所有**提交
    # 都走 v4 校验（非 v4 形状由 wrong_contract/missing_fields 拒绝）。v3 路径不受影响。
    if state.contract_version == 4:
        if state.fact_pack is None or state.rule_slice is None:
            state.fact_pack, state.rule_slice = retrieval_fn(
                state.world_id, state.building_id, state.run_id
            )
        if state.closure_result is None:
            state.closure_result = closure_fn(
                state.rule_slice, state.fact_pack, verifier_config
            )
        pack = _ensure_evidence_pack(state)
        if pack is None or not pack.alias_map:
            _set_fallback_reason(state, "no_analysis_submitted")
            return json.dumps(
                {"status": "deterministic_narrative_fallback",
                 "report_contract_version": 4,
                 "narrative_fallback_reason": state.narrative_fallback_reason},
                ensure_ascii=False,
            ), True
        state.narrative_attempts += 1
        normalized_v4, v4_errors = validate_submission_payload_v4(args, pack.key_items)
        # E-5.4③ 全篇预渲染必须成功，否则整篇 fallback（不局部渲染）
        if not v4_errors and normalized_v4 is not None:
            if render_v4_points(pack, normalized_v4) is None:
                v4_errors = [{"error_code": "v4_prerender_failed", "pointer": "/points",
                              "fix_hint": "部分义务缺权威条文/模板/证据，整篇不接纳"}]
                normalized_v4 = None
        if v4_errors or normalized_v4 is None:
            state.llm_raw_response = json.dumps(args, ensure_ascii=False)
            state.narrative_rejection_codes.extend(e["error_code"] for e in v4_errors)
            max_attempts = 1 + state.narrative_retry_limit
            if state.narrative_attempts >= max_attempts:
                _set_fallback_reason(state, "narrative_guard_exhausted")
                return json.dumps(
                    {"status": "deterministic_narrative_fallback",
                     "report_contract_version": 4,
                     "narrative_fallback_reason": state.narrative_fallback_reason,
                     "rejection_codes": [e["error_code"] for e in v4_errors]},
                    ensure_ascii=False,
                ), True
            result: Dict[str, Any] = {
                "rejected": True,
                "gate": "v4_contract",
                "report_contract_version": 4,
                "rejection_codes": [e["error_code"] for e in v4_errors],
                "details": v4_errors,
                "narrative_attempts": state.narrative_attempts,
                "attempts_left": max_attempts - state.narrative_attempts,
                "hint": "只提交 obligation_alias/analysis_code/selected_fact_aliases/"
                        "review_action_code 四字段；analysis_code 填该义务的 "
                        "suggested_analysis_code，review_action_code 从 allowed_review_actions 选，"
                        "selected_fact_aliases 只用该义务自己的 fact_aliases。",
                "narrative_evidence_pack": build_v4_model_payload(pack),
            }
            return json.dumps(result, ensure_ascii=False), False
        state.accepted_payload = {"points": normalized_v4,
                                  "contract": "report_contract_v4"}
        state.accepted_via = via
        state.accepted_payload_sha256 = _payload_sha256(state.accepted_payload)
        state.llm_raw_response = None
        return json.dumps(
            {"status": "analysis_received",
             "report_contract_version": 4,
             "accepted_point_count": len(normalized_v4)},
            ensure_ascii=False,
        ), True

    payload, errors = validate_submission_payload(args)
    if errors or payload is None:
        return format_failure(errors)

    if state.fact_pack is None or state.rule_slice is None:
        state.fact_pack, state.rule_slice = retrieval_fn(
            state.world_id, state.building_id, state.run_id
        )
    if state.closure_result is None:
        state.closure_result = closure_fn(state.rule_slice, state.fact_pack, verifier_config)
    pack = _ensure_evidence_pack(state)
    if pack is None or not pack.alias_map:
        _set_fallback_reason(state, "no_analysis_submitted")
        return json.dumps(
            {
                "status": "deterministic_narrative_fallback",
                "report_contract_version": 3,
                "narrative_fallback_reason": state.narrative_fallback_reason,
            },
            ensure_ascii=False,
        ), True

    authority_ambiguities = _status_authority_ambiguities(payload, state)
    if authority_ambiguities:
        state.submission_audit_events.append(
            {
                "event": "status_authority_ambiguous",
                "attempt_index": state.submission_format_attempts,
                "details": authority_ambiguities,
            }
        )
        _set_fallback_reason(state, "status_authority_ambiguous")
        return json.dumps(
            {
                "status": "deterministic_narrative_fallback",
                "report_contract_version": 3,
                "narrative_fallback_reason": "status_authority_ambiguous",
            },
            ensure_ascii=False,
        ), True

    state.narrative_attempts += 1
    rejections = narrative_guard(payload, state)
    codes = [item["code"] for item in rejections]
    state.narrative_rejection_codes.extend(codes)
    if rejections:
        state.llm_raw_response = json.dumps(payload, ensure_ascii=False)
        max_attempts = 1 + state.narrative_retry_limit
        if state.narrative_attempts >= max_attempts:
            _set_fallback_reason(state, "narrative_guard_exhausted")
            return json.dumps(
                {
                    "status": "deterministic_narrative_fallback",
                    "report_contract_version": 3,
                    "narrative_fallback_reason": state.narrative_fallback_reason,
                    "rejection_codes": codes,
                    "narrative_attempts": state.narrative_attempts,
                },
                ensure_ascii=False,
            ), True
        result: Dict[str, Any] = {
            "rejected": True,
            "gate": "narrative_guard",
            "report_contract_version": 3,
            "rejection_codes": codes,
            "details": rejections,
            "narrative_attempts": state.narrative_attempts,
            "attempts_left": max_attempts - state.narrative_attempts,
            "hint": "删除任务规则说明，只保留事实限制、疑似风险、证据缺口或人工复核动作，然后重交 JSON 点列。",
        }
        if pack is not None:
            result["narrative_evidence_pack"] = pack.to_model_payload()
        return json.dumps(result, ensure_ascii=False), False

    # 规则 A advisory：候选词命中 + 绑定 O 非全 violated（或无 O）→ 记 warning。
    # 只暂存到 pending，待组合终稿守卫全过、终局仍为 LLM 接纳后才并入权威审计
    # （两阶段接纳，bug6）；不产拒码、不烧叙述预算、不触发确定性兜底。
    advisory_details = [
        detail
        for point_index, point in enumerate(payload["points"])
        for detail in _status_escalation_advisory_details(point, point_index, state)
    ]
    if advisory_details:
        state.pending_acceptance_audit_events.append(
            {
                "event": "status_escalation_warning",
                "attempt_index": state.submission_format_attempts,
                "advisory_only": True,
                "details": advisory_details,
            }
        )

    joined_text = "\n".join(point["text"] for point in payload["points"])
    false_counts = _report_has_false_zero_count_assertions(joined_text, state)
    if false_counts:
        state.false_zero_count_warnings.extend(false_counts)
    state.accepted_payload = payload
    state.accepted_via = via
    state.accepted_payload_sha256 = _payload_sha256(payload)
    state.llm_raw_response = None
    return json.dumps(
        {
            "status": "analysis_received",
            "report_contract_version": 3,
            "accepted_point_count": len(payload["points"]),
        },
        ensure_ascii=False,
    ), True


def _execute_tool_impl(
    *,
    tool_name: str,
    args: Any,
    state: LLMSessionState,
    retrieval_fn: Callable[[str, str, str], Tuple[FactPack, RuleSlice]],
    closure_fn: Callable[[RuleSlice, FactPack, Any], ClosureValidationResult],
    verifier_config: Any,
    submission_via: str = "tool_call",
    submission_parse_errors: Optional[List[Dict[str, Any]]] = None,
    submission_raw_payload: Optional[str] = None,
) -> Tuple[str, bool]:
    """执行单个 tool 调用。返回 (LLM 可读结果文本, 是否触发 finalize)。

    `args` 必须是 dict —— 非 dict 形状（list/string/None 等）应在外层调用
    `_execute_tool` 之前转 JSON 错误，避免内部 `args.get(...)` 抛
    AttributeError 被 RunOrchestrator 兜底成 run.status='failed'。
    """
    if tool_name in ("submit_analysis", "finalize_report"):
        return _handle_submission(
            tool_name=tool_name,
            args=args,
            state=state,
            retrieval_fn=retrieval_fn,
            closure_fn=closure_fn,
            verifier_config=verifier_config,
            via=submission_via,
            parse_errors=submission_parse_errors,
            raw_submission=submission_raw_payload,
        )

    if not isinstance(args, dict):
        return (
            json.dumps(
                {
                    "error": (
                        f"工具参数必须是 JSON object（dict），实得 "
                        f"{type(args).__name__}={args!r}。请重发本工具调用，"
                        f"arguments 字段必须是合法 JSON 对象。"
                    )
                },
                ensure_ascii=False,
            ),
            False,
        )
    if tool_name == "retrieve_building_facts":
        if state.fact_pack is None:
            state.fact_pack, state.rule_slice = retrieval_fn(
                state.world_id, state.building_id, state.run_id
            )
        return _summarize_fact_pack(state.fact_pack), False

    if tool_name == "retrieve_applicable_rules":
        if state.fact_pack is None:
            # 确保 facts 先检索
            state.fact_pack, state.rule_slice = retrieval_fn(
                state.world_id, state.building_id, state.run_id
            )
        return _summarize_rule_slice(state.rule_slice), False

    if tool_name == "run_closure_verification":
        if state.fact_pack is None or state.rule_slice is None:
            state.fact_pack, state.rule_slice = retrieval_fn(
                state.world_id, state.building_id, state.run_id
            )
        if state.closure_result is None:
            state.closure_result = closure_fn(state.rule_slice, state.fact_pack, verifier_config)
        # 契约 v2 修订 3：允许 submit_analysis 前程序先构造叙述证据包，
        # 并随 closure 摘要返回给模型（短别名 [O*]/[R*]/[F*]）。
        _ensure_evidence_pack(state)
        return _summarize_closure(
            state.closure_result, state.evidence_pack, state.contract_version
        ), False

    if tool_name == "query_open_obligations":
        if state.closure_result is None:
            return (
                '{"error": "请先调 run_closure_verification 再查 open 义务"}',
                False,
            )
        limit = _parse_int_arg(args, "limit", 10, min_value=1, max_value=200)
        if limit is _PARSE_INT_FAIL:
            return (
                _int_arg_error("limit", args.get("limit"), min_value=1, max_value=200),
                False,
            )
        return _query_open_obligations_summary(state.closure_result, limit), False

    # ---- KG 深入查询 6 个 tool ----
    if tool_name == "inspect_obligation":
        return _tool_inspect_obligation(state, args), False
    if tool_name == "lookup_clause":
        return _tool_lookup_clause(state, args), False
    if tool_name == "lookup_rule_card":
        return _tool_lookup_rule_card(state, args), False
    if tool_name == "search_regulation":
        return _tool_search_regulation(state, args), False
    if tool_name == "query_fragment":
        return _tool_query_fragment(state, args), False
    if tool_name == "get_facts_by_slot":
        return _tool_get_facts_by_slot(state, args), False

    return f'{{"error": "unknown tool {tool_name!r}"}}', False


def _rule_family_rows(rule_slice: RuleSlice) -> List[Dict[str, Any]]:
    """把 RuleSlice 的 family 信息整理成确定性报告第 3 节所需的行。

    与 run_orchestrator.RunOrchestrator._rule_family_rows 同构（工单裁定 8：
    兜底路径与守卫路径产出同名报告文件，切片表必须同样完整）。
    """
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


# v1 的 _render_deterministic_fallback（整篇 write_report 模板兜底）已随契约 v2
# 移除：叙述失败只降级"分析节槽位"为确定性叙述模板，程序骨架照常渲染（含工单
# 裁定 8 要求的完整溯源元数据），见 run_llm_orchestration 末尾的组合渲染。


def _execute_tool(
    *,
    tool_name: str,
    args: Any,
    state: LLMSessionState,
    retrieval_fn: Callable[[str, str, str], Tuple[FactPack, RuleSlice]],
    closure_fn: Callable[[RuleSlice, FactPack, Any], ClosureValidationResult],
    verifier_config: Any,
    submission_via: str = "tool_call",
    submission_parse_errors: Optional[List[Dict[str, Any]]] = None,
    submission_raw_payload: Optional[str] = None,
) -> Tuple[str, bool]:
    """执行工具；只记录非本次入参注入的模型可见日期 token。"""
    result_text, finalized = _execute_tool_impl(
        tool_name=tool_name,
        args=args,
        state=state,
        retrieval_fn=retrieval_fn,
        closure_fn=closure_fn,
        verifier_config=verifier_config,
        submission_via=submission_via,
        submission_parse_errors=submission_parse_errors,
        submission_raw_payload=submission_raw_payload,
    )
    # 工单裁定 1（P1 日期闸自我洗白）：seen_date_tokens 只从非提交工具
    # （submit_analysis / 迁移期 finalize_report 别名）的真实返回收集。提交工具
    # 的叙述节闸拒绝回执会原样回显编造日期（fabricated_date 的 detail），一旦
    # 入白名单，同一编造日期第二次原样重提必然放行——闸回执一律不入白名单。
    if tool_name not in ("finalize_report", "submit_analysis"):
        injected_dates: Counter[str] = Counter()

        def collect_arg_dates(value: Any) -> None:
            if isinstance(value, str):
                injected_dates.update(_date_tokens(value))
            elif isinstance(value, dict):
                for child in value.values():
                    collect_arg_dates(child)
            elif isinstance(value, (list, tuple, set)):
                for child in value:
                    collect_arg_dates(child)

        collect_arg_dates(args)
        # 严格排除：入参出现过的日期一律不从本次返回入白名单——原"次数差"
        # 口径被"JSON 字段 + 提示语"双回显击穿（get_facts_by_slot 无命中回执
        # 2 次 > 入参 1 次即洗白，复审 P2）。权威日期的合法来源是证据包预注入
        # 与其它无回显返回。
        result_dates = Counter(_date_tokens(result_text))
        state.seen_date_tokens.update(token for token in result_dates if injected_dates[token] == 0)
    return result_text, finalized


# ---------------------------------------------------------------------------
# KG 深入查询 6 个 tool 实现
# ---------------------------------------------------------------------------
_FORBIDDEN_KG_FIELDS = {
    # 防 LLM 不小心查到 W2 字段（spec §2.2.3 blind 红线，loader 已 reject 写入，
    # 这里二次防线：返回前 strip 任何 forbidden 属性）
    "expected_verdict",
    "projection_id",
    "projection_family",
    "projection_status",
    "selected_family",
    "basis_items",
    "coverage_status",
    "raw_projection_ref_hash",
    "projection_ref_hash",
}


def _strip_forbidden(d: Dict[str, Any]) -> Dict[str, Any]:
    """二次防线：strip dict 里 spec §2.2.3 禁止字段（W2 reference truth）。"""
    return {k: v for k, v in d.items() if k not in _FORBIDDEN_KG_FIELDS}


def _tool_inspect_obligation(state: LLMSessionState, args: Dict[str, Any]) -> str:
    """单条 obligation 的完整字段 + next-action hint（spec §7.5.3）。

    obligation 在 closure_result.obligation_set.obligations 列表里，不在 KG。
    LLM 传 obligation_id 前缀也能匹配（spec §6.7 短码可读约定）。
    """
    if state.closure_result is None:
        return '{"error": "请先调 run_closure_verification 再查 obligation"}'
    target_id = (args.get("obligation_id") or "").strip()
    if not target_id:
        return '{"error": "obligation_id 不能为空"}'
    matched: Optional[Obligation] = None
    for o in state.closure_result.obligation_set.obligations:
        if o.obligation_id == target_id or o.obligation_id.startswith(target_id):
            matched = o
            break
    if matched is None:
        return json.dumps(
            {"error": f"未找到 obligation_id={target_id!r}（首 12 位也可）"},
            ensure_ascii=False,
        )
    payload = matched.model_dump()
    payload = _strip_forbidden(payload)
    # 推断接下来该查什么：rule_card / clause / slot
    next_actions: List[str] = []
    if payload.get("source_rule_card_id"):
        next_actions.append(
            f"调 lookup_rule_card(rule_card_id='{payload['source_rule_card_id']}')"
            " 取本义务涉及的 rule_card 法规原文 + source_quote"
        )
    if payload.get("source_clause_ids"):
        next_actions.append(
            "对 source_clause_ids 中任一条调 lookup_clause(clause_id=...) 取法规章节全文"
        )
    if payload.get("slot_ids"):
        next_actions.append(
            "若需查具体 fact 值，对 slot_ids 中任一条调 get_facts_by_slot(slot_id=...)"
        )
    next_actions.append(
        _SUBMIT_NEXT_ACTION
    )
    payload["next_actions"] = next_actions
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _tool_lookup_clause(state: LLMSessionState, args: Dict[str, Any]) -> str:
    """按 clause_id 取法规章节原文，精确未中时按卡侧条款号降级。"""
    if state.kg_client is None:
        return '{"error": "kg_client 未注入，无法查 Neo4j"}'
    clause_id = (args.get("clause_id") or "").strip()
    if not clause_id:
        return '{"error": "clause_id 不能为空"}'
    try:
        rows = state.kg_client.run(
            "MATCH (cl:RegulationClause {clause_id: $cid}) "
            "RETURN cl.document_id AS document_id, cl.clause_id AS clause_id, "
            "cl.heading AS heading, cl.section_id AS section_id, "
            "cl.level AS level, cl.text AS text LIMIT 1",
            {"cid": clause_id},
        )
    except Exception as exc:  # 工具查询失败必须留在本轮内，不能击穿 agent。
        return json.dumps(
            {
                "status": "miss",
                "clause_id": clause_id,
                "reason": "kg_query_failed",
                "detail": str(exc),
            },
            ensure_ascii=False,
        )
    resolved_via = "exact"
    if not rows:
        app_match = re.search(r"\bApp\s*(\d+)\b", clause_id, flags=re.IGNORECASE)
        section_match = re.search(r"(?<![\d.])(\d+(?:\.\d+)+)", clause_id)
        app_prefix = f"app{app_match.group(1)}" if app_match else None
        section_prefix = section_match.group(1) if section_match else None
        parsed = {"app_prefix": app_prefix, "section_prefix": section_prefix}
        if section_prefix is None:
            return json.dumps(
                {
                    "status": "miss",
                    "clause_id": clause_id,
                    "resolved_via": "section_prefix",
                    "reason": "no_parseable_dotted_section_number",
                    "parsed": parsed,
                    "error": "精确 clause_id 未命中，且无法提取点分数字条款号",
                },
                ensure_ascii=False,
            )
        try:
            rows = state.kg_client.run(
                "MATCH (cl:RegulationClause) "
                "WHERE (toLower(coalesce(cl.clause_id, '')) CONTAINS $section_prefix "
                "OR toLower(coalesce(cl.heading, '')) CONTAINS $section_prefix) "
                "AND ($app_prefix IS NULL "
                "OR replace(toLower(coalesce(cl.clause_id, '')), ' ', '') CONTAINS $app_prefix "
                "OR replace(toLower(coalesce(cl.heading, '')), ' ', '') CONTAINS $app_prefix) "
                "RETURN cl.document_id AS document_id, cl.clause_id AS clause_id, "
                "cl.heading AS heading, cl.section_id AS section_id, "
                "cl.level AS level, cl.text AS text ORDER BY cl.clause_id",
                {"section_prefix": section_prefix.lower(), "app_prefix": app_prefix},
            )
        except Exception as exc:  # 同上：降级查询也必须 fail-soft。
            return json.dumps(
                {
                    "status": "miss",
                    "clause_id": clause_id,
                    "resolved_via": "section_prefix",
                    "reason": "kg_query_failed",
                    "parsed": parsed,
                    "detail": str(exc),
                },
                ensure_ascii=False,
            )
        if not rows:
            return json.dumps(
                {
                    "status": "miss",
                    "clause_id": clause_id,
                    "resolved_via": "section_prefix",
                    "reason": "no_clause_contains_section_prefix",
                    "parsed": parsed,
                    "error": "精确 clause_id 与条款号前缀均未命中",
                },
                ensure_ascii=False,
            )
        if len(rows) > 1:
            candidates = []
            for candidate in rows:
                clean = _strip_forbidden(dict(candidate))
                clean.pop("text", None)
                candidates.append(clean)
            return json.dumps(
                {
                    "status": "ambiguous",
                    "clause_id": clause_id,
                    "resolved_via": "section_prefix",
                    "parsed": parsed,
                    "candidates": candidates,
                },
                ensure_ascii=False,
                indent=2,
            )
        resolved_via = "section_prefix"
    row = _strip_forbidden(dict(rows[0]))
    # text 可能很长，截断到 3000 字防爆 context
    if row.get("text") and len(row["text"]) > 3000:
        row["text"] = row["text"][:3000] + "... [truncated]"
    row["resolved_via"] = resolved_via
    # 引导按会话冻结契约给：v4 提交无自由文本，"提交 text"式引导会教模型交 v3 形状
    # 并耗尽重试预算（终审四轮审出；五轮改读冻结值防运行中环境翻转）。
    row["next_actions"] = [
        (
            "本条章节原文只用于理解重点项；提交为结构化字段、不含条文文字，"
            "条文引用由程序权威渲染。"
            if state.contract_version == 4
            else "本条章节原文只用于理解重点项；提交 text 不写真实 ID，"
                 "提及别名须已绑定在本点。"
        ),
        "如需引用同主题其它条款，调 search_regulation(query=...) 找命中",
        _SUBMIT_NEXT_ACTION,
    ]
    return json.dumps(row, ensure_ascii=False, indent=2)


def _tool_lookup_rule_card(state: LLMSessionState, args: Dict[str, Any]) -> str:
    """单张 rule_card 的核心字段 + 所有 source_quote 原文 + clause refs +
    next-action hint（spec §7.5.3）。"""
    if state.kg_client is None:
        return '{"error": "kg_client 未注入，无法查 Neo4j"}'
    rule_card_id = (args.get("rule_card_id") or "").strip()
    if not rule_card_id:
        return '{"error": "rule_card_id 不能为空"}'
    card_rows = state.kg_client.run(
        "MATCH (rc:RuleCard {rule_card_id: $rcid}) "
        "RETURN rc.rule_card_id AS rule_card_id, rc.family_id AS family_id, "
        "rc.phase AS phase, rc.subject AS subject, rc.regime AS regime, "
        "rc.primary_actor AS primary_actor, rc.primary_action AS primary_action, "
        "rc.normalized_rule_text AS normalized_rule_text, "
        "rc.source_document_id AS source_document_id, "
        "rc.building_scope AS building_scope, "
        "rc.component_scope AS component_scope LIMIT 1",
        {"rcid": rule_card_id},
    )
    if not card_rows:
        return json.dumps(
            {"error": f"rule_card_id={rule_card_id!r} 不存在"},
            ensure_ascii=False,
        )
    card = _strip_forbidden(dict(card_rows[0]))
    quote_rows = state.kg_client.run(
        "MATCH (rc:RuleCard {rule_card_id: $rcid})-[:HAS_SOURCE_QUOTE]->(sq:SourceQuote) "
        "RETURN sq.source_quote_id AS sqid, sq.text AS text, "
        "sq.language AS language, sq.page AS page "
        "ORDER BY sq.source_quote_id",
        {"rcid": rule_card_id},
    )
    card["source_quotes"] = [_strip_forbidden(dict(r)) for r in quote_rows]
    clause_rows = state.kg_client.run(
        "MATCH (rc:RuleCard {rule_card_id: $rcid})-[:CITES_CLAUSE]->(cl:RegulationClause) "
        "RETURN DISTINCT cl.clause_id AS clause_id, cl.heading AS heading "
        "ORDER BY cl.clause_id",
        {"rcid": rule_card_id},
    )
    card["cited_clauses"] = [dict(r) for r in clause_rows]
    next_actions: List[str] = []
    if card["cited_clauses"]:
        next_actions.append("如需查 cited_clauses 任一条章节全文，调 lookup_clause(clause_id=...)")
    next_actions.append("如需找同主题其它法规依据，调 search_regulation(query=...)")
    next_actions.append(
        _SUBMIT_NEXT_ACTION
    )
    card["next_actions"] = next_actions
    return json.dumps(card, ensure_ascii=False, indent=2, default=str)


def _tool_search_regulation(state: LLMSessionState, args: Dict[str, Any]) -> str:
    """法规全文搜索 + next-action hint（spec §7.5.3）。

    spec v1.1 §7.4 hook 适用范围补充：`pre_retrieval_query_guard` 必须在 LLM
    提供的任何字符串 query 下发到 KG 之前调用，无工具豁免（含 fulltext 搜索类）。
    本工具在 query 下发前调 guard 拦 LLM 在 query 里写 W2/evaluator 禁字
    （如 `expected_verdict` / `NormativeProjection` / `ThresholdEval` 等）的探测行为。
    """
    if state.kg_client is None:
        return '{"error": "kg_client 未注入，无法查 Neo4j"}'
    query = (args.get("query") or "").strip()
    if not query:
        return '{"error": "query 不能为空"}'
    # spec v1.1 §7.4：LLM 提供的 query 必走 pre_retrieval_query_guard，无豁免。
    # guard 命中禁字抛 SecurityError；catch 后转为 JSON tool 错误返回给 LLM 重试。
    from evo_agent_baseline.agent.hooks import (
        pre_retrieval_query_guard as _guard,
        SecurityError as _SecurityError,
    )

    try:
        _guard(query)
    except _SecurityError as e:
        return json.dumps(
            {
                "error": "pre_retrieval_query_guard 命中禁字",
                "detail": str(e),
                "hint": (
                    "你的 query 含 W2 / evaluator 禁字（如 expected_verdict / "
                    "NormativeProjection / ThresholdEval / basis_items 等）。"
                    "请改用法规原文关键词或 rule_card / RuleThreshold 等允许 label 重查。"
                ),
            },
            ensure_ascii=False,
        )
    top_k = _parse_int_arg(args, "top_k", 5, min_value=1, max_value=20)
    if top_k is _PARSE_INT_FAIL:
        return _int_arg_error("top_k", args.get("top_k"), min_value=1, max_value=20)
    try:
        rows = state.kg_client.run(
            "CALL db.index.fulltext.queryNodes('regulation_clause_text_ft', $q) "
            "YIELD node, score "
            "RETURN node.clause_id AS clause_id, node.heading AS heading, "
            "node.document_id AS document_id, "
            "substring(coalesce(node.text, ''), 0, 300) AS preview, score "
            "ORDER BY score DESC LIMIT $k",
            {"q": query, "k": top_k},
        )
    except Exception as exc:  # pragma: no cover
        return json.dumps({"error": f"fulltext 检索失败: {exc!s}"}, ensure_ascii=False)
    out = [_strip_forbidden(dict(r)) for r in rows]
    return json.dumps(
        {
            "query": query,
            "top_k": top_k,
            "hits": out,
            "next_actions": [
                "对感兴趣的 hit，调 lookup_clause(clause_id=...) 取章节全文"
                "（preview 只有 300 字，引用必须取全文）",
                "若都不相关，换关键字再 search_regulation",
                _SUBMIT_NEXT_ACTION,
            ],
        },
        ensure_ascii=False,
        indent=2,
    )


def _tool_query_fragment(state: LLMSessionState, args: Dict[str, Any]) -> str:
    """单 fragment 的完整状态画像。"""
    if state.kg_client is None:
        return '{"error": "kg_client 未注入，无法查 Neo4j"}'
    fragment_id = (args.get("fragment_id") or "").strip()
    if not fragment_id:
        return '{"error": "fragment_id 不能为空"}'

    # 主体节点 + 直接父
    head_rows = state.kg_client.run(
        "MATCH (f:Fragment {fragment_id: $fid}) "
        "OPTIONAL MATCH (b:Building)-[:HAS_FRAGMENT]->(f) "
        "OPTIONAL MATCH (f)-[:OF_COMPONENT]->(c:Component) "
        "OPTIONAL MATCH (f)-[:AT_LOCATION]->(l:Location) "
        "RETURN f.fragment_id AS fragment_id, f.fragment_role AS fragment_role, "
        "f.in_scope AS in_scope, f.exclusion_reason AS exclusion_reason, "
        "b.building_id AS building_id, "
        "c.component_id AS component_id, c.component_type AS component_type, "
        "l.location_class AS location_class, l.exposure_zone AS exposure_zone LIMIT 1",
        {"fid": fragment_id},
    )
    if not head_rows:
        return json.dumps({"error": f"fragment_id={fragment_id!r} 不存在"}, ensure_ascii=False)
    head = _strip_forbidden(dict(head_rows[0]))

    # 关联状态 + measurement count
    state_count_rows = state.kg_client.run(
        "MATCH (f:Fragment {fragment_id: $fid}) "
        "OPTIONAL MATCH (f)-[:HAS_DRIVER_STATE]->(d:DriverState) "
        "OPTIONAL MATCH (f)-[:HAS_MECHANISM_STATE]->(m:MechanismState) "
        "OPTIONAL MATCH (f)-[:HAS_CONDITION]->(co:ConditionState) "
        "OPTIONAL MATCH (f)-[:HAS_REPAIR_ASSESSMENT]->(r:RepairAssessmentState) "
        "RETURN count(DISTINCT d) AS driver_count, "
        "count(DISTINCT m) AS mechanism_count, "
        "count(DISTINCT co) AS condition_count, "
        "count(DISTINCT r) AS repair_count LIMIT 1",
        {"fid": fragment_id},
    )
    head["state_counts"] = dict(state_count_rows[0]) if state_count_rows else {}

    # condition 子节点高频字段
    cond_rows = state.kg_client.run(
        "MATCH (f:Fragment {fragment_id: $fid})-[:HAS_CONDITION]->(co:ConditionState) "
        "RETURN co.condition_id AS condition_id, co.condition_class AS condition_class, "
        "co.severity_band AS severity_band, co.severity_index AS severity_index "
        "ORDER BY co.condition_id LIMIT 10",
        {"fid": fragment_id},
    )
    head["conditions"] = [_strip_forbidden(dict(r)) for r in cond_rows]
    head["next_actions"] = [
        "若需具体 fact 数值，对该 fragment 涉及的 slot 调 get_facts_by_slot(slot_id=...)",
        "若需查涉及该 fragment 的 obligation，回去 query_open_obligations 看"
        " evidence_fact_ids 引用",
        _SUBMIT_NEXT_ACTION,
    ]
    return json.dumps(head, ensure_ascii=False, indent=2, default=str)


def _tool_get_facts_by_slot(state: LLMSessionState, args: Dict[str, Any]) -> str:
    """从已检索的 FactPack 里筛某 slot 的具体 fact 值 + next-action hint
    （spec §7.5.3）。

    用 FactPack（已经在 session state 里）而不是再查 Neo4j —— 避免重复 IO，
    且确保返回的是当前 evaluation 范围内的 fact。
    """
    if state.fact_pack is None:
        return '{"error": "请先调 retrieve_building_facts"}'
    slot_id = (args.get("slot_id") or "").strip()
    if not slot_id:
        return '{"error": "slot_id 不能为空"}'
    top_k = _parse_int_arg(args, "top_k", 10, min_value=1, max_value=50)
    if top_k is _PARSE_INT_FAIL:
        return _int_arg_error("top_k", args.get("top_k"), min_value=1, max_value=50)
    hits: List[Dict[str, Any]] = []
    for f in state.fact_pack.facts:
        if f.slot_id != slot_id:
            continue
        hits.append(
            _strip_forbidden(
                {
                    "fact_id": f.fact_id,
                    "carrier_type": f.carrier_type,
                    "carrier_id": f.carrier_id,
                    "target_ref": f.target_ref,
                    "value_json": f.value_json,
                    "value_type": f.value_type,
                    "unit": f.unit,
                    "qualifiers": dict(f.qualifiers) if f.qualifiers else {},
                }
            )
        )
        if len(hits) >= top_k:
            break
    return json.dumps(
        {
            "slot_id": slot_id,
            "fact_count": len(hits),
            "facts": hits,
            "next_actions": (
                [
                    # 命中分支同样按会话冻结契约分流（终审五轮中#3：v4 下
                    # "原样作分析论据"是四字段无法表达的自由撰写引导）。
                    (
                        "这些值用于判断该义务的相关证据；提交时从该义务的"
                        " fact_aliases 选对应 F 别名即可，值由程序权威渲染。"
                        if state.contract_version == 4
                        else "把具体值（含 unit / qualifiers）原样作分析论据，"
                             "不要换算/取整/编造"
                    ),
                    "若涉及某 obligation，调 inspect_obligation(obligation_id=...)"
                    " 看 threshold/observed 对比",
                    _SUBMIT_NEXT_ACTION,
                ]
                if hits
                else [
                    # 不回显 slot_id：入参回显会给日期白名单开洗白口（复审 P2）
                    # 引导按会话冻结契约给：v4 模型不写报告，"在报告里写明"会教坏
                    # （终审四轮审出；五轮改读冻结值）。
                    (
                        "该 slot_id 在本 FactPack 内无 fact；这意味着证据缺失。"
                        "提交时按工具 schema 用结构化字段反映该缺口"
                        "（如选择该义务允许的复核动作），不要编造。"
                        if state.contract_version == 4
                        else "该 slot_id 在本 FactPack 内无 fact；这意味着证据缺失。"
                             "请在报告里写明该 slot 未取到 fact 并建议人工补充资料，"
                             "不要编造。"
                    ),
                    "可调 retrieve_applicable_rules 看是否有其它 slot 可替代",
                ]
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


__all__ = [
    "LLM_TOOLS",
    "LLMSessionState",
    "LLMOrchestratorResult",
    "run_llm_orchestration",
    # 报告契约 v2
    "narrative_guard",
    "NARRATIVE_RETRY_LIMIT_RANGE",
    "DEFAULT_NARRATIVE_RETRY_LIMIT",
]
