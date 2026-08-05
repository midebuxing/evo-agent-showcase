# -*- coding: utf-8 -*-
"""S3 A 侧遮蔽开关的编排解析面（镜像 scope-selection 开关测试形状）。"""
from __future__ import annotations

import pytest

from evo_agent_baseline.agent.run_orchestrator import (
    _closure_fn_accepts_mask_lookup,
    resolve_mask_lookup_targets_enabled,
)


def test_default_is_off(monkeypatch):
    monkeypatch.delenv("EVO_MASK_LOOKUP_TARGETS", raising=False)
    assert resolve_mask_lookup_targets_enabled() is False
    monkeypatch.setenv("EVO_MASK_LOOKUP_TARGETS", "")
    assert resolve_mask_lookup_targets_enabled() is False


def test_explicit_values(monkeypatch):
    monkeypatch.setenv("EVO_MASK_LOOKUP_TARGETS", "1")
    assert resolve_mask_lookup_targets_enabled() is True
    monkeypatch.setenv("EVO_MASK_LOOKUP_TARGETS", "0")
    assert resolve_mask_lookup_targets_enabled() is False


@pytest.mark.parametrize("bad", ["true", "yes", " 1", "01"])
def test_invalid_value_fails_closed(monkeypatch, bad):
    monkeypatch.setenv("EVO_MASK_LOOKUP_TARGETS", bad)
    with pytest.raises(ValueError):
        resolve_mask_lookup_targets_enabled()


def test_signature_detection():
    from evo_agent_baseline.closure.validator import validate_building_closure

    assert _closure_fn_accepts_mask_lookup(validate_building_closure)

    def stub(rule_slice, fact_pack, config):
        return None

    assert not _closure_fn_accepts_mask_lookup(stub)
