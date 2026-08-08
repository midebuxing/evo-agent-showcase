# -*- coding: utf-8 -*-
"""在险清单登记表的结构闸（2026-08-07 阶段丙尾巴）。

## 为什么有这个测试

`audit_atrisk_truth_items.py` 的在险清单记的是**楼号**，而楼号只在自己的池里
有意义。清单与真值档不同池时它不会报错——它会**安静地通过**：清单里的楼一栋
都不在批内 ⇒ 全部落进 `skipped` ⇒ 全称量词落在空集上恒真。
2026-08-07 之前那正是实况（清单锚旧池 seed301、批是池 v2 seed401），
`check_batch_acceptance.py` 靠一条 `vacuous ⇒ 判失败` 的兜底才把它抓出来。

⇒ 本文件把「清单与它自己的真值档同池」钉成**结构断言**：
不靠跑批、不靠兜底，改错了当场红。
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO / "agent_v1/scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def audit():
    return _load("audit_atrisk_truth_items")


def test_every_named_truth_file_has_its_own_at_risk_generation(audit):
    """具名真值档与在险清单代际**一一对应**。

    少一代 ⇒ `--truth-file` 选到它时 `AT_RISK_REGISTRY[name]` 直接 KeyError；
    多一代 ⇒ 有一份清单没有任何真值档会用到它（登记了但没人消费）。
    """
    assert set(audit.AT_RISK_REGISTRY) == set(audit.NAMED_TRUTH_FILES)


def test_legacy_alias_still_points_at_the_default_generation(audit):
    """`AT_RISK` 是沿革调用面（外部仍在引），语义必须逐字节等于缺省代。"""
    assert audit.AT_RISK is audit.AT_RISK_REGISTRY[
        audit.DEFAULT_TRUTH_FILE]["items"]


@pytest.mark.parametrize("truth_name", ("v1", "v2"))
def test_at_risk_items_exist_in_their_own_truth_file(audit, truth_name):
    """每一代清单的每一项，都必须在**它自己那份真值**里是 applicable 项。

    🔴 这条同时挡两种错：
    ①换真值档忘了换清单（楼号来自另一个池 ⇒ 这里查不到 ⇒ 红）；
    ②清单里写了一个真值说「不适用/挂起」的项（在险闸对那种项的断言无意义）。
    """
    truth = audit._load_truth(audit.NAMED_TRUTH_FILES[truth_name])
    missing = [k for k in audit.AT_RISK_REGISTRY[truth_name]["items"]
               if k not in truth]
    assert not missing, (
        f"{truth_name} 代在险清单有 {len(missing)} 项不在 {truth_name} 真值的 "
        f"applicable 集合里：{missing[:4]}"
    )


@pytest.mark.parametrize("truth_name", ("v1", "v2"))
def test_each_generation_records_its_provenance(audit, truth_name):
    """清单是**实测积累**出来的，来历不写清楚，下一代就无从复算。"""
    entry = audit.AT_RISK_REGISTRY[truth_name]
    assert entry["pool"] and entry["derived_at"]
    assert entry["derived_from"]["criterion"]
    assert entry["derived_from"]["batches"]
    assert entry["items"], "空清单＝空作用域通过，本仓已把它判为失败形状"


def test_truth_file_selection_never_falls_back_silently(audit):
    """不认识的档名必须抛——「选错了就当没选」正是静默换锚的形状。"""
    with pytest.raises(ValueError):
        audit._resolve_truth_file("v3")
    assert audit._resolve_truth_file(None) == audit.NAMED_TRUTH_FILES[
        audit.DEFAULT_TRUTH_FILE]
