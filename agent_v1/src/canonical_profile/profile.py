"""canonical_profile 核心实现（spec 草案 v4 Block C，§C.0-C.9）。

内容：
- `canonical_json` / `sha256_hex_24`：确定性序列化 + 双哈希用 24 位 sha256（C.8/A.5）。
- Decimal ingress：`parse_json_decimal` / `canonical_decimal_str`（C.8）——JSON 原始
  token 用 Decimal 解析、禁 NaN/Inf、-0→0、去尾零、禁指数、7/7.0→"7"。
- NFC：`nfc`（C.8）。
- 七维 canonical registry：`CanonicalRegistry`（alias→canonical 单向、闭包性
  canon(canon(x))==canon(x)、alias 图无环、冲突 hard-fail）+ 七个便捷函数
  （measure/slot/artifact/unit/formula/deadline）+ C.9 七维 unknown/empty/conflict 规则。
- qualifier 八键 → canonical namespace 八行映射（C.6）+ `qualifier_fingerprint`。
- `in_not_in_sort`（C.8 集合语义排序）。

分层红线：本模块不 import closure / workflow_engine / eval。
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple


# ---------------------------------------------------------------------------
# profile 版本（C.0）——进 identity（改进3），bump → canonical_identity_hash 变。
# v1→v2（2026-07-14，fail-closed 连贯设计 §4）：registry 真键 identity 灌注 + 种子清冲突
# （measure/artifact/slot/unit/deadline 真卡枚举键、slot 别名去撞真键）改变了 canonical
# 归一表 → 身份哈希语义变，据 C.0「profile 变必 bump」升 v2（IDENTITY_SCHEMA binding
# 字段集/哈希函数不变故留 v2；版本由本 profile_id 承载，见交付报告）。
# ---------------------------------------------------------------------------
CANONICAL_PROFILE_ID = "mbis_canonical_v2"


class CanonicalProfileError(Exception):
    """canonical_profile 致命错误（alias 环/冲突、未知 hard-fail 维度、非法数字）。

    直接继承 Exception，不经任何 `except Exception` 兜底基类（对齐 A.5
    ObligationContractError re-raise 白名单精神）。
    """


# ===========================================================================
# C.8 — NFC / Decimal ingress / canonical_json
# ===========================================================================


def nfc(value: str) -> str:
    """Unicode NFC 归一（C.8：所有进 canonical 序列化的字符串先 NFC）。"""
    return unicodedata.normalize("NFC", value)


def parse_json_decimal(text: str) -> Any:
    """按 C.8 从 JSON 文本解析：数字用 Decimal（不先转 float），拒 NaN/Infinity。

    `json.loads(..., parse_float=Decimal)`：带小数点/指数的数字 → Decimal，整数 → int。
    Python json 默认允许 `NaN`/`Infinity` 字面量 → 用 parse_constant 拦截。
    """

    def _reject_constant(name: str) -> Any:
        raise CanonicalProfileError(f"canonical_number_non_finite:{name}")

    return json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)


def canonical_decimal_str(token: Any) -> str:
    """规范化数字为 canonical decimal 字符串（C.8）。

    入参可为 str（原始 JSON token）/ int / Decimal。规则：
    - 拒 NaN / Infinity → `CanonicalProfileError`；
    - `-0 → 0`；去无效尾零（`7.50 → 7.5`）；禁指数（`7 / 7.0 / 7e0 / 700e-2 → "7"`）；
    - 整数与浮点等价：`7` 与 `7.0` 均 → `"7"`。
    """
    if isinstance(token, bool):
        # bool 是 int 子类，但数字语义下不应把 True/False 当 1/0。
        raise CanonicalProfileError("canonical_number_bool_not_allowed")
    try:
        if isinstance(token, Decimal):
            d = token
        elif isinstance(token, int):
            d = Decimal(token)
        elif isinstance(token, str):
            d = Decimal(token.strip())
        elif isinstance(token, float):
            # 不鼓励（应走 Decimal ingress），但为 manifest 等场景保守接纳：
            # 经 str() 再 Decimal，避免二进制浮点噪声。
            d = Decimal(str(token))
        else:
            raise CanonicalProfileError(f"canonical_number_bad_type:{type(token).__name__}")
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalProfileError(f"canonical_number_parse_error:{token!r}") from exc

    if not d.is_finite():
        raise CanonicalProfileError(f"canonical_number_non_finite:{token!r}")

    if d == 0:
        # -0 → 0，且 0.00 → 0
        return "0"

    # normalize() 去尾零，但可能产出指数形式（1E+2）；format(d, 'f') 展开为定点。
    normalized = d.normalize()
    plain = format(normalized, "f")
    # 保险：format 'f' 不产指数，且不会残留尾零（因已 normalize）。
    return plain


def canonical_json(obj: Any) -> str:
    """确定性 canonical 序列化（C.8 / A.5）。

    - dict：键 NFC 后字典序升序，`{"k":v,...}`，分隔符无空白；
    - list / tuple：`[v,...]` 保序（调用方负责先按全序键排好）；
    - str：NFC 归一后 JSON 转义（ensure_ascii=False）；
    - bool：`true/false`；int：十进制；Decimal / float：`canonical_decimal_str`；
    - None：`null`。

    数字统一走 `canonical_decimal_str` → `7` 与 `7.0` bytes 一致。
    """
    return _encode(obj)


def _encode(obj: Any) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, str):
        return json.dumps(nfc(obj), ensure_ascii=False, separators=(",", ":"))
    if isinstance(obj, (int,)) and not isinstance(obj, bool):
        return str(int(obj))
    if isinstance(obj, (Decimal, float)):
        return canonical_decimal_str(obj)
    if isinstance(obj, dict):
        items = sorted(((nfc(str(k)), v) for k, v in obj.items()), key=lambda kv: kv[0])
        inner = ",".join(
            json.dumps(k, ensure_ascii=False, separators=(",", ":")) + ":" + _encode(v)
            for k, v in items
        )
        return "{" + inner + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(_encode(v) for v in obj) + "]"
    raise CanonicalProfileError(f"canonical_json_unserializable:{type(obj).__name__}")


def sha256_hex_24(text: str) -> str:
    """sha256 十六进制前 24 位（A.5 双哈希用）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


# ===========================================================================
# C.0-C.5 / C.7 / C.9 — 七维 canonical registry
# ===========================================================================

# C.9 未知策略：passthrough（保守，unresolved binding + 诊断）或 hard_fail。
UnknownPolicy = Literal["passthrough", "hard_fail"]


@dataclass(frozen=True)
class CanonResult:
    """单值 canonicalize 结果（C.9 输出规则）。

    - resolved：命中 registry（含 alias→canonical 或本身即 canonical），canonical_key 非空。
    - unresolved：未知值经 passthrough（保守），canonical_key = 原值（NFC），diagnostic 记码。
    hard_fail 维度（artifact/formula）不返回本结构，直接 raise。
    """

    canonical_key: str
    resolution: Literal["resolved", "unresolved"]
    diagnostic: Optional[str] = None


class CanonicalRegistry:
    """版本化 canonical 别名表（C.0）。

    - 方向：alias → canonical（单向）。
    - 闭包性：`canon(canon(x)) == canon(x)`——canonical 目标不得再作 alias 键映向他值。
    - 环：alias 图无环（load-time hard-fail `canonical_alias_cycle`）。
    - 冲突：一 alias 映多 canonical → hard-fail `canonical_alias_conflict`。
    - 未知：按 `unknown_policy`（C.9 七维表）。
    """

    def __init__(
        self,
        name: str,
        pairs: Iterable[Tuple[str, str]],
        *,
        unknown_policy: UnknownPolicy,
        unknown_code: str,
        prenormalize_casefold: bool = False,
    ) -> None:
        self.name = name
        self.unknown_policy = unknown_policy
        self.unknown_code = unknown_code
        self._prenormalize_casefold = prenormalize_casefold

        alias_map: Dict[str, str] = {}
        for raw_alias, raw_canon in pairs:
            alias = self._prenormalize(raw_alias)
            canon = nfc(raw_canon)
            if alias in alias_map and alias_map[alias] != canon:
                raise CanonicalProfileError(
                    f"canonical_alias_conflict:{name}:{alias}->"
                    f"{alias_map[alias]}|{canon}"
                )
            alias_map[alias] = canon
        self._alias_map = alias_map
        self._canonicals = set(alias_map.values())

        self._check_cycles()
        self._check_closure()

    def _prenormalize(self, value: str) -> str:
        out = nfc(value)
        if self._prenormalize_casefold:
            out = out.strip().casefold()
        return out

    def _check_cycles(self) -> None:
        """alias 图无环（follow 每条 alias 链，撞回已访问节点 → hard-fail）。

        canonical 自映射（`x -> x` 固定点）合法、非环——遇固定点即停。
        """
        for start in self._alias_map:
            seen = {start}
            cur = start
            while cur in self._alias_map:
                nxt = self._alias_map[cur]
                if nxt == cur:
                    break  # 固定点（canonical 映射到自身），非环
                if nxt in seen:
                    raise CanonicalProfileError(
                        f"canonical_alias_cycle:{self.name}:{start}"
                    )
                seen.add(nxt)
                cur = nxt

    def _check_closure(self) -> None:
        """闭包性：canon(canon(x)) == canon(x)。

        即：任一 canonical 目标 c 若又是 alias 键，必须映向自身；否则 canon 不幂等。
        """
        for canon in self._canonicals:
            key = self._prenormalize(canon)
            if key in self._alias_map and self._alias_map[key] != canon:
                raise CanonicalProfileError(
                    f"canonical_alias_not_idempotent:{self.name}:{canon}"
                )

    def canonicalize(self, value: str) -> CanonResult:
        """归一单值（假定非空；空值由调用方按 C.9「empty→不生成 entry」先行判定）。"""
        key = self._prenormalize(value)
        if key in self._alias_map:
            return CanonResult(self._alias_map[key], "resolved", None)
        if key in self._canonicals:
            # 本身即 canonical（未登记为 alias，但是某 alias 的目标）。
            return CanonResult(nfc(value) if not self._prenormalize_casefold else key,
                               "resolved", None)
        # 未知
        if self.unknown_policy == "hard_fail":
            raise CanonicalProfileError(f"{self.unknown_code}:{self.name}:{value}")
        passthrough = key if self._prenormalize_casefold else nfc(value)
        return CanonResult(passthrough, "unresolved", self.unknown_code)


def is_empty_source_value(value: Any) -> bool:
    """C.9 empty 判定：None / 空串 / 纯空白 → True（调用方据此不生成 binding entry）。"""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


# --- registry（种子 alias 例 + 真实 397 卡枚举键 identity 灌注，spec C.1-C.5/C.7）---------
# 填充范围（DEBT：从 rule_cards.json 枚举，2026-07-14）：measure 24 / artifact 25 /
# slot 43 / unit 15（seed 已含 mm/m/day）/ deadline(time_anchor) 15 维真实键，均以 identity
# 映射（key→key）灌入 → 真键 resolve（非 unresolved / 非被吞 hard-fail）；bogus 键仍按 C.9
# 各维策略（artifact/formula hard-fail；measure/slot/unit/deadline passthrough）。种子合成
# alias 例保留以驱动 C.9 alias-resolution 单测（identity 灌注不与之冲突）。
#
# ⚠️ 真卡与种子冲突（据实报，非顺编）：真卡 slot_id `repair.prescribed.started` 是 canonical
# 本体，而旧种子把它当 alias→`procedure.repair.prescribed.started`（synthetic）。二者冲突
# （一 alias 两 canonical）。化解：真键 `repair.prescribed.started` 灌 identity（尊重真卡权
# 威），旧 alias demo key 改为明确 synthetic 的 `legacy_alias.repair_prescribed_started`
# （保留 alias→canonical 演示，不再撞真键）。见交付报告「与真卡不符处」。

# 真实枚举键（rule_cards.json，397 卡）。
_REAL_MEASURE_KEYS = (
    "area.signboard.display",
    "count.canopy.check_locations.minimum",
    "count.private_premises_access.floor_interval",
    "count.pull_test.additional_after_failure",
    "count.pull_test.failed_cumulative",
    "count.pull_test.per_floor_full_retiling",
    "count.pull_test.per_repaired_facade",
    "count.repair_mortar_specimens.per_strength_property",
    "depth.patch_repair",
    "duration.delivery.deadline",
    "duration.notification.deadline",
    "duration.repair_mortar.test_age",
    "duration.site_visit.interval",
    "duration.submission.deadline",
    "length.canopy.check_location.interval",
    "length.crack.width",
    "length.rendering.layer_thickness",
    "length.rendering.total_thickness",
    "rate.pull_test.per_25m2",
    "ratio.chloride_content.by_cement_weight",
    "ratio.covered_area.inspected",
    "ratio.covered_structure_area.inspected",
    "ratio.external_wall_area.inspected",
    "stress.pull_test.minimum",
)

_REAL_ARTIFACT_KEYS = (
    "certificate.material_compliance",
    "drawing.annotated_location_plan",
    "form.mbi3_or_mbi3a",
    "form.mbi4",
    "form.mbi5",
    "notice.detailed_investigation_intention",
    "notice.representative_appointment_intended",
    "notice.ri_appointment",
    "notice.ri_cessation",
    "notice.ri_temporary_nomination",
    "notice.temporary_ri_nomination_cessation",
    "photo.annotated_defect",
    "proposal.detailed_investigation",
    "proposal.repair",
    "proposal.repair_revision",
    "proposal.supervision",
    "record.inspection_log",
    "record.nonconformity_correction_sp2",
    "record.site_visit_log",
    "record.supervision_checklist",
    "report.completion",
    "report.inspection",
    "report.test_result",
    "statement.mbis_repairs_separated_from_additional_upgrades",
    "statement.outstanding_order_scope_included",
)

_REAL_SLOT_KEYS = (
    "actor.representative.assigned",
    "actor.representative.qualified_for_assigned_role",
    "defect.cause_or_extent.uncertain",
    "defect.class.present",
    "defect.drainage.misconnection.present",
    "defect.range.extends_into_private_premises",
    "defect.range.uncertain",
    "procedure.appointment.completed",
    "procedure.inspection.prescribed.completed",
    "procedure.investigation.detailed.started",
    "procedure.investigation.proposal.endorsed_by_ba",
    "procedure.investigation.proposal.recognized",
    "procedure.investigation.proposal.refused_by_ba",
    "procedure.investigation.proposal.submitted",
    "procedure.nomination.completed",
    "procedure.person.decides_to_proceed_with_investigation",
    "procedure.person.informed_of_ba_refusal",
    "repair.prescribed.completed",
    "repair.prescribed.started",
    "repair.proposal.revision_required",
    "repair.required",
    "reporting.annotated_location_plan.present",
    "reporting.annotated_photo.present",
    "reporting.artifact.delivered",
    "reporting.artifact.prepared",
    "reporting.artifact.signed",
    "reporting.artifact.submitted",
    "reporting.material_certificate.present",
    "reporting.record.maintained",
    "reporting.record.submitted",
    "risk.building_safety.emergency",
    "risk.fire_safety.adverse_impact",
    "risk.public_danger.present",
    "risk.public_health.emergency",
    "scope.component.covered",
    "scope.component.covered_by_large_attached_signboard",
    "scope.component.inspection_excluded",
    "scope.component.inspection_included",
    "supervision.record.completed",
    "supervision.record.retained",
    "supervision.site_visit.performed",
    "verification.test.failed",
    "verification.test.performed",
)

# unit：种子已含 mm/m/day（含 alias）；下列为真卡额外单位（casefold 归一，identity 灌注）。
_REAL_UNIT_KEYS = (
    "%",
    "N/mm2",
    "N_per_mm2",
    "floor",
    "location",
    "m2",
    "m2_per_test",
    "month",
    "ratio",
    "specimen",
    "test",
    "test_per_25m2",
)

# time_anchor（deadline 维）：真卡 threshold time_anchor_key + workflow deadline time_anchor。
_REAL_TIME_ANCHOR_KEYS = (
    "appointment.repair_supervising_ri.made",
    "appointment.representative.supervision.made",
    "appointment.ri.made",
    "inspection.prescribed.completed",
    "inspection.report.submitted_to_ba",
    "investigation.detailed.commencement",
    "nomination.temporary_ri.made",
    "nomination.temporary_ri.terminated",
    "repair.completion_report.submitted_to_ba",
    "repair.prescribed.completed",
    "repair.prescribed.started",
    "repair.revision_need.exposed",
    "repair.revision_proposal.submitted_to_ba",
    "role.ri.terminated",
    "role.supervision_team.changed",
)


def _identity_pairs(keys):
    """真实键 → identity (key, key) 灌注，使真键 resolve。"""
    return [(k, k) for k in keys]


_MEASURE_REGISTRY = CanonicalRegistry(
    "measure",
    [
        # 种子合成 alias 例（驱动 C.9 alias-resolution 单测）。
        ("crack_width", "measure.crack_width"),
        ("crackwidth", "measure.crack_width"),
        ("measure.crack_width", "measure.crack_width"),
        ("spalling_area", "measure.spalling_area"),
    ]
    + _identity_pairs(_REAL_MEASURE_KEYS),
    unknown_policy="passthrough",
    unknown_code="unknown_measure_key",
)

_SLOT_REGISTRY = CanonicalRegistry(
    "slot",
    [
        # 种子合成 alias 例（改为明确 synthetic key，不再撞真卡 slot_id）。
        ("legacy_alias.repair_prescribed_started", "procedure.repair.prescribed.started"),
        ("procedure.repair.prescribed.started", "procedure.repair.prescribed.started"),
        ("inspection.completed", "procedure.inspection.completed"),
    ]
    + _identity_pairs(_REAL_SLOT_KEYS),
    unknown_policy="passthrough",
    unknown_code="unknown_slot_key",
)

_ARTIFACT_REGISTRY = CanonicalRegistry(
    "artifact",
    [
        # 种子合成 alias 例（驱动 C.9 hard-fail 单测）。
        ("inspection_report", "artifact.inspection_report"),
        ("artifact.inspection_report", "artifact.inspection_report"),
        ("repair_certificate", "artifact.repair_certificate"),
    ]
    + _identity_pairs(_REAL_ARTIFACT_KEYS),
    unknown_policy="hard_fail",
    unknown_code="unknown_artifact_key",
)

_UNIT_REGISTRY = CanonicalRegistry(
    "unit",
    [
        ("mm", "mm"),
        ("millimetre", "mm"),
        ("millimeter", "mm"),
        ("m", "m"),
        ("metre", "m"),
        ("meter", "m"),
        ("day", "day"),
        ("days", "day"),
    ]
    + _identity_pairs(_REAL_UNIT_KEYS),
    unknown_policy="passthrough",
    unknown_code="unknown_unit",
    prenormalize_casefold=True,  # C.4：大小写不敏感（MM==mm）
)

_FORMULA_REGISTRY = CanonicalRegistry(
    "formula",
    [
        ("pull_test_additional_after_failure", "formula.pull_test_additional_after_failure"),
        ("formula.pull_test_additional_after_failure",
         "formula.pull_test_additional_after_failure"),
    ],
    unknown_policy="hard_fail",
    unknown_code="unsupported_formula",
)

_DEADLINE_REGISTRY = CanonicalRegistry(
    "deadline",
    [
        ("completion", "time_anchor.completion"),
        ("time_anchor.completion", "time_anchor.completion"),
        ("issue_date", "time_anchor.issue_date"),
    ]
    + _identity_pairs(_REAL_TIME_ANCHOR_KEYS),
    unknown_policy="passthrough",
    unknown_code="unknown_deadline_key",
)


def canonicalize_measure(value: str) -> CanonResult:
    """C.1 measure 归一（unknown → passthrough + unknown_measure_key）。"""
    return _MEASURE_REGISTRY.canonicalize(value)


def canonicalize_slot(value: str) -> CanonResult:
    """C.2 slot 归一（unknown → passthrough + unknown_slot_key）。"""
    return _SLOT_REGISTRY.canonicalize(value)


def canonicalize_artifact(value: str) -> CanonResult:
    """C.3 artifact 归一（unknown → hard-fail unknown_artifact_key，对齐 resolve_artifact_slot）。"""
    return _ARTIFACT_REGISTRY.canonicalize(value)


def canonicalize_unit(value: str) -> CanonResult:
    """C.4 unit 归一（大小写不敏感；unknown → passthrough + unknown_unit）。"""
    return _UNIT_REGISTRY.canonicalize(value)


def canonicalize_formula(value: str) -> CanonResult:
    """C.5 formula 归一（unknown → hard-fail unsupported_formula）。"""
    return _FORMULA_REGISTRY.canonicalize(value)


def canonicalize_deadline(value: str) -> CanonResult:
    """C.7 deadline / time_anchor 归一（unknown → passthrough + unknown_deadline_key）。"""
    return _DEADLINE_REGISTRY.canonicalize(value)


# ===========================================================================
# C.6 — qualifier 八键 → canonical namespace 八行映射
# ===========================================================================

# 真实八键（枚举全 397 卡，附录 D §D.5）→ canonical namespace。
QUALIFIER_NAMESPACE: Dict[str, str] = {
    "artifact_key": "qualifier.artifact",
    "component_type_key": "qualifier.component_type",
    "location_class_key": "qualifier.location_class",
    "actor_role_key": "qualifier.actor_role",
    "defect_class_key": "qualifier.defect_class",
    "method_key": "qualifier.method",
    "risk_class_key": "qualifier.risk_class",
    "material_class_key": "qualifier.material_class",
}


def canonicalize_qualifier(key: str, value: str) -> Tuple[str, str]:
    """单个 qualifier 键值归一（C.6）。

    - 键必须在八键空间，否则 hard-fail `unknown_qualifier_key`（不丢弃、不 str() 糊平）；
    - 返回 `(namespace_canonical, value_canonical)`（均 NFC）。
    """
    k = nfc(key)
    if k not in QUALIFIER_NAMESPACE:
        raise CanonicalProfileError(f"unknown_qualifier_key:{key}")
    return QUALIFIER_NAMESPACE[k], nfc(value)


def qualifier_fingerprint(
    pairs: Iterable[Tuple[str, str]],
) -> Tuple[Tuple[str, str], ...]:
    """一组 qualifier (key, value) → NFC 升序去重的 canonical (namespace, value) 元组（C.6）。

    - 同 key 多值 → 多 entry（不折叠）；完全相同的 (namespace, value) 去重。
    """
    out = {canonicalize_qualifier(k, v) for k, v in pairs}
    return tuple(sorted(out, key=lambda pair: (pair[0], pair[1])))


# ===========================================================================
# C.8 — in / not_in 集合语义排序
# ===========================================================================

# 类型标签排序：none 排最前，其后 bool < decimal < string（字典序约定）。
_IN_TYPE_RANK: Dict[str, int] = {"none": 0, "bool": 1, "decimal": 2, "string": 3}


def in_not_in_sort(
    tagged_values: Iterable[Tuple[str, str]],
) -> Tuple[Tuple[str, str], ...]:
    """in / not_in 集合语义规范化（C.8）。

    入参 `(type_tag, canonical_value)`（value 已按对应类型 canonical：decimal 走
    canonical_decimal_str、string 走 NFC）。总序 = 类型标签序（none/bool/decimal/string）
    + NFC 值全序；去重。真实 397 卡 threshold 无 in/not_in（备用未来卡）。
    """
    normalized: List[Tuple[str, str]] = []
    for tag, value in tagged_values:
        if tag not in _IN_TYPE_RANK:
            raise CanonicalProfileError(f"canonical_in_bad_type_tag:{tag}")
        normalized.append((tag, nfc(value)))
    unique = sorted(set(normalized), key=lambda tv: (_IN_TYPE_RANK[tv[0]], tv[1]))
    return tuple(unique)
