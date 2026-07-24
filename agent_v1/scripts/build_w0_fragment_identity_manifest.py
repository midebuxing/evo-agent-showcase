"""生成 W0 fragment 身份 manifest(DEBT-065 v3 单 bundle 编译式判据,第二块)。

依据 spec 草案 v3 §1.1-3 / §2。

**P1-1 结构性消除**:v2.2 让 runtime 从事实流里"认出"可信身份(专用 slot/channel 标记),
codex 三审证明字符串标记不是来源证明——普通事实自填即可伪造。v3 改为**离线直接从 W0
自己的产物提取**:fragments.parquet 每行恰一个 component_id、components.parquet 每行恰一个
component_type(W0 单类型链在产物层本就成立),join 后经固定别名映射规范化即得身份。
runtime **没有**"从事实重建身份"这条路径,无从伪造。

来源基数是真校验(不是覆盖写):fragment 的 component_id 必须恰好命中 1 条 component 记录,
否则该 fragment 身份判 unknown(保守,不早退)。

用法:python agent_v1/scripts/build_w0_fragment_identity_manifest.py <worldgen_run_dir>
产物:<worldgen_run_dir>/w0_fragment_identity_manifest_v1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
REG = REPO / "agent_v1" / "regulations" / "rulecard_v2" / "mbis_cop_2023"

CANONICAL_HASH_ALGORITHM = "sha256(utf8(json.dumps(obj,sort_keys=True,separators=(',',':'),ensure_ascii=False)))"


def load_leaf_types() -> set:
    """叶集**只读类型格资产**,禁在脚本内硬编码(cursor 评审:禁双源漂移)。"""
    lattice = json.loads((REG / "component_type_lattice_v1.json").read_text(encoding="utf-8"))
    return set(lattice["leaf_types"])


def canonical_hash(obj) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build(worldgen_dir: pathlib.Path) -> dict:
    import pandas as pd

    bundles = worldgen_dir / "WorldgenWorldBundles.v2.parquet"
    frag_df = pd.read_parquet(bundles / "fragments.parquet")
    comp_df = pd.read_parquet(bundles / "components.parquet")

    mapping = json.loads((REG / "projection_runtime_mapping_v1.json").read_text(encoding="utf-8"))
    alias = mapping["qualifier_value_aliases"]["component_type_key"]
    alias_snapshot = canonical_hash(alias)
    leaf_types = load_leaf_types()

    # cursor 第三方评审钉出:fragment_id 必须唯一——字典覆盖写会让"该 fragment 的身份"
    # 不良定义(正是 codex 批 v2.2 的覆盖写毛病,不可在 v3 重犯)。
    fid_counts = frag_df.groupby("fragment_id").size()
    dup_fids = [f for f, n in fid_counts.items() if n > 1]
    if dup_fids:
        raise ValueError(
            f"W0 产物 fragment_id 重复 {len(dup_fids)} 个: {sorted(dup_fids)[:5]}…"
            "(身份不良定义,拒绝出包)"
        )

    # component_id → component_type;记录重复 id(基数校验用)
    comp_counts = comp_df.groupby("component_id").size().to_dict()
    comp_type = dict(zip(comp_df["component_id"], comp_df["component_type"]))

    fragments = {}
    stats = {"leaf": 0, "unknown_non_leaf": 0, "unknown_no_component": 0, "unknown_multi_source": 0}
    for _, row in frag_df.iterrows():
        fid = row["fragment_id"]
        cid = row.get("component_id")
        if not cid or cid not in comp_type:
            fragments[fid] = {"physical_leaf_identity": "unknown", "reason": "no_component"}
            stats["unknown_no_component"] += 1
            continue
        # 真来源基数校验:恰一条来源记录,而不是覆盖写取最后一条
        if comp_counts.get(cid, 0) != 1:
            fragments[fid] = {"physical_leaf_identity": "unknown", "reason": "multi_source"}
            stats["unknown_multi_source"] += 1
            continue
        raw = comp_type[cid]
        canonical = alias.get(raw)
        if canonical in leaf_types:
            fragments[fid] = {
                "physical_leaf_identity": canonical,
                "component_id": cid,
                "raw_component_type": raw,
            }
            stats["leaf"] += 1
        else:
            fragments[fid] = {"physical_leaf_identity": "unknown", "reason": "non_leaf_or_unmapped"}
            stats["unknown_non_leaf"] += 1

    payload = {
        "version": "w0_fragment_identity_manifest.v1",
        "worldgen_run_dir": worldgen_dir.name,
        "leaf_types": sorted(leaf_types),
        "alias_mapping_snapshot_sha256": alias_snapshot,
        "fragments": fragments,
        "stats": stats,
        "canonical_hash_algorithm": CANONICAL_HASH_ALGORITHM,
        "provenance": {
            "spec": "spec草案_DEBT065_v3_单bundle编译式判据",
            "source": "W0 worldgen 产物 fragments.parquet ⋈ components.parquet(单类型链)",
            "cardinality_rule": "fragment.component_id 必须恰命中 1 条 component 记录,否则 unknown",
            "note": "runtime 只读本 manifest 的身份,不从任何事实重建身份(P1-1 结构性消除)",
        },
    }
    payload["content_sha256"] = canonical_hash(
        {k: v for k, v in payload.items() if k != "content_sha256"}
    )
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("worldgen_run_dir", help="W0 worldgen 产物目录(含 WorldgenWorldBundles.v2.parquet)")
    ap.add_argument("--check", action="store_true", help="只校验并打印摘要,不写盘")
    args = ap.parse_args()

    wdir = pathlib.Path(args.worldgen_run_dir)
    manifest = build(wdir)
    s = manifest["stats"]
    total = len(manifest["fragments"])
    print(f"fragment 总数: {total}")
    print(f"  可信叶身份: {s['leaf']}")
    print(f"  unknown(非叶/未映射): {s['unknown_non_leaf']}")
    print(f"  unknown(无组件): {s['unknown_no_component']}")
    print(f"  unknown(来源基数≠1): {s['unknown_multi_source']}")
    by_leaf = {}
    for v in manifest["fragments"].values():
        pid = v["physical_leaf_identity"]
        if pid != "unknown":
            by_leaf[pid] = by_leaf.get(pid, 0) + 1
    for leaf, n in sorted(by_leaf.items()):
        print(f"    {leaf}: {n}")
    print(f"content_sha256: {manifest['content_sha256']}")

    if not args.check:
        out = wdir / "w0_fragment_identity_manifest_v1.json"
        out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
