"""evo-agent v1 §6.2 verifier instrumentation 测试。

验证 `run_closure()` 在 ClosureValidationResult.machine_readable_report
内写入 4 个 v1 instrumentation 字段：
- `skill_invocation_ids`
- `candidate_universe_hash`
- `fact_pack_hash`
- `rule_slice_hash`

并验证不变量：
- 同输入 hash deterministic（spec v1 §6.4 repeatability）；
- Skill / Policy 不影响 allow_stop / closure_status（spec v1 §6.3）；
- skill_invocation_ids 缺省时为空 list，不破坏既有调用方。
"""

from __future__ import annotations

import pytest

from evo_agent_baseline.closure.validator import (
    compute_candidate_universe_hash,
    compute_fact_pack_hash,
    compute_rule_slice_hash,
    validate_building_closure,
)
from pydantic import ValidationError

from evo_agent_baseline.closure.tests.fixtures import catalog_for_slice, run_closure
from evo_agent_baseline.contracts import FactPack, Obligation, ObligationSet, RuleSlice


# ===========================================================================
# 辅助：最小 FactPack / RuleSlice fixture
# ===========================================================================
def _empty_fact_pack(run_id: str = "CAR-test-001") -> FactPack:
    return FactPack(
        run_id=run_id,
        world_id="W-test",
        building_id="B-test",
        facts=[],
        slot_index={},
        measure_index={},
        carrier_index={},
        source_tables=[],
    )


def _empty_rule_slice(
    run_id: str = "CAR-test-001",
    bundle_id: str = "rulecard_v2.mbis_cop_2023",
) -> RuleSlice:
    return RuleSlice(
        run_id=run_id,
        rulecard_bundle_id=bundle_id,
        candidate_rule_cards=[],
        rule_families=[],
        semantic_slots=[],
        measures=[],
        artifacts=[],
        time_anchors=[],
        source_quotes=[],
        retrieval_policy={},
    )


# ===========================================================================
# 4 个 instrumentation 字段写入
# ===========================================================================
class TestInstrumentationFields:
    def test_default_call_includes_new_fields(self):
        """无参数调用 validate_building_closure → machine_report 含 4 个 v1 字段。"""
        result = run_closure(
            _empty_rule_slice(), _empty_fact_pack()
        )
        report = result.machine_readable_report
        assert "skill_invocation_ids" in report
        assert "candidate_universe_hash" in report
        assert "fact_pack_hash" in report
        assert "rule_slice_hash" in report

    def test_default_skill_invocation_ids_empty(self):
        result = run_closure(
            _empty_rule_slice(), _empty_fact_pack()
        )
        assert result.machine_readable_report["skill_invocation_ids"] == []

    def test_explicit_skill_invocation_ids_written(self):
        ids = ["SA-CAR-1-1", "SA-CAR-1-2"]
        result = run_closure(
            _empty_rule_slice(),
            _empty_fact_pack(),
            skill_invocation_ids=ids,
        )
        # 自动去重 + 排序
        assert result.machine_readable_report["skill_invocation_ids"] == sorted(set(ids))
        assert result.machine_readable_report["skill_augmented_retrieval_used"] is True

    def test_no_skill_invocation_means_skill_augmented_false(self):
        result = run_closure(
            _empty_rule_slice(),
            _empty_fact_pack(),
            skill_invocation_ids=None,
        )
        assert result.machine_readable_report["skill_augmented_retrieval_used"] is False

    def test_policy_version_id_recorded(self):
        result = run_closure(
            _empty_rule_slice(),
            _empty_fact_pack(),
            policy_version_id="policy.mbis.runtime.default.v1.0.0",
        )
        assert result.machine_readable_report["policy_version_id"] == "policy.mbis.runtime.default.v1.0.0"

    def test_verifier_authority_check_recorded(self):
        result = run_closure(
            _empty_rule_slice(), _empty_fact_pack(), skill_invocation_ids=["X"]
        )
        check = result.machine_readable_report["verifier_authority_check"]
        assert check["allow_stop_owned_by_verifier"] is True
        assert check["closure_status_owned_by_verifier"] is True
        assert check["satisfaction_status_owned_by_verifier"] is True
        assert check["skill_invocation_count"] == 1


# ===========================================================================
# Hash 确定性 + spec §6.4 repeatability
# ===========================================================================
class TestHashDeterminism:
    def test_same_input_same_hash_repeated(self):
        """spec §6.4：同 input → hash bitwise stable。"""
        rs = _empty_rule_slice()
        fp = _empty_fact_pack()
        r1 = run_closure(rs, fp)
        r2 = run_closure(rs, fp)
        assert (
            r1.machine_readable_report["fact_pack_hash"]
            == r2.machine_readable_report["fact_pack_hash"]
        )
        assert (
            r1.machine_readable_report["rule_slice_hash"]
            == r2.machine_readable_report["rule_slice_hash"]
        )
        assert (
            r1.machine_readable_report["candidate_universe_hash"]
            == r2.machine_readable_report["candidate_universe_hash"]
        )

    def test_different_fact_pack_different_hash(self):
        fp1 = _empty_fact_pack(run_id="CAR-A")
        fp2 = _empty_fact_pack(run_id="CAR-B")
        h1 = compute_fact_pack_hash(fp1)
        h2 = compute_fact_pack_hash(fp2)
        assert h1 != h2

    def test_different_bundle_id_different_rule_slice_hash(self):
        rs1 = _empty_rule_slice(bundle_id="bundle.A")
        rs2 = _empty_rule_slice(bundle_id="bundle.B")
        h1 = compute_rule_slice_hash(rs1)
        h2 = compute_rule_slice_hash(rs2)
        assert h1 != h2

    def test_candidate_universe_hash_order_invariant(self):
        """rule_card_id 顺序变化不应改变 hash（set semantic）。"""
        h1 = compute_candidate_universe_hash(["rc.a", "rc.b", "rc.c"])
        h2 = compute_candidate_universe_hash(["rc.c", "rc.a", "rc.b"])
        assert h1 == h2

    def test_candidate_universe_hash_dedup(self):
        h1 = compute_candidate_universe_hash(["rc.a", "rc.b"])
        h2 = compute_candidate_universe_hash(["rc.a", "rc.a", "rc.b"])
        assert h1 == h2

    def test_candidate_universe_hash_different_when_member_differs(self):
        h1 = compute_candidate_universe_hash(["rc.a"])
        h2 = compute_candidate_universe_hash(["rc.b"])
        assert h1 != h2

    def test_hash_is_sha256_hex_lowercase(self):
        h = compute_fact_pack_hash(_empty_fact_pack())
        assert len(h) == 64
        assert h == h.lower()
        # all hex
        int(h, 16)  # 不抛即为 hex


# ===========================================================================
# 不变量：Skill / Policy 不影响 verifier authority（spec v1 §6.3）
# ===========================================================================
class TestVerifierAuthorityInvariant:
    def test_skill_invocation_ids_do_not_change_allow_stop(self):
        rs = _empty_rule_slice()
        fp = _empty_fact_pack()
        r_no_skill = run_closure(rs, fp, skill_invocation_ids=None)
        r_with_skill = run_closure(
            rs, fp, skill_invocation_ids=["SA-X", "SA-Y"]
        )
        # allow_stop / closure_status / satisfaction_status 必须完全一致
        assert r_no_skill.allow_stop == r_with_skill.allow_stop
        assert (
            r_no_skill.closure_summary.allow_stop
            == r_with_skill.closure_summary.allow_stop
        )
        assert (
            r_no_skill.closure_summary.stop_reason
            == r_with_skill.closure_summary.stop_reason
        )

    def test_policy_version_id_does_not_change_allow_stop(self):
        rs = _empty_rule_slice()
        fp = _empty_fact_pack()
        r_no_policy = run_closure(rs, fp, policy_version_id=None)
        r_with_policy = run_closure(
            rs, fp, policy_version_id="policy.mbis.runtime.default.v1.0.0"
        )
        assert r_no_policy.allow_stop == r_with_policy.allow_stop

    def test_empty_skill_ids_dedup_to_empty(self):
        r = run_closure(
            _empty_rule_slice(), _empty_fact_pack(), skill_invocation_ids=[]
        )
        assert r.machine_readable_report["skill_invocation_ids"] == []

    def test_duplicate_skill_ids_deduplicated(self):
        r = run_closure(
            _empty_rule_slice(),
            _empty_fact_pack(),
            skill_invocation_ids=["SA-1", "SA-1", "SA-2"],
        )
        assert r.machine_readable_report["skill_invocation_ids"] == ["SA-1", "SA-2"]


# ===========================================================================
# Backward compat：既有调用方不传新参数仍工作
# ===========================================================================
class TestIdentityV5CatalogContract:
    """现网键切换增补 §5.2：`identity_blueprint_catalog` keyword-only **必填、无默认、无回退**。"""

    def test_call_with_catalog_works(self):
        """传 catalog（现网键切换后活动契约）正常工作。"""
        r = run_closure(_empty_rule_slice(), _empty_fact_pack())
        assert r.allow_stop is not None
        assert r.machine_readable_report["skill_invocation_ids"] == []
        assert r.obligation_set.obligation_identity_schema == "obligation_identity_v5"

    def test_call_with_config_and_catalog_works(self):
        from evo_agent_baseline.closure.schema import VerifierConfig

        r = run_closure(
            _empty_rule_slice(), _empty_fact_pack(), VerifierConfig()
        )
        assert r.allow_stop is not None

    def test_missing_catalog_raises_typeerror(self):
        """漏传 catalog → TypeError（fail-closed，§5.2：无静默回退 v1 窗口）。"""
        with pytest.raises(TypeError):
            validate_building_closure(_empty_rule_slice(), _empty_fact_pack())

    def test_run_audit_transcribed_from_obligation_set(self):
        """§7 原子版本传播：run_audit 4 容器字段==ObligationSet 实值（抄录，非独立常量）+ 运行不变量。"""
        r = run_closure(_empty_rule_slice(), _empty_fact_pack())
        ra = r.machine_readable_report["run_audit"]
        os_ = r.obligation_set
        # 4 容器/身份版本字段逐一 == ObligationSet 实例字段（抄录闸）。
        assert ra["obligation_set_schema"] == os_.obligation_set_schema
        assert ra["obligation_identity_schema"] == os_.obligation_identity_schema
        assert ra["canonical_profile_id"] == os_.canonical_profile_id
        assert ra["identity_key_policy"] == os_.identity_key_policy
        # 且确为 v5 实值（现网活动路径，非 None）。
        assert os_.obligation_identity_schema == "obligation_identity_v5"
        # catalog sha256 + 运行不变量。
        assert isinstance(ra["identity_catalog_sha256"], str)
        assert len(ra["identity_catalog_sha256"]) == 64
        assert ra["identity_binding_unbound_count"] == 0
        assert ra["identity_collision_postcheck_passed"] is True
        assert ra["legacy_v1_key_used"] is False


class TestObligationSetVersioning:
    """现网键切换增补 §4.2：容器/身份版本 all-or-none + identity_manifest ↔ obligations 一一对应。"""

    @staticmethod
    def _obl(oid: str) -> Obligation:
        return Obligation(
            obligation_id=oid, run_id="r", world_id="w", building_id="b",
            source_rule_card_id="rc", source_family_id="f", kind="threshold",
            closure_status="closed", satisfaction_status="satisfied",
        )

    def _base(self, **kw):
        base = dict(
            obligation_set_id="OS", run_id="r", world_id="w", building_id="b",
            created_at="t", rulecard_bundle_id="bd", verifier_version="v",
            obligations=[self._obl("a")], derivation_policy={},
        )
        base.update(kw)
        return base

    def test_v1_readonly_all_none_ok(self):
        """四版本字段全缺 + manifest 空 → v1 只读容器（合法）。"""
        ObligationSet(**self._base())

    def test_partial_version_fields_raises(self):
        """混合容器：部分版本字段缺（obligation_set_v2 + 身份 None）→ ValidationError。"""
        with pytest.raises(ValidationError):
            ObligationSet(**self._base(obligation_set_schema="obligation_set_v2"))

    def test_v5_all_present_matching_manifest_ok(self):
        """四版本字段全齐=固定 v5 值 + manifest 1:1 → 合法。"""
        ObligationSet(**self._base(
            obligation_set_schema="obligation_set_v2",
            obligation_identity_schema="obligation_identity_v5",
            canonical_profile_id="mbis_canonical_v2",
            identity_key_policy="canonical_identity_hash",
            identity_manifest=[{"obligation_id": "a"}],
        ))

    def test_v5_wrong_value_raises(self):
        """全齐但值非固定 v5（错 profile）→ ValidationError。"""
        with pytest.raises(ValidationError):
            ObligationSet(**self._base(
                obligation_set_schema="obligation_set_v2",
                obligation_identity_schema="obligation_identity_v5",
                canonical_profile_id="WRONG_PROFILE",
                identity_key_policy="canonical_identity_hash",
                identity_manifest=[{"obligation_id": "a"}],
            ))

    def test_v5_manifest_mismatch_raises(self):
        """v5 但 identity_manifest 与 obligations 不一一对应（长度/id 集）→ ValidationError。"""
        with pytest.raises(ValidationError):
            ObligationSet(**self._base(
                obligation_set_schema="obligation_set_v2",
                obligation_identity_schema="obligation_identity_v5",
                canonical_profile_id="mbis_canonical_v2",
                identity_key_policy="canonical_identity_hash",
                identity_manifest=[{"obligation_id": "a"}, {"obligation_id": "b"}],
            ))

    def test_v1_with_manifest_raises(self):
        """v1 只读容器却挂 identity_manifest（无版本标）→ ValidationError。"""
        with pytest.raises(ValidationError):
            ObligationSet(**self._base(identity_manifest=[{"obligation_id": "a"}]))

    def test_v5_manifest_multiset_mismatch_raises(self):
        """重复分布穿透负测（codex 019f7328 阻断 1）：obligations=[a,a,b] vs
        manifest=[a,b,b]——长度相等、id **set** 相等，但**多重集**不等 → 旧"长度+set"闸
        穿透、新 Counter 闸必须拒（且 obligations 内重复 id 本身即拒）。"""
        with pytest.raises(ValidationError):
            ObligationSet(**self._base(
                obligation_set_schema="obligation_set_v2",
                obligation_identity_schema="obligation_identity_v5",
                canonical_profile_id="mbis_canonical_v2",
                identity_key_policy="canonical_identity_hash",
                obligations=[self._obl("a"), self._obl("a"), self._obl("b")],
                identity_manifest=[
                    {"obligation_id": "a"},
                    {"obligation_id": "b"},
                    {"obligation_id": "b"},
                ],
            ))

    def test_v5_duplicate_obligation_id_raises(self):
        """最终容器 obligations 含重复 obligation_id（即便 manifest 逐条对上）→ ValidationError
        （去重后的容器不允许重复 ID——Counter 闸的唯一性分支）。"""
        with pytest.raises(ValidationError):
            ObligationSet(**self._base(
                obligation_set_schema="obligation_set_v2",
                obligation_identity_schema="obligation_identity_v5",
                canonical_profile_id="mbis_canonical_v2",
                identity_key_policy="canonical_identity_hash",
                obligations=[self._obl("a"), self._obl("a")],
                identity_manifest=[
                    {"obligation_id": "a"},
                    {"obligation_id": "a"},
                ],
            ))
