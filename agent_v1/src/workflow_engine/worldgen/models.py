from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, computed_field, model_validator

from workflow_engine.worldgen.constants import (
    CoverageStatus,
    DerivationMode,
    DEFAULT_BATCH_RANDOM_SEED,
    GENERATOR_VERSION,
    MeasurementBranch,
    OutcomeFlagValue,
    SeverityBand,
    SlotPartition,
)


class RegistryTable(BaseModel):
    registry_id: str
    ownership: str
    key_field: str
    fields: List[str] = Field(default_factory=list)
    records: List[Dict[str, Any]] = Field(default_factory=list)


class RegistryBundle(BaseModel):
    version: str = "worldgen.fullcoverage.registry.v1"
    generated_at: str
    source_documents: List[str] = Field(default_factory=list)
    registries: List[RegistryTable] = Field(default_factory=list)


class GraphNode(BaseModel):
    node_id: str
    node_type: str
    label: str
    qualifiers: List[str] = Field(default_factory=list)


class GraphEdge(BaseModel):
    edge_id: str
    relation: str
    source_id: str
    target_id: str
    notes: List[str] = Field(default_factory=list)


class DomainRecord(BaseModel):
    record_id: str
    domain: str
    kind: str
    status: str
    notes: List[str] = Field(default_factory=list)


class DriverState(BaseModel):
    # spec 04 §9 DriverState 13 字段合约（2026-05-21 W0-004 对齐）。
    # `age_years` 不在 driver 上（spec 04 §4 line 79 注 "driver 可引用" 在 BuildingContext）；
    # `drainage_fault_propensity` 走单一字段（spec 06 §5 公式 + spec 11 §2.6 mechanism
    # required_driver_fields 一致），不拆 drainage_usage_intensity / blockage_propensity；
    # `obstruction_index` / `coverage_feasibility_index` 未在 spec 04 §9 / spec 06 公式 /
    # spec 11 §2.6 mechanism required_driver_fields 出现，故不留。
    driver_id: str
    fragment_id: str
    service_load_ratio: float
    restraint_level: float
    moisture_ingress_index: float
    chloride_exposure_index: float
    carbonation_index: float
    workmanship_deficit_index: float
    maintenance_deficit_index: float
    drainage_fault_propensity: float
    alteration_propensity: float
    fire_safety_deficit_index: float
    repair_quality_index: float


class MechanismActivation(BaseModel):
    mechanism_id: str
    mechanism_family: str
    activation_score: float
    derived_from_driver_ids: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class MechanismState(BaseModel):
    mechanism_state_id: str
    fragment_id: str = ""
    mechanism_family: str = ""
    active: bool = True
    severity_index: float = 0.0
    cause_tags: List[str] = Field(default_factory=list)
    primary_mechanism_id: str
    activated_mechanisms: List[MechanismActivation] = Field(default_factory=list)
    crack_mechanism_kind: str = "none"
    corrosion_active: bool = False
    delamination_active: bool = False
    drainage_fault_kind: str = "none"
    ubw_signal_kind: str = "none"
    fire_safety_deficiency_kind: str = "none"
    assessment_origin_kind: str = "none"
    verification_origin_kind: str = "none"

    @model_validator(mode="after")
    def _derive_spec_fields_from_legacy_mechanisms(self) -> "MechanismState":
        if self.activated_mechanisms:
            primary = max(self.activated_mechanisms, key=lambda activation: activation.activation_score)
            if not self.mechanism_family:
                self.mechanism_family = primary.mechanism_family
            if self.severity_index == 0.0:
                self.severity_index = round(float(primary.activation_score), 4)
            if not self.cause_tags:
                tag_map = {
                    "structural_crack": ["load", "moisture"],
                    "moisture_detachment": ["moisture", "poor_maintenance"],
                    "corrosion_spall": ["corrosion", "moisture"],
                    "drainage_fault": ["blockage", "poor_maintenance"],
                    "ubw_signal": ["alteration"],
                    "fire_safety_deficiency": ["fire_component_deficit"],
                    "assessment_origin": ["assessment"],
                }
                self.cause_tags = tag_map.get(self.mechanism_family, ["unknown_origin"])
        return self


class ManifestationFlag(BaseModel):
    slot_id: str
    value: Any
    qualifier_ids: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class DerivedOutcomeState(BaseModel):
    risk_flags: Dict[str, OutcomeFlagValue] = Field(default_factory=dict)
    repair_flags: Dict[str, OutcomeFlagValue] = Field(default_factory=dict)
    verification_flags: Dict[str, OutcomeFlagValue] = Field(default_factory=dict)
    assessment_flags: Dict[str, OutcomeFlagValue] = Field(default_factory=dict)
    # [DEBT-001 closed §7.11] continuous risk index values (float) keyed by index slot id
    risk_index_values: Dict[str, float] = Field(default_factory=dict)
    # DEBT-030 C 组 / spec 06 §11 unknown_policy 列 audit trace：
    # 当某 derived flag 输出 "not_applicable" / "unknown" 时记录原因码（reason code），
    # 便于事后 audit 检查为什么该 flag 没派生出 bool 值——避免 DEBT-010 / DEBT-011 闭环时
    # 的 "silent not_applicable" 行为（spec 07 §4 "不允许 silent 修复"扩展到 fallback 路径）.
    # key: derived flag slot_id（如 "verification.test.failed"）；value: 原因码字符串（按 spec 06 §11
    # unknown_policy 列 verbatim 规范化，如 "no_test" / "no_assessment" / "no_drainage"等）.
    fallback_reasons: Dict[str, str] = Field(default_factory=dict)


class UBWState(BaseModel):
    ubw_id: str = ""
    component_id: str = ""
    alteration_type: str = "none"
    authorization_status_proxy: str = "unknown_authorization"
    present: bool = False
    subdivided_unit_sign_present: bool = False
    structural_impact_index: float = 0.0
    structural_impact: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_ubw_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        if "structural_impact_index" not in migrated and "structural_impact" in migrated:
            migrated["structural_impact_index"] = migrated["structural_impact"]
        return migrated

    @model_validator(mode="after")
    def _sync_legacy_ubw_fields(self) -> "UBWState":
        self.present = bool(self.present or self.alteration_type != "none" or self.subdivided_unit_sign_present)
        self.structural_impact = self.structural_impact_index
        return self


class FireSafetyState(BaseModel):
    fire_state_id: str = ""
    component_id: str = ""
    fire_component_class: Literal[
        "fire_door", "fire_resisting_wall", "escape_route",
        "smoke_vent", "fire_service_installation", "unknown_fire_component",
    ] = "unknown_fire_component"  # T-14 加 Literal
    deficiency_class: Literal[
        "missing", "damaged", "obstructed", "non_functional", "not_applicable",
    ] = "not_applicable"  # T-14 加 Literal
    deficiency_present: bool = False
    severity_index: float = 0.0
    record_status_proxy: Literal[
        "physical_only", "upgrade_record_outstanding", "unknown_record_status",
    ] = "physical_only"  # T-14 加 Literal
    component_deficiency_present: bool = False

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_fire_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        if "deficiency_present" not in migrated and "component_deficiency_present" in migrated:
            migrated["deficiency_present"] = migrated["component_deficiency_present"]
        return migrated

    @model_validator(mode="after")
    def _sync_legacy_fire_fields(self) -> "FireSafetyState":
        self.component_deficiency_present = self.deficiency_present
        if self.deficiency_present and self.deficiency_class == "not_applicable":
            self.deficiency_class = "damaged"
        return self


class DrainageState(BaseModel):
    drainage_id: str = ""
    component_id: str = ""
    segment_type: str = "soil_pipe"
    connection_state: str = "correct"
    blockage_index: float = 0.0
    leakage_index: float = 0.0
    misconnection_present: bool = False
    public_health_risk_index: float = 0.0
    # DEBT-049 Phase3 U5 §2.1a：地上/地下判别轴（CoP §5.6.1/§5.6.2；与 segment_type
    # 的 stack/branch 正交，供 air_test 两压力档 38/0 vs 100/25 分档）。默认 False=地面上；
    # worldgen 由 _drainage_is_underground(drainage_id) SHA-256 散列确定性派生（不消费 RNG）。
    is_underground: bool = False

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_drainage_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        for key, default in (
            ("blockage_index", 0.0),
            ("leakage_index", 0.0),
            ("public_health_risk_index", 0.0),
        ):
            if migrated.get(key) is None:
                migrated[key] = default
        if migrated.get("misconnection_present") is None:
            migrated["misconnection_present"] = False
        if migrated.get("is_underground") is None:
            migrated["is_underground"] = False
        return migrated

    @model_validator(mode="after")
    def _sync_drainage_connection_state(self) -> "DrainageState":
        if self.misconnection_present:
            self.connection_state = "misconnected"
        return self



class MeasurementRecord(BaseModel):
    measurement_id: str
    target_ref: str = ""
    measurement_family: MeasurementBranch
    slot_id: str
    value_num: Optional[float] = None
    value_bool: Optional[bool] = None
    value_enum: Optional[str] = None
    unit: Optional[str] = None
    precision_class: str = "standard"
    method_class: Optional[str] = None
    sample_count: Optional[int] = None
    confidence_index: float = 0.8
    derivation_refs: List[str] = Field(default_factory=list)
    derivation_mode: DerivationMode
    # DEBT-020 round5 sub-task 6 (2026-05-10): physical metadata 携带通道.
    # 不扩 measure_registry qualifier dim (违反 W0 不为下游服务原则)；
    # 而是把物理上下文（如 rebar_type / rebar_location / corrosion_loss_type）写进 measurement.qualifiers，
    # 让消费层（rule_card / projection executor / 分析层）能看到 fragment 物理状态.
    # 详见 spec 06 §4.X RebarSectionLossExtend / spec 04 §16 MeasurementRecord 字段合约.
    qualifiers: Dict[str, Any] = Field(default_factory=dict)
    # D04-3 engineering aliases retained during migration.
    upstream_refs: List[str] = Field(default_factory=list)
    origin_chain_refs: List[str] = Field(default_factory=list)
    derived_from_measurement_ids: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_measurement_shape(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        migrated = dict(data)
        if "measurement_family" not in migrated and "branch" in migrated:
            migrated["measurement_family"] = migrated["branch"]
        if "value" in migrated and not any(k in migrated for k in ("value_num", "value_bool", "value_enum")):
            cls._assign_value_fields(migrated, migrated["value"])
        legacy_refs: List[str] = []
        for key in ("derivation_refs", "upstream_refs", "origin_chain_refs", "derived_from_measurement_ids"):
            values = migrated.get(key) or []
            if isinstance(values, list):
                legacy_refs.extend(str(value) for value in values)
        if "derivation_refs" not in migrated and legacy_refs:
            migrated["derivation_refs"] = sorted(set(legacy_refs))
        if "target_ref" not in migrated:
            refs = migrated.get("derivation_refs") or migrated.get("upstream_refs") or []
            migrated["target_ref"] = refs[0] if refs else ""
        return migrated

    @model_validator(mode="after")
    def _sync_legacy_ref_aliases(self) -> "MeasurementRecord":
        merged_refs = sorted(
            set(
                list(self.derivation_refs)
                + list(self.upstream_refs)
                + list(self.origin_chain_refs)
                + list(self.derived_from_measurement_ids)
            )
        )
        self.derivation_refs = merged_refs
        if not self.upstream_refs:
            self.upstream_refs = list(merged_refs)
        if not self.origin_chain_refs:
            self.origin_chain_refs = list(merged_refs)
        if not self.target_ref and merged_refs:
            self.target_ref = merged_refs[0]
        return self

    @staticmethod
    def _assign_value_fields(payload: Dict[str, Any], value: Any) -> None:
        payload["value_num"] = None
        payload["value_bool"] = None
        payload["value_enum"] = None
        if isinstance(value, bool):
            payload["value_bool"] = value
        elif isinstance(value, (int, float)):
            payload["value_num"] = float(value)
        elif value is not None:
            payload["value_enum"] = str(value)

    @property
    def branch(self) -> MeasurementBranch:
        return self.measurement_family

    @branch.setter
    def branch(self, value: MeasurementBranch) -> None:
        self.measurement_family = value

    @computed_field(return_type=Any)
    @property
    def value(self) -> Any:
        return self.value_resolved()

    @value.setter
    def value(self, value: Any) -> None:
        payload: Dict[str, Any] = {}
        self._assign_value_fields(payload, value)
        self.value_num = payload["value_num"]
        self.value_bool = payload["value_bool"]
        self.value_enum = payload["value_enum"]

    def value_resolved(self) -> Any:
        if self.value_bool is not None:
            return self.value_bool
        if self.value_num is not None:
            return self.value_num
        return self.value_enum


class MeasurementState(BaseModel):
    measurement_state_id: str
    defect_geometry_measurements: List[MeasurementRecord] = Field(default_factory=list)
    coverage_sampling_measurements: List[MeasurementRecord] = Field(default_factory=list)
    technical_validation_measurements: List[MeasurementRecord] = Field(default_factory=list)
    structural_assessment_measurements: List[MeasurementRecord] = Field(default_factory=list)


# W2 dataclass 已物理迁出（DEBT-018-followup-1 第一波 2026-05-13）：
# ThresholdEval / ReportBasisItem / ProjectionFamilyEval / NormativeProjection
# + ThresholdOperator / ThresholdRegime Literal 类型
# 全部迁到 `workflow_engine.regulation_projection_models`（W2 平级位置）。
# 消费方需要这些类型时直接 `from workflow_engine.regulation_projection_models import ...`。
# 2026-05-13 backward-compat re-export 删除（无消费方依赖旧路径，grep 确认）。


class BuildingContext(BaseModel):
    """spec 04 §4 BuildingContext 字段合约（8 字段，给 W2 / 下游消费方使用）.

    W0-008 拆分（2026-05-21）：原本含 3 个内部字段
    (`building_template_id` / `building_name` / `unit_count`)，按 spec 04 §4 line 72-83
    的 8 字段表收紧；3 个内部字段迁移到 `BuildingMetadata`，由
    `WorldBundle.building_metadata` 字段承载。
    """
    building_id: str
    building_use: str
    structure_type: str
    age_years: float
    storey_count: int
    primary_materials: List[str] = Field(default_factory=list)
    configuration_tags: List[str] = Field(default_factory=list)
    occupancy_state: str


class BuildingMetadata(BaseModel):
    """W0-008 (2026-05-21)：generator 内部 metadata（3 字段），不入 W2 contract.

    用途：
    - `building_template_id`：generator 内部用于 fragment_template_registry 匹配 / archetype plan
      复算；spec 11 §2.3 fragment_template_registry 用 `building_template_id` 做 join key，
      所以 round-trip 还原 batch 时必须保留.
    - `building_name`：reporting / human-readable label 用（reporting.py 等模块）.
    - `unit_count`：sidecar / reporting 可能引用的 building-level 计数；保留作 round-trip 索引.

    **不属于 spec 04 §4 BuildingContext 8 字段合约**；W2 / projection layer 不应消费此 class.
    """
    building_template_id: str
    building_name: str
    unit_count: int


class FragmentContext(BaseModel):
    """W0-005 (2026-05-21)：spec 04 §7 FragmentContext 9 字段 reference-based contract——
    generator pipeline 内部及 WorldBundle.fragments contract 唯一的 fragment 形态.

    spec 04 §7 line 108-120 + 封口总则 §2 line 27 权威：FragmentContext 是
    reference-based contract，物理参数（material_system / structural_role / exposure_zone
    / geometry_proxy / cover_depth_mm / has_rebar / 等）按 spec 04 §5 ComponentNode 8+1 字段
    + spec 04 §6 LocationNode 5 字段走 `component_id → ComponentNode` / `location_id →
    LocationNode` 反查路径承担.

    spec 04 §7 + spec 15 §4.3 + spec 06 §0.1 + 顶层封口总则 §2 已 align（commit 6234257）.
    generator 内部 pipeline（generate_mechanism / generate_condition /
    generate_*_measurements 等）全部走显式 ComponentNode + LocationNode 参数（spec 06 §0.1
    reference 反查），不再保留 denormalized cache 中间层（W0-005 删除 FragmentRuntimeState）.
    """
    fragment_id: str
    fragment_template_id: str
    component_id: str
    location_id: str
    fragment_role: str
    fragment_area_m2: float
    fragment_length_m: Optional[float] = None
    in_scope: bool = True
    exclusion_reason: Optional[str] = None


class ComponentNode(BaseModel):
    """spec 04 §5 ComponentNode 8 + 1 字段 contract（W0-004 step 2 2026-05-21 加 cover_depth_mm）.

    `cover_depth_mm`：RC-specific 物理参数；`material_system == reinforced_concrete` 时必填非
    null，其他材质（masonry / steel / composite 等）为 null。reference-based 反查路径
    `fragment.component_id → ComponentNode.cover_depth_mm`（spec 04 §5 + spec 06 §0.1 + spec 15
    §4.4 + 顶层封口总则 §2 line 27 背书）.
    """
    component_id: str
    component_type: str
    parent_component_id: Optional[str] = None
    material_system: str
    structural_role: str
    location_id: str
    geometry_proxy: Dict[str, Any] = Field(default_factory=dict)
    cover_depth_mm: Optional[float] = None
    access_class: str


class LocationNode(BaseModel):
    location_id: str
    location_class: str
    exposure_zone: str
    storey_band: str
    spatial_tags: List[str] = Field(default_factory=list)


class CoverageRelation(BaseModel):
    coverage_id: str
    coverage_relation_type: str
    target_fragment_id: str
    coverage_state: str
    covered_area_m2: float
    inspected_area_m2: float
    obscuration_class: str


class ConditionState(BaseModel):
    condition_id: str
    fragment_id: str
    mechanism_state_id: str = ""  # T-11 新增，引用 MechanismState
    condition_class: str  # T-11 rename from dominant_condition_type；spec 主名
    severity_band: SeverityBand = "moderate"
    severity_index: float = 0.0  # T-11 新增 (C-D)
    extent_area_m2: Optional[float] = None  # T-11 新增
    extent_length_m: Optional[float] = None  # T-11 新增
    depth_mm: Optional[float] = None  # T-11 新增
    count: Optional[int] = None  # T-11 新增
    uncertainty_flag: bool = False  # T-11 新增
    defect_condition_ids: List[str] = Field(default_factory=list)
    condition_classes: List[str] = Field(default_factory=list)
    # spec 草案·DEBT-049 第一波 §2（2026-07-08 v2）：机制可达而未出现的缺陷类
    # （模板机制×组件相容×发射分支可达）。第三波件A 后降级为审计辅助字段
    # （ClassReachabilityAudit 三态区分用），检索侧闭世界负例改消费下面的全集字段。
    generatable_absent_classes: List[str] = Field(default_factory=list)
    # spec 草案·DEBT-049 第三波 件A（闭世界总声明，codex 仲裁修正后通过，2026-07-08）：
    # 全集缺席类 = 缺陷分类注册表全集 − 实际类。W0 世界按构造完备，未生成即不存在；
    # 防伪装建模缺口的职责移交 ClassReachabilityAudit 硬审计产物。
    absent_condition_classes: List[str] = Field(default_factory=list)
    manifestation_flags: List[ManifestationFlag] = Field(default_factory=list)
    derived_outcomes: DerivedOutcomeState = Field(default_factory=DerivedOutcomeState)
    source_tags: List[str] = Field(default_factory=list)


class RepairAssessmentState(BaseModel):
    repair_assessment_id: str
    fragment_id: str
    repair_quality_index: Optional[float] = None
    repair_required: bool = False
    maintenance_required: bool = False
    verification_failed: bool = False
    safe_until_next_cycle: Optional[bool] = None
    residual_risk_index: Optional[float] = None
    notes: List[str] = Field(default_factory=list)


class WorldLifecycleState(BaseModel):
    ri_appointment: bool = False
    inspection_completed: bool = False
    uncertainty_raised: bool = False
    investigation_intention: bool = False
    investigation_proposal: bool = False
    repair_required: bool = False
    repair_completed: OutcomeFlagValue = False
    supervision_active: bool = False
    completion_report_prepared: bool = False
    completion_report_submitted: OutcomeFlagValue = False


# T-17h: WorldItem class removed (was OLD fragment-centric record per v2 schema_version
# "worldgen.fullcoverage.world_record.v2"). Replaced by WorldBundle (spec 04 §3 building-centric)
# defined further below.


# T-17h: WorldBundle (batch container with worlds: List[WorldItem]) removed.
# T-17i (rename) 后将把 WorldBundle 重命名为 WorldBundle (spec 04 §3 单 building 形态)；
# batch 容器形态由 v2 entry 输出的 dict (output JSON) 承担，无需 pydantic class wrapping。


class WorldBundle(BaseModel):  # T-17a 新增 (D05-1 / T-17.1) — spec 04 §3 building-centric WorldBundle
    """Building-centric world record per spec 04 §3.

    T-17a 阶段：仅含 building shell（BuildingContext + components + locations）；
    fragments / drivers / mechanisms / conditions / measurements 等列表 T-17b/c 才填。

    T-17d 收尾时 rename：当前 batch container 形态的 `WorldBundle` → `BatchBundle`；
    `WorldBundle` → `WorldBundle`（对齐 spec 04 §3 命名）。中间过渡期 (T-17a~T-17c)
    两 class 并存：`WorldBundle` 仍保 batch container（兼容 hydration._build_worlds 旧路径），
    `WorldBundle` 是新 building-centric 形态。
    """

    schema_version: str = "worldgen.fullcoverage.world.v1"
    world_id: str  # ^WB-[A-Z0-9-]+$
    generator_version: str = GENERATOR_VERSION
    random_seed: int = DEFAULT_BATCH_RANDOM_SEED
    building: BuildingContext
    # W0-008 (2026-05-21)：generator 内部 metadata（building_template_id / building_name /
    # unit_count），不属于 spec 04 §4 BuildingContext contract；W2 不消费.
    building_metadata: BuildingMetadata
    # W0-005 (2026-05-21)：spec 04 §7 FragmentContext 9 字段 reference-based contract
    # （顶层封口总则 §2 line 27 + spec 15 §4.3 fragments.parquet schema 背书）.
    # 物理上下文（material_system / structural_role / cover_depth_mm / geometry / exposure_zone
    # 等）由消费方按 spec 06 §0.1 reference 反查路径，通过 `fragment.component_id → ComponentNode`
    # / `fragment.location_id → LocationNode` 反查；不在 fragments 列内 denormalize.
    # generator pipeline 函数（generate_mechanism / generate_condition / generate_*_measurements）
    # 全部走显式 ComponentNode + LocationNode 参数（spec 06 §0.1 reference 反查路径），无中间 cache class.
    fragments: List[FragmentContext] = Field(default_factory=list)
    components: List[ComponentNode] = Field(default_factory=list)
    locations: List[LocationNode] = Field(default_factory=list)
    coverage_relations: List[CoverageRelation] = Field(default_factory=list)
    drivers: List[DriverState] = Field(default_factory=list)
    mechanisms: List[MechanismState] = Field(default_factory=list)
    conditions: List[ConditionState] = Field(default_factory=list)
    drainage_states: List[DrainageState] = Field(default_factory=list)
    ubw_states: List[UBWState] = Field(default_factory=list)
    fire_safety_states: List[FireSafetyState] = Field(default_factory=list)
    repair_assessment_states: List[RepairAssessmentState] = Field(default_factory=list)
    measurements: List[MeasurementRecord] = Field(default_factory=list)
    # W1-004 / spec 08 §5：顶层 derived_outcomes 汇总——A 类 6 个综合派生 flag (risk / repair) 写在
    # 这里供 W2 projection executor 按 spec 8 §5 + §3.A 消费；B 类 8 个业务直通类 flag 数据**不再在
    # 此重派**，consumer 直接查对应 State 字段（DrainageState.connection_state 等，详见 spec 08 §3.B）.
    # 同时保留 per-condition derived_outcomes 写入路径作历史兼容（spec 03 step 9 描述派生顺序在 per-
    # condition 粒度计算，顶层是 aggregate）.
    derived_outcomes: Dict[str, Any] = Field(default_factory=dict)


class SlotOwnershipEntry(BaseModel):
    slot_id: str
    partition: SlotPartition
    carrier: str
    notes: str = ""


class SidecarInterfaceField(BaseModel):
    field_id: str
    partition: SlotPartition
    source_slot_ids: List[str] = Field(default_factory=list)
    target_slot_ids: List[str] = Field(default_factory=list)
    notes: str = ""


class SidecarInterfaceSchema(BaseModel):
    interface_id: str
    sidecar_domain: str
    input_fields: List[SidecarInterfaceField] = Field(default_factory=list)
    output_fields: List[SidecarInterfaceField] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class SidecarContract(BaseModel):
    version: str = "worldgen.fullcoverage.sidecar.v1"
    generated_at: str
    ownership_map: List[SlotOwnershipEntry] = Field(default_factory=list)
    interface_schema: List[SidecarInterfaceSchema] = Field(default_factory=list)


class SidecarRuntimeValue(BaseModel):
    slot_id: str
    value: Any
    # 量纲（q6 专员裁定 2026-07-08：卡端 unit 声明合法且注册表登记；数据端缺单位
    # 致闭包单位规则保守拦截——数值行从 sidecar_measurement_registry 带出 unit）。
    unit: Optional[str] = None
    qualifiers: Dict[str, Any] = Field(default_factory=dict)
    time_anchor_key: Optional[str] = None
    source_refs: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class SidecarRuntimeRecord(BaseModel):
    runtime_id: str
    world_id: str
    projection_id: str
    interface_ids: List[str] = Field(default_factory=list)
    facts: List[SidecarRuntimeValue] = Field(default_factory=list)
    runtime_markers: List[SidecarRuntimeValue] = Field(default_factory=list)
    artifact_requirement_state: List[SidecarRuntimeValue] = Field(default_factory=list)
    procedure_gate_state: List[SidecarRuntimeValue] = Field(default_factory=list)
    supervision_runtime_state: List[SidecarRuntimeValue] = Field(default_factory=list)
    completion_runtime_state: List[SidecarRuntimeValue] = Field(default_factory=list)


class SidecarRuntimeBundle(BaseModel):
    version: str = "worldgen.fullcoverage.sidecar_runtime.v2"
    generated_at: str
    source_documents: List[str] = Field(default_factory=list)
    records: List[SidecarRuntimeRecord] = Field(default_factory=list)


# spec 09 §1.2 修订（2026-05-09）：废止 SidecarInput class.
# 旧设计假设 sidecar B 类 slot 由外部 admin record 注入；本数据生成项目无外部供给方，
# sidecar bundle 由 worldgen 同 pipeline 自家派生层生成（详见 spec 09 §1.2、sidecar.py）.


class ValidationCheck(BaseModel):
    check_id: str
    passed: bool
    detail: str


class ValidationReport(BaseModel):
    version: str = "worldgen.fullcoverage.validation.v3"
    generated_at: str
    checks: List[ValidationCheck] = Field(default_factory=list)
    # W1-RC-02 / spec 10 §6 silent fallback 红线：sidecar conditional formula 异常 fallback
    # 到 marginal 时的 per reason class 计数，batch 级可见性落地点。framework_v2 主入口无
    # BatchGateStats，故计数落 validation_report 作持久化 audit 产物（空 dict = 本批次无 fallback）.
    sidecar_fallback_counts: Dict[str, int] = Field(default_factory=dict)


class StageArtifactRef(BaseModel):
    stage_name: str
    artifact_path: str
    record_count: int
    notes: List[str] = Field(default_factory=list)


class FrameworkManifest(BaseModel):
    version: str = "worldgen.fullcoverage.manifest.v3"
    generated_at: str
    generator_version: str = GENERATOR_VERSION
    projection_executor_version: str = "regulation_projection.v1"  # T-29 (D10-1): 法规映射层独立版本号
    batch_profile: str
    registry_bundle_hash: str
    batch_config_hash: str
    deterministic_key: str
    supported_batch_contracts: Dict[str, int] = Field(default_factory=dict)
    source_documents: List[str] = Field(default_factory=list)
    stage_artifacts: List[StageArtifactRef] = Field(default_factory=list)
    runner_entrypoint: Dict[str, str] = Field(default_factory=dict)


class FrameworkSummary(BaseModel):
    version: str = "worldgen.fullcoverage.summary.v3"
    generated_at: str
    generator_version: str = GENERATOR_VERSION
    projection_executor_version: str = "regulation_projection.v1"  # T-29 (D10-1)
    requested_count: int
    seed: int
    batch_profile: str
    registry_bundle_hash: str
    batch_config_hash: str
    deterministic_key: str
    registry_count: int
    world_count: int
    projection_count: int
    sidecar_runtime_count: int
    template_distribution: Dict[str, int] = Field(default_factory=dict)
    projection_distribution: Dict[str, int] = Field(default_factory=dict)
    severity_distribution: Dict[str, int] = Field(default_factory=dict)
    domain_bucket_distribution: Dict[str, int] = Field(default_factory=dict)
    fragment_family_distribution: Dict[str, int] = Field(default_factory=dict)
    domain_tag_distribution: Dict[str, int] = Field(default_factory=dict)
    measurement_branch_distribution: Dict[str, int] = Field(default_factory=dict)
    manifestation_flag_distribution: Dict[str, Dict[str, int]] = Field(default_factory=dict)
    sidecar_fact_count: int = 0
    sidecar_marker_distribution: Dict[str, int] = Field(default_factory=dict)
    slot_partition_counts: Dict[str, int] = Field(default_factory=dict)
    measurement_branch_coverage: Dict[str, bool] = Field(default_factory=dict)
    release_coverage_assertions: Dict[str, Any] = Field(default_factory=dict)
    projection_verdict_coverage: str = "unverified"
    DoD_status: Dict[str, bool] = Field(default_factory=dict)
    framework_completed: bool = False


class FullCoverageFrameworkBundle(BaseModel):
    output_dir: str
    requested_count: int
    seed: int
    registry_bundle_path: str
    world_bundle_path: str
    sidecar_contract_path: str
    sidecar_runtime_bundle_path: str
    validation_report_path: str
    manifest_path: str
    summary_path: str
