"""deadline 事实绑定必须由**本条 deadline 自己的 time_anchor_key**决定。

## 这个文件锁的是什么病

2026-07-27 之前 `_bind_deadline_fact` 的优先级 1 是**无条件遍历**一份硬编码的
`_SIDECAR_DURATION_SLOTS`（4 个 `duration.*` 槽），任一有 sidecar 事实就
`return facts[0]`——**从头到尾不看 `time_anchor_key`**。

真实批实测（`baseline_batch_final_seed301`，30 栋）：225 条 `kind=deadline` 义务
**225/225 全部绑到同一条 `duration.notification.deadline`**，卡包 15 个不同时间锚点
全塌缩成同一条无关事实，而且是 4 行 sidecar 里任取一行。其中 **132 条 satisfied
+ 3 条 violated**——等于拿"别的碎片的通知时长"去比 §2.1.3(o)「檢驗完成後 7 日內
呈交」、§2.1.3(r)「完成修葺後 14 日內」这类**法定硬期限**，期限判定在结构上就是错的。

## 为什么老单测没抓到（本项目反复吃的亏）

`test_derivation.py` 的两个 deadline 用例**只喂一条事实**，只有一个候选时"任取"
与"取对"不可区分，故恒绿；且 `_dl` 的 docstring 把病灶当规格写了进去
（"sidecar duration 槽绑定优先级高于 time_anchor"）。**被测对象的输入全是自造且
自洽，就会恒通过而生产链路是断的。**

## 故本文件的输入尽量取真

- **卡侧全真**：直接读权威卡包 `rule_cards.json` 的 25 个真实 deadline 对象
  （15 个不同 `time_anchor_key`）——不是手搓的。
- **别名表全真**：直接读 `projection_runtime_mapping_v1.json`。
- **事实侧形状照真实批誊写**：`fact_pack.json` 里 sidecar 实产 6 个
  `duration.*` 槽 + 2 个 `procedure.repair.prescribed.*` 门状态槽（见下方常量注释）。
  批产物本身是 gitignore 的派生物，不能直接依赖，故按其真实形状誊写并在此注明来源。
"""

from __future__ import annotations

import json
import pathlib

from evo_agent_baseline.closure.fact_binding import FactIndex
from evo_agent_baseline.closure.obligation_deriver import _bind_deadline_fact
from evo_agent_baseline.closure.validator import _normalize_alias_map

from .fixtures import make_fact, make_fact_pack

_PACK_DIR = (
    pathlib.Path(__file__).resolve().parents[4]
    / "regulations"
    / "rulecard_v2"
    / "mbis_cop_2023"
)

# 真实批 fact_pack.json 里 sidecar_entry 实产的 duration / 门状态槽（逐字誊写）。
# 注意 `.to_person` / `.to_ba` 两槽**不在**旧硬编码 4 槽清单里——那份清单本身已过期。
_REAL_SIDECAR_DURATION_SLOTS = [
    "duration.notification.deadline",
    "duration.submission.deadline",
    "duration.delivery.deadline",
    "duration.delivery.deadline.to_person",
    "duration.delivery.deadline.to_ba",
    "duration.site_visit.interval",
]
# 事实侧真实命名（卡侧写 `repair.prescribed.*`，靠别名表接上）。值是**布尔门状态**，
# 不是时长——这正是修好绑定后这些锚点仍报 missing_time_anchor 的原因。
_REAL_GATE_SLOTS = [
    "procedure.repair.prescribed.started",
    "procedure.repair.prescribed.completed",
]


def _load_json(name: str):
    return json.loads((_PACK_DIR / name).read_text(encoding="utf-8"))


def _real_deadlines():
    """权威卡包里全部 workflow_operands.deadlines[] 对象。"""
    pack = _load_json("rule_cards.json")
    out = []
    for card in pack["cards"]:
        for dl in (card.get("workflow_operands") or {}).get("deadlines") or []:
            out.append(dl)
    return out


def _real_alias_maps():
    mapping = _load_json("projection_runtime_mapping_v1.json")
    return (
        _normalize_alias_map(mapping.get("slot_aliases") or {}),
        _normalize_alias_map(mapping.get("measure_aliases") or {}),
    )


def _bind(deadline, index):
    """`_bind_deadline_fact` 2026-08-05 起返回 `(fact, status)`（碰撞必须外显）。

    本文件锁的是「按本条锚点取事实」，不是碰撞策略（那在
    `test_deadline_anchor_supply.py` B3）；故这里统一断言 status 为 None
    ——一旦某个用例意外走到 `"ambiguous"`，会在这里当场炸，而不是被压成
    "绑不上"混进反塌缩断言里。
    """
    fact, status = _bind_deadline_fact(deadline, index)
    assert status is None, f"用例意外触发碰撞策略：status={status!r}"
    return fact


def _real_shaped_index() -> FactIndex:
    """按真实批形状建 FactIndex：6 个 duration 槽 + 2 个门状态槽，各多行 sidecar。"""
    facts = []
    for frag in ("FRG-A", "FRG-B"):
        for i, slot in enumerate(_REAL_SIDECAR_DURATION_SLOTS):
            facts.append(
                make_fact(
                    f"{frag}-dur-{i}",
                    slot_id=slot,
                    measure_key=slot,
                    value=float(i + 1),
                    value_type="number",
                    carrier_type="sidecar_entry",
                    qualifiers={"fragment_id": frag},
                )
            )
        for i, slot in enumerate(_REAL_GATE_SLOTS):
            facts.append(
                make_fact(
                    f"{frag}-gate-{i}",
                    slot_id=slot,
                    measure_key=slot,
                    value=True,
                    value_type="boolean",
                    carrier_type="sidecar_entry",
                    qualifiers={"fragment_id": frag},
                )
            )
    slot_aliases, measure_aliases = _real_alias_maps()
    return FactIndex(
        make_fact_pack(facts),
        slot_aliases=slot_aliases,
        measure_aliases=measure_aliases,
    )


# --------------------------------------------------------------------- #
# 1. 塌缩本身
# --------------------------------------------------------------------- #
def test_real_card_pack_deadlines_do_not_collapse_to_one_fact():
    """全卡包 25 个 deadline 不许再全部绑到同一条事实（修前恒为 1 条）。"""
    index = _real_shaped_index()
    deadlines = _real_deadlines()
    assert len(deadlines) >= 20, "卡包 deadline 对象数异常，测试前提失效"

    bound = {}
    for dl in deadlines:
        fact = _bind(dl, index)
        bound[dl.get("time_anchor_key")] = fact.slot_id if fact else None

    distinct_facts = {v for v in bound.values() if v is not None}
    # 修前：distinct_facts == {"duration.notification.deadline"}，且**每一个**锚点都命中它。
    assert distinct_facts != {"duration.notification.deadline"}, (
        "锚点塌缩复现：全部 deadline 又绑回同一条 duration.notification.deadline"
    )
    # 没有任何一个锚点该绑到 notification 槽——15 个真实锚点无一命名 duration 槽。
    assert "duration.notification.deadline" not in distinct_facts


def test_anchor_that_names_nothing_binds_nothing():
    """锚点不命名任何事实槽 → 必须绑不到（修前会任取一条 duration 事实返回）。"""
    index = _real_shaped_index()
    fact = _bind(
        {"deadline_id": "D1", "relation": "within", "time_anchor_key": "anchor.none"},
        index,
    )
    assert fact is None, f"锚点 anchor.none 不该绑上任何事实，实得 {fact and fact.slot_id}"


# --------------------------------------------------------------------- #
# 2. 绑上的必须是本条锚点自己的事实
# --------------------------------------------------------------------- #
def test_every_bound_fact_matches_its_own_anchor():
    """不变量：凡绑上事实的 deadline，事实的 canonical 槽/量表 == canonical 锚点。"""
    index = _real_shaped_index()
    for dl in _real_deadlines():
        fact = _bind(dl, index)
        if fact is None:
            continue
        anchor = str(dl.get("time_anchor_key"))
        assert index.canonical_slot(anchor) == fact.slot_id or index.canonical_measure(
            anchor
        ) == fact.measure_key, (
            f"锚点 {anchor!r} 绑到了不相干的事实 "
            f"slot={fact.slot_id!r} measure={fact.measure_key!r}"
        )


# --------------------------------------------------------------------- #
# 3. 别名归一必须同批生效（否则上面几条靠"全都绑不上"也能过）
# --------------------------------------------------------------------- #
def test_alias_anchors_still_bind_after_normalization():
    """卡侧 repair.prescribed.* → 事实侧 procedure.repair.prescribed.*。

    这两个锚点是**唯一**在真实数据里能绑上的。少了 canonical_slot 归一它们会变成
    真 miss——那样上面的反塌缩断言会靠"一条都绑不上"廉价通过，等于没测。
    """
    index = _real_shaped_index()
    for card_key, fact_slot in (
        ("repair.prescribed.started", "procedure.repair.prescribed.started"),
        ("repair.prescribed.completed", "procedure.repair.prescribed.completed"),
    ):
        fact = _bind(
            {"deadline_id": "D1", "relation": "before", "time_anchor_key": card_key},
            index,
        )
        assert fact is not None, f"别名锚点 {card_key!r} 未绑上——canonical_slot 归一失效"
        assert fact.slot_id == fact_slot

    # 反面：裸查（不建别名表）拿不到，证明确实是归一在起作用而非碰巧同名。
    naked = FactIndex(_real_shaped_index().fact_pack)
    assert (
        _bind(
            {"deadline_id": "D1", "time_anchor_key": "repair.prescribed.started"}, naked
        )
        is None
    )


def test_measure_lookup_is_canonicalized():
    """measure 级查找（绑定优先级 3/4）同样必须过 `canonical_measure`。

    `measure_index` 与 `slot_index` 一样是**按 canonical key 建的**，故裸 key 查找
    对任何命中 measure 别名表的锚点必 miss。

    诚实边界：当前 25 个真实 deadline 无一以 measure 别名作锚点（真实 measure_aliases
    的 4 条都是长度/比例量表），故这里取真实登记的别名对
    `depth.patch_repair → length.concrete_repair.depth` 来**打通这条代码路径**，
    锁的是"查找过不过归一"，不是"某张真卡这么用"。
    """
    alias_key, canonical_key = "depth.patch_repair", "length.concrete_repair.depth"
    slot_aliases, measure_aliases = _real_alias_maps()
    assert measure_aliases.get(alias_key) == canonical_key, "measure 别名表实样已变"

    facts = [
        make_fact(
            "M1",
            measure_key=canonical_key,
            value=3.0,
            value_type="number",
            carrier_type="building",
        )
    ]
    deadline = {"deadline_id": "D1", "relation": "within", "time_anchor_key": alias_key}

    index = FactIndex(
        make_fact_pack(facts),
        slot_aliases=slot_aliases,
        measure_aliases=measure_aliases,
    )
    fact = _bind(deadline, index)
    assert fact is not None and fact.fact_id == "M1", "measure 查找未过 canonical_measure"

    # 反面：不建别名表 → 查不到，证明命中确实由归一带来。
    assert _bind(deadline, FactIndex(make_fact_pack(facts))) is None
