"""T-23 unit tests: conflict_group named entities + resolve_family_conflict (spec 07 §4.1 / §4.2)."""
import unittest

from workflow_engine.regulation_projection_executor import (
    CONFLICT_GROUPS,
    ConflictResolutionResult,
    resolve_family_conflict,
)


class ConflictGroupDataTests(unittest.TestCase):
    """spec 07 §4.1 CONFLICT_GROUPS 数据完整性检验。"""

    def test_four_named_conflict_groups(self):
        """CONFLICT_GROUPS 恰好含 4 个 group。"""
        self.assertEqual(len(CONFLICT_GROUPS), 4)

    def test_required_group_ids_present(self):
        """4 个 group id 与 spec §4.1 命名一致。"""
        expected = {
            "structural_external_surface",
            "drainage",
            "ubw_fire",
            "assessment_repair",
        }
        self.assertEqual(set(CONFLICT_GROUPS.keys()), expected)

    def test_each_group_has_members_nonempty(self):
        """每个 group 的 members 非空列表。"""
        for group_id, group in CONFLICT_GROUPS.items():
            with self.subTest(group_id=group_id):
                self.assertIn("members", group)
                self.assertIsInstance(group["members"], list)
                self.assertGreater(len(group["members"]), 0)

    def test_each_group_has_selector_string(self):
        """每个 group 的 selector 是非空字符串。"""
        for group_id, group in CONFLICT_GROUPS.items():
            with self.subTest(group_id=group_id):
                self.assertIn("selector", group)
                self.assertIsInstance(group["selector"], str)
                self.assertGreater(len(group["selector"]), 0)

    def test_structural_external_surface_members(self):
        """structural_external_surface 含 5 个 member（spec §4.1）。"""
        group = CONFLICT_GROUPS["structural_external_surface"]
        self.assertEqual(len(group["members"]), 5)
        self.assertIn("crack", group["members"])
        self.assertIn("spall_rebar", group["members"])

    def test_drainage_members(self):
        """drainage 含 3 个 member。"""
        group = CONFLICT_GROUPS["drainage"]
        self.assertEqual(len(group["members"]), 3)
        self.assertIn("drainage_blockage", group["members"])


class ResolveFamilyConflictTests(unittest.TestCase):
    """spec 07 §4.2 5 种竞争处理 unit tests。"""

    def _c(self, family_id, score=0.5, component_id="CMP-001", slots_present=True):
        """构造一个 candidate_family entry。"""
        return {
            "family_id": family_id,
            "applicability_score": score,
            "target_component_id": component_id,
            "required_slots_present": slots_present,
        }

    # spec §4.2 行 1: no candidates
    def test_empty_candidates_returns_no_match(self):
        families, reason = resolve_family_conflict([], "structural_external_surface")
        self.assertEqual(families, [])
        self.assertEqual(reason, "no_known_family_match")

    # spec §4.2 行 1: candidates but none with required slots
    def test_no_applicable_returns_no_match(self):
        candidates = [
            self._c("crack", slots_present=False),
            self._c("spall_rebar", slots_present=False),
        ]
        families, reason = resolve_family_conflict(candidates, "structural_external_surface")
        self.assertEqual(families, [])
        self.assertEqual(reason, "no_known_family_match")

    # spec §4.2 行 2: exactly one applicable
    def test_single_applicable_returns_it(self):
        candidates = [
            self._c("crack", slots_present=True),
            self._c("spall_rebar", slots_present=False),
        ]
        families, reason = resolve_family_conflict(candidates, "structural_external_surface")
        self.assertEqual(families, ["crack"])
        self.assertIsNone(reason)

    # spec §4.2 行 3: multiple applicable with distinct target components (drainage)
    def test_multi_distinct_component_drainage_allows_multi(self):
        candidates = [
            self._c("drainage_blockage", component_id="CMP-001"),
            self._c("drainage_leakage", component_id="CMP-002"),
        ]
        families, reason = resolve_family_conflict(candidates, "drainage")
        self.assertIn("drainage_blockage", families)
        self.assertIn("drainage_leakage", families)
        self.assertEqual(len(families), 2)
        self.assertIsNone(reason)

    # spec §4.2 行 3: multiple applicable with distinct target components (ubw_fire)
    def test_multi_distinct_component_ubw_fire_allows_multi(self):
        candidates = [
            self._c("ubw_alteration", component_id="CMP-A"),
            self._c("fire_safety_deficiency", component_id="CMP-B"),
        ]
        families, reason = resolve_family_conflict(candidates, "ubw_fire")
        self.assertEqual(len(families), 2)
        self.assertIsNone(reason)

    # spec §4.2 行 5: structural_external_surface → highest score wins
    def test_structural_same_component_highest_score_wins(self):
        candidates = [
            self._c("crack", score=0.6, component_id="CMP-001"),
            self._c("spall_rebar", score=0.9, component_id="CMP-001"),
            self._c("detachment", score=0.4, component_id="CMP-001"),
        ]
        families, reason = resolve_family_conflict(candidates, "structural_external_surface")
        self.assertEqual(families, ["spall_rebar"])
        self.assertIsNone(reason)

    # spec §4.2 行 5: other group same component → multi_family_conflict
    def test_assessment_repair_same_component_unresolvable(self):
        candidates = [
            self._c("structural_assessment_deficit", component_id="CMP-001"),
            self._c("repair_validation_failure", component_id="CMP-001"),
        ]
        families, reason = resolve_family_conflict(candidates, "assessment_repair")
        self.assertEqual(families, [])
        self.assertEqual(reason, "multi_family_conflict")

    # no conflict_group specified → behaves gracefully
    def test_no_conflict_group_single_applicable(self):
        candidates = [self._c("crack")]
        families, reason = resolve_family_conflict(candidates, None)
        self.assertEqual(families, ["crack"])
        self.assertIsNone(reason)


if __name__ == "__main__":
    unittest.main()
