"""生成 exact_fragment_target_authorizations_v1.json 精确目标授权表(DEBT-065 第一波)。

依据 spec 草案 v2.2 §2.5。**保守版**:只纳入 118 卡初裁的**高置信** precise_target
(55 卡,义务动词直指组件本体)。中置信 46 卡 + 存疑口径待人工定后另行扩充——保守授权只
会少授权、绝不错授权(宁可少 NA,守判定权红线)。

card_fingerprint.v1 = sha256(UTF-8(JSON(原始单卡对象,sort_keys,separators=(',',':'),ensure_ascii=False)))
——哈希原始 rule_cards.json 单卡对象,不哈希 KG 重建 DTO。

用法:python agent_v1/scripts/build_exact_fragment_target_authorizations.py
产物:agent_v1/regulations/rulecard_v2/mbis_cop_2023/exact_fragment_target_authorizations_v1.json
"""
import hashlib
import json
import pathlib
import re
import sys

REG = pathlib.Path(__file__).resolve().parents[1] / "regulations" / "rulecard_v2" / "mbis_cop_2023"
DRAFT = pathlib.Path(__file__).resolve().parents[2] / "杂物箱" / "文件包" / "DEBT-065_修复周期材料_20260724" / "授权初裁草稿_118卡_20260724.md"
LEAF = {"external_wall", "fire_safety_component", "drainage_component", "cantilevered_canopy", "wall_tiles"}
ID_PREFIX = "rc.mbis."


def canonical_hash(obj):
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_high_confidence(md_text):
    """解析初裁草稿 section 三(高置信 precise_target 清单)→ [(短尾, 叶值)]。"""
    start = md_text.index("## 三、")
    end = md_text.index("## 四、", start)
    block = md_text[start:end]
    out = []
    cur_leaf = None
    for line in block.splitlines():
        s = line.strip()
        m_leaf = re.match(r"\*\*`(\w+)`\*\*", s)
        if m_leaf:
            cur_leaf = m_leaf.group(1)
            continue
        m_card = re.match(r"-\s*`([^`]+)`", s)
        if m_card and cur_leaf:
            out.append((m_card.group(1), cur_leaf))
    return out


def find_evidence_and_component_values(card, target_leaf):
    """收集该卡中 component_type_key==target_leaf 的证据来源项 + 全部组件值(查单值不变量)。"""
    evidence = []
    comp_values = set()

    def _scan_qual(q, ident_key, ident_val, kind):
        val = (q or {}).get("component_type_key")
        if val:
            comp_values.add(val)
        if val == target_leaf:
            entry = {"slot_ref_id": None, "condition_id": None, "kind": kind}
            entry[ident_key] = ident_val
            evidence.append(entry)

    for e in card.get("slot_role_map", []):
        _scan_qual(e.get("qualifiers"), "slot_ref_id", e.get("slot_ref_id"), "slot_role_map")
    tc = card.get("trigger_conditions", {})
    for e in (tc.get("items", []) if isinstance(tc, dict) else []):
        _scan_qual(e.get("qualifiers"), "condition_id", e.get("condition_id") or e.get("id"), "trigger_conditions")
    # threshold_regimes 仅参与单组件值检查,不作独立 evidence:v2.2 §2.5 evidence 定位只有
    # slot_ref_id/condition_id,threshold 项无此定位;目标叶值若同时在 slot_role_map/trigger 由
    # 那里承载 evidence,若仅在 threshold 则该卡保守不授权(assert evidence 会暴露)。
    for e in card.get("threshold_regimes", []):
        val = (e.get("qualifiers") or {}).get("component_type_key")
        if val:
            comp_values.add(val)

    return evidence, comp_values


def build():
    cards_doc = json.loads((REG / "rule_cards.json").read_text(encoding="utf-8"))
    bundle_id = cards_doc["bundle_id"]
    by_id = {c["rule_card_id"]: c for c in cards_doc["cards"]}

    seeds = parse_high_confidence(DRAFT.read_text(encoding="utf-8"))
    entries = []
    seen = set()
    for short_id, leaf in seeds:
        assert leaf in LEAF, f"目标 {leaf} 非叶型 ({short_id})"
        full_id = ID_PREFIX + short_id
        card = by_id.get(full_id)
        assert card is not None, f"卡不存在: {full_id}"
        assert full_id not in seen, f"重复卡: {full_id}"
        seen.add(full_id)

        evidence, comp_values = find_evidence_and_component_values(card, leaf)
        # v1 不变量:每卡单组件值 + 有目标证据
        assert comp_values <= {leaf}, f"{full_id} 组件值非单一: {comp_values}"
        assert evidence, f"{full_id} 无 {leaf} 证据来源项"

        version = card.get("version", {})
        entries.append({
            "rule_card_id": full_id,
            "card_version_binding": {
                "authoring_revision": version.get("authoring_revision"),
                "interpretation_revision": version.get("interpretation_revision"),
                "card_content_sha256": canonical_hash(card),
            },
            "exact_fragment_target_types": [leaf],
            "evidence": evidence,
            "adjudication_note": "初裁高置信:义务动词直指组件本体(第三节清单);保守版仅纳高置信。",
        })

    return {
        "version": "exact_fragment_target_authorizations.v1",
        "rulecard_bundle_id": bundle_id,
        "card_fingerprint_profile": "card_fingerprint.v1",
        "_provenance_note": "保守版:仅 118 卡初裁高置信 precise_target(55 卡)。中置信 46 卡+存疑口径待人工裁定扩充。来源: 授权初裁草稿_118卡_20260724.md §三。",
        "entries": entries,
    }


def main():
    table = build()
    entries = table["entries"]
    # 唯一性
    ids = [e["rule_card_id"] for e in entries]
    assert len(ids) == len(set(ids)), "授权条目 rule_card_id 重复"
    out = REG / "exact_fragment_target_authorizations_v1.json"
    out.write_text(json.dumps(table, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("written:", out)
    print("entries:", len(entries))
    from collections import Counter
    dist = Counter(e["exact_fragment_target_types"][0] for e in entries)
    for k, v in sorted(dist.items()):
        print(f"  {k}: {v}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
