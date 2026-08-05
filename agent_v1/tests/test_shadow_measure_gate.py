"""shadow 度量门(DEBT-065 v3 §3 第 5 道)的行为锁定。

重点锁「零核不宣绿」:2026-07-25 实证过一次——批 30/30 全崩、fact_pack 一个没有、
覆盖 0 个 fragment、|S_new|=0,门却因为「无反例」打了 exit=0 ✅。空真通过比没有门
更糟,因为它会让崩掉的批看起来验过了。
"""
from __future__ import annotations

import inspect
import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import shadow_measure_applicability as shadow  # noqa: E402


@pytest.fixture
def work_path():
    root = Path(__file__).parent / ".shadow_gate_test_tmp"
    root.mkdir(exist_ok=True)
    path = root / uuid.uuid4().hex
    path.mkdir()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        try:
            root.rmdir()
        except OSError:
            pass


def _empty_batch(root: Path, pool_dir: Path) -> Path:
    """造一个「跑崩了」的批:清单在、buildings 空(无任何 fact_pack)。"""
    batch = root / "batch"
    (batch / "buildings").mkdir(parents=True)
    (batch / "batch_manifest.json").write_text(
        json.dumps({"worldgen_run_dir": str(pool_dir)}, ensure_ascii=False),
        encoding="utf-8")
    return batch


def test_zero_coverage_is_gate_failure_not_vacuous_pass(work_path, monkeypatch, capsys):
    """批崩→零覆盖时必须判门失败，不得因「无反例」宣绿。"""
    pool = work_path / "gen_seed_301"
    pool.mkdir()
    batch = _empty_batch(work_path, pool)
    # 资产读真实的（本仓已有），只把批产物换成空的
    monkeypatch.setattr(sys, "argv", ["x", "--batch-root", str(batch)])

    rc = shadow.main(["--batch-root", str(batch)])

    out = capsys.readouterr().out
    assert rc == 1, "零覆盖必须非零退出（否则崩掉的批会被门放行）"
    assert "门失败" in out
    assert "空真通过" in out


def test_sidecar_gate_fails_on_regression_not_on_baseline():
    """D 门语义必须是「不许恶化」而非「必须为零」——45 个幽灵槽是既存状态。

    2026-07-25 立门。判零会让每批都红，等于没门；判"不许恶化"才拦得住
    "本来有事实的槽突然没了"和"契约新增了没人生成的槽"。
    """
    import check_sidecar_contract_coverage as sc

    # 2026-08-04 棘轮下调 45→39：reporting 三根轴落地后三个批（轴验证批＋满血三连）
    # 实测幽灵槽稳定 39，且 D 门自身输出提示「留着高锚等于给回退开后门」。
    # 下调即是本注释要求的「有意且有实证」。
    assert sc.GHOST_SLOT_BASELINE == 39, \
        "基线锚变动必须是有意的——改小了要有实证，改大了等于给回退开后门"
    src = inspect.getsource(sc.main)
    assert "> GHOST_SLOT_BASELINE" in src, "必须只在超出基线时失败"
    assert "for p in packs:" in src, \
        "必须扫全批——只扫前几栋会把「别的楼型才产出的槽」误判成幽灵槽"


def test_result_payload_flags_vacuous_coverage(work_path):
    """结果 JSON 必须显式带 vacuous_no_coverage，供下游对账，不靠读文案。"""
    pool = work_path / "gen_seed_301"
    pool.mkdir()
    batch = _empty_batch(work_path, pool)

    result = shadow.measure(batch, pool)

    assert result["vacuous_no_coverage"] is True
    assert result["fragments_covered_by_batch"] == 0
    assert result["s_new_pairs_actually_early_exited"] == 0
    # 关键:此时 s_new_subset_of_s_old 仍是 True（无反例），正是它单独不足以宣绿的原因
    assert result["s_new_subset_of_s_old"] is True
