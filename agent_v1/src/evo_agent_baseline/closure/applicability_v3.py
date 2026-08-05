"""v3 单 bundle 编译式适用性判据(DEBT-065 第四轮 runtime 核心)。

依据 spec 草案 v3 §1.2 / §1.2.1 / §1.3 / §1.3.1。

设计要点(与被三轮审核否决的 v2.2 运行时组装式对照):
- runtime **不查授权表、不重建身份、不匹配卡指纹、不做三资产同源冻结**;
  三个可信输入全部来自离线产出的 bundle,用精确 digest 钉住。
- 判据是一个微小纯谓词:已授权卡目标叶 × fragment 可信叶身份 × 显式排斥对 → 早退;
  其余一切情形 → 不早退(fail-safe default)。
- **禁静默全关**:任何禁用早退都返回显式 DisabledReason,由调用方落盘到 run_meta
  (v3 §1.2-3;P1-2 "功能恒关闭却无人察觉" 的教训)。

判定权红线不变:本模块只提供判据数据与谓词,最终合规状态仍由 validate_building_closure 产出。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from evo_agent_baseline.closure.component_lattice import (
    LatticeIngestError,
    validate_disjoint_pair_shapes,
)


def canonical_hash(obj) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# 「调用方压根没传」这一情形的哨兵。用它而不是 None，是为了让**显式传 None**
# 也落进同一个 fail-closed 分支——否则"传 None 就跳过校验"这条 fail-open 通道
# 只是从默认值挪到了实参上（2026-07-27 codex 审核门 P1-B）。
_REQUIRED = object()

_RULECARD_PACK_PATH = ("agent_v1", "regulations", "rulecard_v2",
                       "mbis_cop_2023", "rule_cards.json")


def rulecard_content_digests(repo_root: pathlib.Path):
    """算 (卡包整体规范摘要, {rule_card_id: 卡指纹})——`load_bundle` 两处校验的实参来源。

    口径必须与 `card_applicability_manifest_v1.json` **生成时**一致
    (`scripts/build_card_applicability_manifest.py`)：
      - 卡包整体 = `canonical_hash(整个 cards_doc)`，**不是文件字节 sha256**；
      - 逐卡 = `card_fingerprint_v1(card)`。

    ⚠️ 口径猜错比不校验更糟——会让每次运行都误报 `rulecard_pack_mismatch` 而整路径禁用。
    `tests/test_retrievers.py::test_rulecard_digests_match_manifest_declarations` 钉住口径。

    读不到卡包 → `(None, None)`；调用方把它原样传给 `load_bundle` 即得 fail-closed 拒绝
    （2026-07-27 前是"退回不校验"，那正是审核门抓的 fail-open）。

    放在本模块而不是 `run_orchestrator`：**三个调用点**（运行时编排、发布门禁脚本、
    离线重放脚本）都要算同一个东西，口径散三份迟早漂移。
    """
    from evo_agent_baseline.closure.component_lattice import card_fingerprint_v1

    path = pathlib.Path(repo_root).joinpath(*_RULECARD_PACK_PATH)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        cards = doc.get("cards") or []
        return canonical_hash(doc), {
            c["rule_card_id"]: card_fingerprint_v1(c)
            for c in cards if isinstance(c, dict) and c.get("rule_card_id")
        }
    except Exception as exc:      # noqa: BLE001 —— 读不到就交给 fail-closed，但必须出声
        print(f"[applicability_v3] ⚠️ 卡包摘要算不出（{type(exc).__name__}）：{path}"
              f" —— 适用性判据将被拒绝启用（fail-closed）")
        return None, None


@dataclass(frozen=True)
class DisabledReason:
    """禁用早退的显式原因(必须落盘,禁静默全关)。"""

    code: str
    detail: str = ""

    def as_dict(self) -> dict:
        return {"code": self.code, "detail": self.detail}


@dataclass(frozen=True)
class ApplicabilityBundle:
    """已验证的适用性 bundle;唯一的判据数据来源。"""

    bundle_sha256: str
    leaf_types: frozenset
    disjoint_pairs: frozenset          # frozenset[frozenset[str, str]]
    card_targets: Dict[str, str]       # rule_card_id -> authorized_target_leaf
    fragment_identities: Dict[str, str]  # fragment_id -> physical_leaf_identity
    # ---- DEBT-081 触发器级结构 NA 正向授权（2026-08-02 决策门六字段键）----
    # 键 = (rule_card_id, condition_id, slot_ref_id, required_component_type_key,
    #       physical_leaf_identity, raw_component_type)
    # 值 = {"qualifiers_shape_sha256": ..., "source_combo_no": ...}（触发器限定符
    # 形状须精确等于裁定时形状才命中）。**缺省空 ⇒ 行为逐位不变**——资产存在
    # 本身就是开关；装载与卡指纹核验在 load_bundle 第四成员（步 8），单测可直构。
    trigger_na_authorizations: Dict[tuple, Dict[str, Any]] = None  # type: ignore[assignment]
    # fragment_id -> raw_component_type（原生构件型；授权键第六字段的运行时来源）。
    fragment_raw_types: Dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self):
        # dataclass 可变缺省规避：None → 空 dict（frozen=False 前提下安全）。
        if self.trigger_na_authorizations is None:
            object.__setattr__(self, "trigger_na_authorizations", {})
        if self.fragment_raw_types is None:
            object.__setattr__(self, "fragment_raw_types", {})

    def early_exit(self, rule_card_id: str, fragment_id: Optional[str]) -> Tuple[bool, Optional[str]]:
        """v3 §1.3 微小谓词。返回 (是否早退, 未早退时的原因码)。

        缺省拒绝:未授权 / 身份 unknown / 非叶 / 不在显式排斥对 → 一律不早退。
        """
        if fragment_id is None:
            return False, "not_fragment_scope"          # §1.3.1-1 楼级组件维结构 NA 已废止
        target = self.card_targets.get(rule_card_id)
        if not target:
            return False, "card_not_authorized"
        identity = self.fragment_identities.get(fragment_id)
        if not identity or identity == "unknown":
            return False, "fragment_identity_unknown"
        if target not in self.leaf_types or identity not in self.leaf_types:
            return False, "non_leaf"
        if frozenset((target, identity)) in self.disjoint_pairs:
            return True, None
        return False, "not_provably_disjoint"


# 授权行必备字段（六字段键＋形状哈希＋来源组合号）；缺任一＝模式违例。
_AUTH_ROW_REQUIRED_FIELDS = (
    "rule_card_id", "condition_id", "slot_ref_id",
    "required_component_type_key", "physical_leaf_identity",
    "raw_component_type", "qualifiers_shape_sha256", "source_combo_no",
)


def parse_trigger_na_rows(auth_doc, card_content_shas):
    """授权资产行解析（终审门 4，2026-08-02）：模式校验＋六字段完整性＋重复键硬拒。

    任一模式违例/重复键 ⇒ **拒绝启用授权功能**（返回空字典＋拒启说明——与
    三成员行为逐字节等价），bundle 其余判据不受影响。
    🔴 修复前重复键会被后行静默覆盖——「哪行生效」取决于文件顺序，
    属静默配置退化形状。卡指纹失配为**逐行失效**（引用与失效门语义），
    与整体拒启分开计。
    返回 (键→值字典, 失配行数, 拒启说明或 None)。
    """
    # 🔴 复审件 1′（2026-08-02）：重复键检查在**卡指纹时效过滤之前**独立做——
    # 首版先剔失配行再查重复，「一行有效＋同键一行失配」不会触发拒启，
    # 等于文件顺序仍决定生效行（同一静默退化形状换了件马甲，复审实测抓到）。
    # 结构异常（rows 非列表/行非对象）转拒启说明，不抛异常。
    rows_raw = auth_doc.get("rows")
    if rows_raw is None:
        rows_raw = []
    if not isinstance(rows_raw, list) or any(
            not isinstance(r, dict) for r in rows_raw):
        return {}, 0, "授权资产拒启：rows 结构异常（非列表或含非对象行）"
    schema_violations = 0
    keys_seen: set = set()
    duplicate_keys = 0
    parsed = []
    for row in rows_raw:
        if any(not row.get(f) and row.get(f) != 0 for f in _AUTH_ROW_REQUIRED_FIELDS):
            schema_violations += 1
            continue
        key = (
            str(row.get("rule_card_id")), str(row.get("condition_id")),
            str(row.get("slot_ref_id")),
            str(row.get("required_component_type_key")),
            str(row.get("physical_leaf_identity")),
            str(row.get("raw_component_type")),
        )
        if key in keys_seen:
            duplicate_keys += 1
            continue
        keys_seen.add(key)
        parsed.append((key, row))
    if schema_violations or duplicate_keys:
        return {}, 0, (
            f"授权资产拒启：模式违例 {schema_violations} 行、"
            f"重复键 {duplicate_keys} 个（功能整体关闭，其余判据不受影响）")
    # 键面干净后才做卡指纹时效过滤（逐行失效，另计）。
    auth: Dict[tuple, Dict[str, Any]] = {}
    stale_rows = 0
    for key, row in parsed:
        cid = row.get("rule_card_id")
        declared = row.get("card_content_sha256")
        actual = card_content_shas.get(cid) if card_content_shas else None
        if declared is None or actual is None or declared != actual:
            stale_rows += 1
            continue
        auth[key] = {
            "qualifiers_shape_sha256": row.get("qualifiers_shape_sha256"),
            "source_combo_no": row.get("source_combo_no"),
        }
    return auth, stale_rows, None


def load_bundle(
    bundle_path: Optional[str],
    expected_bundle_sha256: Optional[str],
    *,
    repo_root: pathlib.Path,
    worldgen_run_dir: Optional[str] = None,
    card_content_shas=_REQUIRED,
    rulecard_pack_sha256=_REQUIRED,
) -> Tuple[Optional[ApplicabilityBundle], Optional[DisabledReason]]:
    """按 v3 §1.2 契约加载 bundle。任何异常 → (None, DisabledReason),调用方禁用早退。

    Args:
        bundle_path / expected_bundle_sha256: **只能来自 run_meta 的冻结值**;
            本函数不搜索目录、不猜名字、不回落"最新文件"(§1.2-1)。
        worldgen_run_dir: 当前 run 实际使用的世界目录名;与 bundle 声明不符 → 禁用(§1.2-2)。
        card_content_shas: {rule_card_id: 该卡规范哈希};逐条比对,
            失配的卡视为未授权(§1.2.1-1 条目级时效)。**必传**——见下方 fail-closed 说明。
        rulecard_pack_sha256: 当前卡包整体哈希;与 bundle 声明不符 → 整路径禁用(§1.2.1-2)。
            **必传**。用 `rulecard_content_digests(repo_root)` 算。

    🔴 fail-closed(2026-07-27 codex 审核门 P1-B):后两个参数**不传 = 拒绝授权**,不是
    "跳过校验"。原写法是条件式(`if rulecard_pack_sha256:` / `if card_content_shas is
    not None:`),于是**只有主动传参的调用方才受保护**——发布门禁脚本与离线重放脚本
    一个都没传,过期或手工改过的 `authorized_target_leaf` 照样进 `card_targets`。
    这正是本项目反复踩的「安全校验默认放行」形状,故改成默认拒绝、由调用方证明时效。
    """
    if not bundle_path or not expected_bundle_sha256:
        return None, DisabledReason("bundle_pointer_missing", "run_meta 未冻结 bundle 路径/摘要")

    # 指针检查之后立刻做——比"指针都没有"更靠后、比任何文件读取更靠前(拿不到时效
    # 证明就没必要读盘)。哨兵与显式 None 同等对待,不留"传 None 就放行"的后门。
    if rulecard_pack_sha256 is _REQUIRED or rulecard_pack_sha256 is None:
        return None, DisabledReason(
            "rulecard_pack_sha_not_supplied",
            "调用方未提供当前卡包整体摘要 —— 无法证明 bundle 对应当前卡包，拒绝启用"
            "（用 applicability_v3.rulecard_content_digests(repo_root) 取）")
    if card_content_shas is _REQUIRED or card_content_shas is None:
        return None, DisabledReason(
            "card_content_shas_not_supplied",
            "调用方未提供逐卡内容指纹 —— 无法证明卡级授权未过期，拒绝启用"
            "（用 applicability_v3.rulecard_content_digests(repo_root) 取）")

    p = pathlib.Path(bundle_path)
    if not p.is_absolute():
        p = repo_root / p
    if not p.exists():
        return None, DisabledReason("bundle_file_missing", str(bundle_path))

    try:
        bundle = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return None, DisabledReason("bundle_unreadable", f"{type(exc).__name__}: {exc}")

    # 内容寻址回退（终审门 10，2026-08-02）：主路径内容已被新版替换时，
    # 按**期望摘要**去同目录 `archive/<sha>/` 归档解析（自包含：包＋全部成员副本，
    # 由构建器落包时同步写入）——历史批清单「原路径＋原摘要」无须人工改指针
    # 即可复现。找不到归档才失败（fail-closed 不变）。
    _archive_dir: Optional[pathlib.Path] = None
    if bundle.get("bundle_sha256") != expected_bundle_sha256:
        cand = p.parent / "archive" / str(expected_bundle_sha256) / "applicability_bundle.json"
        if cand.exists():
            try:
                bundle = json.loads(cand.read_text(encoding="utf-8"))
            except (ValueError, OSError) as exc:
                return None, DisabledReason("bundle_unreadable", f"archive: {exc}")
            if bundle.get("bundle_sha256") != expected_bundle_sha256:
                return None, DisabledReason(
                    "bundle_digest_mismatch", "归档内容与其目录名摘要不符")
            _archive_dir = cand.parent
        else:
            return None, DisabledReason(
                "bundle_digest_mismatch",
                f"期望 {expected_bundle_sha256[:12]}… 实际 "
                f"{str(bundle.get('bundle_sha256'))[:12]}…（无归档可回退）",
            )
    # 摘要必须覆盖**除自身外的全部顶层字段**——worldgen_run_dir 等安全相关字段若不在
    # 覆盖内,篡改它可绕过 §1.2-2 世界校验(PlusAI 基于真实代码的复审钉出)。
    if canonical_hash({k: v for k, v in bundle.items() if k != "bundle_sha256"}) != bundle.get("bundle_sha256"):
        return None, DisabledReason(
            "bundle_self_inconsistent", "bundle_sha256 与顶层内容不符(含 worldgen_run_dir)"
        )

    if worldgen_run_dir and bundle.get("worldgen_run_dir") != worldgen_run_dir:
        return None, DisabledReason(
            "worldgen_dir_mismatch",
            f"bundle={bundle.get('worldgen_run_dir')} run={worldgen_run_dir}",
        )

    # 逐成员按 digest 验证并加载
    members = bundle.get("members", {})
    docs = {}
    for name in ("leaf_exclusion_spec", "card_applicability_manifest", "w0_fragment_identity_manifest"):
        m = members.get(name)
        if not m:
            return None, DisabledReason("bundle_member_missing", name)
        # 归档解析时成员从归档目录读（自包含快照——旧成员内容在仓库主路径
        # 早被新版替换，主路径读必然 digest 失配）。
        mp = (_archive_dir / f"{name}.json") if _archive_dir is not None \
            else (repo_root / m["path"])
        if not mp.exists():
            return None, DisabledReason("member_file_missing", f"{name}: {mp}")
        try:
            doc = json.loads(mp.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            return None, DisabledReason("member_unreadable", f"{name}: {exc}")
        if canonical_hash(doc) != m.get("content_sha256"):
            return None, DisabledReason("member_digest_mismatch", name)
        docs[name] = doc

    lattice = docs["leaf_exclusion_spec"]
    card_doc = docs["card_applicability_manifest"]
    ident_doc = docs["w0_fragment_identity_manifest"]

    # 🔴 fail-closed（2026-07-26 codex 审核门高 2）：原写法 `not in (None, sha)` 意味着
    # **声明为 `None` 时通过** ⇒ **删掉 `rulecard_pack_sha256` 反而能绕过校验**。
    # 缺声明的 manifest 不是"兼容旧格式"，而是**无法证明它对应当前卡包** —— 必须拒绝，
    # 并给独立原因码好让批驱动区分"摘要不符"与"根本没声明"。
    declared_pack = card_doc.get("rulecard_pack_sha256")
    if declared_pack is None:
        return None, DisabledReason(
            "legacy_unbound_bundle",
            "manifest 未声明 rulecard_pack_sha256 —— 无法证明它对应当前卡包，拒绝启用")
    if declared_pack != rulecard_pack_sha256:
        return None, DisabledReason(
            "rulecard_pack_mismatch", "卡包整体摘要与 manifest 声明不符")

    leaf_types = frozenset(lattice.get("leaf_types", []))
    # 🔴 加载边界形状校验（2026-07-27 护栏缺口 2）：自反对（`["external_wall",
    # "external_wall"]`，frozenset 坍缩成单元素）或非二元对一旦装进判据，
    # `early_exit` 的 `frozenset((target, identity)) in disjoint_pairs` 会在
    # target == identity 时命中 ⇒ 本该适用的条款被判「结构不适用」跳过义务（假阴性）。
    # `component_lattice` 的加载器本来就拒这种资产，本路径**复用同一份校验**，
    # 不复制第二份；违例 ⇒ 整包禁用早退（fail-closed），显式原因码落盘。
    try:
        disjoint = frozenset(validate_disjoint_pair_shapes(lattice.get("disjoint_pairs", [])))
    except LatticeIngestError as exc:
        return None, DisabledReason("disjoint_shape_invalid", str(exc))

    # 条目级卡绑定时效:失配的卡视为未授权(不早退),而非整体失效
    card_targets: Dict[str, str] = {}
    stale = []
    for cid, entry in (card_doc.get("cards") or {}).items():
        target = entry.get("authorized_target_leaf")
        if not target:
            continue
        declared = entry.get("card_content_sha256")
        actual = card_content_shas.get(cid)
        # 🔴 fail-closed（同高 2）：原写法 `declared and actual and declared != actual`
        # 意味着**任一缺失就跳过检查** ⇒ 删掉 `card_content_sha256`、或卡已不在当前
        # 卡包（`actual` 取不到）时，该卡的旧授权照样进判据路径。
        # 三种情形都视为**明确失效**：①manifest 没声明 ②当前卡包里没这张卡 ③摘要不符。
        # 外层 `if card_content_shas is not None:` 已删（2026-07-27 P1-B）——参数现为
        # 必传，缺席在函数开头就已拒绝，此处不再需要"没传就整段跳过"的分支。
        if declared is None or actual is None or declared != actual:
            stale.append(cid)
            continue
        card_targets[cid] = target

    fragment_identities = {
        fid: e.get("physical_leaf_identity")
        for fid, e in (ident_doc.get("fragments") or {}).items()
        if e.get("physical_leaf_identity") and e.get("physical_leaf_identity") != "unknown"
    }
    # 原生构件型映射（DEBT-081 六字段授权键第六字段的运行时来源）：只收可信身份
    # 的片段（与 fragment_identities 同门槛——身份 unknown 的片段不参与授权判定）。
    fragment_raw_types = {
        fid: e.get("raw_component_type")
        for fid, e in (ident_doc.get("fragments") or {}).items()
        if e.get("raw_component_type") and fid in fragment_identities
    }

    # ---- 可选第四成员：触发器级结构 NA 正向授权（DEBT-081，2026-08-02）----
    # 缺席 = 功能关闭（trigger_na_authorizations 空 ⇒ 行为逐位不变）；
    # 存在 = digest 核验（generic 校验同三成员）＋ **逐行卡指纹核验**
    # （codex 引用与失效门：卡指纹漂移仅该行失效保持 unknown，非整包失效）。
    trigger_na_auth: Dict[tuple, Dict[str, Any]] = {}
    stale_auth_rows = 0
    m4 = members.get("trigger_structural_na_authorizations")
    if m4:
        mp4 = (_archive_dir / "trigger_structural_na_authorizations.json") \
            if _archive_dir is not None else (repo_root / m4["path"])
        if not mp4.exists():
            return None, DisabledReason(
                "member_file_missing", f"trigger_structural_na_authorizations: {m4['path']}")
        try:
            auth_doc = json.loads(mp4.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            return None, DisabledReason(
                "member_unreadable", f"trigger_structural_na_authorizations: {exc}")
        if canonical_hash(auth_doc) != m4.get("content_sha256"):
            return None, DisabledReason(
                "member_digest_mismatch", "trigger_structural_na_authorizations")
        trigger_na_auth, stale_auth_rows, auth_refused = parse_trigger_na_rows(
            auth_doc, card_content_shas)

    loaded = ApplicabilityBundle(
        bundle_sha256=bundle["bundle_sha256"],
        leaf_types=leaf_types,
        disjoint_pairs=disjoint,
        card_targets=card_targets,
        fragment_identities=fragment_identities,
        trigger_na_authorizations=trigger_na_auth,
        fragment_raw_types=fragment_raw_types,
    )
    # stale 卡/授权行不是致命错误(保守退化为未授权),但调用方应记录
    notes = []
    if stale:
        notes.append(f"{len(stale)} 张卡指纹失配已降为未授权")
    if stale_auth_rows:
        notes.append(f"{stale_auth_rows} 行触发器授权卡指纹失配已失效")
    if m4 and auth_refused:
        notes.append(auth_refused)
    reason = DisabledReason("stale_card_bindings", "；".join(notes)) if notes else None
    return loaded, reason
