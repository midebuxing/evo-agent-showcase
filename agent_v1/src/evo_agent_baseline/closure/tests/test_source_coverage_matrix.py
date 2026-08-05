"""A.6 层二·生产源 schema 覆盖矩阵 + 源 DTO 字段穷尽测试（母病断根闸）。

spec 草案 v4 §A.6 层二：可执行「源 JSON path → 目标身份字段 / transform / category /
sentinel」矩阵 + **源 DTO 字段穷尽测试**（`set(DTO.model_fields) == 矩阵声明的该源
字段集`，新增源字段不在矩阵 → 测试红）。

母病（threshold_regime_id 当初漏接）= 「字段在 RuleCard 存在却没进 identity」。断根
两向：
- 向 A（源 → DTO）：`test_typed_dtos_ingest_all_398_cards`——真实 398 卡逐源经 typed DTO
  `**dict` 构造（extra=forbid），新 JSON 键 → ValidationError（不静默丢）。
- 向 B（DTO → 矩阵）：`test_each_source_dto_exhaustively_covered`——`set(model_fields)
  == set(矩阵行)`，DTO 新增字段未登记矩阵 → 红。
- 交叉（矩阵 identity 目标 → 真身份叶子）：`test_identity_targets_land_on_real_leaves`
  ——凡 category=identity 的行，目标须落 `ObligationV2` 真 identity 叶子（防「声称进
  身份却指向不存在的字段」）。

**闸真非空转（copilot 对抗审修，2026-07-14）**：
- 阻断#6：移除未授权 `nested` 伪 transform/category（父子结构改由 `FieldRule.child`
  结构标记表达，不塞进封闭词表）；target 校验改**逐个**断言每 target ∈ 声明 category
  的合法叶子（非 `any(...)` 命中即过），复合行每 target 都验。
- 阻断#7：bundle 缺失 **hard-fail 非 skip**；卡数断言 **精确 == 398**；obligation_graph
  外层键 **穷尽校验**（不 `.get` 绕过）；`QualifierSetDTO` 及全部源 DTO 纳入
  **自动发现等集断言**（`test_all_source_dtos_registered_in_matrix`）。
- 阻断#2：Node/Edge `from_dict` 现全键透传，未知键 → ValidationError；本测试断言其真拦
  （`test_node_edge_from_dict_rejects_unknown_key`）而非旧「静默忽略」自证。
- 阻断#5：applicability 七字段按 A.6 归 identity(scope 决定字段)/explicitly_ignored
  (纯求值/未消费)，**无一归 state**（`test_applicability_has_no_state_field`）。

因 A.0 DTO **本单元未接线**进身份构造（Phase 2），无法测「翻源值 → hash 变」，故按
任务落点测**矩阵 category 分类正确性**（identity/immutable/state/provenance/
explicitly_ignored 目标落点自洽）+ 真卡 ingest 往返（extra=forbid 不误伤现有语料）。

blind：本测试只 import `evo_agent_baseline.closure.{source_dtos,schema}` +
`identity_v2` + `canonical_profile`；不 import eval / workflow_engine / TruthBundle。
"""

from __future__ import annotations

import inspect
import json
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Tuple

import pytest
from pydantic import BaseModel, ValidationError

from evo_agent_baseline.closure import schema as _schema_mod
from evo_agent_baseline.closure import source_dtos as S
from evo_agent_baseline.closure.identity_v2 import ObligationV2


# =========================================================================== #
# ObligationV2 递归叶子集 → 分层参照（自 schema 派生，robust to schema 变更）
# =========================================================================== #


def _strip_optional(ann):
    if typing.get_origin(ann) is typing.Union:
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _leaf_paths(cls, prefix=""):
    out = set()
    for name, fld in cls.model_fields.items():
        out |= _walk(fld.annotation, prefix + name)
    return out


def _walk(ann, path):
    ann = _strip_optional(ann)
    if typing.get_origin(ann) is tuple:
        inner = _strip_optional(typing.get_args(ann)[0])
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return _leaf_paths(inner, path + "[].")
        return {path + "[]"}
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return _leaf_paths(ann, path + ".")
    return {path}


_ALL_LEAVES = _leaf_paths(ObligationV2)
IDENTITY_LEAVES = {p for p in _ALL_LEAVES if p.startswith("identity.")} | {
    "obligation_identity_schema",
    "canonical_identity_hash",
}
IMMUTABLE_LEAVES = {p for p in _ALL_LEAVES if p.startswith("immutable.")}
STATE_LEAVES = {p for p in _ALL_LEAVES if p.startswith("state.")}
PROVENANCE_LEAVES = {
    p for p in _ALL_LEAVES if p.startswith("provenance.") or p.startswith("run_envelope.")
} | {"obligation_id"}


# =========================================================================== #
# transform 词表（spec §A.6 L390 实列 18 值，executable table 权威）+ category 词表
# =========================================================================== #

SPEC_TRANSFORM_VOCAB = frozenset(
    {
        "identity_passthrough",
        "nfc",
        "nfc_sort",
        "canonicalize_measure",
        "canonicalize_slot",
        "canonicalize_unit",
        "canonicalize_artifact",
        "decimal",
        "in_not_in_sort",
        "predicate_spec",
        "deadline_binding",
        "binding",
        "qualifier_map",
        "edge_triplet_derive",
        "source_item_encode",
        "union",
        "to_state",
        "ignore",
    }
)

# 阻断#6：category 封闭词表**只含 A.6 授权五类**（移除偷加的 `nested`——父子结构由
# `FieldRule.child` 结构标记表达，不进封闭词表）。
CATEGORY_VOCAB = frozenset(
    {"identity", "immutable", "state", "provenance", "explicitly_ignored"}
)

# sentinel 目标（非叶子路径）
EXPLICITLY_IGNORED = "<explicitly_ignored>"  # closure 身份/状态均不消费
STATE_EVAL_ONLY = "<state_evaluation_only>"  # 求值时消费、不持久化到具体 state 叶子

# 逐类合法叶子池（per-target 校验用；state 含 STATE_EVAL_ONLY 哨兵）
_LAYER_POOLS = {
    "identity": IDENTITY_LEAVES,
    "immutable": IMMUTABLE_LEAVES,
    "state": STATE_LEAVES | {STATE_EVAL_ONLY},
    "provenance": PROVENANCE_LEAVES,
    "explicitly_ignored": {EXPLICITLY_IGNORED},
}


# =========================================================================== #
# FieldRule + 源覆盖矩阵
# =========================================================================== #


@dataclass(frozen=True)
class FieldRule:
    """一源字段一行。

    两类行（阻断#6：不再用伪 category `nested` 区分）：
    - **叶子行**：`targets` 非空、`transform ∈ 词表`、`category ⊆ 五类`、`child is None`。
    - **容器行**：`child` 指向子 DTO（结构父子关系），`targets=()`、`transform=None`、
      `category=()`——结构标记独立于封闭词表。
    """

    targets: Tuple[str, ...] = ()
    transform: Optional[str] = None
    category: Tuple[str, ...] = ()
    child: Optional[type] = field(default=None)
    note: str = ""


def _container(child: type, note: str = "") -> FieldRule:
    """容器行：父子结构标记（阻断#6：不占 transform/category 封闭词表）。"""
    return FieldRule(child=child, note=note or "容器：子 DTO 有独立矩阵行")


def _ignored(note: str = "") -> FieldRule:
    return FieldRule(
        targets=(EXPLICITLY_IGNORED,),
        transform="ignore",
        category=("explicitly_ignored",),
        note=note,
    )


# ---- 每源 typed DTO → {field_name: FieldRule} ---------------------------- #

# 阻断#5：applicability 七字段按 A.6（源→scope-audit 义务 source_channel=applicability）
# 归 identity(决定 applicability scope 的字段)/explicitly_ignored(纯求值/未消费)，**无一归
# state**。逐字段依 `evaluate_applicability`（applicability.py）真实消费判定：
#   - regime（规则1）/building_scope（规则2）/component_scope（规则3）/subject（规则3-词桥）
#     → 决定「哪些义务适用」= scope 决定字段 → identity（编码进 scope-audit 义务
#     source_item_id：source_channel=applicability, parts 承载 scope 判据）。
#   - phase/exclusions（evaluate_applicability 全程未读）、actors（scope 匹配显式跳过，
#     lines 67/202）→ 纯描述/未消费 → explicitly_ignored。
_APPLIC_SCOPE_IDENTITY = FieldRule(
    ("identity.source_item_id",),
    "source_item_encode",
    ("identity",),
    note="scope 决定字段 → scope-audit 义务 source_item_id（source_channel=applicability）",
)
_MATRIX_APPLICABILITY = {
    "regime": _APPLIC_SCOPE_IDENTITY,
    "building_scope": _APPLIC_SCOPE_IDENTITY,
    "component_scope": _APPLIC_SCOPE_IDENTITY,
    "subject": _APPLIC_SCOPE_IDENTITY,
    "phase": _ignored("evaluate_applicability 未读；纯描述，closure scope 不消费"),
    "actors": _ignored("scope 匹配显式跳过（applicability.py:67/202）；actor 身份真源=node.actor"),
    "exclusions": _ignored("evaluate_applicability 未读；closure scope 不消费"),
}

_MATRIX_QUALIFIER = {
    # 跨源共享值对象：八 qualifier 键 → identity.qualifiers[]（C.6；第九键 extra=forbid 拒）
    k: FieldRule(("identity.qualifiers[]",), "qualifier_map", ("identity",))
    for k in S.QUALIFIER_EIGHT_KEYS
}

_MATRIX_TRIGGER_ITEM = {
    "condition_id": FieldRule(("identity.source_item_id",), "source_item_encode", ("identity",)),
    "predicate_kind": FieldRule(("identity.predicate_kind",), "nfc", ("identity",)),
    "slot_ref_id": FieldRule(
        ("identity.slot_bindings[].local_ref", "identity.slot_bindings[].canonical_key"),
        "binding",
        ("identity",),
    ),
    # B1：trigger operator/expected_value/unit 是求值产物 → state（改值不改 identity hash）
    "operator": FieldRule(("state.evaluated_comparator",), "to_state", ("state",)),
    "expected_value": FieldRule(("state.evaluated_expected_value_json",), "to_state", ("state",)),
    "unit": FieldRule(
        (STATE_EVAL_ONLY,), "to_state", ("state",),
        note="B1：measure-trigger 求值单位，求值时消费、无专属 state 叶子",
    ),
    "measure_key": FieldRule(("identity.measure_bindings[].canonical_key",), "canonicalize_measure", ("identity",)),
    "qualifiers": FieldRule(("identity.qualifiers[]",), "qualifier_map", ("identity",)),
}

_MATRIX_TRIGGER_CONDITIONS = {
    "logic": _ignored("trigger 组合逻辑，closure 身份不消费"),
    "items": _container(S.TriggerItemDTO),
}

_MATRIX_RECIPIENT = {
    "recipient_id": FieldRule(("provenance.workflow_recipient_ids[]",), "nfc", ("provenance",),
                             note="非阻断④：单源=nodes[].recipient_ids；此为悬空校验集 → provenance"),
    "recipient_type": _ignored("closure 不消费（真实字段名，非 spec 表 type）"),
    "recipient_key": _ignored("closure 不消费（真实字段名，非 spec 表 key）"),
    "delivery_mode": _ignored("closure 不消费"),
}

_MATRIX_WF_ARTIFACT = {
    "artifact_key": FieldRule(("identity.artifact_bindings[].canonical_key",), "canonicalize_artifact", ("identity",)),
    "artifact_id": FieldRule(
        ("identity.artifact_bindings[].local_ref", "provenance.artifact_local_ids[]"),
        "nfc",
        ("identity", "provenance"),
    ),
    "artifact_type": _ignored(),
}

_MATRIX_WF_DEADLINE = {
    "deadline_id": FieldRule(("identity.deadline_bindings[].local_ref",), "deadline_binding", ("identity",)),
    "relation": FieldRule(("identity.deadline_bindings[].relation",), "deadline_binding", ("identity",)),
    "offset_value": FieldRule(("identity.deadline_bindings[].offset_value",), "decimal", ("identity",)),
    "offset_unit": FieldRule(("identity.deadline_bindings[].offset_unit",), "canonicalize_unit", ("identity",),
                            note="⚠️ 现 deriver 未读 offset_unit（附录 D §D.6），DTO 补齐"),
    "time_anchor_key": FieldRule(("identity.deadline_bindings[].time_anchor_key",), "deadline_binding", ("identity",)),
}

_MATRIX_WORKFLOW = {
    "primary_actor": _ignored("closure 不消费；KG ingest 用（附录 D §D.3）"),
    "primary_action": _ignored("closure 不消费（真实字段 primary_action）"),
    "recipients": _container(S.RecipientDTO),
    "artifacts": _container(S.WorkflowArtifactDTO),
    "deadlines": _container(S.WorkflowDeadlineDTO),
    "audiences": _ignored("真实全空；非空透传+warning"),
    "method_keys_allowed": FieldRule(("identity.qualifiers[]",), "qualifier_map", ("identity",),
                                    note="method_key qualifier"),
}

_MATRIX_SLOT_ROLE = {
    "slot_ref_id": FieldRule(("identity.slot_bindings[].local_ref",), "nfc", ("identity",)),
    "slot_id": FieldRule(("identity.slot_bindings[].canonical_key",), "canonicalize_slot", ("identity",)),
    "qualifiers": FieldRule(("identity.qualifiers[]",), "qualifier_map", ("identity",)),
    "roles": _ignored("slot 角色语义，身份不消费"),
    "required": FieldRule(("immutable.required",), "identity_passthrough", ("immutable",)),
}

_MATRIX_FORMULA_VAR = {
    "measure_key": FieldRule(
        ("identity.source_predicate_spec.variable_bindings[].canonical_measure_key",),
        "canonicalize_measure",
        ("identity",),
    ),
    "symbol": FieldRule(
        ("identity.source_predicate_spec.variable_bindings[].symbol",), "nfc", ("identity",)
    ),
}

_MATRIX_FORMULA = {
    "expression": FieldRule(("identity.source_predicate_spec.formula_id",), "predicate_spec", ("identity",),
                           note="版本化 AST/formula id"),
    "variables": _container(S.FormulaVariableDTO),
}

_MATRIX_THRESHOLD = {
    "threshold_regime_id": FieldRule(
        ("identity.source_predicate_spec.threshold_regime_id",), "nfc", ("identity",),
        note="母病锚：当初漏接的字段",
    ),
    "measure_key": FieldRule(
        (
            "identity.source_predicate_spec.canonical_measure_key",
            "identity.measure_bindings[].canonical_key",
        ),
        "canonicalize_measure",
        ("identity",),
    ),
    "operator": FieldRule(("identity.source_predicate_spec.source_operator",), "identity_passthrough", ("identity",)),
    "value": FieldRule(
        (
            "identity.source_predicate_spec.literal_value_canonical",
            "identity.source_predicate_spec.literal_value_tag",
        ),
        "decimal",
        ("identity",),
    ),
    "unit": FieldRule(
        (
            "identity.source_predicate_spec.canonical_unit",
            "immutable.canonical_unit",
        ),
        "canonicalize_unit",
        ("identity", "immutable"),
    ),
    "qualifiers": FieldRule(
        ("identity.source_predicate_spec.threshold_qualifier_fingerprint[]",),
        "qualifier_map",
        ("identity",),
        note="threshold-scoped → predicate_spec（非顶层 qualifiers）",
    ),
    "source_quote_refs": FieldRule(("provenance.source_quote_ids[]",), "union", ("provenance",)),
    "time_anchor_key": FieldRule(
        ("identity.source_predicate_spec.canonical_time_anchor_key",), "binding", ("identity",)
    ),
    "formula": _container(S.FormulaDTO),
}

_MATRIX_EVIDENCE_REQ = {
    "evidence_requirement_id": FieldRule(("identity.source_item_id",), "source_item_encode", ("identity",)),
    "kind": FieldRule(("identity.source_item_id",), "source_item_encode", ("identity",),
                     note="source_item_id.parts.kind（复合键）"),
    "required": FieldRule(("immutable.required",), "identity_passthrough", ("immutable",)),
    "description": _ignored("自由文本"),
    "artifact_ids": FieldRule(("identity.artifact_bindings[].local_ref",), "binding", ("identity",)),
    "slot_ref_ids": FieldRule(("identity.slot_bindings[].local_ref",), "nfc", ("identity",)),
    "measure_keys": FieldRule(("identity.measure_bindings[].canonical_key",), "canonicalize_measure", ("identity",)),
    "required_field_groups": FieldRule(("identity.source_item_id",), "source_item_encode", ("identity",),
                                      note="source_item_id.parts.required_field_groups（复合键）"),
}

_MATRIX_EVIDENCE_REQS = {
    "for_matching": _container(S.EvidenceRequirementDTO),
    "for_submission": _container(S.EvidenceRequirementDTO),
    "for_completion": _container(S.EvidenceRequirementDTO),
}

_MATRIX_EXCEPTION = {
    # corpus-empty；按 deriver evaluate_exception 消费键（deriver:1372/1373/1385）
    "slot_id": FieldRule(("identity.slot_bindings[].canonical_key",), "canonicalize_slot", ("identity",)),
    "exception_kind": FieldRule(("identity.source_item_id",), "source_item_encode", ("identity",)),
    "qualifiers": FieldRule(("identity.qualifiers[]",), "qualifier_map", ("identity",)),
}

_MATRIX_DEFINITION = {
    "definition_id": FieldRule(("identity.source_item_id",), "source_item_encode", ("identity",)),
    "term_key": FieldRule(("identity.source_item_id",), "source_item_encode", ("identity",),
                         note="source_item_id.parts（复合键）"),
    "definition_text": _ignored("自由文本"),
    "scope_note": _ignored("自由文本"),
    "source_quote_refs": FieldRule(("provenance.source_quote_ids[]",), "union", ("provenance",)),
}

_MATRIX_NODE = {
    "obligation_node_id": FieldRule(("identity.obligation_node_id",), "nfc", ("identity",)),
    "node_kind": FieldRule(("identity.kind",), "nfc", ("identity",), note="经 refine_action_kind"),
    "actor": FieldRule(("identity.actor",), "nfc", ("identity",), note="closure actor 真源=node"),
    "action": FieldRule(("identity.action",), "nfc", ("identity",), note="closure action 真源=node"),
    "recipient_ids": FieldRule(("identity.recipient_ids[]",), "nfc_sort", ("identity",), note="非阻断④单源"),
    "artifact_ids": FieldRule(("identity.artifact_bindings[].local_ref",), "binding", ("identity",)),
    "deadline_ids": FieldRule(("identity.deadline_bindings[].local_ref",), "deadline_binding", ("identity",)),
    "trigger_condition_ids": FieldRule(("provenance.trigger_dependency_ids[]",), "union", ("provenance",)),
}

_MATRIX_EDGE = {
    "source_node_id": FieldRule(("identity.obligation_edge_ids[]",), "edge_triplet_derive", ("identity",)),
    "target_node_id": FieldRule(("identity.obligation_edge_ids[]",), "edge_triplet_derive", ("identity",)),
    "relation": FieldRule(("identity.obligation_edge_ids[]",), "edge_triplet_derive", ("identity",)),
    # DTO-derived（非 JSON 源字段）：from_dict 从三元组派生
    "obligation_edge_id": FieldRule(("identity.obligation_edge_ids[]",), "edge_triplet_derive", ("identity",),
                                   note="DTO 派生便捷字段（真实 edge 无 edge_id）"),
}


# 源 DTO → 矩阵（九源全 typed DTO + 子 DTO + 跨源共享值对象 QualifierSetDTO）
SOURCE_DTO_MATRIX = {
    S.QualifierSetDTO: _MATRIX_QUALIFIER,
    S.ApplicabilityDTO: _MATRIX_APPLICABILITY,
    S.TriggerConditionsDTO: _MATRIX_TRIGGER_CONDITIONS,
    S.TriggerItemDTO: _MATRIX_TRIGGER_ITEM,
    S.WorkflowOperandsDTO: _MATRIX_WORKFLOW,
    S.RecipientDTO: _MATRIX_RECIPIENT,
    S.WorkflowArtifactDTO: _MATRIX_WF_ARTIFACT,
    S.WorkflowDeadlineDTO: _MATRIX_WF_DEADLINE,
    S.SlotRoleDTO: _MATRIX_SLOT_ROLE,
    S.ThresholdRegimeDTO: _MATRIX_THRESHOLD,
    S.FormulaDTO: _MATRIX_FORMULA,
    S.FormulaVariableDTO: _MATRIX_FORMULA_VAR,
    S.EvidenceRequirementsDTO: _MATRIX_EVIDENCE_REQS,
    S.EvidenceRequirementDTO: _MATRIX_EVIDENCE_REQ,
    S.ExceptionDTO: _MATRIX_EXCEPTION,
    S.DefinitionDTO: _MATRIX_DEFINITION,
    S.ObligationNodeDTO: _MATRIX_NODE,
    S.ObligationEdgeDTO: _MATRIX_EDGE,
}


# =========================================================================== #
# 向 B：源 DTO 字段穷尽（set(model_fields) == set(矩阵行)） —— 母病断根闸
# =========================================================================== #


@pytest.mark.parametrize("dto,rules", list(SOURCE_DTO_MATRIX.items()), ids=lambda x: getattr(x, "__name__", ""))
def test_each_source_dto_exhaustively_covered(dto, rules):
    model_fields = set(dto.model_fields)
    declared = set(rules)
    missing = model_fields - declared
    extra = declared - model_fields
    assert not missing, f"{dto.__name__} 源字段未登记矩阵（母病断根闸）: {sorted(missing)}"
    assert not extra, f"{dto.__name__} 矩阵含 DTO 不存在字段: {sorted(extra)}"


def test_all_nine_sources_present():
    """九源 typed DTO 全部登记矩阵（顶层九源载体齐全）。"""
    names = {d.__name__ for d in SOURCE_DTO_MATRIX}
    for required in (
        "ApplicabilityDTO",
        "TriggerConditionsDTO",
        "WorkflowOperandsDTO",
        "SlotRoleDTO",
        "ThresholdRegimeDTO",
        "EvidenceRequirementsDTO",
        "ExceptionDTO",
        "DefinitionDTO",
        "ObligationNodeDTO",
        "ObligationEdgeDTO",
    ):
        assert required in names, f"九源缺 {required}"


def _discover_source_dtos() -> set:
    """自动发现 source_dtos 定义 + 从 schema 再导出的全部 pydantic 源 DTO 类。"""
    allowed_modules = {S.__name__, _schema_mod.__name__}
    found = set()
    for obj in vars(S).values():
        if (
            inspect.isclass(obj)
            and issubclass(obj, BaseModel)
            and obj is not BaseModel
            and obj.__module__ in allowed_modules
        ):
            found.add(obj)
    return found


def test_all_source_dtos_registered_in_matrix():
    """阻断#7 等集断言：自动发现的每个源 DTO（含 QualifierSetDTO 与嵌套子 DTO）
    **必须**登记 SOURCE_DTO_MATRIX；新增/删除任一 DTO 而未同步矩阵 → 红。

    这堵死「新增一个源 DTO 却不进矩阵」的漂移口（非只自比较同文件常量）。
    """
    discovered = _discover_source_dtos()
    registered = set(SOURCE_DTO_MATRIX)
    assert discovered == registered, (
        f"源 DTO 未登记矩阵: {sorted(d.__name__ for d in discovered - registered)}; "
        f"矩阵多余: {sorted(d.__name__ for d in registered - discovered)}"
    )
    # 显式要求 QualifierSetDTO 在内（阻断#7 点名）
    assert S.QualifierSetDTO in registered


# =========================================================================== #
# transform / category 词表严格对齐（codex 机械项：词表与表值严格一致）
# =========================================================================== #


def _iter_rules():
    for dto, rules in SOURCE_DTO_MATRIX.items():
        for fname, rule in rules.items():
            yield dto, fname, rule


def test_transform_vocab_strict():
    """叶子行 transform 严格 ∈ 18 词表；容器行 transform=None（阻断#6：无 nested 伪词）。"""
    for dto, fname, rule in _iter_rules():
        if rule.child is not None:  # 容器行
            assert rule.transform is None, f"{dto.__name__}.{fname} 容器行 transform 须 None"
            continue
        assert rule.transform in SPEC_TRANSFORM_VOCAB, (
            f"{dto.__name__}.{fname} transform 越词表: {rule.transform}"
        )


def test_category_vocab_strict():
    """叶子行 category 严格 ⊆ 五类且非空；容器行 category=()（阻断#6：无 nested 伪类）。"""
    for dto, fname, rule in _iter_rules():
        if rule.child is not None:  # 容器行
            assert rule.category == (), f"{dto.__name__}.{fname} 容器行 category 须 ()"
            continue
        assert rule.category, f"{dto.__name__}.{fname} 叶子行 category 不得空"
        for cat in rule.category:
            assert cat in CATEGORY_VOCAB, f"{dto.__name__}.{fname} category 越词表: {cat}"


def test_container_rows_are_structural_only():
    """阻断#6：容器行 ⟺ `child is not None` ⟺（targets=() ∧ transform=None ∧ category=()）；
    child 子 DTO 必登记矩阵。父子结构靠结构标记表达，绝不塞进 transform/category 词表。"""
    for dto, fname, rule in _iter_rules():
        is_container = rule.child is not None
        structural = rule.targets == () and rule.transform is None and rule.category == ()
        assert is_container == structural, f"{dto.__name__}.{fname} 容器/结构标记不一致"
        if is_container:
            assert rule.child in SOURCE_DTO_MATRIX, (
                f"{dto.__name__}.{fname} 子 DTO {rule.child} 未登记矩阵"
            )
        # 反向：绝不允许 'nested' 泄漏进封闭词表
        assert rule.transform != "nested"
        assert "nested" not in rule.category


# =========================================================================== #
# 黄金 category 断言（阻断#1 残留修）：**独立于矩阵**逐字段锚死 A.6 权威分类
# =========================================================================== #
#
# 病灶：旧穷尽测试只验「field 集覆盖 + category ∈ 五类词表」，**不验每 field 的
# category 值正确**——把 artifact_key 从 identity 改成 ignore，37 测仍全过（category
# 分类没被钉死）。修：下表**逐字段**给出 A.6 权威期望 category（identity/immutable/
# state/provenance/explicitly_ignored；容器行标 `_GC_CONTAINER`），与矩阵 rule.category
# **逐一比对**。改矩阵任一字段 category（如 artifact_key identity→ignore）→ 与本表不符
# → 红。本表是**手工维护的 A.6 锚**，独立于矩阵派生逻辑，专逮单点分类漂移。

_GC_CONTAINER = "<container>"  # 容器行 sentinel（child 结构行，category=() ∧ transform=None）

GOLDEN_CATEGORY = {
    # QualifierSetDTO：八 qualifier 键 → identity（C.6）
    ("QualifierSetDTO", "artifact_key"): ("identity",),
    ("QualifierSetDTO", "component_type_key"): ("identity",),
    ("QualifierSetDTO", "location_class_key"): ("identity",),
    ("QualifierSetDTO", "actor_role_key"): ("identity",),
    ("QualifierSetDTO", "defect_class_key"): ("identity",),
    ("QualifierSetDTO", "method_key"): ("identity",),
    ("QualifierSetDTO", "risk_class_key"): ("identity",),
    ("QualifierSetDTO", "material_class_key"): ("identity",),
    # ApplicabilityDTO（阻断#5：scope 决定字段 identity / 纯求值未消费 explicitly_ignored）
    ("ApplicabilityDTO", "regime"): ("identity",),
    ("ApplicabilityDTO", "building_scope"): ("identity",),
    ("ApplicabilityDTO", "component_scope"): ("identity",),
    ("ApplicabilityDTO", "subject"): ("identity",),
    ("ApplicabilityDTO", "phase"): ("explicitly_ignored",),
    ("ApplicabilityDTO", "actors"): ("explicitly_ignored",),
    ("ApplicabilityDTO", "exclusions"): ("explicitly_ignored",),
    # TriggerConditionsDTO
    ("TriggerConditionsDTO", "logic"): ("explicitly_ignored",),
    ("TriggerConditionsDTO", "items"): _GC_CONTAINER,
    # TriggerItemDTO（B1：operator/expected_value/unit 求值产物 → state）
    ("TriggerItemDTO", "condition_id"): ("identity",),
    ("TriggerItemDTO", "predicate_kind"): ("identity",),
    ("TriggerItemDTO", "slot_ref_id"): ("identity",),
    ("TriggerItemDTO", "operator"): ("state",),
    ("TriggerItemDTO", "expected_value"): ("state",),
    ("TriggerItemDTO", "unit"): ("state",),
    ("TriggerItemDTO", "measure_key"): ("identity",),
    ("TriggerItemDTO", "qualifiers"): ("identity",),
    # WorkflowOperandsDTO
    ("WorkflowOperandsDTO", "primary_actor"): ("explicitly_ignored",),
    ("WorkflowOperandsDTO", "primary_action"): ("explicitly_ignored",),
    ("WorkflowOperandsDTO", "recipients"): _GC_CONTAINER,
    ("WorkflowOperandsDTO", "artifacts"): _GC_CONTAINER,
    ("WorkflowOperandsDTO", "deadlines"): _GC_CONTAINER,
    ("WorkflowOperandsDTO", "audiences"): ("explicitly_ignored",),
    ("WorkflowOperandsDTO", "method_keys_allowed"): ("identity",),
    # RecipientDTO（recipient_id → provenance 悬空校验集；其余三字段未消费）
    ("RecipientDTO", "recipient_id"): ("provenance",),
    ("RecipientDTO", "recipient_type"): ("explicitly_ignored",),
    ("RecipientDTO", "recipient_key"): ("explicitly_ignored",),
    ("RecipientDTO", "delivery_mode"): ("explicitly_ignored",),
    # WorkflowArtifactDTO（artifact_id 复合：identity local_ref + provenance local_ids）
    ("WorkflowArtifactDTO", "artifact_key"): ("identity",),
    ("WorkflowArtifactDTO", "artifact_id"): ("identity", "provenance"),
    ("WorkflowArtifactDTO", "artifact_type"): ("explicitly_ignored",),
    # WorkflowDeadlineDTO（全 identity，deadline binding）
    ("WorkflowDeadlineDTO", "deadline_id"): ("identity",),
    ("WorkflowDeadlineDTO", "relation"): ("identity",),
    ("WorkflowDeadlineDTO", "offset_value"): ("identity",),
    ("WorkflowDeadlineDTO", "offset_unit"): ("identity",),
    ("WorkflowDeadlineDTO", "time_anchor_key"): ("identity",),
    # SlotRoleDTO（required → immutable；roles → explicitly_ignored）
    ("SlotRoleDTO", "slot_ref_id"): ("identity",),
    ("SlotRoleDTO", "slot_id"): ("identity",),
    ("SlotRoleDTO", "qualifiers"): ("identity",),
    ("SlotRoleDTO", "roles"): ("explicitly_ignored",),
    ("SlotRoleDTO", "required"): ("immutable",),
    # FormulaDTO / FormulaVariableDTO
    ("FormulaDTO", "expression"): ("identity",),
    ("FormulaDTO", "variables"): _GC_CONTAINER,
    ("FormulaVariableDTO", "measure_key"): ("identity",),
    ("FormulaVariableDTO", "symbol"): ("identity",),
    # ThresholdRegimeDTO（母病锚 threshold_regime_id → identity；unit 复合 identity+immutable）
    ("ThresholdRegimeDTO", "threshold_regime_id"): ("identity",),
    ("ThresholdRegimeDTO", "measure_key"): ("identity",),
    ("ThresholdRegimeDTO", "operator"): ("identity",),
    ("ThresholdRegimeDTO", "value"): ("identity",),
    ("ThresholdRegimeDTO", "unit"): ("identity", "immutable"),
    ("ThresholdRegimeDTO", "qualifiers"): ("identity",),
    ("ThresholdRegimeDTO", "source_quote_refs"): ("provenance",),
    ("ThresholdRegimeDTO", "time_anchor_key"): ("identity",),
    ("ThresholdRegimeDTO", "formula"): _GC_CONTAINER,
    # EvidenceRequirementsDTO / EvidenceRequirementDTO（required → immutable）
    ("EvidenceRequirementsDTO", "for_matching"): _GC_CONTAINER,
    ("EvidenceRequirementsDTO", "for_submission"): _GC_CONTAINER,
    ("EvidenceRequirementsDTO", "for_completion"): _GC_CONTAINER,
    ("EvidenceRequirementDTO", "evidence_requirement_id"): ("identity",),
    ("EvidenceRequirementDTO", "kind"): ("identity",),
    ("EvidenceRequirementDTO", "required"): ("immutable",),
    ("EvidenceRequirementDTO", "description"): ("explicitly_ignored",),
    ("EvidenceRequirementDTO", "artifact_ids"): ("identity",),
    ("EvidenceRequirementDTO", "slot_ref_ids"): ("identity",),
    ("EvidenceRequirementDTO", "measure_keys"): ("identity",),
    ("EvidenceRequirementDTO", "required_field_groups"): ("identity",),
    # ExceptionDTO（corpus-empty，按 deriver 消费键）
    ("ExceptionDTO", "slot_id"): ("identity",),
    ("ExceptionDTO", "exception_kind"): ("identity",),
    ("ExceptionDTO", "qualifiers"): ("identity",),
    # DefinitionDTO
    ("DefinitionDTO", "definition_id"): ("identity",),
    ("DefinitionDTO", "term_key"): ("identity",),
    ("DefinitionDTO", "definition_text"): ("explicitly_ignored",),
    ("DefinitionDTO", "scope_note"): ("explicitly_ignored",),
    ("DefinitionDTO", "source_quote_refs"): ("provenance",),
    # ObligationNodeDTO（trigger_condition_ids → provenance；余 identity）
    ("ObligationNodeDTO", "obligation_node_id"): ("identity",),
    ("ObligationNodeDTO", "node_kind"): ("identity",),
    ("ObligationNodeDTO", "actor"): ("identity",),
    ("ObligationNodeDTO", "action"): ("identity",),
    ("ObligationNodeDTO", "recipient_ids"): ("identity",),
    ("ObligationNodeDTO", "artifact_ids"): ("identity",),
    ("ObligationNodeDTO", "deadline_ids"): ("identity",),
    ("ObligationNodeDTO", "trigger_condition_ids"): ("provenance",),
    # ObligationEdgeDTO（三元组 + 派生 edge_id 全 identity）
    ("ObligationEdgeDTO", "source_node_id"): ("identity",),
    ("ObligationEdgeDTO", "target_node_id"): ("identity",),
    ("ObligationEdgeDTO", "relation"): ("identity",),
    ("ObligationEdgeDTO", "obligation_edge_id"): ("identity",),
}


def test_golden_category_keys_match_matrix_exactly():
    """黄金表键集 == 矩阵全 (DTO, field) 键集：新增/删除任一源字段而未同步黄金表 → 红。

    堵死「加字段进矩阵但忘了钉黄金 category」的漂移口。
    """
    matrix_keys = {
        (dto.__name__, f) for dto, rules in SOURCE_DTO_MATRIX.items() for f in rules
    }
    golden_keys = set(GOLDEN_CATEGORY)
    missing = matrix_keys - golden_keys
    extra = golden_keys - matrix_keys
    assert not missing, f"黄金表缺字段（母病闸）: {sorted(missing)}"
    assert not extra, f"黄金表含矩阵不存在字段: {sorted(extra)}"


def test_golden_category_pins_every_field():
    """阻断#1 核心：**逐字段**断言矩阵 rule.category == A.6 黄金期望值（独立锚）。

    直接证据：把 `_MATRIX_WF_ARTIFACT['artifact_key']` 从 identity 改成 `_ignored()`，
    rule.category 变 ('explicitly_ignored',) ≠ 黄金 ('identity',) → 本测试红（旧穷尽
    测试对此改动全绿＝category 未钉死，故本闸真非空转）。
    """
    for dto, rules in SOURCE_DTO_MATRIX.items():
        for fname, rule in rules.items():
            expected = GOLDEN_CATEGORY[(dto.__name__, fname)]
            if expected == _GC_CONTAINER:
                assert rule.child is not None and rule.category == () and rule.transform is None, (
                    f"{dto.__name__}.{fname} 黄金标容器行，实际 "
                    f"category={rule.category} child={rule.child} transform={rule.transform}"
                )
            else:
                assert rule.child is None, (
                    f"{dto.__name__}.{fname} 黄金标叶子行，实际是容器行（child={rule.child}）"
                )
                assert rule.category == expected, (
                    f"{dto.__name__}.{fname} category 漂移 A.6 黄金锚: "
                    f"期望 {expected}，实为 {rule.category}"
                )


# =========================================================================== #
# 交叉：矩阵目标落点 → ObligationV2 真叶子（sentinel 分类正确性，母病断根核心）
# =========================================================================== #


def test_every_target_is_valid_leaf_of_declared_category():
    """阻断#6：**逐个 target** 断言其 ∈ 声明 category 的合法叶子池（非 any(...) 命中即过），
    且每个声明 category 至少有一个 target 落在其池（无空分量）。复合行每 target 都验。

    这是母病断根语义核：任一源字段的任一目标，都必须真实落在其声明层的合法叶子，
    没有任何 target 能「声称进某层却指向该层不存在的字段」而蒙混。
    """
    for dto, fname, rule in _iter_rules():
        if rule.child is not None:  # 容器行无直接 target
            assert rule.targets == ()
            continue
        allowed = set()
        for cat in rule.category:
            allowed |= _LAYER_POOLS[cat]
        # ① 每个 target 都必须属某个声明 category 的合法叶子
        for t in rule.targets:
            assert t in allowed, (
                f"{dto.__name__}.{fname} target {t!r} 不属声明 category {rule.category} 的合法叶子池"
            )
        # ② 每个声明 category 都至少被一个 target 见证（禁空分量）
        for cat in rule.category:
            assert any(t in _LAYER_POOLS[cat] for t in rule.targets), (
                f"{dto.__name__}.{fname} category={cat} 无对应 target（空分量）: {rule.targets}"
            )


def test_identity_targets_land_on_real_identity_leaves():
    """category 含 identity 的每行，至少有一个 target 落 ObligationV2 真 identity 叶子。

    母病断根：一源字段若声称「进身份」，其目标必须是身份里真实存在的叶子
    （threshold_regime_id 当初就是没有落点才漏接）。
    """
    for dto, fname, rule in _iter_rules():
        if rule.child is not None:
            continue
        if "identity" in rule.category:
            assert any(t in IDENTITY_LEAVES for t in rule.targets), (
                f"{dto.__name__}.{fname} category 含 identity 但无目标落身份叶子: {rule.targets}"
            )


def test_explicitly_ignored_targets_are_sentinel():
    for dto, fname, rule in _iter_rules():
        if rule.category == ("explicitly_ignored",):
            assert rule.targets == (EXPLICITLY_IGNORED,), f"{dto.__name__}.{fname} ignored 目标须 sentinel"
            assert rule.transform == "ignore"


def test_trigger_operator_expected_unit_are_state_not_identity():
    """B1 回归锚：trigger operator/expected_value/unit 归 state（改值不改 identity hash）。"""
    for f in ("operator", "expected_value", "unit"):
        rule = _MATRIX_TRIGGER_ITEM[f]
        assert rule.category == ("state",), f"trigger {f} 必须 state（B1）"
        assert "identity" not in rule.category


def test_threshold_regime_id_is_identity():
    """母病锚回归：threshold_regime_id 必须落 identity（predicate_spec.threshold_regime_id）。"""
    rule = _MATRIX_THRESHOLD["threshold_regime_id"]
    assert rule.category == ("identity",)
    assert rule.targets == ("identity.source_predicate_spec.threshold_regime_id",)
    assert rule.targets[0] in IDENTITY_LEAVES


def test_applicability_has_no_state_field():
    """阻断#5：applicability 七字段一个都不许归 state（A.6 只授权 identity/explicitly_ignored）。

    逐字段独立断言分类，防「七字段全塞 state」回潮。
    """
    expect = {
        "regime": ("identity",),
        "building_scope": ("identity",),
        "component_scope": ("identity",),
        "subject": ("identity",),
        "phase": ("explicitly_ignored",),
        "actors": ("explicitly_ignored",),
        "exclusions": ("explicitly_ignored",),
    }
    assert set(_MATRIX_APPLICABILITY) == set(expect), "applicability 七字段集漂移"
    for fname, cat in expect.items():
        rule = _MATRIX_APPLICABILITY[fname]
        assert rule.category == cat, f"applicability.{fname} 分类应 {cat}，实为 {rule.category}"
        assert "state" not in rule.category, f"applicability.{fname} 不得归 state（违反 A.6）"
    # scope 决定字段的 identity 目标须落真身份叶子
    for fname in ("regime", "building_scope", "component_scope", "subject"):
        assert _MATRIX_APPLICABILITY[fname].targets[0] in IDENTITY_LEAVES


# =========================================================================== #
# 向 A：真实 398 卡逐源经 typed DTO ingest（extra=forbid 不误伤 + 捕获新键）
# =========================================================================== #

EXPECTED_CARD_COUNT = 469  # 真实卡数（精确锚，非 >=300）；2026-08-04 件四批 1 退役 §3.2.6 重复卡 470→469

# 阻断#1b：九源容器**每卡必存在**（真卡枚举 9/9 全 398/398 存在为键，即使 list 为空亦带键）。
# 缺任一 → fail（母病闸不 `.get` 静默兜过）。当前语料无 optional 容器（全 398/398 present）。
REQUIRED_CONTAINERS = (
    "applicability",
    "trigger_conditions",
    "slot_role_map",
    "workflow_operands",
    "evidence_requirements",
    "exceptions",
    "definitions",
    "obligation_graph",
    "threshold_regimes",
)

# 九容器 → 其 typed DTO（列表容器映射元素 DTO；obligation_graph 含 Node+Edge 两 DTO）。
# 每容器的 DTO 必登记 SOURCE_DTO_MATRIX（= 该容器已进 typed 处理，非静默放行）。
CONTAINER_TO_DTOS = {
    "applicability": (S.ApplicabilityDTO,),
    "trigger_conditions": (S.TriggerConditionsDTO,),
    "slot_role_map": (S.SlotRoleDTO,),
    "workflow_operands": (S.WorkflowOperandsDTO,),
    "evidence_requirements": (S.EvidenceRequirementsDTO,),
    "exceptions": (S.ExceptionDTO,),
    "definitions": (S.DefinitionDTO,),
    "obligation_graph": (S.ObligationNodeDTO, S.ObligationEdgeDTO),
    "threshold_regimes": (S.ThresholdRegimeDTO,),
}

# ---- 母病闸真漏修：卡顶层键白名单（非九容器的顶层键 = provenance 类顶层源）---------- #
# 病灶：旧 ingest 测试只验九容器「存在」，**不验每卡完整顶层键集**——卡顶层加
# `brand_new_top_source` → 398 测仍过（新顶层源容器静默漏进）。修：读真卡枚举**每卡真实
# 顶层键的并集**，建白名单，ingest 对每卡断言 `set(card.keys()) ⊆ ALLOWED_TOP_LEVEL_KEYS`；
# 白名单外的顶层键 → 红。
#
# 真卡枚举（398/398 全 present）：九容器 + 下列九个 provenance 类顶层源。spec 草案 v4 A.6
# 矩阵行显式列 `source_section/source_quote/version.*/provenance.*/normalized_rule_text/
# neighbor_families/family_id`（provenance / explicitly_ignored，`family_id`→
# `provenance.source_family_id`）；`rule_card_id`/`source_document_id` 未在该行逐字枚举，
# 但真卡 398/398 present、语义即 provenance（primary 卡 id / 源文档 id），据实登记 provenance。
# 每键显式登记 category（provenance / explicitly_ignored），杜绝「新顶层源静默放行」。
PROVENANCE_TOP_LEVEL_SOURCES = {
    "rule_card_id": "provenance",       # primary 卡 id
    "family_id": "provenance",          # spec A.6：→ provenance.source_family_id
    "source_document_id": "provenance",  # 源文档 id
    "source_section": "provenance",     # 源条文段落锚
    "source_quote": "provenance",       # 源条文引文
    "version": "provenance",            # 卡版本
    "provenance": "provenance",         # provenance 子对象
    "normalized_rule_text": "explicitly_ignored",  # 自由文本，closure 不消费（spec A.6：ignore）
    "neighbor_families": "explicitly_ignored",      # KG 邻域导航，closure 不消费
}

# 顶层键白名单 = 九容器 + provenance 类顶层源；卡顶层出现白名单外的键 → ingest 测试红。
ALLOWED_TOP_LEVEL_KEYS = frozenset(REQUIRED_CONTAINERS) | frozenset(
    PROVENANCE_TOP_LEVEL_SOURCES
)


def _find_bundle() -> Optional[Path]:
    here = Path(__file__).resolve()
    for base in here.parents:
        cand = base / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023" / "rule_cards.json"
        if cand.exists():
            return cand
    return None


def _load_cards():
    """阻断#7：bundle 缺失 **hard-fail 非 skip**（skip 让闸空转、绿而不拦）。

    fail-closed 连贯设计 §3：identity 入口用 `parse_json_decimal`（parse_float=Decimal）读——
    数字词元落 int/Decimal（绝不 float），使 strict Decimal DTO（ThresholdRegimeDTO.value /
    TriggerItemDTO.expected_value）接纳真卡，且 float ingress 结构上被排除（拒 Python float）。
    """
    from canonical_profile import parse_json_decimal

    p = _find_bundle()
    if p is None:
        pytest.fail("生产 rule_cards.json 未找到——母病闸不得 skip（skip=空转）")
    data = parse_json_decimal(p.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"bundle_id", "cards"}, f"bundle 外层键漂移: {sorted(data.keys())}"
    return data["cards"]


def test_typed_dtos_ingest_all_398_cards():
    """真实 398 卡逐源经 typed DTO `**dict` 构造：extra=forbid 不误伤现有语料。

    向 A 母病断根：若某源出现新 JSON 键而 DTO 未收录，`**dict` 构造抛 ValidationError。
    本测试证明当前语料被 DTO 完全覆盖（无新键漏网），且反向证明 typed DTO 字段名 /
    optionality 与真卡一致。obligation_graph 外层键**穷尽校验**（不 `.get` 绕过）。
    """
    cards = _load_cards()
    assert len(cards) == EXPECTED_CARD_COUNT, f"卡数须精确 {EXPECTED_CARD_COUNT}，实为 {len(cards)}"

    counts = {
        "applicability": 0, "trigger_items": 0, "recipients": 0, "artifacts": 0,
        "deadlines": 0, "slot_roles": 0, "thresholds": 0, "formulas": 0,
        "evidence": 0, "definitions": 0, "nodes": 0, "edges": 0, "exceptions": 0,
    }
    for c in cards:
        # 阻断#1b：九源容器**显式断言存在**（不 `.get` 静默兜过；缺失 → fail 非默认空列表）。
        for cont in REQUIRED_CONTAINERS:
            assert cont in c, (
                f"卡 {c.get('rule_card_id')!r} 缺源容器 {cont!r}"
                "（母病闸：该容器应全 398/398 存在，缺失 → fail 不静默兜过）"
            )

        # 母病闸真漏修：卡**完整顶层键集** ⊆ 白名单——顶层冒出白名单外的新键（新顶层源
        # 容器 / 未登记 provenance 源）→ 红。旧测试只验九容器「存在」，不验完整键集，故
        # 卡顶层加 `brand_new_top_source` 仍全过（新顶层源静默漏进）；此断言堵死该口。
        extra_top = set(c.keys()) - ALLOWED_TOP_LEVEL_KEYS
        assert not extra_top, (
            f"卡 {c.get('rule_card_id')!r} 顶层出现白名单外的键 {sorted(extra_top)}"
            "（母病闸：新顶层源须先进九容器 typed 处理或登记 PROVENANCE_TOP_LEVEL_SOURCES，"
            "不得静默漏进）"
        )

        S.ApplicabilityDTO(**c["applicability"])
        counts["applicability"] += 1

        tc = S.TriggerConditionsDTO(**c["trigger_conditions"])
        counts["trigger_items"] += len(tc.items)

        wf = S.WorkflowOperandsDTO(**c["workflow_operands"])
        counts["recipients"] += len(wf.recipients)
        counts["artifacts"] += len(wf.artifacts)
        counts["deadlines"] += len(wf.deadlines)

        for s in c["slot_role_map"]:
            S.SlotRoleDTO(**s)
            counts["slot_roles"] += 1

        for t in c["threshold_regimes"]:
            tr = S.ThresholdRegimeDTO(**t)
            counts["thresholds"] += 1
            if tr.formula is not None:
                counts["formulas"] += 1

        er = S.EvidenceRequirementsDTO(**c["evidence_requirements"])
        counts["evidence"] += len(er.for_matching) + len(er.for_submission) + len(er.for_completion)

        # 阻断#1b：exceptions/definitions 容器键已断言存在（上），此处直接索引不 `.get` 兜过。
        for x in c["exceptions"]:
            S.ExceptionDTO(**x)
            counts["exceptions"] += 1

        for x in c["definitions"]:
            S.DefinitionDTO(**x)
            counts["definitions"] += 1

        g = c["obligation_graph"]
        # 阻断#7：graph 外层键穷尽（新增 hyperedges 之类 → 红，不 `.get` 绕过）
        assert set(g.keys()) == {"nodes", "edges"}, f"obligation_graph 外层键漂移: {sorted(g.keys())}"
        for n in g["nodes"]:
            S.ObligationNodeDTO(**n)
            counts["nodes"] += 1
        for e in g["edges"]:
            S.ObligationEdgeDTO(**e)
            counts["edges"] += 1

    # 与真实枚举锚对齐（防 ingest 静默丢源）
    assert counts["applicability"] == len(cards)
    # 2026-08-05 换池捆绑批·乙路 #30 重锚 428→429：意向卡
    # `…s2_1_3_n_investigation_intention_to_ba.c01` 新增卡级触发项 `trg01`
    # （引用新 sr02 = 真前件槽 `procedure.investigation.detailed.intended`）。
    # 「未变的项即证据」：本件只碰这一张卡的 `trigger_conditions` 与 `slot_role_map`，
    # 故只有 trigger_items(+1) 与 slot_roles(+1) 动，其余十项逐位不变。
    assert counts["trigger_items"] == 429
    assert counts["recipients"] == 75  # 2026-07-28 补 64 张缺卡后重锚
    # 2026-07-28 补 64 张缺卡后重锚（卡 398→462）。增量逐项归因于新卡：
    #   artifacts 326→336(+10) / slot_roles 771→872(+101) / nodes 402→480(+78)
    #   recipients 62→73(+11) / trigger_items 377→426(+49)
    # **未变的项恰恰是证据**：deadlines/thresholds/formulas/evidence/definitions/edges
    # 全部零变化 ⇒ 新卡没有污染既有源通道。
    # 2026-08-04 件四批 1 退役 §3.2.6 重复卡（该卡：trigger 1 / artifacts 1 / slot_roles 2 /
    # nodes 1，其余七个容器全空）⇒ 只有这四项各减对应数，deadlines/thresholds/formulas/
    # evidence/definitions/edges/exceptions/recipients 八项**逐位不变**——同样是「未变的项即证据」。
    assert counts["artifacts"] == 335
    assert counts["deadlines"] == 25
    assert counts["slot_roles"] == 878  # 2026-08-05 乙路 #30：意向卡 +sr02（trigger 角色）877→878
    assert counts["thresholds"] == 41
    assert counts["formulas"] == 3
    assert counts["evidence"] == 370  # 三组合计（for_matching+for_submission+for_completion）
    assert counts["definitions"] == 1
    assert counts["nodes"] == 487
    assert counts["edges"] == 4
    assert counts["exceptions"] == 0


def test_allowed_top_level_keys_exhaustive():
    """母病闸真漏修·穷尽锚：白名单顶层键 == 真卡顶层键并集。

    真卡冒出**新顶层源**（新容器 / 新 provenance 源）而未登记白名单 → 红（卡多出）；
    白名单含真卡不存在的幻影键 → 红（白名单多出）。这堵死「新顶层源静默漏进」的口，
    与 `test_typed_dtos_ingest_all_398_cards` 的逐卡 ⊆ 断言互补（并集精确锚）。
    """
    cards = _load_cards()
    real_union = set()
    for c in cards:
        real_union |= set(c.keys())
    assert real_union == set(ALLOWED_TOP_LEVEL_KEYS), (
        f"真卡顶层键并集 ≠ 白名单: 卡多出 {sorted(real_union - set(ALLOWED_TOP_LEVEL_KEYS))}; "
        f"白名单多出 {sorted(set(ALLOWED_TOP_LEVEL_KEYS) - real_union)}"
    )


def test_top_level_key_attribution():
    """白名单每键有归属：九容器进 typed 处理（其 DTO 登记矩阵），provenance 类顶层源
    显式登记 category（provenance / explicitly_ignored）——不许只放行不归属。

    母病闸语义：「新顶层源」要么进 typed 处理、要么显式登记，绝不静默。
    """
    # 九容器与 provenance 类顶层源互斥，并集 == 白名单（无遗漏、无重叠）。
    assert set(REQUIRED_CONTAINERS).isdisjoint(PROVENANCE_TOP_LEVEL_SOURCES), (
        "九容器与 provenance 类顶层源不得重叠"
    )
    assert set(ALLOWED_TOP_LEVEL_KEYS) == set(REQUIRED_CONTAINERS) | set(
        PROVENANCE_TOP_LEVEL_SOURCES
    )
    # 九容器：CONTAINER_TO_DTOS 覆盖全九容器，且每 DTO 登记 SOURCE_DTO_MATRIX（进 typed 处理）。
    assert set(CONTAINER_TO_DTOS) == set(REQUIRED_CONTAINERS), "容器→DTO 映射漂移"
    for cont, dtos in CONTAINER_TO_DTOS.items():
        for dto in dtos:
            assert dto in SOURCE_DTO_MATRIX, (
                f"容器 {cont!r} 的 typed DTO {dto.__name__} 未登记 SOURCE_DTO_MATRIX"
            )
    # provenance 类顶层源：每键 category ∈ {provenance, explicitly_ignored}（封闭词表，非放行）。
    for k, cat in PROVENANCE_TOP_LEVEL_SOURCES.items():
        assert cat in {"provenance", "explicitly_ignored"}, (
            f"provenance 类顶层源 {k!r} 的 category 越界（须 provenance/explicitly_ignored）: {cat}"
        )


def test_extra_forbid_catches_new_source_key():
    """extra=forbid 母病断根自检：源子结构冒出新键 → ValidationError（不静默进入）。"""
    good = dict(
        threshold_regime_id="rc.f.c1.t1", measure_key="count.x", operator="<=",
        unit="mm", qualifiers={}, source_quote_refs=[], value=7,
    )
    S.ThresholdRegimeDTO(**good)  # 基准通过
    with pytest.raises(ValidationError):
        S.ThresholdRegimeDTO(**good, brand_new_regime_field="x")


def test_qualifier_ninth_key_hard_fails():
    """C.9 unknown_qualifier_key：qualifiers 第九键 → ValidationError（extra=forbid）。"""
    S.QualifierSetDTO(artifact_key="report.x", actor_role_key="ba")  # 八键内通过
    with pytest.raises(ValidationError):
        S.QualifierSetDTO(some_ninth_qualifier_key="x")
    # 八键集与 DTO 字段一致（新增/删除八键 → 红）
    assert set(S.QualifierSetDTO.model_fields) == set(S.QUALIFIER_EIGHT_KEYS)


def test_recipient_real_field_names():
    """指令锚点漂移回归：recipient 真实字段名 recipient_type/recipient_key（非 type/key）。"""
    assert set(S.RecipientDTO.model_fields) == {
        "recipient_id", "recipient_type", "recipient_key", "delivery_mode",
    }
    # spec 表的 type/key 若被误建为字段 → extra=forbid 会拒真卡；此处正向构造真字段
    S.RecipientDTO(recipient_id="r1", recipient_type="regulator", recipient_key="ba", delivery_mode="submit_to")


def test_recipient_bare_str_normalized():
    """阻断#4 / §D.7：裸 str recipient 经 ingress 归一为 {recipient_id: <串>}（保 deriver 兼容）。"""
    # 直接 RecipientDTO.from_raw
    r = S.RecipientDTO.from_raw("bd_office")
    assert r.recipient_id == "bd_office"
    assert r.recipient_type == "" and r.recipient_key == "" and r.delivery_mode == ""
    # 经 WorkflowOperandsDTO 顶层 field_validator：混装裸 str + 对象
    # （阻断#3：artifacts/deadlines/audiences/method_keys_allowed 现 required，须显式带）
    wf = S.WorkflowOperandsDTO(
        primary_actor="ri", primary_action="submit",
        recipients=["bd_office", {"recipient_id": "regulator", "recipient_type": "gov",
                                  "recipient_key": "bd", "delivery_mode": "submit_to"}],
        artifacts=[], deadlines=[], audiences=[], method_keys_allowed=[],
    )
    assert [x.recipient_id for x in wf.recipients] == ["bd_office", "regulator"]
    assert isinstance(wf.recipients[0], S.RecipientDTO)


# =========================================================================== #
# Node/Edge frozen + extra=forbid 契约（A.0；from_dict 母病闸真生效）
# =========================================================================== #


def test_node_edge_frozen_and_extra_forbid():
    n = S.ObligationNodeDTO.from_dict({"obligation_node_id": "n1", "node_kind": "obligation"})
    with pytest.raises((TypeError, ValidationError)):
        n.actor = "x"  # frozen
    with pytest.raises(ValidationError):
        S.ObligationNodeDTO(obligation_node_id="n1", node_kind="obligation", brand_new="x")

    e = S.ObligationEdgeDTO.from_dict(
        {"source_node_id": "a", "target_node_id": "b", "relation": "if_failed_then"}
    )
    with pytest.raises((TypeError, ValidationError)):
        e.relation = "z"  # frozen
    with pytest.raises(ValidationError):
        S.ObligationEdgeDTO(source_node_id="a", target_node_id="b", relation="r", brand_new="x")


def test_node_edge_from_dict_rejects_unknown_key():
    """阻断#2 母病闸真生效：from_dict **不预筛**，未知键透传 → extra=forbid ValidationError。

    旧实现 from_dict 先按已声明键过滤再构造，未知键被静默丢弃、extra=forbid 永不触发
    （＝化妆品自证）。此测试锁死「未知键必被拦」——闸真非空转的直接证据。
    """
    with pytest.raises(ValidationError):
        S.ObligationNodeDTO.from_dict({
            "obligation_node_id": "n1", "node_kind": "obligation",
            "UNKNOWN_EXTRA_KEY": "should_be_rejected",
        })
    with pytest.raises(ValidationError):
        S.ObligationEdgeDTO.from_dict({
            "source_node_id": "a", "target_node_id": "b", "relation": "if_unable_then",
            "INJECTED_KEY": 1,
        })


def test_node_edge_from_dict_still_works():
    """回归：加 frozen+extra=forbid 后 from_dict 现行真卡路径不破（真卡恰 8/3 键，透传即过）。"""
    raw_node = {
        "obligation_node_id": "n1", "node_kind": "obligation", "actor": "ba",
        "action": "submit", "recipient_ids": ["r1"], "artifact_ids": ["a1"],
        "deadline_ids": [], "trigger_condition_ids": ["c1"],
    }
    node = S.ObligationNodeDTO.from_dict(raw_node)
    assert node.obligation_node_id == "n1"
    assert node.recipient_ids == ["r1"]

    # 未知 node_kind 归一为 obligation（现行语义，test_method_semantics 依赖）
    coerced = S.ObligationNodeDTO.from_dict({"obligation_node_id": "n2", "node_kind": "duty"})
    assert coerced.node_kind == "obligation"

    raw_edge = {"source_node_id": "a", "target_node_id": "b", "relation": "if_unable_then"}
    edge = S.ObligationEdgeDTO.from_dict(raw_edge)
    assert edge.obligation_edge_id == "a->b:if_unable_then"


# =========================================================================== #
# 阻断#3 弱类型闸 + required 闸真生效（strict：str 不再自动转型；缺字段 → 拒）
# =========================================================================== #


def test_strict_rejects_type_wrong_source():
    """阻断#3 strict 闸真生效：type-wrong 源值 → ValidationError（str 不再自动转型）。

    直接证据：给 str 字段灌 int、给 bool 字段灌 int(1)、给 int 字段灌 str，strict 全拒。
    （旧无 strict 时 pydantic lax 会把这些静默转型＝弱类型空转。）
    """
    # 基准：正确类型通过
    S.ApplicabilityDTO(
        regime="rc.x", actors=[], phase="p", subject="s",
        component_scope=[], building_scope=[], exclusions=[],
    )
    # ① str 字段灌 int → 拒
    with pytest.raises(ValidationError):
        S.ApplicabilityDTO(
            regime=123, actors=[], phase="p", subject="s",
            component_scope=[], building_scope=[], exclusions=[],
        )
    # ② bool 字段灌 int(1) → 拒（strict bool 只收真 bool）
    with pytest.raises(ValidationError):
        S.SlotRoleDTO(slot_ref_id="r", slot_id="s", qualifiers={}, roles=[], required=1)
    # ③ int 字段灌 str → 拒（WorkflowDeadlineDTO.offset_value）
    with pytest.raises(ValidationError):
        S.WorkflowDeadlineDTO(
            deadline_id="d", relation="before", time_anchor_key="t", offset_value="5"
        )
    # ④ List[str] 元素灌 int → 拒
    with pytest.raises(ValidationError):
        S.ApplicabilityDTO(
            regime="r", actors=[7], phase="p", subject="s",
            component_scope=[], building_scope=[], exclusions=[],
        )


def test_required_fields_reject_missing():
    """阻断#3 required 闸真生效：398 全量存在字段去默认改 required——缺 → ValidationError。

    直接证据：applicability 缺 exclusions（曾有 default_factory）、evidence req 缺
    artifact_ids（曾有 default）、workflow 缺 method_keys_allowed（曾有 default）皆被拒。
    """
    # applicability 缺 exclusions（原 default_factory，现 required）
    with pytest.raises(ValidationError):
        S.ApplicabilityDTO(
            regime="r", actors=[], phase="p", subject="s",
            component_scope=[], building_scope=[],  # 缺 exclusions
        )
    # evidence req 缺 artifact_ids（原 default，现 required）
    with pytest.raises(ValidationError):
        S.EvidenceRequirementDTO(
            evidence_requirement_id="e", kind="k", required=True, description="d",
            slot_ref_ids=[], measure_keys=[], required_field_groups=[],  # 缺 artifact_ids
        )
    # workflow 缺 method_keys_allowed（原 default，现 required）
    with pytest.raises(ValidationError):
        S.WorkflowOperandsDTO(
            primary_actor="a", primary_action="x", recipients=[],
            artifacts=[], deadlines=[], audiences=[],  # 缺 method_keys_allowed
        )


def test_edge_id_always_derived_source_injection_discarded():
    """阻断#2 残留修：`ObligationEdgeDTO.from_dict` **始终从三元组派生** obligation_edge_id，
    源端注入的 obligation_edge_id **不被采信**（派生值权威）。

    直接证据：注入伪 edge_id 与无注入产出同一派生值，且 ≠ 注入值。
    """
    derived = "a->b:if_failed_then"
    e0 = S.ObligationEdgeDTO.from_dict(
        {"source_node_id": "a", "target_node_id": "b", "relation": "if_failed_then"}
    )
    assert e0.obligation_edge_id == derived
    # 源注入伪 edge_id → 丢弃，仍派生
    e1 = S.ObligationEdgeDTO.from_dict(
        {
            "source_node_id": "a", "target_node_id": "b", "relation": "if_failed_then",
            "obligation_edge_id": "INJECTED_FORGED_ID",
        }
    )
    assert e1.obligation_edge_id == derived, "源注入 edge_id 必须被丢弃（派生值权威）"
    assert e1.obligation_edge_id != "INJECTED_FORGED_ID"
    # 即使注入值与三元组「看似一致」也走派生（不读源字段）——换 relation 验证派生随三元组变
    e2 = S.ObligationEdgeDTO.from_dict(
        {
            "source_node_id": "x", "target_node_id": "y", "relation": "if_unable_then",
            "obligation_edge_id": "stale->cached:id",
        }
    )
    assert e2.obligation_edge_id == "x->y:if_unable_then"


def test_edge_id_derived_on_direct_construction_forgery_discarded():
    """收口残留修：**直构**路径 `ObligationEdgeDTO(...)` 也不可伪造 obligation_edge_id。

    病灶：from_dict 已丢弃源注入并派生，但 `ObligationEdgeDTO(source_node_id="a",
    target_node_id="b", relation="r", obligation_edge_id="FORGED")` **直构**曾保留
    FORGED——而 398 卡 ingest 测试恰走 `ObligationEdgeDTO(**e)` 直构，故加 edge_id 亦全过。
    修：`model_validator(mode="before")` 无条件从三元组重派生，直构与 from_dict 统一。

    直接证据：直构注入 FORGED → obligation_edge_id 为派生值（非 FORGED）。
    """
    # ① 直构无 edge_id → 派生
    e0 = S.ObligationEdgeDTO(
        source_node_id="a", target_node_id="b", relation="if_failed_then"
    )
    assert e0.obligation_edge_id == "a->b:if_failed_then"
    # ② 直构注入伪 edge_id → 丢弃，仍派生（关键：与 from_dict 统一不可伪造）
    e1 = S.ObligationEdgeDTO(
        source_node_id="a", target_node_id="b", relation="if_failed_then",
        obligation_edge_id="FORGED",
    )
    assert e1.obligation_edge_id == "a->b:if_failed_then", "直构注入 edge_id 必须被丢弃（派生值权威）"
    assert e1.obligation_edge_id != "FORGED"
    # ③ 直构派生随三元组变（换 relation）
    e2 = S.ObligationEdgeDTO(
        source_node_id="x", target_node_id="y", relation="if_unable_then",
        obligation_edge_id="stale->cached:id",
    )
    assert e2.obligation_edge_id == "x->y:if_unable_then"
    # ④ 直构注入 edge_id + 未知键仍触发 extra=forbid（母病闸不被 validator 绕过）
    with pytest.raises(ValidationError):
        S.ObligationEdgeDTO(
            source_node_id="a", target_node_id="b", relation="r",
            obligation_edge_id="FORGED", brand_new="x",
        )
