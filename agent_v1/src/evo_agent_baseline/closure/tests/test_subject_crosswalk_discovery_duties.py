"""闸：发现型（甲）条款统辖的 subject **不得**出现在 subject 词桥表里。

## 为什么要这道闸

词桥的语义是「楼内组件类与该 subject 的组件类集无交集 ⇒ **整卡 not_applicable**」。
这对**处置型（乙）**条款是对的（没有僭建物，就无从清拆），
对**发现型（甲）**条款是错的——「這棟樓沒有僭建物」**不能**推出「不必去認明」。

2026-07-27 实测后果（新批 `phase_a_verify_seed301_20260727`，30 栋）：
`ubw_and_related_scope -> ["ubw"]` 这一条，让 **23/30 栋**（无 `ubw` 组件类的楼）
的 **18 张 §3.7 卡**被整卡判 `not_applicable`，
在验收标准③ 阅卷里表现为 **`wrong_structural_na` 静默漏判**
（系统不会说自己漏了，那条规范项只是不出现）。

## 🔴 为什么必须有这道闸，而不是靠注释

改动本身是**删掉一行数据**。全量测试 2901 项**一条都不会红**——
`test_subject_bridge.py` 全部使用**合成**词桥，**没有任何测试读真表内容**。
⇒ 这一行随时可能被"顺手加回来"，而所有自动闸保持全绿。
这正是本项目记过的形状：**「闸显示 Passed」只说明闸检查的规则没被违反，
不说明规则被检查了**。

## 判据来源（中文正文，`agent_v1/regulations/markdown/MBIS_CoP_2023.md`）

§3.7 六条全部是恒适用：
- §3.7.1(a)「**須認明**的違例建築工程（僭建物）**包括**位於…」——范围规定句，非条件从句
- §3.7.1(b)(ii) 引出句「**須認明**的僭建物的範圍**涵蓋**以下各項」——情态在引出句里，
  分项是裸名词短语（「引出句丢失」陷阱）
- §3.7.1(c)「亦**須**…**尋找**懷疑分間單位的跡象」＝甲；
  「**如發現**這些跡象…**須記錄**」＝丙（嵌套，非卡面义务）
- §3.7.1(d)「**須備存**檢驗日誌…**須將**…呈交」——无条件程序义务（后果同甲）
- §3.7.2(A)(a)「**須**在實際可行的情況下**進行目視檢查，以認明及記錄**所有僭建物」
  ——「實際可行」是尽力性限定，不是对象存在条件
- §3.7.2(A)(b)「**須盡一切努力認明**僭建物」——教科书级发现型

与表首 `_note` 里「行政/流程类 subject 刻意不列——不做组件过滤」是**同一判据**。

## ⚠️ 本闸不覆盖的

- `fire_safety_components` **仍在表内**：§3.5 抽读的引出句同属发现型
  （§3.5.2(B)/(C)/(D)「須**認明**以下欠妥…」），但 47 张卡未逐条裁定，
  **未裁完不动**。裁完后若结论一致，应移出并把它加进本闸。
- 归位只解「整卡被词桥杀掉」这一层。§3.7.2(A)(a) 那张卡**自身**的触发器是
  对象轴的 `scope.component.inspection_included[component_type_key=ubw]`，
  无 UBW 的楼里它仍会落触发器不激活——那是**卡侧另案**，不在本闸射程。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_MAPPING_PATH = (
    Path(__file__).resolve().parents[4]
    / "regulations" / "rulecard_v2" / "mbis_cop_2023"
    / "projection_runtime_mapping_v1.json"
)

# 已逐条对中文正文裁定为「发现型 / 无条件程序义务」的 subject。
# 往这里加成员前，必须先逐条裁定该 subject 统辖的**全部**卡。
_DISCOVERY_SUBJECTS = frozenset({"ubw_and_related_scope"})


@pytest.fixture(scope="module")
def crosswalk() -> dict:
    mapping = json.loads(_MAPPING_PATH.read_text(encoding="utf-8"))
    return mapping["subject_component_crosswalk"]


def test_discovery_subjects_absent_from_crosswalk(crosswalk):
    """发现型 subject 不得被组件类过滤——否则「楼里没有 X」会静默杀掉「去找 X」的义务。"""
    present = sorted(_DISCOVERY_SUBJECTS & set(crosswalk))
    assert not present, (
        f"发现型 subject {present} 出现在 subject 词桥表里。\n"
        "词桥语义是「楼内组件类与该集无交集 ⇒ 整卡 not_applicable」，"
        "对发现型条款是错的：「這棟樓沒有僭建物」推不出「不必去認明」。\n"
        "2026-07-27 实测：这一条让 23/30 栋的 18 张 §3.7 卡被整卡判不适用，"
        "在验收标准③ 里表现为 wrong_structural_na 静默漏判。\n"
        "若确有理由加回，须先逐条对中文正文重新裁定引出句类型，并更新本闸的判据说明。"
    )


def test_crosswalk_still_filters_disposal_type_subjects(crosswalk):
    """反向闸（防过修）：处置型 subject 仍须留在表内做组件过滤。

    只删不该过滤的，不等于把表删空——「没有排水系统就不必检验排水系统」是对的。
    没有这条断言，一个把整表清空的改动同样能让上面那条通过。
    """
    must_stay = {"drainage", "structural_components", "external_defects"}
    missing = sorted(must_stay - set(crosswalk))
    assert not missing, (
        f"处置/对象型 subject {missing} 从词桥表里消失了——"
        "组件过滤对它们是正确语义，不该一并删掉。"
    )


def test_note_records_the_adjudication(crosswalk):
    """表首 `_note` 必须留下裁定依据，否则下次有人看不出为什么少了一条。"""
    note = crosswalk.get("_note") or ""
    assert "ubw_and_related_scope" in note and "認明" in note, (
        "`_note` 里没有记载 ubw_and_related_scope 被移出的法规依据。"
        "数据文件的删除动作不自带理由，理由必须写在文件里。"
    )
