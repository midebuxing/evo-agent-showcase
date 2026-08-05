"""调用方 `rulecard_bundle_id` 标签统一：单一权威读取 + 无硬编码副本（2026-07-27）。

背景：同一入参曾三个调用面三个值——资产 `rulecard_v2.mbis_cop_2023` /
四个脚本常量 `mbis_cop_2023` / `RunOrchestrator` 缺省 `rule_card_v2`。
统一后所有调用方从 `retrieval/rulecard_bundle_identity.py` 读磁盘权威卡包
自声明值。本测试钉住两点，防止下次有人又复制一份常量：

  1. 五个调用方文件 + 读径本身**不再出现**三个历史标签字面量的赋值/
     缺省/关键字实参（路径片段 `Path / "mbis_cop_2023"` 是磁盘目录名，
     不在禁止之列——故只扫 `=` 后的字面量，不裸扫字符串）；
  2. 运行时解析真的等于磁盘卡包声明值（脚本模块常量 + 编排器缺省解析）。
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

import evo_agent_baseline.closure.identity_blueprint_catalog as ibc
from evo_agent_baseline.retrieval.rulecard_bundle_identity import (
    authoritative_rulecard_bundle_id,
    read_authoritative_rulecard_bundle_id,
)

_AGENT_V1 = Path(__file__).resolve().parents[1]
_SRC = _AGENT_V1 / "src" / "evo_agent_baseline"

_ENTRYPOINT_FILES = [
    _AGENT_V1 / "scripts" / "run_baseline_e2e_smoke.py",
    _AGENT_V1 / "scripts" / "run_evo_batch_experiment.py",
    _AGENT_V1 / "scripts" / "run_evo_llm_paired.py",
    _AGENT_V1 / "scripts" / "run_evo_smoke.py",
    _SRC / "agent" / "run_orchestrator.py",
]
# 读径相关文件同样不许藏标签副本（注释里提及历史值不算，见上）。
_READ_PATH_FILES = [
    _SRC / "retrieval" / "rulecard_bundle_identity.py",
    _SRC / "retrieval" / "rule_retriever.py",
]

_LEGACY_LABEL_ASSIGNMENT = re.compile(
    r"=\s*[\"'](?:mbis_cop_2023|rule_card_v2|rulecard_v2\.mbis_cop_2023)[\"']"
)

_SCRIPT_MODULES = [
    "run_baseline_e2e_smoke",
    "run_evo_batch_experiment",
    "run_evo_llm_paired",
    "run_evo_smoke",
]


def _load_script_module(name: str):
    """按文件路径加载脚本模块（scripts/ 不是包，与 run_evo_llm_paired 同法）。"""
    path = _AGENT_V1 / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"bundle_identity_test.{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_authoritative_reader_matches_pack_on_disk():
    """权威读径 == 磁盘卡包自声明 `bundle_id`，并钉住当前资产真值。"""
    pack_doc = json.loads(ibc.DEFAULT_AUTHORITATIVE_BUNDLE_PATH.read_text(encoding="utf-8"))
    expected = pack_doc["bundle_id"]
    assert expected == "rulecard_v2.mbis_cop_2023", (
        "资产 bundle_id 变了？本断言钉的是 2026-07-27 统一时的真值，"
        "若卡包有意改名请同步更新本测试")
    assert read_authoritative_rulecard_bundle_id() == expected
    assert authoritative_rulecard_bundle_id() == expected


@pytest.mark.parametrize("path", _ENTRYPOINT_FILES + _READ_PATH_FILES,
                         ids=[p.name for p in _ENTRYPOINT_FILES + _READ_PATH_FILES])
def test_no_hardcoded_bundle_label(path: Path):
    """结构性断言：调用方/读径文件里不存在任何硬编码卡包标签常量。"""
    src = path.read_text(encoding="utf-8")
    hit = _LEGACY_LABEL_ASSIGNMENT.search(src)
    assert hit is None, (
        f"{path.name} 出现硬编码卡包标签 {hit.group()!r}——"
        "标签一律从 retrieval.rulecard_bundle_identity 读取，不复制常量")


@pytest.mark.parametrize("path", _ENTRYPOINT_FILES, ids=[p.name for p in _ENTRYPOINT_FILES])
def test_entrypoint_uses_single_authority(path: Path):
    """五个调用方必须真的走单一权威读径（不是删掉常量后又换个地方写死）。"""
    src = path.read_text(encoding="utf-8")
    assert "rulecard_bundle_identity" in src


@pytest.mark.parametrize("name", _SCRIPT_MODULES)
def test_script_module_constant_resolves_to_authoritative(name: str):
    """运行时：四个脚本的 `RULECARD_BUNDLE_ID` == 磁盘卡包声明值。"""
    module = _load_script_module(name)
    assert module.RULECARD_BUNDLE_ID == authoritative_rulecard_bundle_id()


def test_orchestrator_default_resolves_to_authoritative():
    """运行时：`RunOrchestrator` 缺省（不传 rulecard_bundle_id）解析到权威值。"""
    import inspect

    from evo_agent_baseline.agent import run_orchestrator

    param = inspect.signature(run_orchestrator.RunOrchestrator.__init__).parameters[
        "rulecard_bundle_id"]
    assert param.default is None, "缺省应是 None（触发权威读径），不得再是字面量"
    assert run_orchestrator._default_rulecard_bundle_id() == (
        authoritative_rulecard_bundle_id())


def test_rule_slice_lands_authoritative_bundle_id_not_caller_label() -> None:
    """🔴 回归闸：`RuleSlice` 落盘的 `rulecard_bundle_id` 必须是**权威值**，不是调用方标签。

    2026-07-27 codex 五审 P2：三方同源校验已正确地不拿调用方标签当身份
    （实测三个调用面三个值：资产 `rulecard_v2.mbis_cop_2023` / 四个脚本常量
    `mbis_cop_2023` / orchestrator 缺省 `rule_card_v2`），
    但**落盘的仍是那个未经校验的标签** ⇒ 规则内容来自当前卡包、
    运行记录与报告却标成另一个卡包，**破坏「池 seed + commit + 库名」三锚可复现性**。

    本闸不看实现细节，只断言：源码里 `build_rule_slice` 的 `rulecard_bundle_id=`
    实参**不是**裸的调用方入参名。
    """
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[1] / "src" / "evo_agent_baseline"
           / "retrieval" / "rule_retriever.py").read_text(encoding="utf-8")
    m = re.search(
        r"build_rule_slice\(\s*\n\s*run_id=run_id,\s*\n\s*rulecard_bundle_id=([A-Za-z_][\w.]*)",
        src,
    )
    assert m, "定位不到 build_rule_slice 的 rulecard_bundle_id 实参——结构变了，本闸需重写"
    arg = m.group(1)
    assert arg != "rulecard_bundle_id", (
        "RuleSlice 落盘的是**未经校验的调用方标签**。"
        "应改用磁盘权威卡包声明的 `_pack_bundle_id`（读不到才退回入参）。"
    )
