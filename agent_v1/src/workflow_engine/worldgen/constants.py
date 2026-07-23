from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Set, Union

# QA-Parallelize 2026-05-09: orjson 替换 json (3-10× 序列化速度，C 扩展)
# fallback to stdlib json 如果 orjson 未安装（不破坏 import）
try:
    import orjson  # type: ignore
    _HAS_ORJSON = True
except ImportError:  # pragma: no cover
    orjson = None  # type: ignore
    _HAS_ORJSON = False

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORLDGEN_FULLCOVERAGE_OUTPUT_DIR = (
    PROJECT_ROOT
    / "experiments"
    / "runs"
    / "review_20260416_worldgenerator_fullcoverage_framework_revision_r1"
)
GENERATOR_VERSION = "worldgen.fullcoverage.framework.v2"
DEFAULT_BATCH_WORLD_COUNT = 120
DEFAULT_BATCH_RANDOM_SEED = 20260416
BATCH_CONTRACT_TARGETS = {
    "smoke_batch": 120,
    "dev_batch": 600,
    "benchmark_batch": 1200,
    "release_batch": 3000,
}

MeasurementBranch = Literal[
    "defect_geometry_measurement",
    "coverage_sampling_measurement",
    "technical_validation_measurement",
    "structural_assessment_measurement",
]
DerivationMode = Literal[
    "damage_downstream",
    "coverage_sampling_plan",
    "technical_validation_plan",
    "repair_geometry_downstream",
    "material_exposure_downstream",
    "assessment_plan",
]
SlotPartition = Literal["world_core", "measurement_family", "qualifier_taxonomy", "sidecar"]
CoverageStatus = Literal["world_core_ready", "unsupported"]
SeverityBand = Literal["none", "minor", "moderate", "severe", "emergency"]

OutcomeFlagValue = Union[bool, Literal["not_applicable", "unknown"]]


def _utc_now_iso() -> str:
    return "2026-04-26T00:00:00+00:00"


def _write_json(path: Path, payload: Any) -> Path:
    """QA-Parallelize 2026-05-09: orjson 优先（3-10× 速度），fallback stdlib json."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if _HAS_ORJSON:
        # orjson 默认 UTF-8 字节输出；OPT_INDENT_2 = 2 空格缩进；OPT_NON_STR_KEYS 兼容 dict 非 str key
        data = orjson.dumps(payload, option=orjson.OPT_INDENT_2 | orjson.OPT_NON_STR_KEYS)
        path.write_bytes(data)
    else:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def _canonical_json(payload: Any) -> str:
    """canonical JSON 用于 _hash_payload；坚持 stdlib json 保证 deterministic_key 跨版本一致.

    QA-Parallelize 2026-05-09 注：orjson 不在此处用 — orjson 与 json.dumps 在 float 字符串化 /
    Unicode escape 等细节可能有差异，会导致 hash 漂移，破坏跨 batch deterministic_key 比对.
    `_write_json`（文件输出，不进 hash）才切到 orjson.
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _resolve_batch_profile(count: int) -> str:
    for contract_name, target_count in BATCH_CONTRACT_TARGETS.items():
        if count == target_count:
            return contract_name
    if count < BATCH_CONTRACT_TARGETS["smoke_batch"]:
        return "custom_below_smoke"
    if count < BATCH_CONTRACT_TARGETS["dev_batch"]:
        return "custom_between_smoke_and_dev"
    if count < BATCH_CONTRACT_TARGETS["benchmark_batch"]:
        return "custom_between_dev_and_benchmark"
    if count < BATCH_CONTRACT_TARGETS["release_batch"]:
        return "custom_between_benchmark_and_release"
    return "custom_above_release"


# [DEBT-002 closed §15.7] canonical baseline for stress.pull_test.minimum measurement slot
PULL_TEST_STRENGTH_CANONICAL_BASELINE = 0.50
# Internal conservative proxy floor retained for qualitative evidence inference only
PULL_TEST_PROXY_SAFETY_FLOOR = 0.58
REPAIR_QUALITY_VERIFICATION_FLOOR = 0.45
MAINTENANCE_SEVERITY_RANKS = {1, 2}
FSP_STRUCTURAL_PERFORMANCE_FLOOR = 0.75
PUBLIC_HEALTH_RISK_EMERGENCY_FLOOR = 0.80
# [DEBT-013 closed §15.8] confirmed canonical value; applies to all coverage-ratio families uniformly
COVERAGE_RATIO_FLOOR_PROXY = 0.35
SEVERITY_MINOR_MAX = 0.33
SEVERITY_MODERATE_MAX = 0.66
SEVERITY_EMERGENCY_MIN = 0.85
# [SCAN03-F04] 规范常量：砂浆标准养护期与标准试件数（a4/行业标准，同 stress.pull_test.minimum 性质）
REPAIR_MORTAR_TEST_AGE_DAYS = 28
REPAIR_MORTAR_SPECIMENS_PER_PROPERTY = 3
# [SCAN06-F04] 仅作为 worldgen 物理自闭行为的 surrogate split；法规阈值只属于 rulecard/projection。
FIRE_DOOR_SELF_CLOSING_SURROGATE_SPLIT_SEC = 3.0
FIRE_DOOR_SELF_CLOSING_DEFECT_MIN_MARGIN_SEC = 0.10
FIRE_DOOR_SELF_CLOSING_DEFECT_LOW_MARGIN_SEC = 0.20
FIRE_DOOR_SELF_CLOSING_DEFECT_MODE_MARGIN_SEC = 1.50
FIRE_DOOR_SELF_CLOSING_DEFECT_HIGH_MARGIN_SEC = 3.00
FIRE_DOOR_SELF_CLOSING_OK_LOW_SEC = 1.20
FIRE_DOOR_SELF_CLOSING_OK_MODE_SEC = 2.00
FIRE_DOOR_SELF_CLOSING_OK_MAX_MARGIN_SEC = 0.01
FIRE_DOOR_SELF_CLOSING_ABSOLUTE_LOW_SEC = 0.50
FIRE_DOOR_SELF_CLOSING_ABSOLUTE_HIGH_SEC = 8.00
# [SCAN03-F07] 规范/计划最低值常量（对照 a4 确认；改为常量返回，不走 _mutate_number）
PULL_TEST_RATE_PER_25M2 = 1              # 每 25m² 拉拔试验次数（a4 计划值）
PULL_TEST_COUNT_PER_REPAIRED_FACADE = 6  # 每修缮立面拉拔试验次数（a4 计划值）
PULL_TEST_COUNT_PER_FLOOR_FULL_RETILING = 4  # 每层全幅重铺拉拔试验次数（a4 计划值）
DRAINAGE_TEST_POINTS_MINIMUM = 3         # 排水系统最少测试点数（a4 规范常量）
DRAINAGE_BRANCH_INTERVAL_M = 8.0         # 排水支管检查间距（a4 规范常量，单位：m）
FIRE_DOOR_SAMPLE_MINIMUM = 4             # 防火门最少抽样扇数（a4 规范常量）
PRIVATE_PREMISES_ACCESS_FLOOR_INTERVAL = 3  # 私人地方进入楼层间距（a4 计划值）
CANOPY_CHECK_LOCATIONS_MINIMUM = 2
CANOPY_CHECK_LOCATION_INTERVAL_MAX_M = 6.0
CORE_SAMPLE_RATE_PER_CONCRETE_VOLUME_MINIMUM = 0.02
SEVERITY_FLOOR_RELEASE = {
    "emergency": 60,
    "severe": 60,
    "none": 60,
    "not_applicable": 60,
}
RELEASE_RESIDUAL_RISK_FALSE_FLOOR = 60
RELEASE_FSP_BELOW_SAFETY_FLOOR = 60
RELEASE_NO_SIDECAR_DEPENDENCY_FLOOR = 1500
RELEASE_SIDECAR_MISSING_FLOOR = 300
WORK_CATEGORY_VALUES = [
    "minor_works",
    "exempted_building_works",
    "approval_and_consent_works",
]
FSP_LOW_TAIL_PROFILE_IDS: Set[str] = {"structural_components", "external_components", "investigation_gate"}
# DEBT-008 closed in code: these are explicit MVP design priors for sidecar
# duration/supervision runtime mapping. They are not legal thresholds; they map
# generated supervision workload to runtime facts until the consume contract is
# promoted to a separate versioned table.
SUPERVISION_RUNTIME_PRIORS = {
    "rep_lvl2_interval_normal_days": 28,
    "rep_lvl2_interval_failed_verification_days": 14,
    "rep_lvl1_interval_normal_days": 14,
    "rep_lvl1_interval_failed_verification_days": 7,
    "rep_lvl2_measurements_per_visit": 4,
    "rep_lvl1_measurements_per_visit": 2,
}
A12_FIRE_COMPONENT_TYPES = {
    "fire_door",
    "fire_resisting_wall",
    "escape_route",
    "smoke_vent",
    "fire_service_installation",
    "unknown_fire_component",
}

SOURCE_DOCUMENTS = [
    "团队文档/研究团队文档/pro-answer/a8.md",
    "团队文档/研究团队文档/pro-answer/a10.md",
    "团队文档/研究团队文档/pro-answer/a11.md",
    "团队文档/研究团队文档/pro-answer/a12.md",
    "团队文档/技术团队文档/rulecard工程/answer/a4.md",
]
