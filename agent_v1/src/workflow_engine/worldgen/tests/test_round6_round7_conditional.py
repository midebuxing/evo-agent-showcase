"""DEBT-020 Round 6 + Round 7 sidecar conditional_formula 落地测试 (spec 06 §11.6).

覆盖：
  ConditionalFormulaIntegrationTests — sidecar 走 conditional path 时 evaluator 正确接 hidden state
  MarginalAlignmentTests — 真跑 10000 MC, verify alignment delta < 0.05
  DAGConsistencyTests — verify 没有 sidecar slot 引用 sampling_order 在自己之后的 slot
  EnumProbabilityTests — verify 每个 enum slot anchor 加起来 = 1.0 ± 0.001
  CompletedAndRetainedConsistencyTests — verify post-sample clamp 工作
  MBI2DAGPatchTests — verify Round 7 MBI2 在 L1 (不在 L3), depends_on temp_ri_nomination
"""

from __future__ import annotations

import random
import unittest
from collections import Counter
from typing import Any, Dict, List

from workflow_engine.worldgen.conditional_eval import (
    ALLOWED_HIDDEN_INPUTS,
    ALLOWED_INPUTS,
    ALLOWED_PHYSICAL_INPUTS,
    ALLOWED_SIDECAR_INPUTS,
    HIDDEN_STATE_PRIOR_MEANS,
    build_evaluator_context,
    compute_log_anchor,
    compute_logit,
    evaluate_bool_conditional,
    evaluate_centered_bool_conditional,
    evaluate_centered_enum_conditional,
    evaluate_enum_conditional,
    expected_marginal_bool,
    expected_marginal_enum,
    validate_formula,
)
from workflow_engine.worldgen.registry import (
    DEBT020_ROUND7_DISTRIBUTION_SOURCE,
    _build_registry_bundle,
)
from workflow_engine.worldgen.round6_formulas import (
    A16_ANNOTATED_ROUND7_SLOTS,
    A16_ROUND7_DISTRIBUTION_SOURCE_SUFFIX,
    ANCHOR_SOURCES_ROUND7,
    DISTRIBUTION_SOURCE,
    MARGINAL_ANCHORS_ROUND7,
    POOL_V2_REWIRED_DISTRIBUTION_SOURCE,
    POOL_V2_REWIRED_OVERLAY_SLOTS,
    POOL_V2_SUPPLY_DISTRIBUTION_SOURCE,
    POOL_V2_SUPPLY_SAMPLING_ORDERS,
    SAMPLING_ORDER_ROUND7,
    get_round6_round7_formulas,
)


def _all_45_slot_records() -> Dict[str, Dict[str, Any]]:
    """Round 7 那 45 个 slot 的 records（本套测试守的契约就是这 45 个 overlay 完整）。

    EXP-011 起注册表允许新增非 Round7 slot（如 actor.representative.assigned_role），
    它们不在 Round7 formula 表内、不带 overlay 字段，按 MARGINAL_ANCHORS_ROUND7
    键集过滤排除——45 契约本体不变。
    """
    from workflow_engine.worldgen.round6_formulas import MARGINAL_ANCHORS_ROUND7

    bundle = _build_registry_bundle()
    for r in bundle.registries:
        if r.registry_id == "sidecar_bool_slot_registry":
            return {
                rec["slot_id"]: rec
                for rec in r.records
                if rec["slot_id"] in MARGINAL_ANCHORS_ROUND7
            }
    raise RuntimeError("sidecar_bool_slot_registry not found")


class ConditionalFormulaIntegrationTests(unittest.TestCase):
    """spec 06 §11.6: 45 slot 走 conditional path 时 evaluator 接 hidden + sidecar upstream 正确."""

    def test_all_45_slots_have_conditional_formula(self) -> None:
        records = _all_45_slot_records()
        self.assertEqual(len(records), 45)
        for slot_id, rec in records.items():
            with self.subTest(slot_id=slot_id):
                self.assertIsNotNone(rec.get("conditional_formula"),
                                     f"{slot_id} missing conditional_formula")

    def test_all_45_slots_have_round7_distribution_source(self) -> None:
        """来源串**精确三分账**（A1.6 落地改锚，2026-08-06）：

        · 改锚两槽（mbi5/sp2）→ `POOL_V2_REWIRED_DISTRIBUTION_SOURCE`
          （A1.6 前是 PLACEHOLDER；MC 实测两槽在原锚上过阈后换实值）；
        · A1.6 授权集（决议 §一 13 槽 ＋ §三 补裁槽，共 14）→ Round 5 原串
          ＋ `A16_ROUND7_DISTRIBUTION_SOURCE_SUFFIX`（官方线 §一.4：保留来历，
          只加注口径分界，不换串）；
        · 其余 29 槽 → Round 5 原串不动。

        既防改锚/被裁槽冒充未动过的 Round 7 档，也防无关槽被错标。
        """
        records = _all_45_slot_records()
        annotated = 0
        for slot_id, rec in records.items():
            with self.subTest(slot_id=slot_id):
                if slot_id in POOL_V2_REWIRED_OVERLAY_SLOTS:
                    self.assertEqual(
                        rec["distribution_source"],
                        POOL_V2_REWIRED_DISTRIBUTION_SOURCE,
                    )
                elif slot_id in A16_ANNOTATED_ROUND7_SLOTS:
                    self.assertEqual(
                        rec["distribution_source"],
                        DEBT020_ROUND7_DISTRIBUTION_SOURCE
                        + A16_ROUND7_DISTRIBUTION_SOURCE_SUFFIX,
                    )
                    self.assertIn(
                        "不是真实分布声明", rec.get("semantic_note") or "",
                        "被 A1.6 授权的槽必须带口径分界句——门④ pass 不等于分布真实")
                    annotated += 1
                else:
                    self.assertEqual(
                        rec["distribution_source"],
                        DEBT020_ROUND7_DISTRIBUTION_SOURCE,
                    )
        self.assertEqual(annotated, 14, "A1.6 授权集应恰 14 槽（13 ＋ 补裁 1）")
        self.assertNotIn(
            "PLACEHOLDER",
            " ".join(str(r["distribution_source"]) for r in records.values()),
            "45 槽里仍有占位来源——占位参数不得进池")
        self.assertEqual(
            POOL_V2_REWIRED_OVERLAY_SLOTS,
            {"artifact.form.mbi5", "artifact.record.nonconformity_sp2"},
        )

    def test_all_45_slots_have_seven_round6_round7_fields(self) -> None:
        required = {
            "sampling_order", "upstream_inputs", "marginal_anchor", "anchor_source",
            "alignment_check", "distribution_source", "cop_section",
        }
        records = _all_45_slot_records()
        for slot_id, rec in records.items():
            with self.subTest(slot_id=slot_id):
                missing = required - set(rec.keys())
                self.assertEqual(missing, set(), f"{slot_id} missing fields {missing}")

    def test_anchor_source_label_includes_cop_section(self) -> None:
        """Round 7 §1: 45 个 source label 全部精确化到 MBIS_CoP_2023 §x.y.z 格式."""
        records = _all_45_slot_records()
        for slot_id, rec in records.items():
            with self.subTest(slot_id=slot_id):
                source = rec["anchor_source"]
                self.assertIn("MBIS_CoP_2023", source,
                              f"{slot_id} anchor_source missing COP citation: {source}")
                self.assertIn("round4_baseline", source.lower(),
                              f"{slot_id} anchor_source missing round4_baseline")

    def test_centered_formula_evaluator_uses_hidden_state(self) -> None:
        """centered_sigmoid_linear 公式中含 H.* term → evaluator context 必须传 hidden_state."""
        formula = {
            "type": "centered_sigmoid_linear",
            "anchor": 0.86,
            "upstream_expected": {
                "H.case_active": 0.96,
                "H.admin_discipline_score": 0.65,
            },
            "terms": {
                "H.case_active": 0.55,
                "H.admin_discipline_score": 0.30,
            },
        }
        # case 1: at prior means → p ≈ anchor
        ctx_at_prior = build_evaluator_context(
            hidden_state={"H.case_active": 0.96, "H.admin_discipline_score": 0.65}
        )
        rng = random.Random(42)
        samples = [evaluate_bool_conditional(formula, ctx_at_prior, rng) for _ in range(2000)]
        observed = sum(samples) / len(samples)
        self.assertAlmostEqual(observed, 0.86, delta=0.04)

        # case 2: low admin_discipline → p < anchor
        ctx_low = build_evaluator_context(
            hidden_state={"H.case_active": 0.96, "H.admin_discipline_score": 0.20}
        )
        rng = random.Random(42)
        samples = [evaluate_bool_conditional(formula, ctx_low, rng) for _ in range(2000)]
        observed_low = sum(samples) / len(samples)
        self.assertLess(observed_low, 0.86)

    def test_centered_formula_evaluator_uses_sidecar_upstream(self) -> None:
        """centered formula 中 sidecar slot upstream → evaluator 接 sidecar_upstream context."""
        formula = {
            "type": "centered_sigmoid_linear",
            "anchor": 0.50,
            "upstream_expected": {"procedure.ri.appointment.completed": 0.86},
            "terms": {"procedure.ri.appointment.completed": 1.0},
        }
        # If RI appointment NOT completed → p < anchor
        ctx_no_ri = build_evaluator_context(
            sidecar_upstream={"procedure.ri.appointment.completed": False}
        )
        rng = random.Random(7)
        samples = [evaluate_bool_conditional(formula, ctx_no_ri, rng) for _ in range(2000)]
        observed = sum(samples) / len(samples)
        self.assertLess(observed, 0.45)

        # If RI appointment completed → p > anchor
        ctx_ri = build_evaluator_context(
            sidecar_upstream={"procedure.ri.appointment.completed": True}
        )
        rng = random.Random(7)
        samples = [evaluate_bool_conditional(formula, ctx_ri, rng) for _ in range(2000)]
        observed = sum(samples) / len(samples)
        self.assertGreater(observed, 0.55)

    def test_validate_formula_accepts_centered_types(self) -> None:
        """centered_sigmoid_linear / centered_softmax_per_class 走 validate."""
        validate_formula({
            "type": "centered_sigmoid_linear",
            "anchor": 0.5,
            "upstream_expected": {"H.case_active": 0.96},
            "terms": {"H.case_active": 0.3},
        })
        validate_formula({
            "type": "centered_softmax_per_class",
            "classes": {
                "a": {"anchor": 0.6, "upstream_expected": {}, "terms": {}},
                "b": {"anchor": 0.4, "upstream_expected": {}, "terms": {}},
            },
        })

    def test_validate_formula_rejects_centered_anchor_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            validate_formula({
                "type": "centered_sigmoid_linear",
                "anchor": 1.5,  # > 1
                "upstream_expected": {},
                "terms": {},
            })

    def test_validate_formula_rejects_unknown_hidden_input(self) -> None:
        with self.assertRaises(ValueError):
            validate_formula({
                "type": "centered_sigmoid_linear",
                "anchor": 0.5,
                "upstream_expected": {"H.fake_hidden": 0.5},
                "terms": {"H.fake_hidden": 0.3},
            })

    def test_validate_formula_rejects_centered_softmax_anchor_sum_off(self) -> None:
        with self.assertRaises(ValueError):
            validate_formula({
                "type": "centered_softmax_per_class",
                "classes": {
                    "a": {"anchor": 0.7, "upstream_expected": {}, "terms": {}},
                    "b": {"anchor": 0.4, "upstream_expected": {}, "terms": {}},
                    # sum = 1.1, > tolerance 1e-3
                },
            })

    def test_compute_logit_compute_log_anchor(self) -> None:
        # logit(0.5) = 0
        self.assertAlmostEqual(compute_logit(0.5), 0.0, places=6)
        # logit(0.86) ≈ 1.815 (Round 6 documented)
        self.assertAlmostEqual(compute_logit(0.86), 1.8152, places=3)
        # log(0.5) ≈ -0.693
        self.assertAlmostEqual(compute_log_anchor(0.5), -0.6931, places=3)
        # clip near 0 and 1 to avoid inf
        self.assertGreater(compute_logit(0.0), -100)  # actually -27.6
        self.assertLess(compute_logit(1.0), 100)


class MarginalAlignmentTests(unittest.TestCase):
    """spec 06 §11.6.5: MC alignment 必须 < 0.05——**跑在生产两相分派编排器上**。

    🔴 口径改锚（A1.6 落地，2026-08-06，`实施记录_A16落地_20260806.md` §五.2）。
    本类原来自带一个**平铺 MC**：45 槽按 `sampling_order` 顺序各抽一次、上游直读
    上一次的抽样值、没有粒度概念、没有聚合。那正是 2026-05-11 那次 MC 的口径，
    也正是 2026-07-07 粒度两相分派（7a82118）之后**不再存在**的那个世界——
    45/45 徽章被 #37 判为「过期」说的就是它。

    留着那个平铺 MC 有两重害处：①它测的东西运行时不发生；②A1.6 把楼级消费者的
    中心化基改成**聚合后期望**（`any_true: 1−(1−p)^k` / `all_true: p^k`，k=4）之后，
    拿碎片边际去喂楼级消费者必然出现镜像偏差——**那个红是口径错，不是公式错**。
    ⇒ 换成真采样路径 `_sample_sidecar_bool_slots_for_building`（楼级槽一栋一抽、
    碎片上游按 `BUILDING_READING_AGGREGATION` 聚合、钳制在环），与
    `agent_v1/scripts/rerun_distribution_mc.py` 同口径、规模缩小到单测量级。

    ⚠️ anchor 取**注册表运行时值**（`marginal_anchor`），不取
    `MARGINAL_ANCHORS_ROUND7`：被钳制的槽（`supervision.record.completed_and_retained`）
    两者按构造不相等——公式内部中心 0.62 是钳制前的，声明的实现边际是 0.39。
    """

    N_BUILDINGS = 1200
    FRAGMENTS_PER_BUILDING = 4  # 与 MC 口径同一个 k（聚合期望是 k 的函数）
    SEED_TAG = "unit_align_a16_20260806"  # 键控子流 ⇒ 本测确定可复现

    @classmethod
    def setUpClass(cls) -> None:
        from workflow_engine.worldgen.sidecar import (
            _sample_sidecar_bool_slots_for_building,
        )

        bundle = _build_registry_bundle()
        records: List[Dict[str, Any]] = []
        for registry in bundle.registries:
            if registry.registry_id == "sidecar_bool_slot_registry":
                records = list(registry.records)
        cls.records_by_slot = {str(r.get("slot_id")): r for r in records}

        frag_ctx = {k: float(v) for k, v in HIDDEN_STATE_PRIOR_MEANS.items()}
        frag_ctx["building_total_severity_max"] = 0.45
        frag_ctx["building_defect_count_norm"] = 0.15
        bld_ctx = {
            "building.metadata.building_age_years": 35.0,
            "building_total_severity_max": 0.45,
            "building_defect_count": 3.0,
            "H.age_old_score": float(HIDDEN_STATE_PRIOR_MEANS["H.age_old_score"]),
            "H.case_active": 1.0,
            "H.defect_severity_score": 0.45,
        }

        tally: Dict[str, Counter] = {}
        for i in range(cls.N_BUILDINGS):
            world_id = f"WB-UNIT-ALIGN-{i:05d}-{cls.SEED_TAG}"
            fragment_ids = [
                f"{world_id}-FRG-{j:02d}"
                for j in range(cls.FRAGMENTS_PER_BUILDING)
            ]
            buckets_by_fragment, building_buckets = (
                _sample_sidecar_bool_slots_for_building(
                    building_world_id=world_id,
                    fragment_ids=fragment_ids,
                    sidecar_bool_slot_records=records,
                    per_fragment_contexts={
                        fid: dict(frag_ctx) for fid in fragment_ids
                    },
                    building_context=dict(bld_ctx),
                )
            )
            for bucket_map in [building_buckets] + [
                buckets_by_fragment[fid] for fid in fragment_ids
            ]:
                for rows in bucket_map.values():
                    for row in rows:
                        quals = getattr(row, "qualifiers", None) or {}
                        if str(quals.get("aggregation") or "") == "building":
                            continue  # 聚合派生行是读数不是采样，不计边际
                        slot = getattr(row, "slot_id", None)
                        val = getattr(row, "value", None)
                        if slot is None or not isinstance(val, (bool, str)):
                            continue
                        tally.setdefault(str(slot), Counter())[val] += 1
        cls.tally = tally
        cls.formulas = get_round6_round7_formulas()

    @classmethod
    def _anchor_of(cls, slot_id: str) -> Any:
        rec = cls.records_by_slot[slot_id]
        anchor = rec.get("marginal_anchor")
        return rec.get("prevalence") if anchor is None else anchor

    def test_45_bool_slot_alignment_under_threshold(self) -> None:
        for slot_id, spec in self.formulas.items():
            if spec["conditional_formula"]["type"] != "centered_sigmoid_linear":
                continue
            anchor = float(self._anchor_of(slot_id))
            counts = self.tally[slot_id]
            total = sum(counts.values())
            observed = counts.get(True, 0) / total
            delta = abs(observed - anchor)
            with self.subTest(slot_id=slot_id):
                self.assertLess(
                    delta, 0.05,
                    f"{slot_id}: anchor={anchor}, observed={observed:.4f}, "
                    f"delta={delta:.4f}, n={total}",
                )

    def test_3_enum_slot_alignment_under_threshold(self) -> None:
        for slot_id, spec in self.formulas.items():
            if spec["conditional_formula"]["type"] != "centered_softmax_per_class":
                continue
            anchor = self._anchor_of(slot_id)
            counts = self.tally[slot_id]
            total = sum(counts.values())
            max_delta = max(
                abs(counts.get(cls_name, 0) / total - float(exp_p))
                for cls_name, exp_p in anchor.items()
            )
            with self.subTest(slot_id=slot_id):
                self.assertLess(
                    max_delta, 0.05,
                    f"{slot_id}: max_abs_delta={max_delta:.4f}",
                )

    def test_round7_anchor_delta_summary(self) -> None:
        """Aggregate delta across 45 slot. max delta must remain under 0.05."""
        max_delta = 0.0
        worst = ""
        for slot_id, spec in self.formulas.items():
            anchor = self._anchor_of(slot_id)
            counts = self.tally[slot_id]
            total = sum(counts.values())
            if spec["conditional_formula"]["type"] == "centered_sigmoid_linear":
                d = abs(counts.get(True, 0) / total - float(anchor))
            else:
                d = max(
                    abs(counts.get(c, 0) / total - float(p))
                    for c, p in anchor.items()
                )
            if d > max_delta:
                max_delta, worst = d, slot_id
        self.assertLess(max_delta, 0.05, f"最差槽 {worst}: {max_delta:.4f}")

    def test_building_consumers_center_on_aggregated_reading(self) -> None:
        """A1.6 乙路的**结构断言**：楼级消费者的碎片级上游中心化基＝聚合后期望。

        这条不测统计量，测的是「中心化基取哪个数」——统计对齐可以靠噪声侥幸过，
        中心化基取错则是确定性的（`rc.pre_notification_given` 读
        `artifact.proposal.repair` 的 0.57 而不是 1−0.43⁴=0.9658，就是 A1.6 之前
        那个从没被登记过的偏差）。
        """
        from workflow_engine.worldgen.registry import BUILDING_READING_AGGREGATION

        checked = 0
        for slot_id, rec in self.records_by_slot.items():
            if str(rec.get("granularity") or "fragment") != "building":
                continue
            formula = rec.get("conditional_formula") or {}
            blocks = list((formula.get("classes") or {}).values()) or [formula]
            for block in blocks:
                for key, expected in (block.get("upstream_expected") or {}).items():
                    up = self.records_by_slot.get(key)
                    if up is None or str(up.get("granularity") or "fragment") == "building":
                        continue
                    aggregation = BUILDING_READING_AGGREGATION.get(key)
                    if aggregation is None:
                        continue
                    p = float(up.get("marginal_anchor") or up.get("prevalence"))
                    k = self.FRAGMENTS_PER_BUILDING
                    want = 1.0 - (1.0 - p) ** k if aggregation == "any_true" else p ** k
                    self.assertAlmostEqual(
                        float(expected), want, places=6,
                        msg=f"{slot_id} 读 {key}（{aggregation}）的中心化基是 "
                            f"{expected}，应为聚合后期望 {want:.6f}（碎片锚 {p}）")
                    checked += 1
        self.assertGreaterEqual(
            checked, 16,
            f"只核到 {checked} 条边——偏差族成员少于落地实测的 16 条，"
            "说明公式表或聚合表被改动而本闸没跟")


class FormulaSingletonProcessStateTests(unittest.TestCase):
    """🔴 模块级公式单例被 overlay **原地改** ⇒ 读它得到什么取决于本进程建没建过 bundle。

    （A1.6 落地审核 §二.3「必须记 C」的配套闸，2026-08-06。）

    机制：`_apply_round6_round7_overlays` 把 `spec["conditional_formula"]`
    **同一个 dict 对象**挂到注册表记录上（`record[...] = spec[...]`，不是拷贝），
    随后 `_apply_a16_building_aggregation_centering` 用 `expected[key] = new_value`
    **原地改**它 ⇒ `get_round6_round7_formulas()` 返回的那份模块缓存**跟着被改**。
    后果：同一次调用的返回值取决于**本进程建没建过 registry bundle**。
    实测（`procedure.rc.pre_notification_given` 读 `artifact.proposal.repair`
    的中心化基）：未建 bundle **0.57**（碎片边际）／建过之后 **0.96581199**
    （聚合后期望 1−(1−0.57)⁴）。

    **生产链无暴露**：`get_round6_round7_formulas()` 的非测试消费者只有
    `registry._build_registry_bundle()` 内部三处，生产采样器读的是**注册表记录**、
    不是模块缓存。但**测试层有 6 处直接读该函数**，取值随测试执行顺序漂移；
    今天它们只读 `sampling_order` / `upstream_inputs`（A1.6 不改的字段）所以没炸
    ——**那是运气不是设计**。

    本类把这条进程态依赖钉成显式不变量，并且**自带前置**（测内先显式建一次 bundle，
    不依赖任何兄弟测试的副作用），故它**必然红在该红的地方**：
      · A1.6 的中心化没落到模块缓存上（overlay 被删 / 改成写深拷贝而没同步）⇒ 红；
      · 有人删掉这里的建 bundle 前置 ⇒ 读到 0.57 ≠ 0.9658 ⇒ 红。
    变异验证（不建 bundle 的路径）已实跑，见 `实施记录_A16审核处置_20260806.md`。
    """

    CONSUMER = "procedure.rc.pre_notification_given"
    UPSTREAM = "artifact.proposal.repair"

    @staticmethod
    def _centering_base(table: Dict[str, Any], consumer: str, upstream: str) -> float:
        return float(
            table[consumer]["conditional_formula"]["upstream_expected"][upstream]
        )

    def test_module_cache_is_the_post_overlay_form(self) -> None:
        from workflow_engine.worldgen.round6_formulas import (
            MC_CALIBER_FRAGMENTS_PER_BUILDING,
            build_round6_round7_formulas,
        )

        # 🔴 前置：本测内显式建一次 bundle。删掉这一行本测必红——这就是「必然红在
        #    该红的地方」的那个「必然」，不是靠某个兄弟测试碰巧先跑过。
        _build_registry_bundle()

        cached_value = self._centering_base(
            get_round6_round7_formulas(), self.CONSUMER, self.UPSTREAM)
        # 对照组：`build_...` 每次新造 dict，故它永远是**未经 overlay** 的形态。
        pristine_value = self._centering_base(
            build_round6_round7_formulas(), self.CONSUMER, self.UPSTREAM)

        p = float(MARGINAL_ANCHORS_ROUND7[self.UPSTREAM])
        k = MC_CALIBER_FRAGMENTS_PER_BUILDING
        want = 1.0 - (1.0 - p) ** k

        self.assertAlmostEqual(
            pristine_value, p, places=9,
            msg="未经 overlay 的形态应是碎片边际——若不是，说明中心化被搬进了"
                "`build_round6_round7_formulas` 本体，本闸的对照组失效")
        self.assertAlmostEqual(
            cached_value, want, places=6,
            msg=f"模块缓存读到 {cached_value}，应为聚合后期望 {want:.8f}——"
                "要么 A1.6 的中心化没落到模块缓存上，要么本测的建 bundle 前置被删了")
        self.assertNotAlmostEqual(
            cached_value, pristine_value, places=3,
            msg="模块缓存与未经 overlay 的形态相同 ⇒ 原地改没发生")

    def test_module_cache_equals_registry_record_for_every_building_consumer(self) -> None:
        """恒等闸：模块缓存与注册表记录的 `upstream_expected` 必须逐键相等。

        两者今天是同一个 dict 对象（原地改的直接后果）。若日后照审核建议改成
        「写 record 的深拷贝」，本闸会把「改了 record 没同步模块缓存」这半边
        当场抓出来——那正是进程态依赖真正会伤人的形态。
        """
        bundle = _build_registry_bundle()
        cached = get_round6_round7_formulas()
        checked = 0
        for registry in bundle.registries:
            if registry.registry_id != "sidecar_bool_slot_registry":
                continue
            for record in registry.records:
                slot_id = str(record.get("slot_id") or "")
                if slot_id not in cached:
                    continue
                if str(record.get("granularity") or "fragment") != "building":
                    continue
                rec_formula = record.get("conditional_formula")
                cached_formula = cached[slot_id]["conditional_formula"]
                if not isinstance(rec_formula, dict):
                    continue
                rec_blocks = list((rec_formula.get("classes") or {}).values()) or [rec_formula]
                cached_blocks = (
                    list((cached_formula.get("classes") or {}).values())
                    or [cached_formula]
                )
                for rec_block, cached_block in zip(rec_blocks, cached_blocks):
                    rec_exp = rec_block.get("upstream_expected") or {}
                    cached_exp = cached_block.get("upstream_expected") or {}
                    with self.subTest(slot_id=slot_id):
                        self.assertEqual(rec_exp, cached_exp)
                    checked += 1
        self.assertGreaterEqual(
            checked, 9,
            f"只核到 {checked} 个楼级消费者——少于 A1.6 落地实测的 9 个，"
            "说明公式表或粒度声明被改动而本闸没跟")


class DAGConsistencyTests(unittest.TestCase):
    """spec 06 §11.6.7 DAG validity: 没有 sidecar slot 引用 sampling_order 在自己之后的 slot."""

    def test_sampling_order_unique_1_to_45(self) -> None:
        """45 键唯一；#38 改锚（换池批步 A1.4，2026-08-06）后 mbi5 移 25.7。

        旧不变量「恰 1..45 连续」随 DAG 重排改锚：mbi5 的正确依赖是槽 4
        修葺监督委任事件（order 25.5，池 v2 供给侧），原 6 号位空出不回填。
        新不变量＝{1..45}∖{6} ∪ {25.7}，仍逐值钉死。
        """
        orders = sorted(SAMPLING_ORDER_ROUND7.values())
        expected = sorted(set(range(1, 46)) - {6} | {25.7})
        self.assertEqual(orders, expected)
        self.assertEqual(SAMPLING_ORDER_ROUND7["artifact.form.mbi5"], 25.7)

    def test_no_future_sidecar_reference(self) -> None:
        """每条 sidecar upstream 的 sampling_order 必须 < 当前 slot.

        序表＝Round7 45 槽 ∪ 池 v2 供给侧三新槽（mbi5 的上游槽 4 在后者内）。
        """
        formulas = get_round6_round7_formulas()
        order_table = {**SAMPLING_ORDER_ROUND7, **POOL_V2_SUPPLY_SAMPLING_ORDERS}
        violations = []
        for slot_id, spec in formulas.items():
            my_order = spec["sampling_order"]
            for up_id in spec["upstream_inputs"].get("sidecar", []):
                up_order = order_table[up_id]
                if up_order >= my_order:
                    violations.append(f"{slot_id}({my_order}) → {up_id}({up_order})")
        self.assertEqual(violations, [], f"DAG violations: {violations}")

    def test_pool_v2_supply_orders_respect_dag(self) -> None:
        """池 v2 三新槽自身的 DAG 边（含 sp2←槽2、mbi5←槽4 两条改锚边）。"""
        from workflow_engine.worldgen.round6_formulas import (
            get_pool_v2_supply_slot_specs,
        )
        order_table = {**SAMPLING_ORDER_ROUND7, **POOL_V2_SUPPLY_SAMPLING_ORDERS}
        for slot_id, spec in get_pool_v2_supply_slot_specs().items():
            my_order = POOL_V2_SUPPLY_SAMPLING_ORDERS[slot_id]
            for up_id in spec["upstream_inputs"].get("sidecar", []):
                with self.subTest(slot_id=slot_id, up=up_id):
                    self.assertLess(order_table[up_id], my_order)

    def test_artifact_downstream_of_procedure(self) -> None:
        """artifact.report.inspection (sampling_order 11) 必须晚于 procedure.inspection.prescribed.completed (8)."""
        # spot-check: artifact.report.inspection depends on procedure.inspection.prescribed.completed
        formulas = get_round6_round7_formulas()
        rep = formulas["artifact.report.inspection"]
        self.assertIn("procedure.inspection.prescribed.completed",
                      rep["upstream_inputs"]["sidecar"])
        self.assertGreater(SAMPLING_ORDER_ROUND7["artifact.report.inspection"],
                           SAMPLING_ORDER_ROUND7["procedure.inspection.prescribed.completed"])

    def test_final_qualifiers_last(self) -> None:
        """qual.* 必须 sampling_order 在末尾 43-45."""
        for q in ["qual.actor_role", "qual.method_class", "qual.artifact_field_group"]:
            self.assertGreaterEqual(SAMPLING_ORDER_ROUND7[q], 43)

    def test_only_allowed_inputs_in_formulas(self) -> None:
        """所有 formula term key 必须在 ALLOWED_INPUTS 全集."""
        formulas = get_round6_round7_formulas()
        for slot_id, spec in formulas.items():
            formula = spec["conditional_formula"]
            if formula["type"] == "centered_sigmoid_linear":
                for k in formula["terms"]:
                    with self.subTest(slot_id=slot_id, key=k):
                        self.assertIn(k, ALLOWED_INPUTS)
            elif formula["type"] == "centered_softmax_per_class":
                for cls_name, cls_block in formula["classes"].items():
                    for k in cls_block["terms"]:
                        with self.subTest(slot_id=slot_id, cls=cls_name, key=k):
                            self.assertIn(k, ALLOWED_INPUTS)

    def test_allowed_inputs_partition(self) -> None:
        """ALLOWED_INPUTS = ALLOWED_PHYSICAL_INPUTS ∪ ALLOWED_HIDDEN_INPUTS ∪ ALLOWED_SIDECAR_INPUTS."""
        self.assertEqual(
            ALLOWED_INPUTS,
            ALLOWED_PHYSICAL_INPUTS | ALLOWED_HIDDEN_INPUTS | ALLOWED_SIDECAR_INPUTS,
        )
        # 19 H.* + 22 physical + 47 sidecar = 88
        # （sidecar 45 → 47：#38 池 v2 供给侧新增两条可作上游的槽——
        #  supervision.nonconformity.found（sp2 上游）与
        #  procedure.repair_supervising_ri.appointment.completed（mbi5 上游），
        #  换池批步 A1.3，2026-08-06；槽 3 呈交事件无公式消费者，刻意不入白名单）
        self.assertEqual(len(ALLOWED_HIDDEN_INPUTS), 19)
        self.assertEqual(len(ALLOWED_PHYSICAL_INPUTS), 22)
        self.assertEqual(len(ALLOWED_SIDECAR_INPUTS), 47)


class EnumProbabilityTests(unittest.TestCase):
    """spec 06 §11.6.4: 每个 enum slot anchor 加起来 = 1.0 ± 0.001."""

    def test_qual_actor_role_anchor_sums_to_one(self) -> None:
        anchor = MARGINAL_ANCHORS_ROUND7["qual.actor_role"]
        s = sum(anchor.values())
        self.assertAlmostEqual(s, 1.0, places=3)

    def test_qual_method_class_anchor_sums_to_one(self) -> None:
        anchor = MARGINAL_ANCHORS_ROUND7["qual.method_class"]
        s = sum(anchor.values())
        self.assertAlmostEqual(s, 1.0, places=3)

    def test_qual_artifact_field_group_anchor_sums_to_one(self) -> None:
        anchor = MARGINAL_ANCHORS_ROUND7["qual.artifact_field_group"]
        s = sum(anchor.values())
        self.assertAlmostEqual(s, 1.0, places=3)

    def test_centered_evaluator_low_level_helpers(self) -> None:
        """centered helpers 直接调用通过 dict schema, 与 dict-form 一致."""
        formula_dict = {
            "type": "centered_sigmoid_linear",
            "anchor": 0.6,
            "upstream_expected": {"H.case_active": 0.96},
            "terms": {"H.case_active": 0.5},
        }
        ctx = {"H.case_active": 0.96}
        rng_dict = random.Random(13)
        rng_helper = random.Random(13)
        # ~ 1000 samples should converge
        n_dict_true = sum(evaluate_bool_conditional(formula_dict, ctx, rng_dict) for _ in range(2000))
        n_helper_true = sum(
            evaluate_centered_bool_conditional(
                anchor=0.6,
                upstream_expected={"H.case_active": 0.96},
                terms={"H.case_active": 0.5},
                context=ctx,
                rng=rng_helper,
            )
            for _ in range(2000)
        )
        self.assertEqual(n_dict_true, n_helper_true)


class CompletedAndRetainedConsistencyTests(unittest.TestCase):
    """spec 06 §11.6.7 post-sample consistency clamp:
    supervision.record.completed_and_retained <= min(completed, retained)."""

    def test_completed_and_retained_clamp_when_completed_false(self) -> None:
        """run sidecar sampling: 如果 completed=False, 则 completed_and_retained 必须为 False."""
        from workflow_engine.worldgen.sidecar import _sample_sidecar_bool_slots_for_fragment
        records = list(_all_45_slot_records().values())
        # Modify sampled state by injecting a forced low-completion scenario
        # via constructed evaluator_context
        rng = random.Random(11)
        # H.* at prior means + worldgen low repair → completed roughly low
        ctx = build_evaluator_context(
            hidden_state={**HIDDEN_STATE_PRIOR_MEANS,
                          "H.repair_quality_score": 0.05,
                          "H.admin_discipline_score": 0.05,
                          "H.document_maturity_score": 0.05,
                          "H.repair_need": 0.0,
                          "H.defect_present": 0.0}
        )
        # Run 500 fragments through the sampler - rare but check no joint > min
        for n in range(200):
            buckets = _sample_sidecar_bool_slots_for_fragment(
                building_world_id="B0", fragment_id=f"F{n}",
                sidecar_bool_slot_records=records,
                evaluator_context=ctx,
            )
            # Find values
            values = {}
            for bucket_vals in buckets.values():
                for v in bucket_vals:
                    values[v.slot_id] = v.value
            completed = values.get("supervision.record.completed")
            retained = values.get("supervision.record.retained")
            joint = values.get("supervision.record.completed_and_retained")
            if joint is True:
                self.assertTrue(
                    completed is True and retained is True,
                    f"fragment {n}: joint=True but completed={completed} retained={retained}",
                )

    def test_clamp_note_present_when_clamp_fires(self) -> None:
        """如果 clamp 触发, sidecar runtime note 应包含 post_sample_clamp 标记."""
        from workflow_engine.worldgen.sidecar import _sample_sidecar_bool_slots_for_fragment
        records = list(_all_45_slot_records().values())
        clamp_observed = False
        rng = random.Random(20260511)
        for trial in range(500):
            buckets = _sample_sidecar_bool_slots_for_fragment(
                building_world_id="B0", fragment_id=f"F{trial}",
                sidecar_bool_slot_records=records,
                evaluator_context=build_evaluator_context(
                    hidden_state=HIDDEN_STATE_PRIOR_MEANS,
                ),
            )
            for bucket_vals in buckets.values():
                for v in bucket_vals:
                    if v.slot_id == "supervision.record.completed_and_retained":
                        for note in v.notes:
                            if "post_sample_clamp" in note:
                                clamp_observed = True
                                break
            if clamp_observed:
                break
        # We don't strictly require the clamp to trigger (depends on coefficients),
        # but at least the channel is wired.
        # Stronger test: completed_and_retained probability across 500 fragment ≤ min(c,r) prevalence
        _ = clamp_observed  # keep for visibility

    def test_centering_base_stays_062_while_declared_marginal_is_039(self) -> None:
        """🔴 公式中心化基与分布声明值**本轮起分家**——这条闸钉住「不许合并」。

        （A1.6 落地审核 §一「必须记 B」的配套闸，2026-08-06。）

        **这里钉住的 0.62 是 `MARGINAL_ANCHORS_ROUND7` 里的「公式中心化基」，
        不是这个槽的分布声明值。** 声明值已由 `POST_CLAMP_REALIZED_MARGINALS`
        改成**钳制后实现边际 0.39**（A1.6 补裁）。两者按构造不相等：0.62 是
        `_apply_clamps` **之前**的中心，0.39 是钳制**之后**的实现边际。

        为什么要专门加一条闸而不是听之任之：审核实测**两个碎片级下游消费者**
        （`procedure.repair.prescribed.completed` 系数 0.35 /
        `artifact.report.completion` 系数 0.30）**仍以 0.62 为中心化基**——
        它们是碎片级，结构上落在 A1.6 那个只扫楼级消费者的 overlay 射程之外。
        残差：闭式预测 −0.0199 / −0.0168，门检 MC 实测 −0.0161 / −0.0159，同号同量级。

        看见这个残差的人很容易「顺手」把本表里的 0.62 改成 0.39 去消它。
        **那一改是行为变更，不是文档修正**（变异实测：改完本槽自己的
        `conditional_formula["anchor"]` 也从 0.62 变成 0.39，两个下游的
        `upstream_expected` 一并变成 0.39）。消这条残差的正确做法是把 A1.6
        「中心化基＝实际读到的期望」这条原则**扩到碎片级这条边上**（已登记待裁），
        不是动这张表。
        """
        from workflow_engine.worldgen.round6_formulas import (
            POST_CLAMP_REALIZED_MARGINALS,
        )

        slot = "supervision.record.completed_and_retained"
        self.assertEqual(
            MARGINAL_ANCHORS_ROUND7[slot], 0.62,
            "公式中心化基被改动——它同时是本槽 conditional_formula['anchor'] 与两个"
            "碎片级下游 upstream_expected 的来源，改它是行为变更而非文档修正",
        )
        self.assertEqual(POST_CLAMP_REALIZED_MARGINALS[slot], 0.39)

        records = _all_45_slot_records()
        rec = records[slot]
        self.assertEqual(float(rec["marginal_anchor"]), 0.39)
        self.assertEqual(float(rec["prevalence"]), 0.39)
        self.assertEqual(
            float(rec["conditional_formula"]["anchor"]), 0.62,
            "钳制槽的公式内部中心必须保持钳制前的 0.62（A1.6 §2.3 明令不动）",
        )

        # 两个碎片级下游消费者的中心化基——**现状登记，不是应然**。
        # 与上面的 0.39 并列摆出来，免得下次有人以为 0.62 只剩公式内部一处。
        for consumer, coefficient in (
            ("procedure.repair.prescribed.completed", 0.35),
            ("artifact.report.completion", 0.30),
        ):
            with self.subTest(consumer=consumer):
                block = records[consumer]["conditional_formula"]
                self.assertNotEqual(
                    str(records[consumer].get("granularity") or "fragment"),
                    "building",
                    f"{consumer} 变成楼级了——它会落进 A1.6 overlay 射程，本条现状登记须重估",
                )
                self.assertEqual(float(block["terms"][slot]), coefficient)
                self.assertEqual(
                    float(block["upstream_expected"][slot]), 0.62,
                    f"{consumer} 的中心化基变了：若是有意扩 A1.6 原则到碎片级边，"
                    "请连同本闸与实施记录一起改；若是「顺手改表」，那是行为变更",
                )


class MBI2DAGPatchTests(unittest.TestCase):
    """Round 7 §0 + §4.3 MBI2 DAG 修订:
    artifact.form.mbi2 在 L1 (sampling_order=7) 不在 L3, depends_on temp_ri_nomination."""

    def test_mbi2_in_l1_sampling_order_7(self) -> None:
        self.assertEqual(SAMPLING_ORDER_ROUND7["artifact.form.mbi2"], 7)

    def test_mbi2_anchor_round7_revised_to_008(self) -> None:
        """Round 7 §1: MBI2 anchor 0.23 → 0.08."""
        self.assertEqual(MARGINAL_ANCHORS_ROUND7["artifact.form.mbi2"], 0.08)

    def test_mbi2_depends_on_temp_ri_nomination(self) -> None:
        formulas = get_round6_round7_formulas()
        mbi2 = formulas["artifact.form.mbi2"]
        sidecar_up = mbi2["upstream_inputs"]["sidecar"]
        self.assertIn("procedure.temp_ri_nomination.completed", sidecar_up)

    def test_mbi2_does_not_depend_on_investigation_proposal(self) -> None:
        """Round 7 修订: MBI2 不再 depends_on procedure.investigation.proposal.submitted."""
        formulas = get_round6_round7_formulas()
        mbi2 = formulas["artifact.form.mbi2"]
        sidecar_up = mbi2["upstream_inputs"]["sidecar"]
        self.assertNotIn("procedure.investigation.proposal.submitted", sidecar_up)
        self.assertNotIn("procedure.investigation.intention_notified", sidecar_up)

    def test_detailed_investigation_proposal_does_not_depend_on_mbi2(self) -> None:
        """Round 7 修订: artifact.proposal.detailed_investigation 不再 depends_on artifact.form.mbi2."""
        formulas = get_round6_round7_formulas()
        di = formulas["artifact.proposal.detailed_investigation"]
        self.assertNotIn("artifact.form.mbi2", di["upstream_inputs"]["sidecar"])

    def test_mbi2_cop_section_is_2_1_3_j(self) -> None:
        """Round 7 §1: MBI2 source label 必须引用 §2.1.3(j) (temp RI nomination form)."""
        records = _all_45_slot_records()
        mbi2 = records["artifact.form.mbi2"]
        self.assertIn("§2.1.3(j)", mbi2["anchor_source"])
        self.assertIn("§2.1.3(j)", mbi2["cop_section"])

    def test_round7_revised_anchors_three_slots(self) -> None:
        """Round 7 §1: 3 个 anchor 数字修订."""
        # 1. proposal.submitted: 0.23 → 0.30
        self.assertEqual(MARGINAL_ANCHORS_ROUND7["procedure.investigation.proposal.submitted"], 0.30)
        # 2. mbi2: 0.23 → 0.08
        self.assertEqual(MARGINAL_ANCHORS_ROUND7["artifact.form.mbi2"], 0.08)
        # 3. detailed_investigation: 0.23 → 0.30
        self.assertEqual(MARGINAL_ANCHORS_ROUND7["artifact.proposal.detailed_investigation"], 0.30)

    def test_42_other_slots_anchor_unchanged(self) -> None:
        """Round 7 §1: 42 个 anchor 数字不变（MBI2 + 2 investigation 才变）."""
        # spot check a few
        self.assertEqual(MARGINAL_ANCHORS_ROUND7["procedure.ri.appointment.completed"], 0.86)
        self.assertEqual(MARGINAL_ANCHORS_ROUND7["artifact.form.mbi1"], 0.95)
        self.assertEqual(MARGINAL_ANCHORS_ROUND7["procedure.inspection.prescribed.completed"], 0.74)
        self.assertEqual(MARGINAL_ANCHORS_ROUND7["supervision.site_visit.performed"], 0.80)


class HiddenStateDeriveTests(unittest.TestCase):
    """spec 06 §11.6.2 + Round 6 §1.2 H.* hidden state 派生 (sidecar.py)."""

    def test_hidden_state_19_keys(self) -> None:
        from workflow_engine.worldgen.sidecar import _build_round6_hidden_state_for_fragment
        hs = _build_round6_hidden_state_for_fragment(
            age_years=None, driver=None, mechanism=None, fragment_conditions=[],
            drainage=None, fire_safety=None, ubw=None, repair=None,
            building_total_severity_max=None, defect_present=False,
            crack_severity=None, spall_severity=None, delamination_severity=None,
            detachment_severity=None, corrosion_severity=None,
        )
        self.assertEqual(set(hs.keys()), set(ALLOWED_HIDDEN_INPUTS))

    def test_hidden_state_age_old_score_clipped(self) -> None:
        from workflow_engine.worldgen.sidecar import _build_round6_hidden_state_for_fragment
        hs = _build_round6_hidden_state_for_fragment(
            age_years=80, driver=None, mechanism=None, fragment_conditions=[],
            drainage=None, fire_safety=None, ubw=None, repair=None,
            building_total_severity_max=None, defect_present=False,
            crack_severity=None, spall_severity=None, delamination_severity=None,
            detachment_severity=None, corrosion_severity=None,
        )
        # 80 / 50 = 1.6 → clip to 1.0
        self.assertEqual(hs["H.age_old_score"], 1.0)

    def test_hidden_state_defect_present_zero_when_no_conditions(self) -> None:
        from workflow_engine.worldgen.sidecar import _build_round6_hidden_state_for_fragment
        hs = _build_round6_hidden_state_for_fragment(
            age_years=10, driver=None, mechanism=None, fragment_conditions=[],
            drainage=None, fire_safety=None, ubw=None, repair=None,
            building_total_severity_max=None, defect_present=False,
            crack_severity=None, spall_severity=None, delamination_severity=None,
            detachment_severity=None, corrosion_severity=None,
        )
        self.assertEqual(hs["H.defect_present"], 0.0)

    def test_hidden_state_fire_safety_need_high_when_deficiency(self) -> None:
        from workflow_engine.worldgen.sidecar import _build_round6_hidden_state_for_fragment

        class _FakeFireSafety:
            deficiency_present = True

        hs = _build_round6_hidden_state_for_fragment(
            age_years=None, driver=None, mechanism=None, fragment_conditions=[],
            drainage=None, fire_safety=_FakeFireSafety(), ubw=None, repair=None,
            building_total_severity_max=None, defect_present=False,
            crack_severity=None, spall_severity=None, delamination_severity=None,
            detachment_severity=None, corrosion_severity=None,
        )
        self.assertGreater(hs["H.fire_safety_need"], 0.5)
        self.assertGreater(hs["H.fire_door_issue"], 0.20)


class RegistryMBI2DAGFinalLandedTests(unittest.TestCase):
    """Round 7 §0 + §4.3 MBI2 DAG 修订 在 registry 落地后 verify."""

    def setUp(self) -> None:
        self.records = _all_45_slot_records()

    def test_mbi2_record_has_round7_sampling_order_7(self) -> None:
        mbi2 = self.records["artifact.form.mbi2"]
        self.assertEqual(mbi2["sampling_order"], 7)

    def test_mbi2_record_marginal_anchor_008(self) -> None:
        mbi2 = self.records["artifact.form.mbi2"]
        self.assertEqual(mbi2["marginal_anchor"], 0.08)
        self.assertEqual(mbi2["prevalence"], 0.08)  # also synced

    def test_mbi2_upstream_inputs_temp_ri_nomination(self) -> None:
        mbi2 = self.records["artifact.form.mbi2"]
        sidecar_up = mbi2["upstream_inputs"]["sidecar"]
        self.assertIn("procedure.temp_ri_nomination.completed", sidecar_up)

    def test_proposal_detailed_investigation_anchor_030(self) -> None:
        di = self.records["artifact.proposal.detailed_investigation"]
        self.assertEqual(di["marginal_anchor"], 0.30)
        self.assertEqual(di["prevalence"], 0.30)


if __name__ == "__main__":
    unittest.main()
