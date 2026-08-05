# -*- coding: utf-8 -*-
"""DEBT-083 第 5 步开关的编排解析面（镜像哨兵开关 `EVO_FALLBACK_BOUNDARY` 测试形状）。

面：①缺省关闭（审核门过前单跑工具保守——与哨兵开关缺省开**相反**，别抄错）；
②"1"/"0" 显式值；③非法值 fail-closed ValueError（防拼写静默退化换判定面）；
④签名探测：真验证器接受 `authorized_scope_selection`、单测桩不接受。
"""
from __future__ import annotations

import pytest

from evo_agent_baseline.agent.run_orchestrator import (
    _closure_fn_accepts_scope_selection,
    resolve_authorized_scope_selection_enabled,
)


def test_default_is_off(monkeypatch):
    monkeypatch.delenv("EVO_AUTHORIZED_SCOPE_SELECTION", raising=False)
    assert resolve_authorized_scope_selection_enabled() is False
    monkeypatch.setenv("EVO_AUTHORIZED_SCOPE_SELECTION", "")
    assert resolve_authorized_scope_selection_enabled() is False


def test_explicit_values(monkeypatch):
    monkeypatch.setenv("EVO_AUTHORIZED_SCOPE_SELECTION", "1")
    assert resolve_authorized_scope_selection_enabled() is True
    monkeypatch.setenv("EVO_AUTHORIZED_SCOPE_SELECTION", "0")
    assert resolve_authorized_scope_selection_enabled() is False


@pytest.mark.parametrize("bad", ["true", "yes", " 1", "01", "on"])
def test_invalid_value_fails_closed(monkeypatch, bad):
    monkeypatch.setenv("EVO_AUTHORIZED_SCOPE_SELECTION", bad)
    with pytest.raises(ValueError):
        resolve_authorized_scope_selection_enabled()


def test_signature_detection():
    from evo_agent_baseline.closure.validator import validate_building_closure

    assert _closure_fn_accepts_scope_selection(validate_building_closure)

    def stub(rule_slice, fact_pack, config):
        return None

    assert not _closure_fn_accepts_scope_selection(stub)
