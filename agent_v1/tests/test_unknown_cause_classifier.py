"""「需要你提供」vs「系统未能确定」分类器的行为锁定（第四刀，DEBT-075）。

验收标准来自用户 2026-07-26 拍板：「**不是判定系统，最终判决从一开始就是使用这个系统的
专业人员做的事情，但是也不能无故 unknown，这是两码事**」。

⇒ 「无故 unknown → 零」是硬指标；而**判据必须显式可审**，否则调一下清单就能把
缺陷洗成"正当边界"，指标立刻失真。本文件锁的就是这件事。
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import classify_unknown_cause as cuc  # noqa: E402


def test_out_of_scope_list_is_explicit_and_auditable():
    """🔴 「需要你提供」的判据必须是**显式清单**，不能是启发式。

    调一下清单就能把缺陷洗成"正当边界"——所以它必须写死、可审、可复核。
    2026-07-27 逐条重审（重锚批 seed301 实测）后清单**清空**：原四条全是误判。
    清单可以为空，但**清空必须附证据注释**，不许无声洗白。
    """
    import inspect
    body = inspect.getsource(cuc)
    assert "非规格明文" in body, "须标明这是语义归类、不是规格定义"
    if not cuc._OUT_OF_SCOPE_PREFIX and not cuc._OUT_OF_SCOPE_EXACT:
        assert "逐条重审" in body, "清单为空时须附逐条重审的证据注释"


def test_out_of_scope_entries_reclassified_20260727():
    """原「需要你提供」四条 2026-07-27 实测全部是误判，不再属本体边界之外。

    - `repair.prescribed.*`：命名不匹配——别名归一后世界有
      `procedure.repair.prescribed.started/completed`（批内各 150 条）。
    - `procedure.investigation.detailed.started`：世界有上游可派生（30 条楼级），
      只是当时没接线。
    - `procedure.minor_works.`：供给侧未建（卡注释自认"还须补事实通道"），非本体边界。
    - `actor.representative.qualified_for_assigned_role`：卡包 authoring 错误
      （lookup_rule 限定符词表与承载槽值词表结构性不相交）。
    """
    for slot in ("repair.prescribed.started", "repair.prescribed.completed",
                 "procedure.investigation.detailed.started",
                 "procedure.minor_works.regulation_27.applies",
                 "actor.representative.qualified_for_assigned_role"):
        assert not cuc._out_of_scope(slot), f"{slot} 已实测为误判，不得再判「需要你提供」"


def test_world_modelled_state_is_a_defect_not_your_input():
    """构件状态类的槽**不属**本体边界之外——查不到就是缺陷，不许洗成"要你提供"。"""
    for slot in ("defect.class.present", "scope.component.covered",
                 "measure.crack.width", "reporting.record.submitted"):
        assert not cuc._out_of_scope(slot), f"{slot} 不该被算成「需要你提供」"


def test_open_trigger_dependency_is_inherited_not_a_defect():
    """`depends_on_open_trigger` 是继承标签，自身无病 —— 不得计入缺口。

    它占比很大（本批 1,779 条）；混进缺陷会让"该修的活"虚高。
    """
    assert cuc._REASON_CLASS["depends_on_open_trigger"] == "inherited"


def test_unmodelled_upstream_is_a_defect():
    """上游产物/量测"世界模型根本没建"→ 与「声明了没产出」同族，是缺陷不是边界。"""
    for reason in ("artifact_not_modeled_upstream", "missing_artifact_evidence",
                   "missing_measurement", "missing_time_anchor"):
        assert cuc._REASON_CLASS[reason].startswith("defect."), reason


BATCH = Path(__file__).resolve().parents[1] / "experiments" / "baseline_batch_final_seed301"


def test_real_batch_alias_normalized_repair_prescribed_not_your_input():
    """真实批产物回归：别名归一后 `repair.prescribed.*` 不得再被判「有故」。

    锁的就是 2026-07-27 修掉的那个 bug：比对按裸 slot_id、没走别名归一，
    把命名不匹配误记成本体边界。世界侧 `procedure.repair.prescribed.started/
    completed` 批内各 150 条——归一后命中，归入「世界有该槽」。
    """
    if not BATCH.exists():
        import pytest
        pytest.skip("重锚批产物不在本机")
    r = cuc.classify(BATCH, None)
    niy = r["per_slot"]["need_your_input"]
    assert not any("repair.prescribed" in s for s in niy), dict(niy)
    # 且原四条各自落到实测归属的缺陷类
    assert r["per_slot"]["defect.derivable_upstream"][
        "procedure.investigation.detailed.started"] > 0
    assert r["per_slot"]["defect.card_authoring"][
        "actor.representative.qualified_for_assigned_role"] > 0
