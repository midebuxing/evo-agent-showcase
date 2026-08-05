"""重渲工具「叙述接纳」检查的**分档**行为（2026-08-03 放宽后配的变异测试）。

## 为什么这几条测试必须存在

我**放宽了一道防损坏闸**：`offline_rerender_report.py` 原先要求
`run_audit.llm_narrative_accepted` 必须是显式布尔，缺字段即抛错——
那条检查是 2026-07-23 codex 审 E-5.9 钉出的，防的是
「缺字段默认当未接纳 ⇒ 静默渲染回退稿 ⇒ 掩盖产物损坏」。

放宽的理由正当（确定性地板档从不写这个字段，导致整批 30/30 栋重渲失败、
消费者面的改动**在手头唯一的批上无法端到端验证**），
但本项目规矩是「**新闸/改闸必做变异验证**」——放宽尤其如此，
否则「让我自己方便」的收窄会悄悄变成一个洞。

## 这几条锁的是什么

**判据必须是「这一档本就该有叙述接纳吗」，不是「这栋恰好有没有这个字段」。**
后者会让**真损坏的 LLM 档产物**通过丢掉字段把自己降级成地板档蒙混过去
——那正好是原检查要挡的事。
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_SCRIPT = (pathlib.Path(__file__).resolve().parents[3]
           / "scripts" / "offline_rerender_report.py")


def _mod():
    spec = importlib.util.spec_from_file_location("_rerender", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_floor_tier_missing_field_means_not_accepted():
    """地板档（contract 1、无 llm）缺字段 ⇒ 未接纳，**不抛错**。"""
    assert _mod().narrative_accepted({"report_contract_version": 1}) is False


def test_llm_tier_by_contract_still_raises():
    """contract ≥ 2 ⇒ LLM 档 ⇒ 缺字段仍必须抛（原防损坏语义不得被放宽掉）。"""
    with pytest.raises(ValueError):
        _mod().narrative_accepted({"report_contract_version": 4})


def test_llm_tier_by_llm_field_still_raises():
    """只要 `llm` 非 None 就算 LLM 档——**即使 contract 写着 1**。

    这一条是本组的核心：判档看的是「本就该有」，
    所以**损坏产物无法靠篡改 contract 把自己降级**。
    """
    with pytest.raises(ValueError):
        _mod().narrative_accepted(
            {"llm": {"model": "qwen3.5:latest"}, "report_contract_version": 1})


def test_explicit_bool_is_honoured_in_both_tiers():
    m = _mod()
    assert m.narrative_accepted(
        {"report_contract_version": 4, "llm_narrative_accepted": True}) is True
    assert m.narrative_accepted(
        {"report_contract_version": 1, "llm_narrative_accepted": True}) is True
    assert m.narrative_accepted(
        {"report_contract_version": 4, "llm_narrative_accepted": False}) is False


def test_non_bool_truthy_is_not_accepted_as_bool():
    """字符串 "true" 之类**不算**显式布尔——LLM 档必须抛，地板档当未接纳。

    放宽只针对「字段不存在」，不针对「字段存在但类型不对」；
    后者恰恰是产物损坏的信号。
    """
    m = _mod()
    with pytest.raises(ValueError):
        m.narrative_accepted(
            {"report_contract_version": 4, "llm_narrative_accepted": "true"})
    assert m.narrative_accepted(
        {"report_contract_version": 1, "llm_narrative_accepted": "true"}) is False
