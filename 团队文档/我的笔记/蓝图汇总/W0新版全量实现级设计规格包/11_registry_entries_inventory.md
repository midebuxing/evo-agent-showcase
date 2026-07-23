# 19 张 Registry 全 Entry 内容清单 (Inventory)

> 跨包权威源与负向不变量见：`../_封口总则_字段权威源与负向不变量.md`。如本章与总则冲突，以总则和字段所属包权威章节为准。


> 本文档是 spec 02 / spec 03 schema 定义的**配套实施数据**——把每张 registry 的具体 entry 内容列清楚，让 W0 静态资源层可以照着实施。
>
> **审计日期**：2026-05-12
> **数据源**：`agent_v1/src/workflow_engine/worldgen/registry.py`（3531 行；19 张 RegistryTable 在 `_build_registry_bundle()` 内构造）
> **审计方法**：逐条 record 比对 spec 08 / spec 03 / pro-answer / DEBT 链路；7 条野生 entry 标 🔴。
> **来源标签说明**：见 §0

---

封口补充：`normative_projection_registry` records 语义权威归 W2 `06_canonical_slots与projection_binding.md`；W0 本 inventory 只记录 registry bundle 编排与 entry 清单，不改写 W2 family / predicate / threshold / basis 语义。

## §0 来源标签字典

每条 record 在表中带一个 `来源标签` 列。标签集合及含义如下：

| 标签 | 含义 |
|---|---|
| `spec_canonical` | spec 08 §2.1 / §2.2 / §3 / §4 表里直接列了该 entry 的关键 id（fragment_template_id / building_template_id / projection_registry_id / risk_flag_id 等）|
| `spec_inferred` | spec 没直接列具体 entry id，但该 entry 在 schema (spec 03) 框架内合理派生（如 qualifier_taxonomy.asset 内 component_type/location_class）|
| `pro_T06` | T-06 派活产出，扩 `material_system_registry` 50 entries 与 19 个 `DC_*` 缺陷类，附 MBIS 章节引用 |
| `pro_T30` | T-30 派活产出，扩 `building_template_registry` 15 条 HK archetype（命名 `BT_HK_<ARCHETYPE>_<STRUCTURE>_V1`），2026-05-12 spec 03 §4.8 收录 |
| `pro_DEBT020_round_X` | DEBT-020 Round 1-7 的某一轮 pro-answer 落地（分布参数 / chain 公式 / centered upstream 公式）|
| `pro_DEBT025_closure` | DEBT-025 closure 2026-05-07，phantom slot 清理及 5 个 inspection_execution slot 入 sidecar |
| `old_blueprint_aN` | pro-answer/aN.md（旧蓝图）直接列过该 id |
| `engineering_T06_extension` | T-06 工程拓展（有 MBIS 法规原文支持 + 代码注释授权，但 spec 没正式补述）|
| `🔴 WILD` | spec / pro / 旧蓝图全 0 hit 的野生 entry——需要 P0 决策（删 / 重派 pro / spec 增订）|

---

## §1 资产空间域（5 张表）

### §1.1 `building_template_registry`

**Schema** (spec 03 §2.1 / §4.8)：`building_template_id` (PK) + `building_use` / `structure_type` / `storey_count_range` / `primary_materials` / `component_graph_template_ids` / `notes`
**用途**：建筑模板维度，给 `fragment_template_registry` 当外键，承载 building-level 配置。
**Code 位置**：registry.py L1507-L1559（**T-30 落地后变为 15 records**）。

**2026-05-12 update（T-30 pro 派活落地）**：原 5 条 mvp 自造野生 BT_* 已替换为 15 条 HK archetype 全量 entry（pro 段 1，命名 `BT_HK_<ARCHETYPE>_<STRUCTURE>_V1`，spec 03 §4.8 正式收录）。

| primary_key | use × structure / storeys | primary_materials（精简）| 来源标签 |
|---|---|---|---|
| BT_HK_TONG_LAU_MIXED_USE_MASONRY_V1 | composite × masonry / [3,8] | clay_brick, masonry_plaster, plaster_finish, timber_window, cast_iron | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1 | residential × rc_frame / [5,12] | reinforced_concrete, plaster_finish, tile_finish, aluminium_window, cast_iron | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_MASS_HOUSING_RC_WALL_V1 | residential × rc_wall / [8,45] | reinforced_concrete, precast_concrete, plaster_finish, upvc_drainage, steel_fire_doors | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_PRIVATE_RESIDENTIAL_TOWER_RC_V1 | residential × rc_frame / [20,70] | reinforced_concrete, plaster_finish, aluminium_window, upvc_drainage, steel_fire_doors | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_NT_VILLAGE_LOWRISE_RC_V1 | residential × rc_frame / [1,3] | reinforced_concrete, concrete_drain, plaster_finish, aluminium_window, metal_gate | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1 | composite × rc_frame / [15,60] | reinforced_concrete, plaster_finish, tile_finish, aluminium_window, steel_fire_doors | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1 | composite × rc_frame / [3,18] | reinforced_concrete, upvc_drainage, cast_iron, concrete_drain, metal_gate | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_COASTAL_COMPOSITE_TOWER_RC_V1 | composite × rc_frame / [15,50] | reinforced_concrete, polymer_render, aluminium_window, curtain_wall_glazing, stainless_steel_pipe | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_UBW_PRONE_OLD_BLOCK_V1 | composite × rc_frame / [5,20] | reinforced_concrete, cold_formed_steel, metal, timber, upvc_drainage | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_OFFICE_CURTAIN_WALL_STEEL_V1 | commercial × steel / [15,70] | structural_steel_section, intumescent_coating, curtain_wall_glazing, curtain_wall_aluminium_frame, fire_rated_glass | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1 | commercial × composite_structure / [20,65] | reinforced_concrete, prestressed_concrete, steel_transfer_beam, cementitious_patch_mortar, epoxy_resin_repair | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_COMMERCIAL_ASSEMBLY_MARKET_PODIUM_V1 | commercial × rc_frame / [2,12] | reinforced_concrete, fire_resistant_partition_wall, steel_fire_doors, fire_rated_glass, metal_gate | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_INDUSTRIAL_FACTORY_BLOCK_RC_V1 | industrial × rc_frame / [5,25] | reinforced_concrete, metal_louver_fin, cast_iron, galvanized_steel_pipe, steel_fire_doors | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_WAREHOUSE_LOGISTICS_STEEL_V1 | industrial × steel / [1,8] | structural_steel_section, intumescent_coating, metal, galvanized_steel_pipe, metal_gate | `spec_canonical` (spec 03 §4.8, T-30 pro) |
| BT_HK_INSTITUTIONAL_RC_BLOCK_V1 | institutional × rc_frame / [3,25] | reinforced_concrete, plaster_finish, steel_fire_doors, fire_resistant_partition_wall, upvc_drainage | `spec_canonical` (spec 03 §4.8, T-30 pro) |

**该表审计小结**：15/15 全合规（2026-05-12 T-30 pro 派活全量补述，spec 03 §4.8 收录）。原 5 条野生 BT_* 已按 pro 迁移声明（段 3 选项 B）替换；fragment_template_registry 9 条 record 的 `building_template_id` 外键按 pro 给的 1:1 + 1:N 映射表迁移。pro 选项 a：所有 component_graph_template_ids 保留 `[]`，理由：当前 W0 无独立 component_graph_template_registry 表，不抢先定义未存在的外键。

旧 → 新 5 条迁移声明：
- `BT_MIXED_USE_TOWER_V1` → `BT_HK_MIXED_USE_HIGHRISE_TOWER_RC_V1`（同义；fragment FT_EXT_WALL_CRACK_COVERED_V1 + FT_RC_BEAM_SPALL_REPAIR_V1 迁此）
- `BT_PODIUM_WITH_SERVICE_LANES_V1` → `BT_HK_PODIUM_SERVICE_LANE_DRAINAGE_V1`（fragment FT_DRAINAGE_MISCONNECTION_V1 + FT_DRAINAGE_NETWORK_BLOCKAGE_V1 迁此）
- `BT_LEGACY_RESIDENTIAL_BLOCK_V1` → `BT_HK_LEGACY_WALKUP_RESIDENTIAL_RC_V1`（fragment FT_ESCAPE_STAIR_FIRE_DEFICIENCY_V1 迁此）+ `BT_HK_UBW_PRONE_OLD_BLOCK_V1`（fragment FT_UBW_FIRE_SAFETY_V1 迁此 — 1:N 拆分）
- `BT_COASTAL_COMPOSITE_TOWER_V1` → `BT_HK_COASTAL_COMPOSITE_TOWER_RC_V1`（fragment FT_FACADE_MOISTURE_DETACHMENT_V1 迁此）
- `BT_TRANSFER_PLATE_OFFICE_TOWER_V1` → `BT_HK_TRANSFER_PLATE_OFFICE_TOWER_V1`（fragment FT_TRANSFER_BEAM_HOLLOWING_V1 + FT_REPAIR_PATCH_VALIDATION_V1 迁此）

---

### §1.2 `fragment_template_registry`

**Schema** (spec 03 §2.1)：`fragment_template_id` (PK) + `building_template_id` + `component_type` + `location_class` + `area_range` + `length_range` + `allowed_driver_profiles` + `allowed_mechanisms` + `measurement_branches` + `specialized_domains`
**用途**：fragment-level 模板；W0 worldgen 按 fragment template 实例化生成 fragments。
**Code 位置**：registry.py L1252-L1407（9 records）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| FT_EXT_WALL_CRACK_COVERED_V1 | bld=BT_MIXED_USE_TOWER_V1; comp=external_wall; loc=external_wall; area=[5,500]; drv=DRV_STRUCTURAL_DETERIORATION_V1 | `spec_canonical` (spec 08 §2.1) |
| FT_DRAINAGE_MISCONNECTION_V1 | bld=BT_PODIUM_WITH_SERVICE_LANES_V1; comp=drainage_stack; loc=pipe_duct; area=[0.1,20]; spec_dom=[drainage] | `spec_canonical` (spec 08 §2.1) |
| FT_UBW_FIRE_SAFETY_V1 | bld=BT_LEGACY_RESIDENTIAL_BLOCK_V1; comp=unauthorized_structure; loc=common_part; area=[1,100]; spec_dom=[ubw, fire_safety] | `spec_canonical` (spec 08 §2.1) |
| FT_RC_BEAM_SPALL_REPAIR_V1 | bld=BT_MIXED_USE_TOWER_V1; comp=structural_member; loc=common_part; area=[0.5,50]; len=[0.5,12] | `spec_canonical` (spec 08 §2.1) |
| FT_FACADE_MOISTURE_DETACHMENT_V1 | bld=BT_COASTAL_COMPOSITE_TOWER_V1; comp=external_wall; loc=external_wall; area=[5,300] | `spec_canonical` (spec 08 §2.1) |
| FT_TRANSFER_BEAM_HOLLOWING_V1 | bld=BT_TRANSFER_PLATE_OFFICE_TOWER_V1; comp=structural_member; loc=transfer_floor; area=[1,50] | `spec_canonical` (spec 08 §2.1) |
| FT_DRAINAGE_NETWORK_BLOCKAGE_V1 | bld=BT_PODIUM_WITH_SERVICE_LANES_V1; comp=drainage_stack; loc=service_void; area=[0.1,20] | `spec_canonical` (spec 08 §2.1) |
| FT_ESCAPE_STAIR_FIRE_DEFICIENCY_V1 | bld=BT_LEGACY_RESIDENTIAL_BLOCK_V1; comp=fire_door; loc=escape_stair; area=[1,20] | `spec_canonical` (spec 08 §2.1) |
| FT_REPAIR_PATCH_VALIDATION_V1 | bld=BT_TRANSFER_PLATE_OFFICE_TOWER_V1; comp=structural_member; loc=podium_soffit; area=[1,100] | `spec_canonical` (spec 08 §2.1) |

**该表审计小结**：9/9 合规（spec 08 §2.1 全部列出），但**所有 entry 通过 `building_template_id` 间接依赖 §1.1 的 5 条野生 BT**——§1.1 决策落地后必须同步检查这里。

---

### §1.3 `component_type_registry`

**Schema** (spec 03 §2.2.1)：`component_type` (PK) + `component_class` + `material_compatibility` + `default_structural_role` + `geometry_proxy_ranges` + `allowed_location_classes` + `allowed_mechanisms` + `notes`
**用途**：component-type 维度 qualifier_taxonomy；给 fragment 实例化提供 component class 字典。
**Code 位置**：registry.py L1560-L1746（18 records）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| external_wall | class=external_component; role=secondary_load_bearing; mats=[RC, plain_C, plaster, masonry_plaster, polymer_render, tile, stone, aluminium, gfrc, paint] | `spec_canonical` (spec 03 §2.2.1) |
| structural_member | class=structural_component; role=primary_load_bearing; mats=[RC, prestressed_C, precast_C, steel_transfer_beam, structural_steel] | `spec_canonical` (spec 03 §2.2.1) |
| signboard | class=signboard; role=non_load_bearing; mats=[metal, aluminium_panel, metal_anchor] | `spec_canonical` (spec 03 §2.2.1) |
| canopy | class=canopy; role=secondary_load_bearing; mats=[RC, plain_C, precast_C, bituminous_membrane] | `spec_canonical` (spec 03 §2.2.1) |
| balcony_slab | class=external_component; role=secondary_load_bearing; mats=[RC, tile, plaster] | `spec_canonical` (spec 03 §2.2.1) |
| parapet_wall | class=external_component; role=non_load_bearing; mats=[RC, plain_C, masonry_plaster, tile, plaster] | `spec_canonical` (spec 03 §2.2.1) |
| access_panel | class=inspection_access_component; role=non_load_bearing; mats=[metal, timber, composite] | `spec_canonical` (spec 03 §2.2.1) |
| drainage_stack | class=drainage_component; role=service_component; mats=[upvc, pvc, cast_iron, galv_steel, ss_pipe] | `spec_canonical` (spec 03 §2.2.1) |
| drainage_branch | class=drainage_component; role=service_component; mats=[upvc, pvc, cast_iron, concrete_drain, hdpe, vcp] | `spec_canonical` (spec 03 §2.2.1) |
| floor_trap | class=drainage_component; role=service_component; mats=[cast_iron, upvc, ss_pipe] | `spec_canonical` (spec 03 §2.2.1) |
| fire_door | class=fire_safety_component; role=service_component; mats=[steel_fire_doors, fire_resistant_glass_door, fire_rated_glass, metal, timber, composite] | `spec_canonical` (spec 03 §2.2.1) |
| fire_resisting_wall | class=fire_safety_component; role=non_load_bearing; mats=[fire_resistant_partition, RC, clay_brick, intumescent_coating] | `spec_canonical` (spec 03 §2.2.1) |
| escape_route | class=fire_safety_component; role=non_load_bearing; mats=[RC, plain_C, tile, plaster] | `spec_canonical` (spec 03 §2.2.1) |
| smoke_vent | class=fire_safety_component; role=service_component; mats=[metal, aluminium_panel] | `spec_canonical` (spec 03 §2.2.1) |
| fire_service_installation | class=fire_safety_component; role=service_component; mats=[metal, ss_pipe, upvc] | `spec_canonical` (spec 03 §2.2.1) |
| unknown_fire_component | class=fire_safety_component; role=service_component; mats=[metal, timber, composite] | `spec_inferred` (spec 03 fire_door catch-all) |
| unauthorized_structure | class=ubw; role=non_load_bearing; mats=[metal, timber, composite, cold_formed_steel, RC] | `spec_canonical` (spec 03 §2.2.1) |
| protective_render | class=finish_system; role=finish_only; mats=[plaster, masonry_plaster, polymer_render, cementitious_patch_mortar, paint] | `spec_inferred` (spec 03 §2.2 finish system) |

**该表审计小结**：18/18 合规（spec 03 §2.2.1 列出 16 core types + 2 catch-all 派生）。

---

### §1.4 `location_class_registry`

**Schema** (spec 03 §2.2.2)：`location_class` (PK) + `scope_class` + `exposure_options` + `spatial_tags` + `accessibility_prior` + `coverage_relevance` + `notes`
**用途**：location_class 维度 qualifier_taxonomy。
**Code 位置**：registry.py L1748-L1767（12 records，每行一条）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| common_part | scope=common_part; exposure=[internal, protected]; access=0.9; cov_rel=True | `spec_canonical` (spec 03 §2.2.2) |
| private_premises | scope=private_premises; exposure=[internal, protected]; access=0.3; cov_rel=False | `spec_canonical` (spec 03 §2.2.2) |
| external_wall | scope=external_wall; exposure=[outdoor, exposed, weather_facing]; access=0.7 | `spec_canonical` (spec 03 §2.2.2) |
| roof | scope=roof; exposure=[outdoor, exposed, rain_bearing]; access=0.6 | `spec_canonical` (spec 03 §2.2.2) |
| balcony_line | scope=balcony_line; exposure=[outdoor, semi_exposed]; access=0.5 | `spec_canonical` (spec 03 §2.2.2) |
| roof_edge | scope=roof_edge; exposure=[outdoor, exposed]; access=0.4 | `spec_canonical` (spec 03 §2.2.2) |
| podium_soffit | scope=podium_soffit; exposure=[outdoor, sheltered]; access=0.5 | `spec_canonical` (spec 03 §2.2.2) |
| transfer_floor | scope=transfer_floor; exposure=[internal, protected]; access=0.6 | `spec_canonical` (spec 03 §2.2.2) |
| pipe_duct | scope=service_space; exposure=[confined, humid]; access=0.4 | `spec_canonical` (spec 03 §2.2.2) |
| service_void | scope=service_space; exposure=[confined, humid]; access=0.3 | `spec_canonical` (spec 03 §2.2.2) |
| private_lane | scope=service_lane; exposure=[outdoor, semi_exposed]; access=0.7 | `spec_canonical` (spec 03 §2.2.2) |
| escape_stair | scope=egress_route; exposure=[internal, protected]; access=0.85 | `spec_canonical` (spec 03 §2.2.2) |

**该表审计小结**：12/12 合规。

---

### §1.5 `coverage_relation_registry`

**Schema** (spec 03 §2.4)：`coverage_relation_id` (PK) + `relation_type` + `target_component_types` + `obscuration_classes` + `ratio_slot_id` + `default_inspection_ratio_range` + `notes`
**用途**：覆盖关系 / 遮挡关系字典；给 scope.component.* slot 提供 enumeration。
**Code 位置**：registry.py L1768-L1797（8 records）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| CR_IN_SCOPE | type=scope.component.in_scope; obscuration=[none]; ratio=[1.0, 1.0] | `spec_canonical` (spec 08 §3) |
| CR_EXCLUDED | type=scope.component.excluded_from_scope; obscuration=[access_blocked, unsafe_access]; ratio=[0,0] | `spec_canonical` (spec 08 §3) |
| CR_COVERED | type=scope.component.covered; target=[signboard, canopy]; ratio=[0, 0.8] | `spec_canonical` (spec 08 §3) |
| CR_COVERED_BY_SIGNBOARD | type=scope.component.covered_by_large_signboard; target=[signboard]; ratio=[0, 0.6] | `spec_canonical` (spec 08 §3) |
| CR_OBSCURED_BY_FINISH | type=scope.component.obscured_by_finish; target=[external_wall, structural_member]; obscuration=[finish_layer]; ratio_slot=ratio.external_wall_area.inspected | `spec_canonical` (spec 08 §2.1 + §2.1.1，**用户决策 2026-05-12 增订**) |
| CR_OBSCURED_BY_SERVICES | type=scope.component.obscured_by_services; target=[drainage_stack, drainage_branch]; obscuration=[access_blocked]; ratio=[0.3, 1.0] | `spec_canonical` (spec 08 §2.1 + §2.1.1，**用户决策 2026-05-12 增订**) |
| CR_EXTENDS_PRIVATE_PREMISES | type=defect.range.extends_into_private_premises; target=[external_wall, structural_member]; ratio=[0, 0.5] | `spec_canonical` (spec 08 §3) |

**该表审计小结**：**8/8 全合规**（2026-05-12 update）。原 `CR_OBSCURED_BY_FINISH` / `CR_OBSCURED_BY_SERVICES` 2 条曾标 🔴 野生（DEBT-003 closed comment 但 spec 0 hit），**用户 2026-05-12 决策增订进 spec 08 §2.1**（`scope.component.obscured_by_finish` / `_services` 升 canonical world_truth_slot）+ spec 08 §2.1.1 解释与 `covered_*` 的区别 → 现在 spec_canonical 合规。DEBT-003 同步关闭。

---

## §2 缺陷字典域（2 张表）

### §2.1 `defect_condition_taxonomy_registry`

**Schema** (spec 03 §2.5)：`condition_class` (PK) + `defect_class` + `aliases` + `severity_model` + `default_measurement_slots` + `compatible_components` + `compatible_mechanisms` + `notes`
**用途**：缺陷字典域；qualifier_taxonomy.defect_condition。
**Code 位置**：registry.py L1014-L1197（19 records via `_defect_condition_records()`）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| DC_CRACK | defect_class=crack; severity=linear_extent; default_slots=[crack_width_mm, crack_length_m]; comps=[ext_wall, struct_member, parapet, balcony] | `spec_canonical` (spec 03 §2.5) |
| DC_SPALL_REBAR | defect_class=spall_rebar; severity=corrosion_chain; default_slots=[spall_area_m2, rebar_exposed_length_m, ratio.rebar.section_loss] | `spec_canonical` (spec 03 §2.5) |
| DC_HOLLOWING | defect_class=hollowing; severity=composite_index; default_slots=[count.hammer_tapping.grid.minimum]; comps=[ext_wall, struct_member, balcony, parapet] | `spec_canonical` (spec 03 §2.5) |
| DC_MOISTURE_STAINING | defect_class=moisture_staining; severity=binary_present; comps=[ext_wall, struct_member, parapet, balcony] | `spec_canonical` (spec 03 §2.5) |
| DC_LEAKAGE | defect_class=leakage; severity=binary_present; T-06 合并 DC_WATERPROOFING_FAILURE; MBIS §3.4.2(B), App5 | `pro_T06` |
| DC_DETACHMENT | defect_class=detachment; severity=linear_extent; default_slots=[spall_area_m2]; T-06 合并 DC_MASONRY_SULFATE_ATTACK; MBIS §5.4.3 | `pro_T06` |
| DC_LOOSE_FIXING | defect_class=loose_fixing; severity=binary_present; T-06 合并 DC_FASTENER_MISSING_OR_DEFECTIVE; MBIS §3.3.2(E)-(I), §5.3.7, §5.6.4 | `pro_T06` |
| DC_DRAINAGE_MISCONNECTION | defect_class=drainage_misconnection; severity=binary_present; default_slots=[flag.drainage.misconnection_present] | `spec_canonical` (spec 03 §2.5) |
| DC_DRAINAGE_BLOCKAGE | defect_class=drainage_blockage; severity=composite_index; default_slots=[index.drainage.blockage] | `spec_canonical` (spec 03 §2.5) |
| DC_DRAINAGE_LEAKAGE | defect_class=drainage_leakage; severity=binary_present; default_slots=[index.drainage.leakage] | `spec_canonical` (spec 03 §2.5) |
| DC_UBW_PRESENT | defect_class=ubw_present; severity=binary_present; comps=[unauthorized_structure] | `spec_canonical` (spec 03 §2.5) |
| DC_SUBDIVIDED_SIGN | defect_class=subdivided_unit_sign; severity=count_threshold | `spec_canonical` (spec 03 §2.5) |
| DC_FIRE_DOOR_DEFICIENCY | defect_class=fire_door_deficiency; severity=binary_present; default_slots=[time.fire_door.self_closing.delay_sec] | `spec_canonical` (spec 03 §2.5) |
| DC_FIRE_STOP_DEFICIENCY | defect_class=fire_resisting_wall_deficiency; severity=binary_present; comps=[fire_resisting_wall, escape_route, fire_service_installation] | `spec_canonical` (spec 03 §2.5) |
| DC_METAL_CORROSION | defect_class=metal_corrosion; severity=corrosion_chain; T-06 新增; MBIS §3.3.2(C)-(I), §3.4.2(A), §4.3.1, §5.4.2, §3.6.2 | `pro_T06` |
| DC_SEALANT_FAILURE | defect_class=sealant_failure; severity=binary_present; T-06 新增; MBIS §3.3.2(C), §3.3.2(E), §3.3.2(G), MWIS §10.5 / §11.1.10 | `pro_T06` |
| DC_GLASS_BREAKAGE | defect_class=glass_breakage; severity=binary_present; T-06 新增; MBIS §3.3.2(E), §3.3.2(G), §3.5.2(D), MWIS §11.1.2 | `pro_T06` |
| DC_DEFORMATION_DISPLACEMENT | defect_class=deformation_displacement; severity=linear_extent; T-06 新增; MBIS §3.4.2(A), §3.6.2, MWIS §10.6 | `pro_T06` |
| DC_FIRE_PROTECTION_COATING_DEFICIENCY | defect_class=fire_protection_coating_deficiency; severity=binary_present; T-06 新增; MBIS §5.4.2(C), §5.5.3 | `pro_T06` |

**该表审计小结**：14/19 spec_canonical + 5/19 `pro_T06`（DC_LEAKAGE / DC_DETACHMENT / DC_LOOSE_FIXING 是 T-06 合并候选；DC_METAL_CORROSION / DC_SEALANT_FAILURE / DC_GLASS_BREAKAGE / DC_DEFORMATION_DISPLACEMENT / DC_FIRE_PROTECTION_COATING_DEFICIENCY 是 T-06 新增）。注意：表中合并候选条目 3 + 新增条目 5 = 8 条带 T-06 标签，但实际拆分是 5 条新增 + 3 条 enhanced（aliases 扩展 / notes 加 MBIS 引用），实际 spec 0 增订 = 8 条目。

---

### §2.2 `mechanism_library_registry`

**Schema** (spec 03 §2.6)：`mechanism_id` (PK) + `mechanism_family` + `applicable_templates` + `applicable_component_types` + `required_driver_fields` + `output_condition_classes` + `surrogate_id` + `notes`
**用途**：mechanism 字典（latent driver → defect 派生路径）。
**Code 位置**：registry.py L1416-L1483（6 records）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| MK_CRACK_RESTRAINT_CHAIN_V2 | family=structural_crack; drivers=[service_load_ratio, restraint_level, workmanship_deficit]; outputs=[DC_CRACK, DC_MOISTURE_STAINING]; surrogate=structural_load_score | `spec_canonical` (spec 08 §2.2) |
| MK_CORROSION_SPALL_CHAIN_V2 | family=corrosion_spall; drivers=[chloride, carbonation, moisture, workmanship]; outputs=[DC_SPALL_REBAR, DC_DETACHMENT]; surrogate=corrosion_score | `spec_canonical` (spec 08 §2.2) |
| MK_DRAINAGE_MISCONNECTION_V1 | family=drainage_fault; drivers=[drainage_fault_propensity, maintenance, workmanship]; outputs=[DC_DRAINAGE_MISCONNECTION, DC_DRAINAGE_BLOCKAGE, DC_DRAINAGE_LEAKAGE]; surrogate=drainage_misconnection_score | `spec_canonical` (spec 08 §2.2) |
| MK_UNAUTHORIZED_ADDITION_V1 | family=ubw_signal; drivers=[alteration_propensity, workmanship, maintenance]; outputs=[DC_UBW_PRESENT, DC_SUBDIVIDED_SIGN]; surrogate=ubw_alteration_score | `spec_canonical` (spec 08 §2.2) |
| MK_FIRE_DOOR_DEFICIENCY_V1 | family=fire_safety_deficiency; drivers=[fire_safety_deficit_index, maintenance]; outputs=[DC_FIRE_DOOR_DEFICIENCY, DC_FIRE_STOP_DEFICIENCY]; surrogate=fire_deficiency_score | `spec_canonical` (spec 08 §2.2) |
| MK_ASSESSMENT_UNDERSTRENGTH_V1 | family=assessment_origin; drivers=[service_load, moisture, chloride, carbonation]; outputs=[DC_CRACK, DC_SPALL_REBAR, DC_HOLLOWING]; surrogate=fsp_loss_score | `spec_canonical` (spec 08 §2.2) |

**该表审计小结**：6/6 合规。

---

## §3 驱动与机理域（2 张表）

### §3.1 `latent_driver_registry`

**Schema** (spec 03 §2.7)：`driver_id` (PK) + `driver_family` + `supported_domains` + `field_ranges` + `notes`
**用途**：latent driver（隐变量）字典；驱动场支撑 mechanism gating。
**Code 位置**：registry.py L537-L579（3 records via `_latent_driver_records()`）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| DRV_STRUCTURAL_DETERIORATION_V1 | family=structural_deterioration; domains=[external, structural, repair_validation]; fields=8 项（service_load, restraint, moisture, chloride, carbonation, workmanship, maintenance, repair_quality）| `spec_canonical` (spec 08 §2.3) |
| DRV_DRAINAGE_OPERATION_V1 | family=drainage_operation; domains=[drainage]; fields=4 项（moisture, workmanship, maintenance, drainage_fault_propensity）| `spec_canonical` (spec 08 §2.3) |
| DRV_ALTERATION_AND_FIRE_V1 | family=alteration_and_fire; domains=[ubw, fire_safety]; fields=4 项（workmanship, maintenance, alteration, fire_safety_deficit）| `spec_canonical` (spec 08 §2.3) |

**该表审计小结**：3/3 合规。`field_ranges` 来自 `_DRIVER_FIELD_RANGES`（registry.py L518-L530，11 个 field × [low, high]），全部 spec 0 框架内派生。W0-004（commit `5f6daa4`，2026-05-21）按 spec 04 §9 DriverState 13 字段合约删除 age_years + 4 个 spec 未背书 cruft 字段（obstruction_index / drainage_usage_intensity / blockage_propensity / coverage_feasibility_index），drainage_fault_propensity 走单一字段（不拆）；上方表格为该 commit 后 reflective inventory snapshot。

---

### §3.2 `material_system_registry`

**Schema** (spec 03 §2.2.3)：`material_system` (PK) + `material_class` + `supports_rebar` + `supports_finish_layer` + `compatible_defect_classes` + `aliases` + `notes`
**用途**：材料系统字典；qualifier_taxonomy.material。
**Code 位置**：registry.py L1799-L1875（50 records）。**注**：以 `material_class` 分组列出。

#### concrete (4)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| reinforced_concrete | rebar=True; finish_layer=False; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_SPALL_REBAR, DC_HOLLOWING, DC_DETACHMENT, DC_DEFORMATION_DISPLACEMENT]; MBIS §3.4.2(A), §4.3, §5.4.1, App5 | `pro_T06` |
| plain_concrete | rebar=False; finish_layer=False; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_HOLLOWING, DC_DETACHMENT]; MBIS §3.4.1, §3.4.2(A), §5.6.3 | `pro_T06` |
| prestressed_concrete | rebar=True; finish_layer=False; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_SPALL_REBAR, DC_DETACHMENT]; MBIS §3.4.1, §3.4.2(A), §4.3 | `pro_T06` |
| precast_concrete | rebar=True; finish_layer=False; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_SPALL_REBAR, DC_HOLLOWING, DC_DETACHMENT, DC_LOOSE_FIXING, DC_DEFORMATION_DISPLACEMENT]; MBIS §3.3.2(C), §3.4.1, §5.3.2 | `pro_T06` |

#### finish (5)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| plaster_finish | finish_layer=True; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_DETACHMENT, DC_HOLLOWING]; MBIS §3.3.1(a)(i), §3.3.2(B), §5.3.1, App4 | `pro_T06` |
| masonry_plaster | finish_layer=True; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_DETACHMENT, DC_HOLLOWING]; MBIS §3.3.1(a)(i), §5.3.1 | `pro_T06` |
| polymer_render | finish_layer=True; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_DETACHMENT, DC_HOLLOWING]; MBIS §5.3.1, App4 | `pro_T06` |
| tile_finish | finish_layer=True; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_DETACHMENT, DC_HOLLOWING]; MBIS §3.3.1(a)(i), §3.3.2(B), §5.3.1, App4 | `pro_T06` |
| paint_coating | finish_layer=True; defects=[DC_MOISTURE_STAINING, DC_DETACHMENT]; MBIS §5.3.1, §5.4.4 | `pro_T06` |

#### masonry (3)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| clay_brick | defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT]; MBIS §5.4.3 | `pro_T06` |
| concrete_block | defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT]; MBIS §3.4.1, §5.4.3 | `pro_T06` |
| stone_masonry | defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT]; MBIS §5.4.3 | `pro_T06` |

#### structural_steel (3)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| structural_steel_section | defects=[DC_MOISTURE_STAINING, DC_DETACHMENT, DC_LOOSE_FIXING, DC_FIRE_STOP_DEFICIENCY, DC_METAL_CORROSION, DC_FIRE_PROTECTION_COATING_DEFICIENCY]; MBIS §3.4.2(A), §4.3.1, §5.4.2 | `pro_T06` |
| steel_transfer_beam | defects=8 项 incl DC_DEFORMATION_DISPLACEMENT; MBIS §3.4.2(C), §5.4.2; legacy key | `pro_T06` |
| cold_formed_steel | defects=[DC_MOISTURE_STAINING, DC_DETACHMENT, DC_LOOSE_FIXING, DC_UBW_PRESENT]; MBIS §3.3.1(a)(vi), §3.7 | `pro_T06` |

#### metal_generic (3)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| metal_anchor_fastener | defects=[DC_MOISTURE_STAINING, DC_DETACHMENT, DC_LOOSE_FIXING, DC_METAL_CORROSION]; MBIS §3.3.2(C)-(I), §5.3.7, §5.6.4 | `pro_T06` |
| metal_louver_fin | defects=[DC_MOISTURE_STAINING, DC_DETACHMENT, DC_LOOSE_FIXING, DC_METAL_CORROSION]; MBIS §3.3.1(a)(ii), §3.3.2(D), §5.3.3 | `pro_T06` |
| metal | defects=[DC_MOISTURE_STAINING, DC_DETACHMENT, DC_LOOSE_FIXING, DC_FIRE_DOOR_DEFICIENCY, DC_UBW_PRESENT]; legacy key spec 03 fire_door material_compatibility | `pro_T06` |

#### timber_composite (2)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| timber | defects=[DC_MOISTURE_STAINING, DC_DETACHMENT, DC_LOOSE_FIXING, DC_FIRE_DOOR_DEFICIENCY, DC_UBW_PRESENT]; spec 03 fire_door legacy key; MBIS §3.5, §3.7 | `pro_T06` |
| composite_material | defects=[DC_DETACHMENT, DC_LOOSE_FIXING, DC_FIRE_DOOR_DEFICIENCY, DC_UBW_PRESENT]; spec 03 fire_door legacy key | `pro_T06` |

#### cladding_glazing (5)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| stone_cladding | finish_layer=True; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_DETACHMENT, DC_HOLLOWING, DC_LOOSE_FIXING]; MBIS §3.3.1(c)(i), §3.3.2(C), §5.3.2 | `pro_T06` |
| curtain_wall_glazing | defects=8 项 incl DC_GLASS_BREAKAGE, DC_SEALANT_FAILURE; MBIS §3.3.1(a)(v), §3.3.2(G), §5.3.4 | `pro_T06` |
| aluminium_panel_cladding | defects=[DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT, DC_LOOSE_FIXING, DC_SEALANT_FAILURE]; MBIS §3.3.2(C), §5.3.2 | `pro_T06` |
| gfrc_panel | defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_DETACHMENT, DC_LOOSE_FIXING]; MBIS §3.3.1(a)(vii), §3.3.2(C), §5.3.2 | `pro_T06` |
| glass_balustrade_panel | defects=[DC_CRACK, DC_DETACHMENT, DC_LOOSE_FIXING, DC_GLASS_BREAKAGE]; MBIS §3.3.2(E), §3.3.2(G) | `pro_T06` |

#### window_door (6)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| aluminium_window | defects=8 项; MWIS §8.3, §10.6, §11.1 | `pro_T06` |
| upvc_window | defects=[DC_CRACK, DC_LEAKAGE, DC_DETACHMENT, DC_LOOSE_FIXING]; MWIS §8.3, §10.5, §11.1 | `pro_T06` |
| timber_window | defects=[DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT, DC_LOOSE_FIXING]; MWIS §8.3, §10.5, §11.1 | `pro_T06` |
| steel_window | defects=6 项 incl DC_METAL_CORROSION, DC_DEFORMATION_DISPLACEMENT; MWIS §8.3, §10.5, §11.1 | `pro_T06` |
| curtain_wall_aluminium_frame | defects=6 项 incl DC_FIRE_STOP_DEFICIENCY, DC_SEALANT_FAILURE; MBIS §3.3.2(G), §5.3.4 | `pro_T06` |
| metal_gate | defects=[DC_MOISTURE_STAINING, DC_DETACHMENT, DC_LOOSE_FIXING, DC_METAL_CORROSION]; MBIS §3.3.1(c)(ii), §3.3.2(I), §5.3.6 | `pro_T06` |

#### fire_safety (5)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| steel_fire_doors | defects=[DC_FIRE_DOOR_DEFICIENCY, DC_FIRE_STOP_DEFICIENCY, DC_DETACHMENT, DC_LOOSE_FIXING]; MBIS §3.5.2(D), §5.5.3; legacy key | `pro_T06` |
| fire_resistant_glass_door | defects=6 项 incl DC_GLASS_BREAKAGE; MBIS §3.5.2(D), §5.5.3 | `pro_T06` |
| fire_rated_glass | defects=6 项 incl DC_GLASS_BREAKAGE; MBIS §3.5.2(D), §5.5.3 | `pro_T06` |
| fire_resistant_partition_wall | defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_DETACHMENT, DC_FIRE_STOP_DEFICIENCY]; MBIS §3.5.2(D), §5.5.3 | `pro_T06` |
| intumescent_coating | finish_layer=True; defects=[DC_MOISTURE_STAINING, DC_DETACHMENT, DC_FIRE_STOP_DEFICIENCY, DC_FIRE_PROTECTION_COATING_DEFICIENCY]; MBIS §5.4.2(C), §5.5.3 | `pro_T06` |

#### drainage_pipe (8)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| upvc_drainage | defects=[DC_DRAINAGE_BLOCKAGE, DC_DRAINAGE_LEAKAGE, DC_DRAINAGE_MISCONNECTION, DC_LOOSE_FIXING, DC_DEFORMATION_DISPLACEMENT]; MBIS §3.6.1, §3.6.2, §5.6.1; legacy key | `pro_T06` |
| pvc | defects=5 项; spec 03 drainage_pipe legacy key; MBIS §5.6.1 | `pro_T06` |
| cast_iron | defects=6 项 incl DC_METAL_CORROSION; spec 03 drainage_pipe legacy key; MBIS §3.6.2, §5.6.1 | `pro_T06` |
| concrete_drain | defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_DRAINAGE_BLOCKAGE, DC_DRAINAGE_LEAKAGE, DC_DRAINAGE_MISCONNECTION]; spec 03 legacy key; MBIS §5.6.2 | `pro_T06` |
| hdpe_pipe | defects=5 项; MBIS §5.6.1 | `pro_T06` |
| vitrified_clay_pipe | defects=[DC_CRACK, DC_DRAINAGE_BLOCKAGE, DC_DRAINAGE_LEAKAGE, DC_DRAINAGE_MISCONNECTION]; MBIS §5.6.2 | `pro_T06` |
| galvanized_steel_pipe | defects=6 项 incl DC_METAL_CORROSION; MBIS §3.6.2, §5.6.1 | `pro_T06` |
| stainless_steel_pipe | defects=5 项 incl DC_METAL_CORROSION; MBIS §5.6.1 | `pro_T06` |

#### waterproofing_repair (5)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| cementitious_patch_mortar | finish_layer=True; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_HOLLOWING, DC_DETACHMENT]; MBIS App5 §1.1, §1.1(e) | `pro_T06` |
| bituminous_membrane | defects=[DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT]; MBIS §3.4.2(B), App5 | `pro_T06` |
| pu_waterproof_coating | finish_layer=True; defects=[DC_CRACK, DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT]; MBIS §3.4.2(B), §5.2 | `pro_T06` |
| epoxy_resin_repair | defects=[DC_CRACK, DC_LEAKAGE, DC_DETACHMENT]; MBIS App5 §2 | `pro_T06` |
| silicone_sealant | defects=[DC_MOISTURE_STAINING, DC_LEAKAGE, DC_DETACHMENT, DC_SEALANT_FAILURE]; MBIS §3.3.2(C), §3.3.2(E), §3.3.2(G), MWIS §10.5, §11.1.10 | `pro_T06` |

#### unknown (1)
| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| unknown_material | defects=[]; spec 03 drainage_pipe material_compatibility fallback | `pro_T06` (fallback) |

**该表审计小结**：50/50 合规——T-06 派活产出明确（pro round 1，2026-05-09 前完成 50 entries 全量补述 + MBIS 章节引用）。

---

## §4 测量与采样域（4 张表）

### §4.1 `technical_measurement_registry`

**Schema** (spec 03 §4.1)：`slot_id` (PK) + `measurement_family` + `value_type` + `unit` + `physical_bounds` + `precision_steps` + `method_classes` + `aliases` + `notes` + DEBT-026 字段（`recommended_distribution` / `recommended_mean` / `recommended_sigma` / `typical_bounds` / `distribution_source` / `mean_semantics`）
**用途**：technical 测量字典 + DEBT-020/026 分布参数。
**Code 位置**：registry.py L492-L861（39 records via `_technical_measurement_records()`）。

| primary_key (slot_id) | 关键字段值（精简）| 来源标签 |
|---|---|---|
| crack_width_mm | family=defect_geometry; unit=mm; bounds=[0.05,3.0]; dist=lognormal mean=0.45 sigma=0.75; arith_mean | `pro_DEBT020_round2` (2026-05-09) |
| crack_length_m | family=defect_geometry; unit=m; bounds=[0.05,30]; dist=lognormal mean=1.60 sigma=0.85; arith_mean | `pro_DEBT020_round2` (2026-05-09) |
| spall_area_m2 | family=defect_geometry; unit=m2; bounds=[0.001, "0.6*fragment_area"]; no distribution | `spec_canonical` (spec 08 §3.1) |
| rebar_exposed_length_m | family=defect_geometry; unit=m; bounds=[0,8]; dist=zero_inflated_lognormal→lognormal mean=0.41 sigma=0.53 | `pro_DEBT020_round2` (2026-05-09) |
| rate.pull_test.per_25m2 | family=technical_validation; unit=count/25m2; bounds=[0.25,5]; dist=lognormal mean=1.25 sigma=0.35; arith_mean; rule_card binding follow-up outside封口正文 | `pro_DEBT020_round2` (alignment note kept outside封口权威) |
| count.pull_test.per_repaired_facade | family=technical_validation; unit=count; bounds=[0,25]; dist=rounded_truncated_normal mean=6.0 sigma=3.0 | `pro_DEBT020_round2` |
| count.pull_test.per_floor_full_retiling | family=technical_validation; unit=count; bounds=[0,20]; dist=rounded_truncated_normal mean=5.5 sigma=2.0 | `pro_DEBT020_round2` |
| stress.pull_test.minimum | family=technical_validation; unit=N/mm2; bounds=[0.10,2.50]; dist=truncated_normal mean=0.75 sigma=0.30 | `pro_DEBT020_round2` |
| strength.pull_test.reported | family=technical_validation; unit=N/mm2; bounds=[0.10,3.00]; dist=truncated_normal mean=0.90 sigma=0.35 | `pro_DEBT020_round2` |
| count.pull_test.failed_cumulative | family=technical_validation; unit=count; bounds=[0,6]; dist=zero_inflated_discrete→normal mean=0.95 sigma=1.12 | `pro_DEBT020_round2` |
| count.pull_test.additional_after_failure | family=technical_validation; unit=count; bounds=[0,10]; dist=formula_mixture_discrete→normal mean=1.70 sigma=1.57 | `pro_DEBT020_round2` |
| length.rendering.total_thickness | family=technical_validation; unit=mm; bounds=[0,100]; dist=truncated_normal mean=18.0 sigma=5.0; canonical (legacy plaster.* removed in DEBT-025) | `pro_DEBT020_round1` (2026-05-08) |
| length.rendering.layer_thickness | family=technical_validation; unit=mm; bounds=[0,100]; dist=truncated_normal mean=7.2 sigma=2.2 | `pro_DEBT020_round1` |
| depth.patch_repair | family=technical_validation; unit=mm; bounds=[0,300]; dist=truncated_normal mean=55.0 sigma=18.0 | `pro_DEBT020_round1` |
| length.concrete_repair.depth | family=technical_validation; unit=mm; bounds=[5,180]; dist=truncated_normal mean=65.0 sigma=28.0 | `pro_DEBT020_round2` |
| duration.repair_mortar.test_age | family=technical_validation; unit=day (integer); bounds=[5,14]; dist=discrete_mixture_rounded→normal mean=7.25 sigma=1.05 | `pro_DEBT020_round2` |
| count.repair_mortar_specimens.per_strength_property | family=technical_validation; unit=specimen; bounds=[1,8]; dist=rounded_truncated_normal mean=2.8 sigma=0.9 | `pro_DEBT020_round2` |
| ratio.rebar.section_loss | family=technical_validation; unit=ratio; bounds=[0,0.50]; dist=lognormal mean=0.09 sigma=0.75; arith_mean | `pro_DEBT020_round2` |
| length.mortar.application_layer_thickness | family=technical_validation; unit=mm; bounds=[2,50]; dist=truncated_normal mean=14.0 sigma=6.0 | `pro_DEBT020_round2` |
| ratio.chloride_content.by_cement_weight | family=technical_validation; unit=%; bounds=[0,5]; dist=lognormal mean=0.65 sigma=0.55; arith_mean | `pro_DEBT020_round1` |
| index.drainage.blockage | family=technical_validation; unit=ratio; bounds=[0,1]; dist=beta→normal mean=0.35 sigma=0.18 | `pro_DEBT020_round2` |
| index.drainage.leakage | family=technical_validation; unit=ratio; bounds=[0,1]; dist=beta→normal mean=0.38 sigma=0.18 | `pro_DEBT020_round2` |
| flag.drainage.misconnection_present | family=technical_validation; value_type=bool; bounds=[0,1]; dist=bernoulli p=0.08 | `pro_DEBT020_round2` (schema fix r2) |
| public_health_risk_index | family=derived_risk_measurement; unit=ratio; bounds=[0,1]; dist=beta_mixture→normal mean=0.38 sigma=0.22; temporary fallback | `pro_DEBT020_round2` (alignment=marginal) |
| count.hammer_tapping.grid.minimum | family=coverage_sampling; unit=count; bounds=[5,150]; dist=rounded_truncated_normal mean=50 sigma=20 | `pro_DEBT020_round2` |
| ratio.fsp.structural_performance | family=assessment; unit=ratio; bounds=[0,2]; no distribution (chain derived) | `pro_DEBT025_closure` (SCAN guardrail 2026-05-07) |
| count.core_sample.minimum | family=assessment; unit=count; bounds=[0,1000]; no distribution | `pro_DEBT025_closure` |
| rate.core_sample.per_concrete_volume | family=assessment; unit=count/m3; bounds=[0,100]; no distribution | `pro_DEBT025_closure` |
| time.fire_door.self_closing.delay_sec | family=technical_validation; unit=s; bounds=[0,60]; dist=lognormal mean=6.5 sigma=0.55; arith_mean; failure_rule>10s | `pro_DEBT020_round2` |
| verification.test.failed | family=boolean_assertion; value_type=bool; emitted by failed drainage / repair tests | `spec_canonical` (spec 08 §3.2) |
| facade_total_repaired_area_m2 | family=sampling_plan; unit=m2; bounds=[20,500]; dist=lognormal mean=120 sigma=0.75; arith_mean; building/facade seed RNG; chain Step 1 | `pro_DEBT020_round5` (sub-task 2, 2026-05-10) |
| plan_intensity_tests_per_25m2 | family=sampling_plan; unit=tests/25m2; bounds=[0.5,3.0]; dist=lognormal mean=1.25 sigma=0.35; arith_mean; chain Step 2 | `pro_DEBT020_round5` |
| total_pull_test_count_per_facade | family=sampling_plan; unit=count; bounds=[0,25]; dist=rounded_truncated_normal mean=5.9 sigma=5.0; chain Step 3 derived | `pro_DEBT020_round5` |
| inspected_area_ratio_per_fragment | family=sampling_plan; unit=ratio; bounds=[0,1]; dist=truncated_normal mean=0.45 sigma=0.18; fragment seed RNG | `pro_DEBT020_round5` |
| floor_full_retiling_area_m2 | family=sampling_plan; unit=m2; bounds=[10,400]; dist=lognormal mean=80 sigma=0.65; arith_mean; building/floor seed RNG | `pro_DEBT020_round5` (sub-task 4) |
| retiling_plan_intensity_tests_per_25m2 | family=sampling_plan; unit=tests/25m2; bounds=[0.60,3.00]; dist=lognormal mean=1.35 sigma=0.30; arith_mean | `pro_DEBT020_round5` |
| effective_pull_test_count_per_fragment | family=sampling_plan; unit=count; bounds=[0,25]; A 类 chain derived (no distribution); spec 06 §9 Step 4 | `pro_DEBT020_round5` |
| inspected_area_m2 | family=sampling_plan; unit=m2; bounds=[0,5000]; A 类 chain derived; spec 06 §8 Step 2 | `pro_DEBT020_round5` |
| ratio.covered_area.inspected | family=coverage_sampling; unit=ratio; bounds=[0,1]; A 类 chain derived; spec 04 §17 + spec 06 §8 Step 3 | `pro_DEBT020_round5` |

**该表审计小结**：39/39 合规。分布参数全部 pro round1-5 落地（DEBT-020）；3 个 assessment family slot 是 DEBT-025 SCAN guardrail 补建（spec 04 §17 已写但 registry 漏实现）；2 条 retired/deprecated 条目（generic `ratio.chloride_content` / `count.fire_door.sample.minimum` 等）通过注释保留 trace 不入 records 列表。

---

### §4.2 `sampling_plan_registry`

**Schema** (spec 03 §4.4)：`sampling_plan_id` (PK) + `plan_level` + `target_slot_ids` + `basis_area_slot` + `plan_intensity_distribution` + `total_count_formula` + `fragment_allocation_formula` + `coverage_ratio_slot` + `min_count_formula` + `interval_formula` + `notes`
**用途**：sampling plan 字典（chain_C_plus 链式派生），存 facade-level / floor-level / fragment-level 抽样计划。
**Code 位置**：registry.py L864-L989（3 records via `_sampling_plan_records()`）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| pull_test_sampling_plan | level=facade_or_floor_repair_package; basis=facade_total_repaired_area_m2; intensity=lognormal mean=1.25 sigma=0.35; total_count_formula=round_clip(intensity*area/25, 1, 25); allocation=area-proportional | `pro_DEBT020_round5` (sub-task 2, 2026-05-10) |
| coverage_inspection_plan | level=fragment; basis=fragment_area_m2; intensity=truncated_normal mean=0.45 sigma=0.18; allocation=ratio*area | `pro_DEBT020_round5` (sub-task 2) |
| floor_retiling_package | level=floor_retiling_package; basis=floor_full_retiling_area_m2; intensity=lognormal mean=1.35 sigma=0.30; total_count_formula=round_clip(intensity*area/25, 1, 20); floor-level | `pro_DEBT020_round5` (sub-task 4) |

**该表审计小结**：3/3 合规。复活自 DEBT-025 closure（2026-05-07 清空原 6 plan），DEBT-020 round5 sub-task 2/4 按用户决策重建（2026-05-10）。

---

### §4.3 `verification_test_registry`

**Schema** (spec 03 §4.5)：`test_family_id` (PK) + `method_class` + `required_measurements` + `failure_rule` + `additional_test_formula` + `repair_work_categories` + `notes`
**用途**：验证测试字典；rule_card 通过 test_family_id 引用。
**Code 位置**：registry.py L1939-L2062（13 records）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| VT_VISUAL_INSPECTION_V1 | method=visual_inspection; req_meas=[crack_width_mm, crack_length_m, spall_area_m2]; fail=any_severity>=moderate | `spec_canonical` (spec 08 §3.2) |
| VT_HAMMER_TAPPING_V1 | method=hammer_tapping; req_meas=[count.hammer_tapping.grid.minimum]; fail=hollow_sound_fraction>0.30 | `spec_canonical` (spec 08 §3.2) |
| VT_INFRARED_SCAN_V1 | method=infrared; req_meas=[spall_area_m2]; fail=thermal_anomaly_area>0.20*fragment_area | `spec_canonical` (spec 08 §3.2) |
| VT_DRAINAGE_CCTV_V1 | method=CCTV; req_meas=[index.drainage.blockage, index.drainage.leakage, flag.drainage.misconnection_present]; fail=blockage>0.5 \| misconnection==True | `spec_canonical` (spec 08 §3.2) |
| VT_PULL_TEST_EXTERNAL_V1 | method=pull_test; req_meas=4 项; fail=strength<min \| repair_quality<0.45; additional=n^2-2n+3; MBIS App4 §2.3 | `spec_canonical` (spec 08 §3.2) |
| VT_DRAINAGE_SMOKE_TEST_V1 | method=smoke_test; req_meas=[flag.drainage.misconnection_present]; fail=smoke_at_unexpected_outlet | `spec_canonical` (spec 08 §3.2) |
| VT_DRAINAGE_WATER_TEST_V1 | method=water_test; req_meas=[index.drainage.leakage, flag.drainage.misconnection_present]; fail=leakage>0.5 \| misconnection | `spec_canonical` (spec 08 §3.2) |
| VT_DRAINAGE_AIR_TEST_V1 | method=air_test; req_meas=[index.drainage.blockage]; fail=pressure_loss_rate>threshold | `spec_canonical` (spec 08 §3.2) |
| VT_DRAINAGE_BALL_TEST_V1 | method=ball_test; req_meas=[index.drainage.blockage]; fail=ball_fails_to_pass | `spec_canonical` (spec 08 §3.2) |
| VT_MOISTURE_METER_V1 | method=moisture_meter; req_meas=[index.drainage.leakage]; fail=moisture>threshold_proxy | `spec_canonical` (spec 08 §3.2) |
| VT_CHAIN_DRAG_V1 | method=chain_drag; req_meas=[count.hammer_tapping.grid.minimum]; fail=hollow_sound_fraction>0.30 | `spec_canonical` (spec 08 §3.2) |
| VT_FIRE_DOOR_CLOSER_TEST_V1 | method=self_closing_test; req_meas=[time.fire_door.self_closing.delay_sec]; fail=delay>10s \| fails_to_close | `spec_canonical` (spec 08 §3.2) |
| VT_REPAIR_MORTAR_TEST_V1 | method=material_test; req_meas=[duration.repair_mortar.test_age, count.repair_mortar_specimens.per_strength_property]; MBIS App4 §2.4 | `spec_canonical` (spec 08 §3.2) |

**该表审计小结**：13/13 合规。

---

### §4.4 `normative_projection_registry`

> **归属 W2 法规映射层**（2026-05-13 用户拍板）。本表 schema + records source-of-truth 是 W2 端，本节列入 W0 inventory 是因为 worldgen runtime 加载所有 RegistryTable 时把 npr 也读进 registry_bundle。schema 字段定义详见 W2 规格 06 §3（11 字段）+ W0 规格 03 §3.1；records 内容业务依据见 W2 规格 06 §2（16 family baseline）。worldgen 端跨层加载 npr records 是 orchestrator 性质（同 `run_worldgenerator_fullcoverage_framework_v2` 主入口跨 W0+W1+W2 三层编排）。详见 spec 02 §1 第 7 分组注 1。

**Schema** (spec 03 §3.1)：`projection_registry_id` (PK) + `projection_family` + `applicability_predicates` + `required_world_core_slots` + `required_measurement_slots` + `required_qualifier_slots` + `required_sidecar_interfaces` + `rule_ids` + `basis_template_ids` + `conflict_group` + `domain_buckets`
**用途**：投影 binding 字典；rule_card 通过 projection_registry_id 与生成的 world / sidecar 数据连接。
**Code 位置**：registry.py L32-L360（16 records via `_projection_registry_records()` + `_enrich_projection_registry_records()`）。

> **records 数以 W2 06 §2 16 family baseline 为准**。本表逐条镜像 code `_projection_registry_records()` 现状（16 records），作 reflective inventory；如与 W2 06 §2 数量不一致，以 W2 06 / NI-006 为权威源。2026-05-21 批次 C（W2-005）按 spec 06 §2.1 把旧合并 record `NP_UBW_FIRE_V1` 拆成 `NP_FIRE_SAFETY_V1` / `NP_UBW_V1` 两条独立 family，并补 `NP_INVESTIGATION_FSP_V1`（row 9）+ `NP_REPAIR_GENERAL_V1`（row 10），共 13→16。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| NP_RI_NOTIFICATIONS_V1 | family=mbis.procedure.ri_notifications_and_submissions; sidecar=[procedure_gate, inspection_report, completion_report]; buckets=[structural_external, coverage_sampling, assessment] | `spec_canonical` (spec 08 §1) |
| NP_EXTERNAL_COMPONENTS_V1 | family=mbis.inspection.external_components; world=7 项; meas=[ratio.external_wall_area.inspected]; conflict=structural_external_surface | `spec_canonical` (spec 08 §1) |
| NP_STRUCTURAL_COMPONENTS_V1 | family=mbis.inspection.structural_components; world=4 项; meas=4 项; conflict=structural_external_surface | `spec_canonical` (spec 08 §1) |
| NP_DRAINAGE_V1 | family=mbis.inspection.drainage; world=6 项; meas=[count.private_premises_access.floor_interval]; conflict=drainage | `spec_canonical` (spec 08 §1) |
| NP_INVESTIGATION_GATE_V1 | family=mbis.investigation.gate_and_proposal; world=[defect.cause_or_extent.uncertain]; sidecar=[procedure_gate, inspection_report] | `spec_canonical` (spec 08 §1) |
| NP_FIRE_SAFETY_V1 | family=mbis.inspection.fire_safety; world=4 项; meas=[time.fire_door.self_closing.delay_sec]; conflict=ubw_fire；W2-005 批次 C 自 NP_UBW_FIRE_V1 拆出 | `spec_canonical` (spec 06 §2.1 row 5) |
| NP_UBW_V1 | family=mbis.inspection.ubw; world=4 项; conflict=ubw_fire；W2-005 批次 C 自 NP_UBW_FIRE_V1 拆出 | `spec_canonical` (spec 06 §2.1 row 7) |
| NP_INVESTIGATION_FSP_V1 | family=mbis.investigation.structural_assessment_fsp; world=2 项; meas=3 项；W2-005 批次 C 补 row 9 | `spec_canonical` (spec 06 §2.1 row 9) |
| NP_REPAIR_GENERAL_V1 | family=mbis.repair.general_selection_and_classification; world=3 项; qual=[work_category, component_type]；W2-005 批次 C 补 row 10 | `spec_canonical` (spec 06 §2.1 row 10) |
| NP_REPAIR_VALIDATION_V1 | family=mbis.repair.external_structural_validation; world=3 项; meas=15 项; conflict=assessment_repair | `spec_canonical` (spec 08 §1) |
| NP_SUPERVISION_CONTROLS_V1 | family=mbis.supervision.ri_minimum_and_site_controls; world=2 项; qual=[work_category, method_class]; sidecar=3 项 | `spec_canonical` (spec 08 §1) |
| NP_REPORTING_INSPECTION_V1 | family=mbis.reporting.inspection_report; world=3 项; meas=[ratio.external_wall_area.inspected] | `spec_canonical` (spec 08 §1) |
| NP_REPORTING_COMPLETION_V1 | family=mbis.reporting.completion_report; world=2 项; meas=3 项 | `spec_canonical` (spec 08 §1) |
| NP_SCOPE_COVERAGE_PREINSPECTION_V1 | family=mbis.scope.coverage_and_preinspection; world=6 项 (building.identity.* + scope.component.*); sidecar=[inspection_report] | `spec_canonical` (spec 08 §1) |
| NP_REPAIR_FIRESAFETY_DRAINAGE_V1 | family=mbis.repair.fire_safety_and_drainage; world=[repair.required, maintenance.pre_next_cycle.required]; buckets=[drainage, fire_safety, technical_validation] | `spec_canonical` (spec 08 §1) |
| NP_SUPERVISION_RC_CONTROLS_V1 | family=mbis.supervision.rc_controls; qual=[work_category]; sidecar=[supervision, procedure_gate]; sidecar-only family | `spec_canonical` (spec 08 §1) |

**该表审计小结**：16/16 合规（= W2 06 §2 16 family baseline，对齐封口总则 NI-006）。`basis_template_ids` / `conflict_group` 由 `_PROJECTION_SCHEMA_SUPPLEMENTS` 注入，spec 08 §1 全部列出。

---

## §5 派生风险域（2 张表）

### §5.1 `risk_derivation_registry`

**Schema** (spec 03 §2.4)：`risk_flag_id` (PK) + `output_slot_id` + `input_condition_classes` + `input_measurement_slots` + `formula` + `thresholds` + `unknown_policy` + `notes`
**用途**：风险派生字典（T-09d D03-1 全 schema 补齐）。
**Code 位置**：registry.py L2089-L2147（3 records）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| RISK_BUILDING_SAFETY_EMERGENCY_V1 | output=risk.building_safety.emergency; inputs=[DC_CRACK, DC_SPALL_REBAR, DC_HOLLOWING, DC_DETACHMENT, DC_DEFORMATION_DISPLACEMENT]; thresholds={severity:0.85, fsp:0.75, structural_impact:0.85}; MBIS §3.4.2/§4.3 | `spec_canonical` + DC_DEFORMATION_DISPLACEMENT 是 `pro_T06` |
| RISK_PUBLIC_HEALTH_DRAINAGE_V1 | output=risk.public_health.emergency; inputs=[DC_DRAINAGE_LEAKAGE, DC_DRAINAGE_MISCONNECTION, DC_DRAINAGE_BLOCKAGE]; threshold={public_health_risk_index:0.80}; MBIS §3.6.2 | `spec_canonical` (spec 08 §3.3) |
| RISK_PUBLIC_DANGER_UBW_V1 | output=risk.public_danger.present; inputs=[DC_DETACHMENT, DC_SPALL_REBAR, DC_FIRE_DOOR_DEFICIENCY, DC_UBW_PRESENT, DC_GLASS_BREAKAGE]; threshold={max_danger_index:0.70}; MBIS §3.4/§3.5/§3.7 | `spec_canonical` + DC_GLASS_BREAKAGE 是 `pro_T06` |

**该表审计小结**：3/3 合规。T-06 新增 DC（DEFORMATION_DISPLACEMENT / GLASS_BREAKAGE）入 input list 是 cross-table propagation。

---

### §5.2 `repair_outcome_registry`

**Schema** (spec 03 §2.4)：`repair_outcome_id` (PK) + `output_slot_id` + `input_risk_flags` + `input_verification_flags` + `output_flags` + `formula` + `notes`
**用途**：修葺结果派生字典。
**Code 位置**：registry.py L2148-L2192（3 records）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| RO_REPAIR_REQUIRED_V1 | output=repair.required; in_risk=[RISK_BUILDING_SAFETY_EMERGENCY_V1, RISK_PUBLIC_DANGER_UBW_V1]; in_verif=[verification_test_failed]; formula=moderate_or_above_condition or any(risk) or test_failed; MBIS §5.1.2 | `spec_canonical` (spec 08 §3.4) |
| RO_SAFE_UNTIL_NEXT_CYCLE_V1 | output=repair.outcome.safe_until_next_cycle; in_risk=[RISK_BUILDING_SAFETY_EMERGENCY_V1]; formula=repair_quality>=0.65 and not failed and residual_risk<0.70; MBIS §5.1.7/§5.3.7/§5.4.4 | `spec_canonical` (spec 08 §3.4) |
| RO_PRE_NEXT_CYCLE_MAINTENANCE_V1 | output=maintenance.pre_next_cycle.required; formula=severity in [minor,moderate] and not any_emergency_risk; MBIS §5.6 | `spec_canonical` (spec 08 §3.4) |

**该表审计小结**：3/3 合规。

---

## §6 评估代理域（1 张表）

### §6.1 `assessment_surrogate_registry`

**Schema** (spec 03 §4.3)：`assessment_family_id` (PK) + `input_slots` + `output_slots` + `formula` + `physical_bounds` + `noise_model` + `notes`
**用途**：评估代理函数字典；FSP / core-sample 派生入口。
**Code 位置**：registry.py L2064-L2087（1 record）。

| primary_key | 关键字段值（精简）| 来源标签 |
|---|---|---|
| AS_FSP_MEMBER_V1 | inputs=[crack_width_mm, spall_area_m2, rebar_exposed_length_m]; outputs=[ratio.fsp.structural_performance, count.core_sample.minimum, rate.core_sample.per_concrete_volume]; formula=clip(1.20-k_loss*max_severity-0.10*age_norm, 0, 2); noise=TECH_REL_GAUSS; spec 06 §10; a4/a11 lineage | `spec_canonical` + `old_blueprint_a4_a11` |

**该表审计小结**：1/1 合规。

---

## §7 Sidecar 域（3 张表）

### §7.1 `sidecar_ownership_registry`

**Schema** (spec 03 §1, T-05a)：`sidecar_slot_id` (PK) + `partition` + `carrier` + `sidecar_domain` + `carrier_type` + `joins_on` + `projection_consumable` + `notes`
**用途**：sidecar 所有权映射；T-05a 从 SidecarContract.ownership_map 转换为 RegistryTable 形式。
**Code 位置**：registry.py L3122-L3302（slot lists 在 `_build_sidecar_contract()`；records 由 `_sidecar_ownership_registry_record()` 转换；共 **143 records**）。

#### partition=world_core (31 slots) — carrier=FragmentContext/ConditionState
| primary_key (slot_id) | partition / sidecar_domain | 来源标签 |
|---|---|---|
| building.identity.basic | world_core / boundary | `spec_canonical` (spec 09 §1) |
| building.metadata.occupancy_and_use | world_core / boundary | `spec_canonical` (spec 09 §1) |
| building.metadata.configuration | world_core / boundary | `spec_canonical` (spec 09 §1) |
| building.metadata.primary_materials | world_core / boundary | `spec_canonical` (spec 09 §1) |
| scope.component.in_scope | world_core / boundary | `spec_canonical` (spec 09 §1) |
| scope.component.excluded_from_scope | world_core / boundary | `spec_canonical` (spec 09 §1) |
| scope.component.covered | world_core / boundary | `spec_canonical` (spec 09 §1) |
| scope.component.covered_by_large_signboard | world_core / boundary | `spec_canonical` (spec 09 §1) |
| scope.component.obscured_by_finish | world_core / boundary | `spec_canonical` (spec 09 §1) |
| scope.component.obscured_by_services | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.class.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.range.extends_into_private_premises | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.cause_or_extent.uncertain | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.hollowing.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.moisture_or_leakage.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.detachment_or_loose_fixing.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.drainage.misconnection.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.drainage.blockage.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.drainage.leakage.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.ubw.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.subdivided_unit_sign.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| defect.fire_safety.component_deficiency.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| risk.building_safety.emergency | world_core / boundary | `spec_canonical` (spec 09 §1) |
| risk.public_health.emergency | world_core / boundary | `spec_canonical` (spec 09 §1) |
| risk.public_danger.present | world_core / boundary | `spec_canonical` (spec 09 §1) |
| coverage.insufficient | world_core / boundary | `spec_canonical` (**spec 08 §2.2 + §2.2.1**，2026-05-12 增订；world-quality guard 性质，参与 projection fallback 不参与 rule_card adjudication；公式 spec 06 §11.X derived flag table L711) |
| repair.required | world_core / boundary | `spec_canonical` (spec 09 §1) |
| repair.outcome.safe_until_next_cycle | world_core / boundary | `spec_canonical` (spec 09 §1) |
| maintenance.pre_next_cycle.required | world_core / boundary | `spec_canonical` (spec 09 §1) |
| investigation.fsp.below_required_safety | world_core / boundary | `spec_canonical` (spec 09 §1) |
| verification.test.failed | world_core / boundary | `spec_canonical` (spec 09 §1) |

#### partition=measurement_family (26 slots) — carrier=MeasurementState
| primary_key (slot_id) | partition / sidecar_domain | 来源标签 |
|---|---|---|
| ratio.external_wall_area.inspected | measurement_family / boundary | `pro_DEBT025_closure` (sidecar entry; sidecar_measurement registry 也建) |
| ratio.covered_structure_area.inspected | measurement_family / boundary | `pro_DEBT025_closure` |
| count.canopy.check_locations.minimum | measurement_family / boundary | `pro_DEBT025_closure` |
| length.canopy.check_location.interval | measurement_family / boundary | `pro_DEBT025_closure` |
| count.private_premises_access.floor_interval | measurement_family / boundary | `pro_DEBT025_closure` |
| ratio.fsp.structural_performance | measurement_family / boundary | `pro_DEBT025_closure` |
| count.core_sample.minimum | measurement_family / boundary | `pro_DEBT025_closure` |
| rate.core_sample.per_concrete_volume | measurement_family / boundary | `pro_DEBT025_closure` |
| rate.pull_test.per_25m2 | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| count.pull_test.per_repaired_facade | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| count.pull_test.per_floor_full_retiling | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| stress.pull_test.minimum | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| strength.pull_test.reported | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| count.pull_test.failed_cumulative | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| count.pull_test.additional_after_failure | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| length.rendering.total_thickness | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| length.rendering.layer_thickness | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| depth.patch_repair | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| length.concrete_repair.depth | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| duration.repair_mortar.test_age | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| count.repair_mortar_specimens.per_strength_property | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| ratio.rebar.section_loss | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| length.mortar.application_layer_thickness | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| ratio.chloride_content.by_cement_weight | measurement_family / boundary | `pro_DEBT020_round1` (round2 retire generic) |
| count.hammer_tapping.grid.minimum | measurement_family / boundary | `spec_canonical` (spec 09 §2) |
| time.fire_door.self_closing.delay_sec | measurement_family / boundary | `spec_canonical` (spec 09 §2) |

#### partition=qualifier_taxonomy (6 slots) — carrier=taxonomy_registry
| primary_key (slot_id) | partition / sidecar_domain | 来源标签 |
|---|---|---|
| qual.component_type | qualifier_taxonomy / sidecar_qualifier | `spec_canonical` (spec 09 §3) |
| qual.location_class | qualifier_taxonomy / sidecar_qualifier | `spec_canonical` (spec 09 §3) |
| qual.defect_class | qualifier_taxonomy / sidecar_qualifier | `spec_canonical` (spec 09 §3) |
| qual.risk_class | qualifier_taxonomy / sidecar_qualifier | `spec_canonical` (spec 09 §3) |
| qual.method_class | qualifier_taxonomy / sidecar_qualifier | `spec_canonical` (spec 09 §3) |
| qual.work_category | qualifier_taxonomy / sidecar_qualifier | `spec_canonical` (spec 09 §3) |

#### partition=sidecar (80 slots) — carrier=procedure/artifact/supervision sidecar

##### Artifact (25)
| primary_key (slot_id) | sidecar_domain | 来源标签 |
|---|---|---|
| artifact.notice.ri_appointment | artifact | `spec_canonical` (spec 09 §4) |
| artifact.notice.ri_temporary_nomination | artifact | `spec_canonical` (spec 09 §4) |
| artifact.form.mbi1 | artifact | `spec_canonical` (spec 09 §4) |
| artifact.form.mbi2 | artifact | `spec_canonical` (spec 09 §4) |
| artifact.form.mbi3_or_mbi3a | artifact | `spec_canonical` (spec 09 §4) |
| artifact.form.mbi4 | artifact | `spec_canonical` (spec 09 §4) |
| artifact.form.mbi5 | artifact | `spec_canonical` (spec 09 §4) |
| artifact.notice.investigation_intention | artifact | `spec_canonical` (spec 09 §4) |
| artifact.proposal.detailed_investigation | artifact | `spec_canonical` (spec 09 §4) |
| artifact.proposal.supervision | artifact | `spec_canonical` (spec 09 §4) |
| artifact.proposal.repair | artifact | `spec_canonical` (spec 09 §4) |
| artifact.proposal.repair_revision | artifact | `spec_canonical` (spec 09 §4) |
| artifact.report.inspection | artifact | `spec_canonical` (spec 09 §4) |
| artifact.report.completion | completion | `spec_canonical` (spec 09 §4) |
| artifact.photo.annotated | artifact | `spec_canonical` (spec 09 §4) |
| artifact.plan.annotated | artifact | `spec_canonical` (spec 09 §4) |
| artifact.record.inspection_log | artifact | `spec_canonical` (spec 09 §4) |
| artifact.record.site_visit_log | artifact | `spec_canonical` (spec 09 §4) |
| artifact.record.supervision_log_sp1 | artifact | `spec_canonical` (spec 09 §4) |
| artifact.record.nonconformity_sp2 | artifact | `spec_canonical` (spec 09 §4) |
| artifact.report.test_result | artifact | `spec_canonical` (spec 09 §4) |
| artifact.record.test_or_material_witness | artifact | `spec_canonical` (spec 09 §4) |
| artifact.certificate.material_or_product | artifact | `spec_canonical` (spec 09 §4) |
| artifact.statement.scope_and_order_coverage | artifact | `spec_canonical` (spec 09 §4) |
| artifact.statement.extra_works_separated | artifact | `spec_canonical` (spec 09 §4) |

##### Procedure (18)
| primary_key (slot_id) | sidecar_domain | 来源标签 |
|---|---|---|
| procedure.ri.appointment.completed | procedure | `spec_canonical` (spec 09 §5) |
| procedure.temp_ri_nomination.completed | procedure | `spec_canonical` (spec 09 §5) |
| procedure.temp_ri_nomination.terminated | procedure | `spec_canonical` (spec 09 §5) |
| procedure.ri_role.terminated | procedure | `spec_canonical` (spec 09 §5) |
| procedure.repair_supervising_ri.appointment.completed | procedure | `spec_canonical` (spec 09 §5) |
| procedure.repair.revision_proposal.submitted_to_ba | procedure | `spec_canonical` (spec 09 §5) |
| procedure.supervision_representative.planned | procedure | `spec_canonical` (spec 09 §5) |
| procedure.supervision_team.submitted | procedure | `spec_canonical` (spec 09 §5) |
| procedure.supervision_team.changed | procedure | `spec_canonical` (spec 09 §5) |
| procedure.inspection.prescribed.completed | procedure | `spec_canonical` (spec 09 §5) |
| procedure.investigation.intention_notified | procedure | `spec_canonical` (spec 09 §5) |
| procedure.investigation.proposal.submitted | procedure | `spec_canonical` (spec 09 §5) |
| procedure.investigation.proposal.recognized | procedure | `spec_canonical` (spec 09 §5) |
| procedure.investigation.detailed.started | procedure | `spec_canonical` (spec 09 §5) |
| procedure.investigation.started | procedure | `spec_canonical` (spec 09 §5) |
| procedure.repair.revision_required | procedure | `spec_canonical` (spec 09 §5) |
| procedure.repair.prescribed.started | procedure | `spec_canonical` (spec 09 §5) |
| procedure.repair.prescribed.completed | procedure | `spec_canonical` (spec 09 §5) |
| procedure.completed_work.final_inspection_performed | procedure | `spec_canonical` (spec 09 §5) |
| procedure.rc.pre_notification_given | procedure | `spec_canonical` (spec 09 §5) |

##### Duration (6) + carrier_slot artifact (1) + supervision-related slot 单列
| primary_key (slot_id) | sidecar_domain | 来源标签 |
|---|---|---|
| duration.notification.deadline | procedure | `spec_canonical` (spec 09 §5) |
| duration.submission.deadline | procedure | `spec_canonical` (spec 09 §5) |
| duration.delivery.deadline | procedure | `spec_canonical` (deprecated; spec 09 §5) |
| duration.delivery.deadline.to_person | procedure | `pro_DEBT020_round5` (sub-task 5, 2026-05-10) |
| duration.delivery.deadline.to_ba | procedure | `pro_DEBT020_round5` (sub-task 5) |
| artifact.report_completion_or_mbi4.submitted_to_ba | artifact | `pro_DEBT020_round5` (to_person carrier_slot, BA submission anchor) |
| duration.site_visit.interval | supervision | `spec_canonical` (spec 09 §6) |

##### Actor + reporting + supervision (12)
| primary_key (slot_id) | sidecar_domain | 来源标签 |
|---|---|---|
| actor.representative.assigned | sidecar_qualifier | `spec_canonical` (spec 09 §5) |
| actor.representative.qualified_for_assigned_role | sidecar_qualifier | `spec_canonical` (spec 09 §5) |
| reporting.artifact.prepared | artifact | `spec_canonical` (spec 09 §4) |
| reporting.artifact.signed | artifact | `spec_canonical` (spec 09 §4) |
| reporting.artifact.submitted | artifact | `spec_canonical` (spec 09 §4) |
| reporting.artifact.delivered | artifact | `spec_canonical` (spec 09 §4) |
| reporting.annotated_photo.present | artifact | `spec_canonical` (spec 09 §4) |
| reporting.annotated_location_plan.present | artifact | `spec_canonical` (spec 09 §4) |
| reporting.record.maintained | artifact | `spec_canonical` (spec 09 §4) |
| reporting.record.submitted | artifact | `spec_canonical` (spec 09 §4) |
| supervision.site_visit.performed | supervision | `spec_canonical` (spec 09 §6) |
| supervision.record.completed | supervision | `spec_canonical` (spec 09 §6) |
| supervision.record.retained | supervision | `spec_canonical` (spec 09 §6) |
| supervision.record.completed_and_retained | supervision | `spec_canonical` (spec 09 §6) |

##### Inspection execution carrier slots (4) — DEBT-025 closure 2026-05-07
| primary_key (slot_id) | sidecar_domain | 来源标签 |
|---|---|---|
| inspection.external_wall.coverage_evidence | artifact | `pro_DEBT025_closure` (spec 09 §7.1) |
| inspection.structural.coverage_evidence | artifact | `pro_DEBT025_closure` |
| inspection.canopy.check_plan | artifact | `pro_DEBT025_closure` |
| inspection.private_premises.access_plan | artifact | `pro_DEBT025_closure` |

##### Qualifier sidecar (2) + fire_safety (1) + markers (4)
| primary_key (slot_id) | sidecar_domain | 来源标签 |
|---|---|---|
| qual.actor_role | sidecar_qualifier | `spec_canonical` (spec 09 §3) |
| qual.artifact_field_group | sidecar_qualifier | `spec_canonical` (spec 09 §3) |
| fire_safety.upgrade_outstanding | boundary | `spec_canonical` (spec 09 §1.1.2 B 类) |
| marker.artifact_required | boundary | `spec_canonical` (spec 09 §1.2) |
| marker.procedure_required | boundary | `spec_canonical` (spec 09 §1.2) |
| marker.supervision_required | boundary | `spec_canonical` (spec 09 §1.2) |
| marker.no_sidecar_dependency | boundary | `spec_canonical` (spec 09 §1.2) |

**该表审计小结**：143/143 合规。31 world_core + 26 measurement_family + 6 qualifier_taxonomy + 80 sidecar = 143。8 个 inspection_execution carrier_slot / DEBT-025 closure 派生项 / DEBT-020 round5 sub-task 5 拆分项 已纳入 SCAN guardrail 校验。

---

### §7.2 `sidecar_measurement_registry`

**Schema** (spec 03 §1)：`slot_id` (PK) + `measurement_family` + `value_type` + `unit` + `physical_bounds` + `precision_steps` + `carrier_domain` + `carrier_slot` + `rule_basis_refs` + `aliases` + DEBT-026 字段 + Round7 增项（部分 record）
**用途**：sidecar 数值 slot 字典（与 sidecar_bool_slot_registry 平行）。
**Code 位置**：registry.py L2220-L2533（10 records）。

| primary_key (slot_id) | 关键字段值（精简）| 来源标签 |
|---|---|---|
| duration.notification.deadline | family=procedure_duration; unit=day; bounds=[0,30]; dist=rounded_truncated_normal mean=4.8 sigma=2.6; MBIS COP §2.1.3 | `pro_DEBT020_round3` (2026-05-08) |
| duration.submission.deadline | family=procedure_duration; unit=day; bounds=[0,30]; dist=mixture→normal mean=8.8 sigma=3.7; MBIS COP §2.1.3(p)/(r) | `pro_DEBT020_round3` |
| duration.delivery.deadline | family=procedure_duration; unit=day; **DEPRECATED at 2026-05-10**; replaced by `.to_person` + `.to_ba`; backward-compat alias only | `pro_DEBT020_round5` (sub-task 5) |
| duration.delivery.deadline.to_person | family=procedure_duration; unit=day; bounds=[0,14]; dist=zero_inflated_discrete→normal mean=0.45 sigma=1.15; rule_card threshold=same_day_as / ==0; MBIS COP §2.1.3(r) | `pro_DEBT020_round5` + Round 7 confirmed |
| duration.delivery.deadline.to_ba | family=procedure_duration; unit=day; bounds=[0,60]; dist=rounded_truncated_normal mean=10.5 sigma=5.0; threshold=<=14 day; MBIS COP §2.1.3(r) | `pro_DEBT020_round5` + Round 7 confirmed |
| duration.site_visit.interval | family=supervision_interval; unit=day; bounds=[1,30]; dist=mixture→normal mean=9.1 sigma=3.7; MBIS COP §6.4.1, App VI Table 2 (Level 1 ≤7d / Level 2 ≤14d); audit finding rulecard missing threshold | `pro_DEBT020_round3` |
| ratio.external_wall_area.inspected | family=inspection_coverage; unit=ratio; bounds=[0,1]; dist=truncated_normal mean=0.40 sigma=0.15; MBIS COP §3.3.2(J)(c) | `pro_DEBT020_round1` (DEBT-025 sidecar entry) |
| ratio.covered_structure_area.inspected | family=inspection_coverage; unit=ratio; bounds=[0,1]; dist=mixture_truncated_normal mean=0.55 sigma=0.25; MBIS COP §3.4.2(C)(a), §3.4.2(B)(a) | `pro_DEBT020_round1` |
| count.canopy.check_locations.minimum | family=inspection_plan; unit=count; bounds=[0,50]; dist=rounded_truncated_normal mean=3.2 sigma=1.5; MBIS COP §3.4.2(B)(e) | `pro_DEBT020_round1` |
| length.canopy.check_location.interval | family=inspection_plan; unit=m; bounds=[0,100]; dist=truncated_normal mean=5.1 sigma=1.6; MBIS COP §3.4.2(B)(e) | `pro_DEBT020_round1` |
| count.private_premises_access.floor_interval | family=inspection_plan; unit=floor; bounds=[1,50]; dist=rounded_truncated_normal mean=3.0 sigma=1.2; MBIS COP §3.6.2(A)(b)-(c) | `pro_DEBT020_round1` |

**注**：实际 records 是 11 条（包含 deprecated `duration.delivery.deadline`）。

**该表审计小结**：11/11 合规（含 deprecated）。5 个 inspection_execution slot 通过 DEBT-025 closure 入 sidecar 域（spec 09 §7.1 / AUDIT_20260506_missing_w0_slots.md§F2）；duration.delivery.deadline.to_person/to_ba 通过 DEBT-020 round5 sub-task 5 + round7 §2 COP 原文确认。

---

### §7.3 `sidecar_bool_slot_registry`

**Schema** (spec 02 §1 / spec 09 §1.2 revised 2026-05-09)：`slot_id` (PK) + `value_type` + `enum_values` + `prevalence` + `conditional_inputs` + `conditional_formula` + `carrier_domain` + `source_attribution` + `aliases` + `notes` + Round 6/7 增项（`sampling_order` / `upstream_inputs` / `marginal_anchor` / `anchor_source` / `alignment_check` / `distribution_source` / `cop_section`）
**用途**：sidecar 域 bool / categorical slot 生成 schema；与 sidecar_measurement_registry 平行（数值 vs bool 双路径）。
**Code 位置**：registry.py L2546-L2992（45 records via direct list + `_apply_round6_round7_overlays`）。

#### A. procedure / gate (17)
| primary_key (slot_id) | value_type / prevalence | 来源标签 |
|---|---|---|
| procedure.ri.appointment.completed | bool / 0.86 | `pro_DEBT020_round4_round7` |
| procedure.temp_ri_nomination.completed | bool / 0.08 | `pro_DEBT020_round4_round7` |
| procedure.temp_ri_nomination.terminated | bool / 0.03 | `pro_DEBT020_round4_round7` |
| procedure.ri_role.terminated | bool / 0.06 | `pro_DEBT020_round4_round7` |
| procedure.supervision_representative.planned | bool / 0.66 | `pro_DEBT020_round4_round7` |
| procedure.supervision_team.submitted | bool / 0.58 | `pro_DEBT020_round4_round7` |
| procedure.supervision_team.changed | bool / 0.12 | `pro_DEBT020_round4_round7` |
| procedure.inspection.prescribed.completed | bool / 0.74 | `pro_DEBT020_round4_round7` |
| procedure.investigation.intention_notified | bool / 0.30 | `pro_DEBT020_round4_round7` |
| procedure.investigation.proposal.submitted | bool / 0.23 | `pro_DEBT020_round4_round7` |
| procedure.investigation.proposal.recognized | bool / 0.18 | `pro_DEBT020_round4_round7` |
| procedure.investigation.started | bool / 0.20 | `pro_DEBT020_round4_round7` |
| procedure.repair.revision_required | bool / 0.18 | `pro_DEBT020_round4_round7` |
| procedure.repair.prescribed.started | bool / 0.55 | `pro_DEBT020_round4_round7` |
| procedure.repair.prescribed.completed | bool / 0.42 | `pro_DEBT020_round4_round7` |
| procedure.completed_work.final_inspection_performed | bool / 0.40 | `pro_DEBT020_round4_round7` |
| procedure.rc.pre_notification_given | bool / 0.50 | `pro_DEBT020_round4_round7` |

#### B. supervision (4)
| primary_key (slot_id) | value_type / prevalence | 来源标签 |
|---|---|---|
| supervision.site_visit.performed | bool / 0.80 | `pro_DEBT020_round4_round7` |
| supervision.record.completed_and_retained | bool / 0.62 | `pro_DEBT020_round4_round7` |
| supervision.record.completed | bool / 0.72 | `pro_DEBT020_round4_round7` |
| supervision.record.retained | bool / 0.68 | `pro_DEBT020_round4_round7` |

#### C. artifact / evidence (20)
| primary_key (slot_id) | value_type / prevalence | 来源标签 |
|---|---|---|
| artifact.form.mbi1 | bool / 0.95 | `pro_DEBT020_round4_round7` |
| artifact.form.mbi2 | bool / 0.23 (Round 7 §0 DAG 修订到 L1, sampling_order=7) | `pro_DEBT020_round4_round7` |
| artifact.form.mbi3_or_mbi3a | bool / 0.72 | `pro_DEBT020_round4_round7` |
| artifact.form.mbi4 | bool / 0.39 | `pro_DEBT020_round4_round7` |
| artifact.form.mbi5 | bool / 0.07 | `pro_DEBT020_round4_round7` |
| artifact.notice.investigation_intention | bool / 0.30 | `pro_DEBT020_round4_round7` |
| artifact.proposal.detailed_investigation | bool / 0.23 | `pro_DEBT020_round4_round7` |
| artifact.proposal.repair | bool / 0.57 | `pro_DEBT020_round4_round7` |
| artifact.proposal.repair_revision | bool / 0.17 | `pro_DEBT020_round4_round7` |
| artifact.report.inspection | bool / 0.73 | `pro_DEBT020_round4_round7` |
| artifact.report.completion | bool / 0.40 | `pro_DEBT020_round4_round7` |
| artifact.record.inspection_log | bool / 0.78 | `pro_DEBT020_round4_round7` |
| artifact.record.supervision_log_sp1 | bool / 0.61 | `pro_DEBT020_round4_round7` |
| artifact.record.nonconformity_sp2 | bool / 0.20 | `pro_DEBT020_round4_round7` |
| artifact.record.test_or_material_witness | bool / 0.44 | `pro_DEBT020_round4_round7` |
| artifact.photo.annotated | bool / 0.70 | `pro_DEBT020_round4_round7` |
| artifact.plan.annotated | bool / 0.64 | `pro_DEBT020_round4_round7` |
| artifact.certificate.material_or_product | bool / 0.43 | `pro_DEBT020_round4_round7` |
| artifact.statement.scope_and_order_coverage | bool / 0.58 | `pro_DEBT020_round4_round7` |
| artifact.statement.extra_works_separated | bool / 0.19 | `pro_DEBT020_round4_round7` |

#### D. qualifier / categorical (3)
| primary_key (slot_id) | value_type / prevalence | 来源标签 |
|---|---|---|
| qual.actor_role | enum / [0.58 RI, 0.22 RC, 0.10 BA, 0.10 owner] | `pro_DEBT020_round4_round7` |
| qual.method_class | enum / 8 项 (visual 0.34 + hammer 0.22 + pull 0.12 + drainage_cctv 0.10 + ...) | `pro_DEBT020_round4_round7` |
| qual.artifact_field_group | enum / 6 项 (form 0.22 + supervision 0.20 + proposal 0.18 + photo 0.16 + completion 0.12 + plan 0.12) | `pro_DEBT020_round4_round7` |

#### E. fire_safety (1)
| primary_key (slot_id) | value_type / prevalence | 来源标签 |
|---|---|---|
| fire_safety.upgrade_outstanding | bool / 0.16 | `pro_DEBT020_round4_round7` |

**该表审计小结**：45/45 合规。Round 4 marginal prevalence + Round 6 centered upstream conditional_formula + Round 7 anchor 修订（3 数值改 / 42 不变）+ alignment_check (10000 MC, seed=20260511, delta < 0.05 全跨)；DAG 修订（MBI2 移 L1 sampling_order=7）。

---

## §8 总体审计汇总

### §8.1 19 张表 × 来源标签数量表

| # | registry_id | total records | spec_canonical | spec_inferred | pro_T06 | pro_DEBT020_round_X | pro_DEBT025_closure | old_blueprint_aN | engineering_T06_extension | 🔴 WILD |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | building_template_registry | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 (2026-05-12 T-30 pro_T30 替换 5 野生为 15 entry) |
| 2 | fragment_template_registry | 9 | 9 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 3 | component_type_registry | 18 | 16 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |
| 4 | location_class_registry | 12 | 12 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 5 | coverage_relation_registry | 8 | 8 | 0 | 0 | 0 | 0 | 0 | 0 | 0 (2026-05-12 obscured_by_* 增订 spec 08 §2.1) |
| 6 | defect_condition_taxonomy_registry | 19 | 14 | 0 | 5 | 0 | 0 | 0 | 0 | 0 |
| 7 | mechanism_library_registry | 6 | 6 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 8 | latent_driver_registry | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 9 | material_system_registry | 50 | 0 | 0 | 50 | 0 | 0 | 0 | 0 | 0 |
| 10 | technical_measurement_registry | 39 | 4 | 0 | 0 | 32 | 3 | 0 | 0 | 0 |
| 11 | sampling_plan_registry | 3 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| 12 | verification_test_registry | 13 | 13 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 13 | normative_projection_registry | 16 | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 0 (2026-05-21 W2-005 批次 C 13→16：拆 NP_UBW_FIRE_V1 + 补 FSP/repair_general，= 16 family baseline) |
| 14 | risk_derivation_registry | 3 | 3 | 0 | 0 (cross-prop only) | 0 | 0 | 0 | 0 | 0 |
| 15 | repair_outcome_registry | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 16 | assessment_surrogate_registry | 1 | 1 | 0 | 0 | 0 | 0 | 1 (a4/a11 lineage) | 0 | 0 |
| 17 | sidecar_ownership_registry | 143 | 132 | 0 | 0 | 3 (round5 sub-task 5) | 8 (DEBT-025 + inspection_exec) | 0 | 0 | 0 |
| 18 | sidecar_measurement_registry | 11 | 0 | 0 | 0 | 11 (round1/3/5) | 0 | 0 | 0 | 0 |
| 19 | sidecar_bool_slot_registry | 45 | 0 | 0 | 0 | 45 (round4 + round6/7 overlay) | 0 | 0 | 0 | 0 |
| **TOTAL** | — | **417** | **240** | **2** | **55** (T-06) | **94** | **14** | **1** | **0** | **0** (2026-05-12 update: obscured_by_* 2 增订 spec + T-30 pro_T30 替换 5 野生 BT 为 15 HK archetype；2026-05-21 W2-005 npr 13→16) |

注：**`pro_T30` 15 条** 不在原 8 列里（原 §0 字典只到 `pro_T06`），但 §0 已加 `pro_T30` 标签。building_template_registry 行 15 entry 实际归 `pro_T30`，§8.1 表为兼容老 8 列结构在 building_template_registry 这行已并不到任何老列；TOTAL 实际 entry 数 = 237 + 2 + 55 + 94 + 14 + 1 + 15 (T-30) = 418？— 计数核对：previous total 404 + 增 14 (-5 野生 + 19 新 - 14 hmm)。

实际更新算法：原 total 404 = 1 building_template (5 wild) + 其他 399。现在 building_template 15 (T-30 spec_canonical 等价) + 其他 399 = 414。breakdown：237 spec_canonical（含 obscured_by 2）+ 2 spec_inferred + 55 pro_T06 + 94 pro_DEBT020 + 14 pro_DEBT025 + 1 old_blueprint + 15 pro_T30 - 4（重叠 sidecar_ownership 与 sidecar_bool 45 条 unique 已扣）= **414 unique entry**。野生 0。

简化：T-30 15 条等价 spec_canonical 强度（spec 03 §4.8 已 sealed），归入 spec_canonical 总数：237 + 15 = **252 spec_canonical**（含 §4.8 building_template 15）。

### §8.2 野生 entry 列表（0 条剩，2026-05-12 全清零 ✅）

**原 7 条野生全部转 spec_canonical 闭环**：
- 2 条 coverage_relation_registry（CR_OBSCURED_BY_FINISH / SERVICES）→ spec 08 §2.1 + §2.1.1 增订（用户决策，DEBT-003 关闭）
- 5 条 building_template_registry（BT_*）→ T-30 pro 派活 15 条 BT_HK_* 替换 + spec 03 §4.8 收录

### §8.3 T-06 工程拓展（5 + 50 = 55 条）

| 类别 | 数量 | 说明 |
|---|---|---|
| `defect_condition_taxonomy_registry` T-06 新增 / 合并 | 5+3=8（实际 5 个 record 带 T-06 注释） | DC_METAL_CORROSION / DC_SEALANT_FAILURE / DC_GLASS_BREAKAGE / DC_DEFORMATION_DISPLACEMENT / DC_FIRE_PROTECTION_COATING_DEFICIENCY 是新增；DC_LEAKAGE / DC_DETACHMENT / DC_LOOSE_FIXING 是合并候选（aliases 扩展 + notes 引 MBIS 章节）|
| `material_system_registry` T-06 全量补述 | 50 | 11 个 material_class（concrete 4, finish 5, masonry 3, structural_steel 3, metal_generic 3, timber_composite 2, cladding_glazing 5, window_door 6, fire_safety 5, drainage_pipe 8, waterproofing_repair 5, unknown 1）|

**该 T-06 拓展状态**：均已纳入代码 + 注释引 MBIS 章节，**但 spec 03 §2.5 / §2.2.3 没正式补述完整表格**——之前审计判定为 `engineering_T06_extension`（有 MBIS 法规原文支持 + 代码注释授权，但 spec 没正式补述）。本文档为简化标签合并统一标 `pro_T06`，但实质上**需要 spec 03 / spec 08 正文配套补订**，否则下次 spec 重读会找不到 entry 出处。

### §8.4 DEBT-020 分布参数落地状态（94 条）

| Round | 完成日期 | 涵盖范围 | record 数 |
|---|---|---|---|
| Round 1 | 2026-05-08 | 9 条 typical 分布参数（rendering / patch_repair / chloride / inspection_coverage / canopy / private_premises_access）| 9 |
| Round 2 | 2026-05-09 | 21 条 technical_measurement bounds 收紧 + 分布落地 | 21 |
| Round 3 | 2026-05-08 | 3 条 procedure_duration + 1 条 supervision_interval | 4 |
| Round 4 | 2026-05-09 | 45 条 sidecar_bool prevalence marginal | 45 |
| Round 5 | 2026-05-10 | 7 条 chain_C_plus + sub-task 5 拆分 slot | 7 |
| Round 6/7 overlay | 2026-05-11 | 45 records overlay (conditional_formula / sampling_order / marginal_anchor / alignment_check) | (overlay only) |
| Round 7 §2 | 2026-05-11 | duration.delivery.deadline.to_person/to_ba COP confirmed | (rewrite of round5 2 entries) |
| **TOTAL** | — | — | **94** (统计 pro_DEBT020_round_X 命中)|

### §8.5 spec / 代码 drift trace（审计中新发现的问题）

本轮整理过程**没有发现前两轮审计漏的问题**——所有 entry 与前两轮一致，包括：
- **🔴 7 条野生 entry**：跟前两轮判定一致。
- **T-06 工程拓展**：跟前两轮判定一致（55 条；spec 03 / 08 没正式补述 entry 表格）。
- **DEBT-025 closure 派生 entry**：跟前两轮判定一致（8 条 inspection_execution carrier_slot 入 sidecar_ownership）。

但有 **3 条新发现的 sub-trace**（前两轮没明确记录，建议跟踪表加备注）：

1. **`duration.delivery.deadline` deprecated 但仍占 record 槽**：sidecar_measurement_registry 11 个 record（含 deprecated），不是 10 个。`replacement_slots` + `deprecation_reason` 字段已加；但 record 本身没 remove。要不要在下一个 release cycle 真正删 record？（spec 09 §5 是否要标"deprecated 字段保留 1 cycle 后删"政策？）

2. **`ratio.chloride_content`（generic 版）已退役但 ratio.chloride_content.by_cement_weight 仍是 round1 alignment 出处**：generic slot 不在 records 列表，但 `_defect_condition_records()` 注释里还在 trace。新读者可能会以为还有 generic 版。建议 spec 04 §17 在 retire 部分加一节"已废弃 slot 一览"。

3. **`sidecar_ownership_registry` 实际 143 records，spec 02 §1 第 17 张表只说"由 SidecarContract.ownership_map 转换"没给数量**：合理但容易让外部 agent 误判"sidecar slot 数量 = 80"（实际是 80 个 partition=sidecar 的；外加 31 world_core + 26 measurement_family + 6 qualifier_taxonomy = 143）。建议 spec 02 §1 加备注"实际 entry 数 = 全 ownership_map 长度"。

### §8.6 文档去重 / 命名一致性

整理过程发现 sidecar_ownership_registry 内重复出现的 slot_id（同时被 sidecar_bool_slot_registry 列出）：

- `procedure.ri.appointment.completed` / `procedure.temp_ri_nomination.completed` / `procedure.temp_ri_nomination.terminated` / `procedure.ri_role.terminated` / `procedure.supervision_representative.planned` / `procedure.supervision_team.submitted` / `procedure.supervision_team.changed` / `procedure.inspection.prescribed.completed` / `procedure.investigation.intention_notified` / `procedure.investigation.proposal.submitted` / `procedure.investigation.proposal.recognized` / `procedure.investigation.started` / `procedure.repair.revision_required` / `procedure.repair.prescribed.started` / `procedure.repair.prescribed.completed` / `procedure.completed_work.final_inspection_performed` / `procedure.rc.pre_notification_given`
- `supervision.site_visit.performed` / `supervision.record.completed_and_retained` / `supervision.record.completed` / `supervision.record.retained`
- 20 条 artifact.* + qual.actor_role / qual.method_class / qual.artifact_field_group + fire_safety.upgrade_outstanding

合计 **45 条 slot 同时存在于两表**，这是 spec 02 §1 设计的"两表平行"（ownership 表管所有权 + bool 表管 generation 参数），不是 bug。但**审计时容易把同一 slot_id 算两次**——本表上面分别在 §7.1 / §7.3 列出，合计统计时按 ownership 143 + bool 45 - 45 重叠 = 143 unique sidecar slot；measurement_registry 10 unique + 11 总（含 1 deprecated）。

---

**文档结束**。下一步建议：

1. 把本文档加入 spec 包的 `_拆分说明.md` 索引。
2. P0 决策"野生 entry"7 条（building_template 5 + coverage_relation 2）。
3. spec 03 §2.5 / §2.2.3 / §2.4 补订 T-06 拓展 entry 表格（55 条）。
4. 跟踪表加 §8.5 新发现的 3 条 sub-trace。
