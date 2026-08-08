"""`--step bundle` 粒度感知细尺的形状回归与变异测试（R1 repo 化，2026-08-06）。

末尾另含 `--step poolv2` 新步键的量具测试（官方线步 A 审核 M1，2026-08-06）：
B2 旧池配对专用尺——bundle 允许集 ∪ 三新槽纯追加 ∪ {mbi5, sp2} DAG 下游闭包值漂。

两层来源，两类测试：

1. **R1 归档产物形状回归**（夹具＝`杂物箱/备份_R1配对_20260806/产物留档/` 的留档
   JSON，归档缺席时跳过并说明）：把 repo 化细尺的冻结判据常量钉到 R1 实跑读数上
   ——R1 判据②细尺 0 失败、①ba 行一致、④合成对账 0/0、⑤ 130/130，且 R1 位移里
   实际出现的锚点槽必须落在本尺写死的 10 槽清单内。防的是「repo 化时抄错判据集」
   （细尺是换池验收的量具，量具错了红绿都不可信）。

2. **细尺本体的绿/红对照**（夹具＝按预登记改动形状合成的最小两世界池表）：
   - 绿：捆绑三件合并态（乙12 塌缩＋期限锚十槽＋#29 轴积）恰好按预登记形状变
     ⇒ 0 失败；
   - 红（变异一条）：在候选侧**伪造一行位移**（改一条保留行的值）⇒ 必须红。
     只有一个候选时「量对」与「量错」不可分——变异臂是细尺自身的反向验证
     （期限锚案「老单测只喂一条事实抓不到任取」的教训搬到量具上）。

⚠️ 本文件只测边界层（细尺答「哪里可以红」）；楼级锚点行的值对不对由
`test_deadline_anchor_emission.py` 语义层承担，两层缺一即漏（1b 先例同款分工）。
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

_AGENT_V1 = Path(__file__).resolve().parents[4]
_SCRIPTS = _AGENT_V1 / "scripts"
_REPO = _AGENT_V1.parent
_R1_ARCHIVE = _REPO / "杂物箱" / "备份_R1配对_20260806" / "产物留档"

if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

vp = importlib.import_module("verify_rng_isolation_pairing")

_WORLDS = ("WB-T-PAIRTEST-0000-S00301", "WB-T-PAIRTEST-0001-S00301")
_COLLAPSED = sorted(vp._BUNDLE_COLLAPSED_SLOTS)
_ANCHORS = sorted(vp._BUNDLE_ANCHOR_SLOTS)
_AXIS_SLOT = "reporting.record.submitted"


# ---------------------------------------------------------------------------
# 合成夹具：按预登记改动形状构造 base / cand 两侧的 entries + records
# ---------------------------------------------------------------------------
def _entry(runtime_id, seq_no, entry_type, slot_id, value_json,
           qualifiers, time_anchor_key=None, unit=None):
    return {
        "runtime_id": runtime_id,
        "seq_no": seq_no,
        "entry_type": entry_type,
        "slot_id": slot_id,
        "value_json": value_json,
        "unit": unit,
        "qualifiers_json": json.dumps(qualifiers, sort_keys=True,
                                      ensure_ascii=False),
        "time_anchor_key": time_anchor_key,
        "source_refs": [runtime_id],
        "notes": ["pairing bundle ruler fixture"],
    }


def _build_fixture():
    """返回 (base_entries, cand_entries, base_records, cand_records)。

    base＝捆绑前旧池形：每世界 4 个碎片 runtime，塌缩槽每碎片各 1 行
    （合计 8 行/栋，落在 kimi §8.3-5 的「7-8 行/栋」尺度）＋若干与本案无关的
    保留行；无期限锚楼级行、无轴积槽行。
    cand＝捆绑后新池形：塌缩槽碎片行消失；每世界 10 个锚点槽各恰 1 条楼级行
    （带 time_anchor_key）；轴积槽 ba+bd 两格（槽整体新增）；保留行内容逐列
    相同但 seq_no 因插行位移（细尺必须容忍位移、拒绝重排）。
    """
    base_rows, cand_rows, records = [], [], []
    for world in _WORLDS:
        bldg = f"SCR-BLDG-{world}"
        frags = [f"SCR-FRG-{world}-MEMBER-{i:02d}" for i in range(4)]
        for rt in [bldg] + frags:
            records.append({"seq_no": len(records), "runtime_id": rt,
                            "world_id": world, "projection_id": "",
                            "interface_ids": []})

        # --- 楼级 runtime：与本案无关的保留行（procedure + artifact 两桶） ---
        keep_bldg = [
            _entry(bldg, 0, "procedure_gate_state", "investigation.started",
                   "true", {"carrier_domain": "procedure",
                            "granularity": "building"}),
            _entry(bldg, 1, "procedure_gate_state",
                   "repair.prescribed.completed", "false",
                   {"carrier_domain": "procedure", "granularity": "building"}),
            _entry(bldg, 0, "artifact_requirement_state",
                   "artifact.inspection_report", "true",
                   {"carrier_domain": "artifact", "granularity": "building",
                    "artifact_key": "report.inspection"}),
        ]
        base_rows.extend(keep_bldg)

        # --- 碎片 runtime：塌缩槽行（撤）＋保留行（facts / procedure 两桶） ---
        for i, rt in enumerate(frags):
            frag_q = {"fragment_id": rt.replace("SCR-", ""),
                      "carrier_domain": "procedure"}
            for j, slot in enumerate(_COLLAPSED):
                base_rows.append(_entry(rt, 3 + j, "procedure_gate_state",
                                        slot, str(float(i + j)), frag_q,
                                        unit="day"))
            keep_frag = [
                _entry(rt, 0, "facts", "defect.hollowing.ratio",
                       f"0.1{i}", {"fragment_id": frag_q["fragment_id"]}),
                _entry(rt, 5, "procedure_gate_state",
                       "inspection.access.granted", "true", frag_q),
                _entry(rt, 6, "procedure_gate_state",
                       "inspection.scaffold.erected", "false", frag_q),
            ]
            base_rows.extend(keep_frag)
            # 候选侧：塌缩槽行消失，保留行 seq_no 因撤行前移（相对序保持）
            for r in keep_frag:
                r2 = dict(r)
                if r2["entry_type"] == "procedure_gate_state":
                    r2 = dict(r2, seq_no=r2["seq_no"] - 3)
                cand_rows.append(r2)

        # 候选侧楼级 runtime：保留行 seq_no 位移（procedure 桶被锚点行顶后）
        for r in keep_bldg:
            r2 = dict(r)
            if r2["entry_type"] == "procedure_gate_state":
                r2 = dict(r2, seq_no=r2["seq_no"] + 10)
            if r2["entry_type"] == "artifact_requirement_state":
                r2 = dict(r2, seq_no=r2["seq_no"] + 2)
            cand_rows.append(r2)
        # 候选侧：期限锚十槽恰 1 行（楼级、带锚点键）
        for j, slot in enumerate(_ANCHORS):
            cand_rows.append(_entry(
                bldg, j, "procedure_gate_state", slot, str(float(j)),
                {"carrier_domain": "procedure", "granularity": "building"},
                time_anchor_key=f"anchor.{slot}", unit="day"))
        # 候选侧：轴积槽 ba＋bd 两格（基线整槽缺席＝纯追加）
        for j, role in enumerate(("ba", "bd")):
            cand_rows.append(_entry(
                bldg, j, "artifact_requirement_state", _AXIS_SLOT, "true",
                {"carrier_domain": "artifact", "granularity": "building",
                 "artifact_key": "record.inspection_log",
                 "actor_role_key": role}))

    rec = pd.DataFrame(records)
    return (pd.DataFrame(base_rows), pd.DataFrame(cand_rows), rec, rec.copy())


# ---------------------------------------------------------------------------
# 判据常量与登记形状
# ---------------------------------------------------------------------------
class TestBundleStepRegistration:
    def test_bundle_registered_with_deadline_shape(self):
        """bundle 步在 STEP_ALLOWED_CHANGE 里，整表级 allowed 集与 deadline 同形。"""
        assert "bundle" in vp.STEP_ALLOWED_CHANGE
        assert set(vp.STEP_ALLOWED_CHANGE["bundle"]) == set(
            vp.STEP_ALLOWED_CHANGE["deadline"]
        ) == {"world.meta", "sidecar.entries", "proj.cohort_manifest"}

    def test_frozen_slot_lists(self):
        """判据常量：塌缩槽＝deadline 回填白名单同两槽；锚点槽恰 10 且含塌缩槽。"""
        assert vp._BUNDLE_COLLAPSED_SLOTS == vp._DEADLINE_BACKFILL_SLOTS
        assert len(vp._BUNDLE_ANCHOR_SLOTS) == 10
        assert vp._BUNDLE_COLLAPSED_SLOTS <= vp._BUNDLE_ANCHOR_SLOTS
        assert vp._BUNDLE_AXIS_SLOTS == {"reporting.record.submitted"}

    def test_anchor_list_matches_registry(self):
        """写死清单与权威注册表现算值逐字相同（失配＝改动出了预登记范围）。"""
        from workflow_engine.worldgen.sidecar import (
            _deadline_anchor_duration_slots,
        )
        assert set(_deadline_anchor_duration_slots()) == set(
            vp._BUNDLE_ANCHOR_SLOTS
        )


# ---------------------------------------------------------------------------
# R1 归档产物形状回归（留档 JSON 当夹具；归档缺席即跳过）
# ---------------------------------------------------------------------------
class TestR1ArchiveShapeRegression:
    @pytest.fixture(scope="class")
    def r1_full(self):
        path = _R1_ARCHIVE / "r1_full.json"
        if not path.exists():
            pytest.skip(f"R1 归档不在盘（{path}）——归档是 gitignore 的本机留档")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_r1_criteria_readings(self, r1_full):
        """R1 实跑读数原样：50/50 栋、②细尺 0 失败、①一致、④ 0/0、d29 射程外 0。"""
        ok = [b for b in r1_full["buildings"] if "error" not in b]
        assert len(ok) == 50
        assert r1_full["criterion2_failures"] == []
        assert r1_full["criterion1_ba_row_mismatch"] == []
        assert sum(b["interaction_overlap"] for b in ok) == 0
        assert sum(b["compose_fail"] for b in ok) == 0
        assert r1_full["totals"]["d29_scope"].get("out_scope", 0) == 0

    def test_r1_anchor_slots_within_frozen_list(self, r1_full):
        """R1 位移里实际出现的 duration 锚点槽 ⊆ 本尺写死的 10 槽清单且非空。"""
        seen = set()
        for b in r1_full["buildings"]:
            for rec in b.get("dC_rows", []):
                _typ, a, c, _card, _kind = rec["row"]
                for state in (a, c):
                    if state is None:
                        continue
                    seen.update(s for s in json.loads(state[4])
                                if s.startswith("duration."))
        assert seen, "归档里应有 duration 锚点槽出现（R1 dC=1,088 非空）"
        assert seen <= set(vp._BUNDLE_ANCHOR_SLOTS), (
            f"归档出现了清单外的锚点槽：{seen - set(vp._BUNDLE_ANCHOR_SLOTS)}"
        )

    def test_r1_criterion5_all_worlds(self):
        """判据⑤留档：两池 50/50＋wave1 键稳 30/30（ba 格「同键⇒值不变」）。"""
        path = _R1_ARCHIVE / "r1_criterion5.json"
        if not path.exists():
            pytest.skip(f"R1 归档不在盘（{path}）")
        c5 = json.loads(path.read_text(encoding="utf-8"))
        for key in ("reanchor", "fragcov2", "wave1_key_stability"):
            assert c5[key]["same"] == c5[key]["n"], key


# ---------------------------------------------------------------------------
# 细尺本体：绿（R1 形状）／红（变异一条：伪造一行位移）
# ---------------------------------------------------------------------------
class TestBundleRulerOnSyntheticShape:
    def test_green_on_preregistered_shape(self):
        base, cand, brec, crec = _build_fixture()
        failures, info = vp._verify_bundle_sidecar_delta(base, cand, brec, crec)
        assert failures == [], failures
        text = "\n".join(info)
        # 读数形状：2 世界 × 2 塌缩槽 = 4 组，撤 16 条碎片行（8 行/栋）
        assert "撤碎片行 16 条" in text and "4 个（世界,槽）组" in text
        assert "归约失败 0 组" in text
        # 十槽恰 1 行：2 世界 × 10 槽 = 20 条楼级锚点行
        assert "合计 20 行" in text and "十槽恰 1 行破 0 处" in text
        # 轴积两格各 2 行（槽整体新增＝纯追加）
        assert "'ba': 2" in text and "'bd': 2" in text
        assert "内容零漂移、行序保持" in text

    def test_mutation_forged_row_displacement_is_red(self):
        """变异臂：候选侧伪造一行位移（改一条保留行的值）⇒ 细尺必须红。"""
        base, cand, brec, crec = _build_fixture()
        mask = (cand["slot_id"] == "defect.hollowing.ratio") & (
            cand["runtime_id"] == f"SCR-FRG-{_WORLDS[0]}-MEMBER-00")
        assert int(mask.sum()) == 1
        cand.loc[mask, "value_json"] = "0.99"
        failures, _info = vp._verify_bundle_sidecar_delta(base, cand, brec, crec)
        assert failures, "伪造一行位移未被细尺抓住（细尺失明）"
        assert any("随机流被搅动" in f for f in failures), failures


# ---------------------------------------------------------------------------
# main() 级端到端：整表二分那一路（换池批步 A1.2 验收补测，2026-08-06）
# ---------------------------------------------------------------------------
class TestBundleMainBisection:
    """M11 验收的两条在 main() 级别钉死：

    - 绿臂：捆绑后世界按预登记形状变 ⇒ `--step bundle` 退 0（「不再按构造必红」
      的端到端证据——此前只有细尺函数级绿臂）；
    - 红臂：**非放行单元**（`world.measurements`）变一格 ⇒ 整表二分（main :1059-1064）
      判 FAIL 退 1（「其余单元变仍会红」——此前该路只被 allowed 集静态断言间接钉住）。
    """

    @staticmethod
    def _fake_pool_cls(mutate_measurements: bool):
        base_e, cand_e, brec, crec = _build_fixture()
        meas = pd.DataFrame([
            {"world_id": w, "measure_key": "crack.width.max", "value": 0.3}
            for w in _WORLDS
        ])
        meas_cand = meas.copy()
        if mutate_measurements:
            meas_cand.loc[0, "value"] = 0.9

        class _FakePool:
            def __init__(self, root):
                is_base = str(root).endswith("base")
                self.root = root
                self.units = {
                    "sidecar.entries": base_e if is_base else cand_e,
                    "sidecar.records": brec if is_base else crec,
                    "world.measurements": meas if is_base else meas_cand,
                }

            def anchors(self):
                return {"dir": str(self.root)}

            def limit_worlds(self, n):  # pragma: no cover - 本测不截栋
                pass

        return _FakePool

    def _run_main(self, monkeypatch, mutate: bool):
        monkeypatch.setattr(vp, "Pool", self._fake_pool_cls(mutate))
        return vp.main([
            "--baseline", "base", "--candidate", "cand", "--step", "bundle",
            "--pool-seed", "301", "--pool-count", "2", "--ctcov", "on",
        ])

    def test_main_green_on_preregistered_shape(self, monkeypatch, capsys):
        rc = self._run_main(monkeypatch, mutate=False)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "[PASS] 本步字节锚全过" in out

    def test_main_nonallowed_unit_mutation_is_red(self, monkeypatch, capsys):
        rc = self._run_main(monkeypatch, mutate=True)
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "world.measurements" in out
        assert "本不该变却变了" in out


# ===========================================================================
# `--step poolv2` 新步键（官方线步 A 审核 M1，2026-08-06）
# ===========================================================================
# B2 拿旧池（步 A 前）对「步 A 后代码态再生池」配对时，bundle 尺按构造必红：
# ①三新槽新增行会记 illegal_added；②mbi5/sp2 公式已改——1a-i′ 键控子流保
# 同 (world,slot) 抽签不变而概率变，抽签落在新旧概率区间之间的行值必翻，
# 且翻转沿构造期 DAG 级联（sp2→revision_required→下游），全落进判据④射程。
# poolv2 允许集＝bundle 四判据 ∪ ⑤三新槽整槽纯追加 ∪ ⑥闭包槽值漂
# （行在、锚点列/结构列不变、仅值列许翻）。清单外任何值漂照④红。

_POOLV2_DRIFT_BLDG_SLOT = "artifact.form.mbi5"            # 闭包种子（楼级形夹具）
_POOLV2_DRIFT_FRAG_SLOT = "procedure.repair.revision_required"  # 级联下游（碎片形夹具）


def _build_poolv2_fixture():
    """bundle 夹具＋poolv2 增量形状：

    - 值漂臂：每世界 2 条闭包槽保留行（mbi5 楼级形＋revision_required 碎片形），
      基线在场、候选同键行**只翻 value_json**（锚点列/结构列逐字节同）；
    - 纯追加臂：候选每世界加三新槽行（槽 2 碎片形、槽 3/槽 4 楼级形），
      基线整槽缺席。
    """
    base, cand, brec, crec = _build_fixture()
    base_extra, cand_extra = [], []
    for world in _WORLDS:
        bldg = f"SCR-BLDG-{world}"
        frag0 = f"SCR-FRG-{world}-MEMBER-00"
        drift_rows = [
            _entry(bldg, 20, "artifact_requirement_state",
                   _POOLV2_DRIFT_BLDG_SLOT, "false",
                   {"carrier_domain": "artifact", "granularity": "building",
                    "artifact_key": "form.mbi5"}),
            _entry(frag0, 20, "procedure_gate_state",
                   _POOLV2_DRIFT_FRAG_SLOT, "false",
                   {"fragment_id": frag0.replace("SCR-", ""),
                    "carrier_domain": "procedure"}),
        ]
        base_extra.extend(drift_rows)
        cand_extra.extend(dict(r, value_json="true") for r in drift_rows)
        # 三新槽（基线整槽缺席 ⇒ 纯追加）
        cand_extra.append(_entry(
            frag0, 30, "supervision_observation",
            "supervision.nonconformity.found", "true",
            {"fragment_id": frag0.replace("SCR-", ""),
             "carrier_domain": "supervision"}))
        cand_extra.append(_entry(
            bldg, 30, "procedure_gate_state",
            "procedure.repair.revision_proposal.submitted_to_ba", "false",
            {"carrier_domain": "procedure", "granularity": "building"}))
        cand_extra.append(_entry(
            bldg, 31, "procedure_gate_state",
            "procedure.repair_supervising_ri.appointment.completed", "true",
            {"carrier_domain": "procedure", "granularity": "building"}))
    base = pd.concat([base, pd.DataFrame(base_extra)], ignore_index=True)
    cand = pd.concat([cand, pd.DataFrame(cand_extra)], ignore_index=True)
    return base, cand, brec, crec


def _poolv2_verify(base, cand, brec, crec):
    return vp._verify_bundle_sidecar_delta(
        base, cand, brec, crec,
        drift_value_slots=vp._POOLV2_FORMULA_DRIFT_SLOTS,
        new_append_slots=vp._POOLV2_NEW_SUPPLY_SLOTS,
        step_label="poolv2",
    )


class TestPoolV2StepRegistration:
    def test_poolv2_registered_with_bundle_shape(self):
        """poolv2 在 STEP_ALLOWED_CHANGE 里，整表级 allowed 集与 bundle 同形。"""
        assert "poolv2" in vp.STEP_ALLOWED_CHANGE
        assert set(vp.STEP_ALLOWED_CHANGE["poolv2"]) == set(
            vp.STEP_ALLOWED_CHANGE["bundle"]
        ) == {"world.meta", "sidecar.entries", "proj.cohort_manifest"}

    def test_frozen_new_supply_slots(self):
        """三新槽清单＝#38 G 组三记录；与值漂清单交集恰槽 3（它真在 sp2 下游）。"""
        assert vp._POOLV2_NEW_SUPPLY_SLOTS == {
            "supervision.nonconformity.found",
            "procedure.repair.revision_proposal.submitted_to_ba",
            "procedure.repair_supervising_ri.appointment.completed",
        }
        assert (vp._POOLV2_NEW_SUPPLY_SLOTS & vp._POOLV2_FORMULA_DRIFT_SLOTS
                ) == {"procedure.repair.revision_proposal.submitted_to_ba"}

    def test_drift_closure_matches_registry_dag(self):
        """写死的 13 槽清单 == 构造期 DAG 现算 {mbi5, sp2} 下游闭包（含种子）。

        边定义与生产 `_validate_sidecar_sampling_dag` 同源（conditional_inputs
        里凡属 sidecar_bool_slot_registry 的槽即一条边）。失配＝公式又动了：
        必须重算清单、重过审核门＋预登记（量具先于被量物），不许改断言了事。
        同时机器验证「三新槽下游 ∖ 闭包 ＝ ∅」——种子 {mbi5, sp2} 足够。
        """
        from workflow_engine.worldgen.registry import _build_registry_bundle

        bundle = _build_registry_bundle()
        order_by_slot, edges = {}, {}
        records = [
            record
            for registry in bundle.registries
            if registry.registry_id == "sidecar_bool_slot_registry"
            for record in registry.records
            if record.get("slot_id")
        ]
        for record in records:
            order_by_slot[str(record["slot_id"])] = record.get("sampling_order")
        for record in records:
            if record.get("conditional_formula") is None:
                continue
            for up in record.get("conditional_inputs") or []:
                if up in order_by_slot:
                    edges.setdefault(str(up), set()).add(str(record["slot_id"]))

        def closure(seeds):
            seen, stack = set(seeds), list(seeds)
            while stack:
                for nxt in edges.get(stack.pop(), ()):
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            return seen

        seeds = {"artifact.form.mbi5", "artifact.record.nonconformity_sp2"}
        assert closure(seeds) == set(vp._POOLV2_FORMULA_DRIFT_SLOTS)
        assert len(vp._POOLV2_FORMULA_DRIFT_SLOTS) == 13
        # 三新槽全部在注册表在场，且其下游不超出 {mbi5, sp2} 闭包
        assert vp._POOLV2_NEW_SUPPLY_SLOTS <= set(order_by_slot)
        extra = closure(set(vp._POOLV2_NEW_SUPPLY_SLOTS)) - set(
            vp._POOLV2_NEW_SUPPLY_SLOTS) - closure(seeds)
        assert extra == set(), f"三新槽有闭包外下游：{sorted(extra)}"


class TestPoolV2RulerOnSyntheticShape:
    def test_green_on_preregistered_shape(self):
        base, cand, brec, crec = _build_poolv2_fixture()
        failures, info = _poolv2_verify(base, cand, brec, crec)
        assert failures == [], failures
        text = "\n".join(info)
        # 值漂读数：2 世界 × 2 漂移行 = 4 处允许值翻
        assert "允许值翻 4 处" in text
        # 纯追加读数：2 世界 × 3 新槽 = 6 行
        assert "三新槽纯追加 6 行" in text
        # bundle 既有判据照常在场（乙12 塌缩＋十槽恰 1 行）
        assert "撤碎片行 16 条" in text and "十槽恰 1 行破 0 处" in text

    def test_same_shape_under_bundle_step_is_red(self):
        """同一形状拿 `--step bundle` 旧尺量必红——审核 §八⑤ 病灶复现，
        同时证明新允许集没有稀释 bundle 键（两把尺判据各自独立）。"""
        base, cand, brec, crec = _build_poolv2_fixture()
        failures, _info = vp._verify_bundle_sidecar_delta(base, cand, brec, crec)
        assert any("随机流被搅动" in f for f in failures), failures
        assert any("越界" in f for f in failures), failures

    def test_mutation_out_of_list_value_drift_is_red(self):
        """变异臂（M1 验收判据原文）：伪造一条**清单外**槽的值漂 ⇒ 必红。"""
        base, cand, brec, crec = _build_poolv2_fixture()
        mask = (cand["slot_id"] == "defect.hollowing.ratio") & (
            cand["runtime_id"] == f"SCR-FRG-{_WORLDS[0]}-MEMBER-00")
        assert int(mask.sum()) == 1
        cand.loc[mask, "value_json"] = "0.99"
        failures, _info = _poolv2_verify(base, cand, brec, crec)
        assert failures, "清单外值漂未被抓住（细尺失明）"
        assert any("随机流被搅动" in f for f in failures), failures

    def test_mutation_drift_slot_structural_column_is_red(self):
        """漂移槽只许值列翻：结构列（unit）变 ⇒ 仍红（锚点列/结构列不变）。"""
        base, cand, brec, crec = _build_poolv2_fixture()
        mask = (cand["slot_id"] == _POOLV2_DRIFT_BLDG_SLOT) & (
            cand["runtime_id"] == f"SCR-BLDG-{_WORLDS[0]}")
        assert int(mask.sum()) == 1
        cand.loc[mask, "unit"] = "forged_unit"
        failures, _info = _poolv2_verify(base, cand, brec, crec)
        assert any("随机流被搅动" in f for f in failures), failures

    def test_mutation_drift_slot_row_disappears_is_red(self):
        """漂移槽行消失 ⇒ 红——「行在」是判据⑥的一部分，值漂许可不含丢行。"""
        base, cand, brec, crec = _build_poolv2_fixture()
        mask = (cand["slot_id"] == _POOLV2_DRIFT_FRAG_SLOT) & (
            cand["runtime_id"] == f"SCR-FRG-{_WORLDS[0]}-MEMBER-00")
        assert int(mask.sum()) == 1
        cand = cand[~mask].reset_index(drop=True)
        failures, _info = _poolv2_verify(base, cand, brec, crec)
        assert any("消失" in f for f in failures), failures

    def test_mutation_new_slot_present_in_baseline_is_red(self):
        """三新槽在基线已有行 ⇒「整槽缺席⇒纯追加」前提失效，红。"""
        base, cand, brec, crec = _build_poolv2_fixture()
        stale = _entry(
            f"SCR-BLDG-{_WORLDS[0]}", 40, "procedure_gate_state",
            "procedure.repair_supervising_ri.appointment.completed", "false",
            {"carrier_domain": "procedure", "granularity": "building",
             "provenance": "stale_baseline_row"})
        base = pd.concat([base, pd.DataFrame([stale])], ignore_index=True)
        cand = pd.concat([cand, pd.DataFrame([dict(stale)])],
                         ignore_index=True)
        failures, _info = _poolv2_verify(base, cand, brec, crec)
        assert any("整槽缺席" in f for f in failures), failures


class TestPoolV2MainLevel:
    """main() 级：poolv2 分支接线（判据打印＋两清单真被传给细尺）。"""

    @staticmethod
    def _fake_pool_cls(forge_out_of_list: bool):
        base_e, cand_e, brec, crec = _build_poolv2_fixture()
        if forge_out_of_list:
            mask = (cand_e["slot_id"] == "defect.hollowing.ratio") & (
                cand_e["runtime_id"] == f"SCR-FRG-{_WORLDS[0]}-MEMBER-00")
            cand_e.loc[mask, "value_json"] = "0.99"

        class _FakePool:
            def __init__(self, root):
                is_base = str(root).endswith("base")
                self.root = root
                self.units = {
                    "sidecar.entries": base_e if is_base else cand_e,
                    "sidecar.records": brec if is_base else crec,
                }

            def anchors(self):
                return {"dir": str(self.root)}

            def limit_worlds(self, n):  # pragma: no cover - 本测不截栋
                pass

        return _FakePool

    def _run_main(self, monkeypatch, forge: bool):
        monkeypatch.setattr(vp, "Pool", self._fake_pool_cls(forge))
        return vp.main([
            "--baseline", "base", "--candidate", "cand", "--step", "poolv2",
            "--pool-seed", "301", "--pool-count", "2", "--ctcov", "on",
        ])

    def test_main_green_on_preregistered_shape(self, monkeypatch, capsys):
        rc = self._run_main(monkeypatch, forge=False)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "[PASS] 本步字节锚全过" in out
        assert "⑤" in out and "⑥" in out  # 六条判据打印在场

    def test_main_out_of_list_drift_is_red(self, monkeypatch, capsys):
        rc = self._run_main(monkeypatch, forge=True)
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "随机流被搅动" in out
