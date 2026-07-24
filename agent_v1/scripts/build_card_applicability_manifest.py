"""生成卡适用性 manifest(DEBT-065 v3 单 bundle 编译式判据,第一块)。

依据 spec 草案 v3 §1.1-2 / §2。

v3 与 v2.2 的关键差别:授权不再是 runtime 查询的独立资产 + 卡指纹匹配,而是
**离线规范化产出的卡适用性 manifest**——每卡一个规范叶 ID 或 null。runtime 只读
规范叶 ID,永不接触 authoring 标签/别名/法律属性词表值(runtime 域保持极小)。

**P1-4 结构性消除**:v2.2 靠 runtime 护栏防"卡值 A 却授权目标 B"(codex 三审证明
仍可绕过);v3 在**生成时**强制 `卡唯一组件值 == 授权目标`,不合规直接 raise、不出包
——错误授权在制品阶段就无法产生。

用法:python agent_v1/scripts/build_card_applicability_manifest.py [--check]
产物:agent_v1/regulations/rulecard_v2/mbis_cop_2023/card_applicability_manifest_v1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REG = pathlib.Path(__file__).resolve().parents[1] / "regulations" / "rulecard_v2" / "mbis_cop_2023"

CANONICAL_HASH_ALGORITHM = "sha256(utf8(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False)))"


def load_leaf_types() -> set:
    """叶集**只读类型格资产**,禁在脚本内硬编码(cursor 评审:禁双源漂移)。"""
    lattice = json.loads((REG / "component_type_lattice_v1.json").read_text(encoding="utf-8"))
    return set(lattice["leaf_types"])


def canonical_hash(obj) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def card_component_values(card: dict) -> set:
    """提取一张卡的全部 component_type_key 值(三处嵌套位置)。"""
    vals = set()
    for sr in card.get("slot_role_map", []) or []:
        v = (sr.get("qualifiers") or {}).get("component_type_key")
        if v:
            vals.add(v)
    for tr in card.get("threshold_regimes", []) or []:
        v = (tr.get("qualifiers") or {}).get("component_type_key")
        if v:
            vals.add(v)
    for item in ((card.get("trigger_conditions") or {}).get("items") or []):
        v = (item.get("qualifiers") or {}).get("component_type_key")
        if v:
            vals.add(v)
    return vals


def build() -> dict:
    leaf_types = load_leaf_types()
    cards_doc = json.loads((REG / "rule_cards.json").read_text(encoding="utf-8"))
    bundle_id = cards_doc.get("bundle_id")
    cards = {c["rule_card_id"]: c for c in cards_doc.get("cards", []) if c.get("rule_card_id")}

    # 卡包完整性前提:rule_card_id 唯一(重复会让"该卡"不良定义)
    ids = [c.get("rule_card_id") for c in cards_doc.get("cards", []) if c.get("rule_card_id")]
    if len(ids) != len(set(ids)):
        dup = {i for i in ids if ids.count(i) > 1}
        raise ValueError(f"卡包内 rule_card_id 重复: {sorted(dup)}")

    # 裁定来源:v2.2 授权表(法规卡专员初裁的高置信集),v3 只取其 target 作为裁定输入
    auth_path = REG / "exact_fragment_target_authorizations_v1.json"
    adjudications = {}
    if auth_path.exists():
        auth_doc = json.loads(auth_path.read_text(encoding="utf-8"))
        for entry in auth_doc.get("entries", []) or []:
            rid = entry.get("rule_card_id")
            targets = entry.get("exact_fragment_target_types") or []
            if rid and len(targets) == 1:
                adjudications[rid] = targets[0]

    manifest_cards = {}
    for rid, target in sorted(adjudications.items()):
        if rid not in cards:
            raise ValueError(f"裁定引用了卡包中不存在的卡: {rid}")
        # 结构性消除 P1-4:授权目标必须 ∈ 叶集,且 == 该卡的唯一组件值
        if target not in leaf_types:
            raise ValueError(f"卡 {rid} 的授权目标 {target} 不是叶型")
        cvals = card_component_values(cards[rid])
        if len(cvals) != 1:
            raise ValueError(f"卡 {rid} 组件值非唯一 {sorted(cvals)},无法良定义授权目标")
        if cvals != {target}:
            raise ValueError(
                f"卡 {rid} 的唯一组件值 {sorted(cvals)} 与授权目标 {target} 不一致"
                "(P1-4 结构性消除:不一致的授权不出包)"
            )
        manifest_cards[rid] = {"authorized_target_leaf": target}

    # 未授权卡显式记 null(runtime 缺省拒绝,不依赖"查不到"这种隐式语义)
    for rid in sorted(cards):
        manifest_cards.setdefault(rid, {"authorized_target_leaf": None})

    payload = {
        "version": "card_applicability_manifest.v1",
        "rulecard_bundle_id": bundle_id,
        "leaf_types": sorted(leaf_types),
        "cards": manifest_cards,
        "canonical_hash_algorithm": CANONICAL_HASH_ALGORITHM,
        "provenance": {
            "spec": "spec草案_DEBT065_v3_单bundle编译式判据",
            "adjudication_source": "法规卡专员逐卡裁定(高置信集);生成时强校验卡唯一组件值==授权目标",
            "note": "runtime 只消费本 manifest 的规范叶 ID,不接触 authoring 标签/别名/法律属性词表值",
        },
    }
    payload["content_sha256"] = canonical_hash(
        {k: v for k, v in payload.items() if k != "content_sha256"}
    )
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验并打印摘要,不写盘")
    args = ap.parse_args()

    manifest = build()
    authorized = {k: v for k, v in manifest["cards"].items() if v["authorized_target_leaf"]}
    print(f"卡总数: {len(manifest['cards'])}")
    print(f"已授权(单叶目标): {len(authorized)}")
    by_leaf = {}
    for v in authorized.values():
        by_leaf[v["authorized_target_leaf"]] = by_leaf.get(v["authorized_target_leaf"], 0) + 1
    for leaf, n in sorted(by_leaf.items()):
        print(f"  {leaf}: {n}")
    print(f"content_sha256: {manifest['content_sha256']}")
    print("强校验(卡唯一组件值 == 授权目标): 全部通过")

    if not args.check:
        out = REG / "card_applicability_manifest_v1.json"
        out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
