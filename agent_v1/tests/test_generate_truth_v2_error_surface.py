"""真值 v2 生成器的**报错面**（2026-08-07，D9 正单 §一.② 清 SF-1 / O-2）。

这两条都不改任何判据、不动任何产物字节，改的是**判据违规时说出来的那句话**。
之所以要为「一句话」建测试：本项目已经记过两次同形状的账——

  - **SF-1（`_rel` 抛 `ValueError`）**：格式化器把它要描述的那个错误吃掉了。
    真病是「源文件被指到仓库外」这条契约违规，看到的却是一句
    `ValueError: '…' is not in the subpath of '…'`，与病因毫不相干。
    同族记录：`preregistration_dry_run` 因 stderr 编码而崩，看起来像闸挂了，
    实则判据根本没跑到。
  - **O-2（报错串里的中间那个数写成了 45）**：报错串里的数字**会被下一个人
    当契约读**。45 是 `move_to_varying` 的数，被顺手抄了进去 ⇒ 一条假规格。
    ⇒ 判据常量必须**从常量取**，不许在文案里手写第二遍。

⚠️ 本文件**有意不写出那个错误串的字面量**（`test_no_stale_contract_literal_*`
用拼接构造它）：写进来就会被自己的扫描判成残留，是那类「测试因为描述被测物
而自己变成被测物」的自伤。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "agent_v1" / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


gen = _load("generate_truth_v2")


# ── SF-1：`_rel()` 对仓库外路径不许崩 ──────────────────────────────────

def test_rel_returns_absolute_posix_for_paths_outside_the_repo(tmp_path):
    """仓库外路径 → 规范化绝对路径，**不抛**。"""
    outside = tmp_path / "somewhere" / "final_partition.json"
    got = gen._rel(outside)

    assert got == outside.as_posix()
    assert "\\" not in got


def test_rel_still_returns_a_repo_relative_path_inside_the_repo():
    """仓库内行为一字节不变（别为了修边界把主路径也改了）。"""
    got = gen._rel(SCRIPTS / "generate_truth_v2.py")
    assert got == "agent_v1/scripts/generate_truth_v2.py"


def test_contract_violation_outside_the_repo_surfaces_as_a_contract_error(
        tmp_path, monkeypatch):
    """病因必须显示为契约错，不是一句无关的 `ValueError`。

    **变异复现（这就是 SF-1 的真实触发条件）**：源文件确实存在、但在仓库外，
    且内容违反契约 ⇒ 走到 `_rel(PARTITION_PATH)` 那句格式化。
    修前此处抛 `ValueError: '…' is not in the subpath of '…'`
    ——与真病「schema 不符」毫无关系，且**不是** `TruthContractError`，
    上层按契约错兜底的地方一个都接不住。
    """
    outside = tmp_path / "outside_the_repo" / "final_partition.json"
    outside.parent.mkdir(parents=True)
    outside.write_text(
        json.dumps({"schema_version": "final_partition_v4"}), encoding="utf-8")
    monkeypatch.setattr(gen, "PARTITION_PATH", outside)

    with pytest.raises(gen.TruthContractError) as excinfo:
        gen.load_partition()

    message = str(excinfo.value)
    assert "schema_version 不符" in message
    assert outside.as_posix() in message      # 仓库外 → 绝对 posix，没崩


# ── O-2：报错串里的契约数字必须从常量取 ────────────────────────────────

def test_partition_schema_error_quotes_the_real_contract_numbers(
        tmp_path, monkeypatch):
    """变异复现：写一份 schema 不符的分区 → 报错串必须是 161/110/7。

    修前中间那个数印的是 `move_to_varying` 的 45，不是本脚本任何一个契约常量。
    """
    bogus = tmp_path / "final_partition.json"
    bogus.write_text(
        json.dumps({"schema_version": "final_partition_v4"}),
        encoding="utf-8")
    monkeypatch.setattr(gen, "PARTITION_PATH", bogus)

    with pytest.raises(gen.TruthContractError) as excinfo:
        gen.load_partition()

    message = str(excinfo.value)
    expected = (f"{gen.CONTRACT_CONSTANT_ITEMS}/{gen.CONTRACT_GRID_ITEMS}"
                f"/{gen.CONTRACT_PENDING_ITEMS}")
    assert expected == "161/110/7"          # 常量本身没被顺手改掉
    assert expected in message
    assert _stale_literal() not in message
    assert gen.REQUIRED_PARTITION_SCHEMA in message


def _stale_literal() -> str:
    """被修掉的那个错误串，拼出来而不写字面量（理由见模块 docstring）。"""
    return "/".join(("161", "45", str(gen.CONTRACT_PENDING_ITEMS)))


def test_no_stale_contract_literal_survives_anywhere_in_the_source():
    """整份源码里不许再出现那个旧串 —— 换个地方写一遍等于没修。"""
    source = (SCRIPTS / "generate_truth_v2.py").read_text(encoding="utf-8")
    assert _stale_literal() not in source
