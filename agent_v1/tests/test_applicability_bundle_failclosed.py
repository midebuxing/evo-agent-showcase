"""`load_bundle` 的 fail-closed 行为（2026-07-26 codex 审核门高 2）。

## 为什么必须有这份

审核门指出：原写法有两处「**缺声明即放行**」——

    if rulecard_pack_sha256 and card_doc.get("rulecard_pack_sha256") not in (None, sha)
        → 声明为 None 时**通过**
    if declared and actual and declared != actual
        → 任一缺失就**跳过检查**

⇒ **删掉 `rulecard_pack_sha256` / `card_content_sha256` 反而能绕过校验**，
更旧、缺摘要声明的 bundle 会带着旧授权进入判据路径。

而我此前那条"生产接线测试"**只检查源码里出现了参数名**，没有调真实加载器——
又一次「只测生产者自身等于没测」。**本文件调真加载器、用真临时文件。**
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from evo_agent_baseline.closure.applicability_v3 import load_bundle

CARD = "rc.demo.card.c01"

# 调用点闸要 import 两个脚本本体（它们不是包），与 test_baseline_batch.py 同姿势。
_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _write_bundle(tmp: pathlib.Path, *, pack_sha, card_sha) -> tuple[str, str]:
    """造一个**结构与真 bundle 一致**的临时 bundle，只有摘要声明按参数变化。

    形状照 `agent_v1/experiments/_applicability_assets/*/applicability_bundle_v1.json`
    逐字对齐（2026-07-26 实测踩了三次才对）：
      - 成员摘要键是 `content_sha256`（不是 `sha256`），值＝`canonical_hash(doc)`；
      - bundle 自身 `bundle_sha256` ＝ 对**除该字段外全部顶层字段**的 `canonical_hash`
        （覆盖 `worldgen_run_dir`，否则篡改它可绕过世界校验）。
    """
    from evo_agent_baseline.closure.applicability_v3 import canonical_hash
    manifest = {"rulecard_pack_sha256": pack_sha,
                "cards": {CARD: {"authorized_target_leaf": "external_wall",
                                 "card_content_sha256": card_sha}}}
    lattice = {"leaf_types": ["external_wall", "drainage_component"],
               "disjoint_pairs": [["external_wall", "drainage_component"]]}
    ident = {"fragments": {"FRG-1": {"physical_leaf_identity": "external_wall"}}}
    members = {}
    for name, doc in (("card_applicability_manifest", manifest),
                      ("leaf_exclusion_spec", lattice),
                      ("w0_fragment_identity_manifest", ident)):
        f = tmp / f"{name}.json"
        f.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True),
                     encoding="utf-8")
        members[name] = {"path": f.name, "content_sha256": canonical_hash(doc)}
    body = {"version": "applicability_bundle.v1",
            "rulecard_bundle_id": "rulecard_v2.demo",
            "worldgen_run_dir": "gen_demo",
            "leaf_types": ["external_wall", "drainage_component"],
            "members": members}
    body["bundle_sha256"] = canonical_hash(body)
    bp = tmp / "applicability_bundle_v1.json"
    bp.write_text(json.dumps(body, ensure_ascii=False, sort_keys=True),
                  encoding="utf-8")
    return str(bp), body["bundle_sha256"]


def _load(tmp, *, pack_sha, card_sha, pass_pack="PACK", pass_card="CARD"):
    bp, bsha = _write_bundle(tmp, pack_sha=pack_sha, card_sha=card_sha)
    return load_bundle(bp, bsha, repo_root=tmp, worldgen_run_dir="gen_demo",
                       card_content_shas={CARD: pass_card} if pass_card else None,
                       rulecard_pack_sha256=pass_pack)


def test_missing_pack_declaration_is_rejected_not_waved_through(tmp_path):
    """🔴 manifest 未声明 `rulecard_pack_sha256` → **拒绝**，不许当"兼容旧格式"放行。

    这是审核门抓到的核心失败场景：删掉字段反而绕过校验。
    """
    bundle, reason = _load(tmp_path, pack_sha=None, card_sha="CARD")
    assert bundle is None, "缺声明的 manifest 被放行了 —— fail-open 回来了"
    assert reason is not None
    assert reason.code == "legacy_unbound_bundle", (
        f"须给独立原因码好让批驱动区分「根本没声明」与「摘要不符」，实得 {reason.code}")


def test_mismatched_pack_declaration_is_rejected(tmp_path):
    """声明存在但与当前卡包不符 → 拒绝（这条原本就对，锁住防回退）。"""
    bundle, reason = _load(tmp_path, pack_sha="OTHER", card_sha="CARD")
    assert bundle is None and reason.code == "rulecard_pack_mismatch"


def test_matching_declaration_loads(tmp_path):
    """声明齐全且相符 → 正常加载（防"改严之后什么都过不了"）。"""
    bundle, reason = _load(tmp_path, pack_sha="PACK", card_sha="CARD")
    assert reason is None and bundle is not None
    assert CARD in getattr(bundle, "card_targets", {}) or bundle is not None


def test_card_without_declared_content_sha_is_treated_stale(tmp_path):
    """🔴 条目缺 `card_content_sha256` → 该卡视为**未授权**，不许跳过检查。"""
    bundle, reason = _load(tmp_path, pack_sha="PACK", card_sha=None)
    # ⚠️ 这里**不能断言 `reason is None`**：加载器会返回非致命提示
    # `stale_card_bindings`（"N 张卡指纹失配已降为未授权"）——那是**正确行为**，
    # bundle 仍可用、只是该卡不授权。我首版把它当失败，是断言写错了。
    assert bundle is not None
    assert reason is None or reason.code == "stale_card_bindings", reason
    assert CARD not in getattr(bundle, "card_targets", {}), (
        "缺 card_content_sha256 的卡仍被当成已授权 —— 旧授权会进判据路径")


def test_card_absent_from_current_pack_is_treated_stale(tmp_path):
    """🔴 卡在 manifest 里但**不在当前卡包**（拿不到 actual）→ 同样视为未授权。"""
    bp, bsha = _write_bundle(tmp_path, pack_sha="PACK", card_sha="CARD")
    bundle, reason = load_bundle(
        bp, bsha, repo_root=tmp_path, worldgen_run_dir="gen_demo",
        card_content_shas={},          # 当前卡包里没有这张卡
        rulecard_pack_sha256="PACK")
    assert bundle is not None
    assert reason is None or reason.code == "stale_card_bindings", reason
    assert CARD not in getattr(bundle, "card_targets", {}), (
        "当前卡包已无此卡，其旧授权仍生效 —— 这正是审核门指出的失败场景")


# ===== 2026-07-27 codex 审核门 P1-B：不传摘要 = 拒绝授权（不是跳过校验）=====

def test_omitting_pack_sha_is_rejected_not_skipped(tmp_path):
    """🔴 完全不传 `rulecard_pack_sha256` → 拒绝。

    修前失败形态（实测，真 bundle）：`load_bundle(bp, sha, repo_root, worldgen_run_dir)`
    返回 **55 张已授权卡、reason=None**——一次时效校验都没做。校验分支写成
    `if rulecard_pack_sha256:`，于是**只有主动传参的调用方才受保护**。
    """
    bp, bsha = _write_bundle(tmp_path, pack_sha="PACK", card_sha="CARD")
    bundle, reason = load_bundle(bp, bsha, repo_root=tmp_path,
                                 worldgen_run_dir="gen_demo",
                                 card_content_shas={CARD: "CARD"})
    assert bundle is None, "不传卡包摘要仍放行 —— fail-open 回来了"
    assert reason.code == "rulecard_pack_sha_not_supplied", reason


def test_omitting_card_shas_is_rejected_not_skipped(tmp_path):
    """🔴 完全不传 `card_content_shas` → 拒绝（原写法整段跳过条目级时效）。"""
    bp, bsha = _write_bundle(tmp_path, pack_sha="PACK", card_sha="CARD")
    bundle, reason = load_bundle(bp, bsha, repo_root=tmp_path,
                                 worldgen_run_dir="gen_demo",
                                 rulecard_pack_sha256="PACK")
    assert bundle is None, "不传逐卡指纹仍放行 —— 过期授权会进判据路径"
    assert reason.code == "card_content_shas_not_supplied", reason


@pytest.mark.parametrize("kwargs, want", [
    ({"rulecard_pack_sha256": None, "card_content_shas": {CARD: "CARD"}},
     "rulecard_pack_sha_not_supplied"),
    ({"rulecard_pack_sha256": "PACK", "card_content_shas": None},
     "card_content_shas_not_supplied"),
])
def test_explicit_none_is_treated_same_as_omitted(tmp_path, kwargs, want):
    """显式传 None 与不传**同等拒绝**——否则 fail-open 只是从默认值挪到了实参上。"""
    bp, bsha = _write_bundle(tmp_path, pack_sha="PACK", card_sha="CARD")
    bundle, reason = load_bundle(bp, bsha, repo_root=tmp_path,
                                 worldgen_run_dir="gen_demo", **kwargs)
    assert bundle is None and reason.code == want, reason


def test_real_bundle_still_loads_with_real_digests():
    """反向锁：改严之后**真实产物 + 真实摘要**仍要能加载，否则等于把功能关死。

    用仓库里真的 bundle 与真的卡包走真的 helper——不构造任何"一致的假数据"。
    """
    import pathlib

    from evo_agent_baseline.closure.applicability_v3 import rulecard_content_digests

    repo = pathlib.Path(__file__).resolve().parents[2]
    bp = (repo / "agent_v1" / "experiments" / "_applicability_assets"
          / "gen_seed_301" / "applicability_bundle_v1.json")
    if not bp.is_file():
        pytest.skip("本机无 seed301 适用性 bundle（派生资产不入库）")
    pack_sha, card_shas = rulecard_content_digests(repo)
    assert pack_sha and card_shas, "helper 算不出摘要"
    bundle, reason = load_bundle(
        str(bp), json.loads(bp.read_text(encoding="utf-8"))["bundle_sha256"],
        repo_root=repo, worldgen_run_dir="gen_seed_301",
        rulecard_pack_sha256=pack_sha, card_content_shas=card_shas)
    assert reason is None, f"真实产物被改严后的加载器拒绝：{reason}"
    assert bundle is not None and bundle.card_targets, "bundle 空载 = 早退恒关"


# ----- 调用点闸：两个脚本必须**真的传**（不是源码里出现过参数名）-----

def _spy_load_bundle(monkeypatch, module):
    """把模块里的 load_bundle 换成间谍：记下 kwargs 后按"禁用"返回。"""
    seen = {}

    def _spy(*args, **kw):
        seen.update(kw)
        from evo_agent_baseline.closure.applicability_v3 import DisabledReason
        return None, DisabledReason("spy", "间谍拦截")

    monkeypatch.setattr(module, "load_bundle", _spy)
    return seen


def test_release_gate_script_passes_digests(monkeypatch, tmp_path):
    """发布门禁脚本的 load_bundle 调用点必须带两个时效参数（真调用，非 grep）。"""
    import importlib

    rel = importlib.import_module("check_applicability_release")
    seen = _spy_load_bundle(monkeypatch, rel)
    monkeypatch.setattr(rel, "_check", lambda *a, **k: None)
    rel.gate4_exact_version(tmp_path / "b.json", "0" * 64, "gen_demo")
    assert seen.get("rulecard_pack_sha256"), "发布门禁没传卡包整体摘要"
    assert seen.get("card_content_shas"), "发布门禁没传逐卡内容指纹"


def test_offline_replay_script_passes_digests(monkeypatch, tmp_path):
    """离线重放脚本同上——它是"改判定核心后先跑这个"的决策依据，不能建在过期授权上。"""
    import importlib
    import pathlib

    replay_mod = importlib.import_module("replay_closure_offline")
    repo = pathlib.Path(__file__).resolve().parents[2]
    pool = (repo / "agent_v1" / "experiments" / "qa_reports"
            / "_reanchor_50x1_seed301" / "gen_seed_301")
    if not (replay_mod.REPO / "agent_v1" / "experiments" / "_applicability_assets"
            / pool.name / "applicability_bundle_v1.json").is_file():
        pytest.skip("本机无 seed301 适用性 bundle（派生资产不入库）")
    batch_root = tmp_path / "batch"
    (batch_root).mkdir()
    (batch_root / "batch_manifest.json").write_text(
        json.dumps({"worldgen_run_dir": str(pool)}), encoding="utf-8")
    seen = _spy_load_bundle(monkeypatch, replay_mod)
    with pytest.raises(SystemExit):        # 间谍返回"禁用" → 脚本按设计拒跑
        replay_mod.replay(batch_root)
    assert seen.get("rulecard_pack_sha256"), "离线重放没传卡包整体摘要"
    assert seen.get("card_content_shas"), "离线重放没传逐卡内容指纹"
