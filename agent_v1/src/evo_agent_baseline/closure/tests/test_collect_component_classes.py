"""varC 持久化测试：collect_building_component_classes 六条不变量。

锁住 DEBT-047 varC（第二条组件类来源：受控 carrier_type→组件类映射）
的所有关键不变量。

不变量清单——
  1. 两条来源并集正确（显式 component_type + 合格 carrier_type）
  2. 受控性：carrier_type 只接纳别名表的键或值
  3. 无 UBW 特例：函数体无 "ubw" 硬编码分支（行为测试）
  4. 别名归一：命中别名键时输出规范值
  5. 空/异常输入：aliases 为空/None 时 fail-closed
  6. 真实数据回归：30 栋批产物验证
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Set

import pytest

from evo_agent_baseline.closure.applicability import (
    collect_building_component_classes,
)

from .fixtures import make_fact, make_fact_pack


# ── 真实别名表 ──────────────────────────────────────────────────

_MAPPING_PATH = (
    Path(__file__).resolve().parents[4]  # agent_v1/
    / "regulations"
    / "rulecard_v2"
    / "mbis_cop_2023"
    / "projection_runtime_mapping_v1.json"
)


@pytest.fixture(scope="module")
def real_aliases() -> Dict[str, Any]:
    """读取生产用 component_type_key 别名表。"""
    with open(_MAPPING_PATH, encoding="utf-8") as f:
        mapping = json.load(f)
    return mapping["qualifier_value_aliases"]["component_type_key"]


# ── 真实批产物路径 ──────────────────────────────────────────────

_BATCH_DIR = (
    Path(__file__).resolve().parents[4]  # agent_v1/
    / "experiments"
    / "baseline_batch_final_seed301"
    / "buildings"
)


def _load_fact_pack_from_batch(building_dir: Path) -> Dict[str, Any]:
    """从批产物目录加载 fact_pack.json（原始 dict）。"""
    runs_dir = building_dir / "runs"
    for run_dir in sorted(runs_dir.iterdir()):
        fp_path = run_dir / "fact_pack.json"
        if fp_path.exists():
            with open(fp_path, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"No fact_pack.json in {runs_dir}")


# ── 辅助 ──────────────────────────────────────────────────────

def _component_vocabulary(aliases: Dict[str, str]) -> Set[str]:
    """镜像函数内部的 component_vocabulary 构建逻辑。"""
    return set(aliases.keys()) | set(aliases.values())


# =========================================================================
# 不变量 1：两条来源并集正确
# =========================================================================

class TestBothSourcesContribute:
    """slot_id=="component_type" 与合格 carrier_type 两条来源的并集。"""

    def test_slot_only(self):
        """仅有 component_type 事实、无合格 carrier_type → 只取 slot 来源。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="component_type", value="external_wall"),
            make_fact("F-2", slot_id="present", value=True,
                      value_type="boolean", carrier_type="building"),
        ])
        aliases = {"external_wall": "external_wall"}
        result = collect_building_component_classes(pack, aliases)
        assert result == {"external_wall"}

    def test_carrier_only(self):
        """仅有合格 carrier_type 事实、无 component_type slot → 只取 carrier 来源。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="present", value=True,
                      value_type="boolean", carrier_type="ubw"),
        ])
        aliases = {"unauthorized_structure": "ubw"}
        result = collect_building_component_classes(pack, aliases)
        assert result == {"ubw"}

    def test_both_sources_union(self):
        """两条来源同时存在 → 取并集。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="component_type", value="external_wall"),
            make_fact("F-2", slot_id="present", value=True,
                      value_type="boolean", carrier_type="ubw"),
        ])
        aliases = {"external_wall": "external_wall", "unauthorized_structure": "ubw"}
        result = collect_building_component_classes(pack, aliases)
        assert result == {"external_wall", "ubw"}

    def test_carrier_does_not_clobber_slot(self):
        """carrier 来源不会覆盖/挤掉 slot 来源的结果。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="component_type", value="structural_member"),
            make_fact("F-2", slot_id="component_type", value="canopy"),
            make_fact("F-3", slot_id="present", value=True,
                      value_type="boolean", carrier_type="fire_safety"),
        ])
        aliases = {
            "structural_member": "structural_component",
            "canopy": "cantilevered_canopy",
            "fire_safety": "fire_safety_component",
        }
        result = collect_building_component_classes(pack, aliases)
        assert result == {"structural_component", "cantilevered_canopy", "fire_safety_component"}


# =========================================================================
# 不变量 2：受控性 —— 非组件词汇的 carrier_type 不得进入
# =========================================================================

class TestCarrierControlledAdmission:
    """普通载体枚举（building/measurement/fragment/...）不得被当成组件类。"""

    # 所有 carrier_type Literal 枚举中不在组件词汇的值
    _NON_COMPONENT_CARRIERS = [
        "building", "component", "location", "fragment", "driver",
        "mechanism", "condition", "drainage", "repair_assessment",
        "measurement", "sidecar_entry",
    ]

    @pytest.mark.parametrize("carrier", _NON_COMPONENT_CARRIERS)
    def test_non_component_carrier_excluded(self, carrier: str, real_aliases):
        """每种非组件 carrier_type 确认不会进入组件类集合。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="some_slot", value="x",
                      carrier_type=carrier),
        ])
        result = collect_building_component_classes(pack, real_aliases)
        assert carrier not in result, (
            f"carrier_type={carrier!r} 不在组件词汇中，不应进入组件类集合"
        )

    def test_carrier_only_admits_vocabulary_members(self, real_aliases):
        """验证受控边界：词汇表外的 carrier_type 不生效。"""
        vocab = _component_vocabulary(real_aliases)
        # 任何 carrier_type Literal 值
        all_carrier_types = {
            "building", "component", "location", "fragment", "driver",
            "mechanism", "condition", "drainage", "ubw", "fire_safety",
            "repair_assessment", "measurement", "sidecar_entry",
        }
        expected_admitted = all_carrier_types & vocab
        expected_rejected = all_carrier_types - vocab

        # 用真实别名表构建事实包——所有 carrier_type 都来一条
        facts = [
            make_fact(f"F-{i}", slot_id="test_slot", value="x",
                      carrier_type=ct)
            for i, ct in enumerate(sorted(all_carrier_types))
        ]
        pack = make_fact_pack(facts)
        result = collect_building_component_classes(pack, real_aliases)

        # 被拒绝的不应出现
        for ct in expected_rejected:
            assert ct not in result, f"{ct!r} 应被拒绝"
        # 被接纳的（经别名归一）应出现
        for ct in expected_admitted:
            canonical = real_aliases.get(ct, ct)
            assert canonical in result, f"{ct!r} → {canonical!r} 应出现"


# =========================================================================
# 不变量 3：无 UBW 特例 —— 行为测试
#
# 选择行为测试而非源码扫描，理由：
# - 源码扫描是脆弱断言（合理注释/文档字符串中出现 "ubw" 就假阳）
# - 行为测试更可靠：换一个不含 ubw 的别名表，ubw carrier 就不应被接纳
# =========================================================================

class TestNoUbwHardcoding:
    """函数对 ubw 无特殊分支——去掉别名后 ubw 不再被接纳。"""

    def test_ubw_not_admitted_without_alias(self):
        """别名表不含 ubw 相关映射时，carrier_type=ubw 不被接纳。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="present", value=True,
                      value_type="boolean", carrier_type="ubw"),
        ])
        # 别名表有其他组件但无 ubw
        aliases = {"external_wall": "external_wall", "fire_safety": "fire_safety_component"}
        result = collect_building_component_classes(pack, aliases)
        assert "ubw" not in result, "别名表不含 ubw 时不应接纳"

    def test_custom_carrier_admitted_via_alias(self):
        """任意 carrier_type 只要别名表承认就被接纳——证明无特例。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="present", value=True,
                      value_type="boolean", carrier_type="fire_safety"),
        ])
        aliases = {"fire_safety": "fire_safety_component"}
        result = collect_building_component_classes(pack, aliases)
        assert "fire_safety_component" in result


# =========================================================================
# 不变量 4：别名归一 —— 命中别名键时输出规范值
# =========================================================================

class TestAliasNormalization:
    """别名键 → 规范值的映射。"""

    def test_slot_value_normalized(self):
        """component_type slot 值经别名归一。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="component_type", value="unauthorized_structure"),
        ])
        aliases = {"unauthorized_structure": "ubw"}
        result = collect_building_component_classes(pack, aliases)
        assert result == {"ubw"}
        assert "unauthorized_structure" not in result

    def test_carrier_type_normalized(self):
        """carrier_type 为别名键时归一到规范值。"""
        # 注意 carrier_type 的 Literal 枚举中没有 "unauthorized_structure"
        # 但 fire_safety 是有的，而且 "fire_safety" 在真实别名表里映射到 fire_safety_component
        pack = make_fact_pack([
            make_fact("F-1", slot_id="test", value=True,
                      value_type="boolean", carrier_type="fire_safety"),
        ])
        aliases = {"fire_safety": "fire_safety_component"}
        result = collect_building_component_classes(pack, aliases)
        assert result == {"fire_safety_component"}
        assert "fire_safety" not in result

    def test_canonical_value_passes_through(self):
        """已经是规范值的不再二次映射。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="component_type", value="external_wall"),
        ])
        aliases = {"external_wall": "external_wall"}
        result = collect_building_component_classes(pack, aliases)
        assert result == {"external_wall"}

    def test_real_aliases_normalization(self, real_aliases):
        """用真实别名表验证全部键的归一。"""
        for raw, canonical in real_aliases.items():
            if not isinstance(canonical, str) or not canonical:
                continue
            pack = make_fact_pack([
                make_fact("F-1", slot_id="component_type", value=raw),
            ])
            result = collect_building_component_classes(pack, real_aliases)
            assert canonical in result, f"{raw!r} 应归一到 {canonical!r}"


# =========================================================================
# 不变量 5：空/异常输入 → fail-closed
# =========================================================================

class TestFailClosed:
    """aliases 为空/None 时不崩溃，且第二条来源自然失效。"""

    def test_none_aliases_no_crash(self):
        """aliases=None 不抛异常。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="present", value=True,
                      value_type="boolean", carrier_type="ubw"),
        ])
        result = collect_building_component_classes(pack, None)
        assert isinstance(result, set)

    def test_none_aliases_carrier_rejected(self):
        """aliases=None → 词表为空 → 任何 carrier_type 都不合格。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="present", value=True,
                      value_type="boolean", carrier_type="ubw"),
        ])
        result = collect_building_component_classes(pack, None)
        assert "ubw" not in result
        assert len(result) == 0

    def test_empty_aliases_carrier_rejected(self):
        """aliases={} → 同上。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="present", value=True,
                      value_type="boolean", carrier_type="ubw"),
        ])
        result = collect_building_component_classes(pack, {})
        assert "ubw" not in result
        assert len(result) == 0

    def test_none_aliases_slot_still_works(self):
        """aliases=None 但 slot 来源仍工作（值原样保留）。"""
        pack = make_fact_pack([
            make_fact("F-1", slot_id="component_type", value="external_wall"),
        ])
        result = collect_building_component_classes(pack, None)
        assert result == {"external_wall"}

    def test_empty_fact_pack(self):
        """空事实包 → 空集。"""
        pack = make_fact_pack([])
        result = collect_building_component_classes(
            pack, {"unauthorized_structure": "ubw"})
        assert result == set()


# =========================================================================
# 不变量 6：真实数据回归 —— 30 栋批产物
# =========================================================================

# 🔴 期望值的**出处已于 2026-07-28 更换**——这一点比数字本身更重要。
#
# 旧出处：`scan_batch_component_classes.py` 跑**本实现自己**的输出后抄下来的。
# 那是**自证快照**：实现漏报，快照就把漏报钉成"正确"。实测它确实钉住了一个 bug——
# 旧实现只读**采样后的** `component_type` 事实，而事实包是对世界的采样、不是全量
# （`BLD-…-0007` 池里有 8 个组件含 `fire_door`，事实包只采到 4 条 `component_type`，
# `fire_door` 没进去）⇒ 19/30 栋漏掉 `fire_safety_component`，
# 经 subject 词桥放大成 47 张 §3.5 卡整卡 `not_applicable`（阅卷 `wrong_structural_na`）。
#
# 新出处：**世界池地面真值** ——
# `agent_v1/experiments/qa_reports/_reanchor_50x1_seed301/gen_seed_301/**/components.parquet`
# 逐楼取 `component_type` 全量 → 经 `component_type_key` 别名表归一
# → 按人裁关系表 `component_type_relations_v1.json` 的 `is_a` 求**父类闭包**
# （世界侧名册行本身带 `derivation=category_membership`，父类是从成员派生的）。
# 实现输出与该真值**逐栋 0/30 不匹配**。
#
# ⚠️ `ubw` 不在池推口径内：它是**状态轴不是类型轴**
# （§3.7.1(b) 僭建物涵蓋「經改動的結構構件/外牆/簷篷」），
# 来自 `carrier_type=ubw` 来源，由 `_UBW_BUILDINGS` 单独钉。
#
# ⇒ **下次改这个函数时，不要拿新输出覆盖本表**；要么重新从世界池推，
#    要么说明为什么真值该变。
_EXPECTED_CLASSES: Dict[str, Set[str]] = {
    "0002": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0005": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "ubw"},
    "0006": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "ubw"},
    "0007": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0008": {"cantilevered_canopy", "drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "wall_tiles"},
    "0009": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0010": {"cantilevered_canopy", "drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "wall_tiles"},
    "0012": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0013": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0015": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0016": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0019": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0022": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0023": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "ubw"},
    "0024": {"cantilevered_canopy", "drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "wall_tiles"},
    "0028": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0029": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "ubw"},
    "0030": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "ubw"},
    "0032": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "ubw"},
    "0033": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0036": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0037": {"cantilevered_canopy", "drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "wall_tiles"},
    "0038": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0040": {"cantilevered_canopy", "drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "wall_tiles"},
    "0042": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0043": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0045": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
    "0046": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "ubw"},
    "0047": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component", "wall_tiles"},
    "0048": {"drainage_component", "external_component", "external_wall", "fire_safety_component", "structural_component"},
}

_UBW_BUILDINGS = {"0005", "0006", "0023", "0029", "0030", "0032", "0046"}
_NON_UBW_BUILDINGS = set(_EXPECTED_CLASSES.keys()) - _UBW_BUILDINGS

# 所有楼都必须有的"旧来源"组件类的全域联集（经别名归一后）
_ALL_LEGACY_CLASSES = {
    "external_wall", "structural_component", "drainage_component",
    "fire_safety_component", "cantilevered_canopy", "wall_tiles",
}


@pytest.fixture(scope="module")
def batch_results(real_aliases) -> Dict[str, Set[str]]:
    """对 30 栋批产物执行 collect_building_component_classes。"""
    from evo_agent_baseline.contracts import FactPack

    results: Dict[str, Set[str]] = {}
    for bld_dir in sorted(_BATCH_DIR.iterdir()):
        if not bld_dir.is_dir():
            continue
        four_digit = bld_dir.name.split("-")[-1]
        raw = _load_fact_pack_from_batch(bld_dir)
        fp = FactPack(**raw)
        classes = collect_building_component_classes(fp, real_aliases)
        results[four_digit] = classes
    return results


class TestRealDataRegression:
    """用 30 栋真实批产物验证 collect_building_component_classes。"""

    def test_all_30_buildings_present(self, batch_results):
        """确认 30 栋全部加载成功。"""
        assert len(batch_results) == 30
        assert set(batch_results.keys()) == set(_EXPECTED_CLASSES.keys())

    def test_ubw_buildings_contain_ubw(self, batch_results):
        """7 栋有僭建物的楼结果含 ubw。"""
        for bid in _UBW_BUILDINGS:
            assert "ubw" in batch_results[bid], (
                f"Building {bid} 应含 ubw，实际: {batch_results[bid]}"
            )

    def test_non_ubw_buildings_lack_ubw(self, batch_results):
        """23 栋无僭建物的楼不含 ubw。"""
        for bid in _NON_UBW_BUILDINGS:
            assert "ubw" not in batch_results[bid], (
                f"Building {bid} 不应含 ubw，实际: {batch_results[bid]}"
            )

    def test_legacy_classes_preserved(self, batch_results):
        """每栋楼原有的组件类（来自 slot 来源）一个不少。"""
        for bid, expected in _EXPECTED_CLASSES.items():
            legacy = expected - {"ubw"}  # ubw 只来自 carrier 来源
            actual = batch_results[bid]
            missing = legacy - actual
            assert not missing, (
                f"Building {bid} 丢失旧来源组件类: {missing}，"
                f"实际: {actual}"
            )

    def test_exact_match_per_building(self, batch_results):
        """每栋精确匹配预期集合（并集完整性）。"""
        for bid, expected in _EXPECTED_CLASSES.items():
            actual = batch_results[bid]
            assert actual == expected, (
                f"Building {bid} 不匹配：\n"
                f"  预期: {sorted(expected)}\n"
                f"  实际: {sorted(actual)}\n"
                f"  多余: {sorted(actual - expected)}\n"
                f"  缺失: {sorted(expected - actual)}"
            )
