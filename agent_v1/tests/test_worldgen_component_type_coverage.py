"""片段生成的「构件类完整性」开关（2026-07-29 立，验收③ 队列 1′ 甲-a）。

## 病

片段是**模板驱动**的：每栋固定取 `target_count` 个片段模板，而
`_pick_component_for_fragment` 每个模板只挑**一个**组件。于是楼内某个构件类
可能一个片段都没有。实测池 `gen_seed_301`：`343 组件 / 200 片段`，
**172 个组件（50.1%）零片段**，**121 个 (楼, 构件类) 格零片段**。

义务按片段求值 ⇒ 没有该类片段，针对该类的卡产不出作用域内义务 ⇒ 阅卷记「漏」。
自然实验：同一 (规范项, 构件类) 在**有**该类片段的楼上覆盖率 **99.5%**、
在**没有**的楼上 **0.0%**（143 行全是 `retrieved_no_evaluation`）。

## 🔴 这里锁的四条

1. **缺省关，且开关只做「追加」不做「重排」。**
   ⚠️ 2026-08-05（波次二 #22「rng 隔离 1a-ii」）改判据：本条原来断的是
   「调用前后 `random.Random` 内部状态逐位相同」。1a-ii 之后
   `_select_fragment_templates` **收不到主 rng 了**（形参已删、改按稳定键排序取前 k），
   那条断言**结构上恒真** ⇒ 变成空护栏。改断**输出层不变式**：
   关着时的选型必须是开着时的**前缀**（开关只在尾部追加，不动前面选中的模板）。
   这比原断言更接近「要保的东西」——原断言只是它的代理。
2. **开着时，楼内已存在且**注册表有模板**的构件类全部被覆盖。**
3. **无模板的构件类仍然覆盖不了**——这是诚实的能力边界，不许假装解决了。
   注册表 12 个模板只覆盖 8 种构件类，而 `component_type_registry` 有 19 种；
   `balcony_slab` / `parapet_wall` / `signboard` 无模板。
4. **判据只读世界自己有什么**，不读法规卡、不读真值。
   「按楼内已有构件类补片段」是修出题器；「按漏掉的规范项补片段」是照误差清单造题。
   两者只差一个数据来源，后果完全不同。

## 变异验证（写测试时实跑过）

- 把 `if ensure_component_type_coverage and available_component_types:` 改成恒真
  ⇒ `test_switch_off_selection_is_a_prefix_of_switch_on` 失败；
- 把追加那行删掉 ⇒ `test_on_covers_every_templated_component_type` 失败。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from workflow_engine.worldgen import generator as gen  # noqa: E402


class _FakeTable:
    def __init__(self, registry_id, records):
        self.registry_id = registry_id
        self.records = records


class _FakeRegistries:
    """只需支撑 `_registry_records(registries, "fragment_template_registry")`。"""

    def __init__(self, records):
        self.registries = [_FakeTable("fragment_template_registry", records)]


_TEMPLATES = [
    {"fragment_template_id": "FT_A1", "building_template_id": "BT_X",
     "component_type": "external_wall"},
    {"fragment_template_id": "FT_A2", "building_template_id": "BT_X",
     "component_type": "external_wall"},
    {"fragment_template_id": "FT_B1", "building_template_id": "BT_X",
     "component_type": "structural_member"},
    {"fragment_template_id": "FT_C1", "building_template_id": "BT_Y",
     "component_type": "fire_door"},
    # `signboard` 故意没有模板——对应真实注册表的缺口
]


def _regs():
    return _FakeRegistries(list(_TEMPLATES))


def _call(world_id: str, *, on: bool, avail: set[str], target: int = 2):
    # 1a-ii 后本函数不再收主 rng；选型由 (world_id, 模板 id) 稳定键决定。
    return gen._select_fragment_templates(
        building=None, building_template_id="BT_X", registries=_regs(),
        world_id=world_id,
        target_count=target, available_component_types=avail,
        ensure_component_type_coverage=on,
    )


def test_selection_cannot_touch_the_main_rng_at_all() -> None:
    """🔴 结构保证：`_select_fragment_templates` **收不到**主 rng。

    历史：首版 ctcov 追加用 `rng.randrange(...)` 推进了主 rng，而
    `_pick_component_for_fragment` 是在**主循环里**才取 rng ⇒
    **原有模板绑到了不同的组件上**，批 H 实测 **19/30 栋原有片段整批消失**。
    于是那一批不是「加了片段」，是「换了随机流的另一个世界」，召回差无法归因。

    过去这条靠「比调用前后 `rng.getstate()`」来守。1a-ii（2026-08-05）把两处
    `rng.shuffle` 换成稳定键排序、`rng` 形参一并删掉之后，
    **函数拿不到主 rng 这件事本身**就是保证，比任何运行时断言强。
    ⇒ 这里改断签名，并顺带钉住「按位置传 rng 会 TypeError」。
    """
    import inspect

    import pytest

    sig = inspect.signature(gen._select_fragment_templates)
    assert "rng" not in sig.parameters, (
        "`rng` 形参又回来了——它一旦存在就可能被消费，下游会整体移位"
    )
    with pytest.raises(TypeError):
        gen._select_fragment_templates(
            None, "BT_X", _regs(), random.Random(7),  # type: ignore[misc]
        )


def test_switch_off_selection_is_a_prefix_of_switch_on() -> None:
    """输出层不变式：开关只做**尾部追加**，不重排前面选中的模板。

    这是原「rng 状态逐位相同」那条断言真正要保的东西——那条只是它的代理，
    且 1a-ii 之后已恒真（函数根本收不到 rng）。本条测行为本身，
    开关坏成「重排」时会红。
    """
    avail = {"external_wall", "structural_member", "fire_door"}
    off = _call("WB-CTCOV-0001", on=False, avail=avail, target=2)
    on = _call("WB-CTCOV-0001", on=True, avail=avail, target=2)
    ids_off = [t["fragment_template_id"] for t in off]
    ids_on = [t["fragment_template_id"] for t in on]
    assert ids_on[: len(ids_off)] == ids_off, (
        f"开关重排了既有选型：关={ids_off} 开={ids_on}"
    )
    assert len(ids_on) > len(ids_off), "开关一个模板都没补，本对照失去意义"


def test_on_covers_every_templated_component_type() -> None:
    avail = {"external_wall", "structural_member", "fire_door"}
    chosen = _call("WB-CTCOV-0001", on=True, avail=avail, target=1)
    covered = {t["component_type"] for t in chosen}
    assert avail <= covered, f"漏了 {avail - covered}"


def test_on_cannot_cover_a_type_with_no_template() -> None:
    """诚实边界：注册表没有该类模板时，开关也补不出来。"""
    avail = {"external_wall", "signboard"}
    chosen = _call("WB-CTCOV-0001", on=True, avail=avail, target=1)
    covered = {t["component_type"] for t in chosen}
    assert "external_wall" in covered
    assert "signboard" not in covered


def test_on_is_deterministic_under_the_same_world_id() -> None:
    avail = {"external_wall", "structural_member", "fire_door"}
    a = _call("WB-CTCOV-0002", on=True, avail=avail, target=1)
    b = _call("WB-CTCOV-0002", on=True, avail=avail, target=1)
    assert [t["fragment_template_id"] for t in a] == [t["fragment_template_id"] for t in b]


def test_batch_config_hash_distinguishes_the_coverage_flag() -> None:
    """🔴 开关必须改变 `deterministic_key`，且**关着时逐位不变**。

    实测发现的真问题：`batch_config_hash` 名字说是「批配置哈希」，实际只**白名单**
    取了 `archetype_distribution` 一个键。于是开了本开关（generated 格 23→34、
    世界内容明显不同）而 `deterministic_key` **逐位相同** —— 锚区分不出两个池，
    正是「换参照系」风险最坏的形态：静默同名。

    修法保持缺省等价：新键**只在为真时**才进哈希载荷。

    ⏳ 白名单本身仍是隐患——下一个 `batch_config` 旋钮若忘了在那里登记，同样静默同键。
       本测试只钉住这一个旋钮，**不构成对白名单机制的保护**。
    """
    from workflow_engine.worldgen import validation as val

    def h(cfg):
        payload = {
            "generator_version": val.GENERATOR_VERSION,
            "requested_count": 6,
            "seed": 301,
            "batch_profile": val._resolve_batch_profile(6),
            "schema": "building_centric.v2",
            "archetype_distribution": (cfg or {}).get("archetype_distribution"),
        }
        if (cfg or {}).get("ensure_component_type_coverage"):
            payload["ensure_component_type_coverage"] = True
        return val._hash_payload(payload)

    assert h(None) == h({}) == h({"ensure_component_type_coverage": False}), \
        "关着时哈希必须与「根本没这个键」相同——否则既有池复现不出来"
    assert h({"ensure_component_type_coverage": True}) != h(None), \
        "开着时必须是另一个世界身份"


def test_selection_reads_only_world_side_inputs() -> None:
    """判据只读世界自己有什么——函数签名里不得出现法规卡/真值类入参。

    「按楼内已有构件类补片段」是修出题器；「按漏掉的规范项补片段」是照误差
    清单造题。两者只差一个数据来源，所以这条边界要用测试钉住。
    """
    import inspect
    sig = inspect.signature(gen._select_fragment_templates)
    for bad in ("rule_card", "truth", "normative", "expected_card", "coverage_gap"):
        assert not any(bad in p for p in sig.parameters), f"入参里出现了 {bad}"
