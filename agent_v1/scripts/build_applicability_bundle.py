"""生成适用性 bundle manifest(DEBT-065 v3 单 bundle 编译式判据,第三块)。

依据 spec 草案 v3 §1.2 / §2。

**P1-2 / P1-3 结构性消除**:v2.2 让三份资产各自经 KG 运输、各自按字典序取"最新版本",
再在 runtime 做三方同源校验(codex 三审证明:节点属性与查询字段错配即真实链路断路、
恒关闭功能;且 bundle_id 缺失时 loader 自动补默认值使校验永不触发)。v3 改为**一个
bundle manifest 用精确 digest 钉住三个成员**,validator 只加载被指向的这一个 bundle、
不问"最新是什么"、没有默认值旁路;任一成员 digest 不符或缺失 → 整体禁用早退。

用法:python agent_v1/scripts/build_applicability_bundle.py <worldgen_run_dir>
产物:<worldgen_run_dir>/applicability_bundle_v1.json
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


def canonical_hash(obj) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _member(path: pathlib.Path, rel_to: pathlib.Path) -> dict:
    """成员条目:精确版本 + 内容 digest(整份文件的规范哈希,不依赖文件内自报字段)。"""
    if not path.exists():
        raise FileNotFoundError(f"bundle 成员缺失: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {
        "path": str(path.relative_to(rel_to)) if str(path).startswith(str(rel_to)) else str(path),
        "version": doc.get("version"),
        "content_sha256": canonical_hash(doc),
    }


def build(worldgen_dir: pathlib.Path) -> dict:
    lattice_p = REG / "component_type_lattice_v1.json"
    card_p = REG / "card_applicability_manifest_v1.json"
    ident_p = worldgen_dir / "w0_fragment_identity_manifest_v1.json"

    lattice_doc = json.loads(lattice_p.read_text(encoding="utf-8"))
    card_doc = json.loads(card_p.read_text(encoding="utf-8"))
    ident_doc = json.loads(ident_p.read_text(encoding="utf-8"))

    # 三成员必须同源:叶集一致 + 卡包一致
    leaf_sets = [
        set(lattice_doc["leaf_types"]),
        set(card_doc["leaf_types"]),
        set(ident_doc["leaf_types"]),
    ]
    if len({frozenset(s) for s in leaf_sets}) != 1:
        raise ValueError(f"三成员叶集不一致: {[sorted(s) for s in leaf_sets]}")
    if lattice_doc.get("rulecard_bundle_id") != card_doc.get("rulecard_bundle_id"):
        raise ValueError(
            f"卡包不一致: lattice={lattice_doc.get('rulecard_bundle_id')} "
            f"card_manifest={card_doc.get('rulecard_bundle_id')}"
        )
    # 身份 manifest 的别名快照须与类型格一致(同一别名映射版本产出)
    if ident_doc.get("alias_mapping_snapshot_sha256") != lattice_doc.get("alias_mapping_snapshot_sha256"):
        raise ValueError("身份 manifest 与类型格的别名快照不一致(非同一别名映射版本)")

    members = {
        "leaf_exclusion_spec": _member(lattice_p, REPO),
        "card_applicability_manifest": _member(card_p, REPO),
        "w0_fragment_identity_manifest": _member(ident_p, REPO),
    }
    payload = {
        "version": "applicability_bundle.v1",
        "rulecard_bundle_id": lattice_doc.get("rulecard_bundle_id"),
        "worldgen_run_dir": worldgen_dir.name,
        "leaf_types": sorted(leaf_sets[0]),
        "members": members,
        "canonical_hash_algorithm": CANONICAL_HASH_ALGORITHM,
        "provenance": {
            "spec": "spec草案_DEBT065_v3_单bundle编译式判据",
            "loading_rule": "validator 只加载被指向的这一个 bundle;不做任何'最新版本'选择;"
                            "任一成员 digest 不符/缺失 → 整体禁用组件结构早退(fail-safe)",
        },
    }
    payload["bundle_sha256"] = canonical_hash(members)
    return payload


def verify(bundle_path: pathlib.Path) -> list:
    """按 bundle 逐成员重算 digest,返回不符项(供发布门禁与 runtime 加载共用)。"""
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    problems = []
    for name, m in bundle["members"].items():
        p = REPO / m["path"]
        if not p.exists():
            problems.append(f"{name}: 文件缺失 {m['path']}")
            continue
        actual = canonical_hash(json.loads(p.read_text(encoding="utf-8")))
        if actual != m["content_sha256"]:
            problems.append(f"{name}: digest 不符(期望 {m['content_sha256'][:12]}… 实际 {actual[:12]}…)")
    if canonical_hash(bundle["members"]) != bundle.get("bundle_sha256"):
        problems.append("bundle_sha256 与 members 不符")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("worldgen_run_dir")
    ap.add_argument("--verify-only", action="store_true")
    args = ap.parse_args()
    wdir = pathlib.Path(args.worldgen_run_dir)
    out = wdir / "applicability_bundle_v1.json"

    if args.verify_only:
        problems = verify(out)
        print("bundle 校验:", "通过" if not problems else "失败")
        for p in problems:
            print("  -", p)
        return 1 if problems else 0

    bundle = build(wdir)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"bundle_sha256: {bundle['bundle_sha256']}")
    for name, m in bundle["members"].items():
        print(f"  {name}: {m['version']} @ {m['content_sha256'][:12]}…")
    print(f"written: {out}")
    problems = verify(out)
    print("自校验:", "通过" if not problems else f"失败 {problems}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
