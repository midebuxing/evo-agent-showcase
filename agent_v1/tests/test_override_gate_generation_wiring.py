#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C3 接线行为锁定：真值面生成命令必须先过 P5 override 对账闸。

授权：`审核结果_kimi_G6_20260806.md` C3（换池批生成命令接对账闸）；
闸本体与三条断言见 `agent_v1/scripts/check_override_registry_reconciliation.py`，
接线点＝`workflow_engine/worldgen/validation.py` 的 `main()`（生成命令侧最早强制点，
解析参数后、任何生成步骤之前）。

四类用例（全部**不真生成池**——生成函数一律换成假桩）：

1. 正例：现状闸绿 ⇒ 生成不被拦（假桩被调、退 0）。
2. 变异：临时把一条**未登记槽**谓词注入真 `card_overrides` ⇒ 生成命令退非零、
   逐条点名违例、生成函数一次都不被调；用后**逐字节还原**并断言还原成功。
3. 旁路：同一变异在场，`--force-override-gate <理由>` ⇒ 生成放行，
   但醒目警告＋理由＋被旁路的问题逐条留在输出里。
4. 旁路卫生：理由为空白 ⇒ 拒绝；闸本绿时给旁路开关 ⇒ 放行但注明未起作用。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # agent_v1
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from workflow_engine.worldgen import validation  # noqa: E402

MAPPING_PATH = (
    PROJECT_ROOT
    / "regulations"
    / "rulecard_v2"
    / "mbis_cop_2023"
    / "projection_runtime_mapping_v1.json"
)
MUTATION_SLOT = "test.mutation.unregistered_slot_c3"


class _GenerationStub:
    """替掉 `run_worldgenerator_fullcoverage_framework_v2`——绝不真生成。"""

    def __init__(self, forbid: bool = False):
        self.calls = []
        self.forbid = forbid

    def __call__(self, **kwargs):
        if self.forbid:
            raise AssertionError("闸没拦住：生成函数被调用了（本用例里它必须一次都不被调）")
        self.calls.append(kwargs)
        return {"stub": True}


@pytest.fixture
def mutated_mapping():
    """临时注入一条未登记槽谓词到真 `card_overrides`，用后逐字节还原。

    注入形状照抄现存谓词（`predicate_kind=slot`、`alias_slot_ids=[]`），
    只换 `slot_id` 为一个三张表（登记表 / 白名单 / 冻结绑定）都没有的名字
    ⇒ A1/A2/A3 三条断言应各自打红。
    """
    original = MAPPING_PATH.read_bytes()
    doc = json.loads(original.decode("utf-8"))
    card_id = sorted(doc["card_overrides"])[0]
    doc["card_overrides"][card_id]["extra_trigger_predicates"].append(
        {
            "condition_id": "c3-wiring-mutation",
            "predicate_kind": "slot",
            "slot_id": MUTATION_SLOT,
            "alias_slot_ids": [],
            "partition": "sidecar",
            "operator": "==",
            "expected_value": True,
            "qualifiers": {},
            "lookup_rule": None,
            "owning_interface_ids": [],
            "owning_interface_mode": "any_of",
            "deferred_reason_code": None,
            "deferred_note": None,
        }
    )
    MAPPING_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        yield card_id
    finally:
        MAPPING_PATH.write_bytes(original)
        assert MAPPING_PATH.read_bytes() == original, "变异还原失败——权威文件被留在脏状态"


def test_positive_green_gate_does_not_block(monkeypatch, tmp_path, capsys):
    """正例：现状闸绿 ⇒ 生成命令不被拦（最小干跑：生成函数是假桩）。"""
    stub = _GenerationStub()
    monkeypatch.setattr(
        validation, "run_worldgenerator_fullcoverage_framework_v2", stub
    )
    rc = validation.main(["--output-dir", str(tmp_path / "out"), "--count", "1"])
    assert rc == 0
    assert len(stub.calls) == 1
    out = capsys.readouterr()
    assert '"stub": true' in out.out


def test_mutation_unregistered_slot_refuses_generation(
    mutated_mapping, monkeypatch, capsys
):
    """变异：未登记 override 谓词在场 ⇒ 退非零、点名违例、生成函数零调用。"""
    stub = _GenerationStub(forbid=True)
    monkeypatch.setattr(
        validation, "run_worldgenerator_fullcoverage_framework_v2", stub
    )
    rc = validation.main(["--count", "1"])
    assert rc == validation.EXIT_REFUSED_BY_OVERRIDE_GATE
    assert rc != 0
    err = capsys.readouterr().err
    assert "拒绝生成真值队列" in err
    assert MUTATION_SLOT in err  # 逐条明细里点名违例槽
    assert "[A1·登记]" in err  # 未登记
    assert "[A2·白名单]" in err  # 白名单外
    assert "[A3·两侧]" in err  # 未冻结绑定


def test_bypass_flag_generates_with_prominent_warning(
    mutated_mapping, monkeypatch, tmp_path, capsys
):
    """旁路：--force-override-gate <理由> ⇒ 放行，但警告＋理由＋问题清单必须在场。"""
    reason = "C3 接线测试：验证旁路通道（非生产用）"
    stub = _GenerationStub()
    monkeypatch.setattr(
        validation, "run_worldgenerator_fullcoverage_framework_v2", stub
    )
    rc = validation.main(
        [
            "--output-dir", str(tmp_path / "out"),
            "--count", "1",
            "--force-override-gate", reason,
        ]
    )
    assert rc == 0
    assert len(stub.calls) == 1
    err = capsys.readouterr().err
    assert "被显式旁路" in err
    assert reason in err  # 理由字符串留在输出里
    assert MUTATION_SLOT in err  # 被旁路的问题逐条列出，不是静默吞掉


def test_bypass_requires_nonempty_reason(monkeypatch, capsys):
    """旁路卫生：理由为空白 ⇒ 拒绝（不看闸状态，不给匿名通道）。"""
    stub = _GenerationStub(forbid=True)
    monkeypatch.setattr(
        validation, "run_worldgenerator_fullcoverage_framework_v2", stub
    )
    rc = validation.main(["--count", "1", "--force-override-gate", "   "])
    assert rc == validation.EXIT_REFUSED_BY_OVERRIDE_GATE
    assert "非空理由" in capsys.readouterr().err


def test_bypass_flag_on_green_gate_notes_no_effect(monkeypatch, tmp_path, capsys):
    """旁路卫生：闸本绿时给旁路开关 ⇒ 放行，但注明未起作用（理由仍留痕）。"""
    stub = _GenerationStub()
    monkeypatch.setattr(
        validation, "run_worldgenerator_fullcoverage_framework_v2", stub
    )
    rc = validation.main(
        [
            "--output-dir", str(tmp_path / "out"),
            "--count", "1",
            "--force-override-gate", "多余的旁路",
        ]
    )
    assert rc == 0
    assert len(stub.calls) == 1
    err = capsys.readouterr().err
    assert "未起作用" in err
    assert "多余的旁路" in err
