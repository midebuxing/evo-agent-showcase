# 15. Parquet 列存（column store）落地 Schema

> 跨包权威源与负向不变量见：`../_封口总则_字段权威源与负向不变量.md`。如本章与总则冲突，以总则和字段所属包权威章节为准。


**版本**: W0-parquet-v1
**日期**: 2026-05-10
**状态**: 全替换实施（不双轨；存量 JSON 通过 migration 脚本一次性转换）

---

封口补充：凡涉及 `NormativeProjection` / `ProjectionFamilyEval` / `ThresholdEval` / `ReportBasisItem` 的列存字段，字段语义与 enum 权威均以 W2 `09_输出契约_NormativeProjection.md` 为准；本章只描述列存承载形态，不单独定义 verdict enum。

## 1. 背景与范围

W0 worldgen 当前以 3 个嵌套 JSON bundle 持久化每个 seed 的产出，单 release_batch 5 seed × 3000 building × 4 fragment 实测 ≈ 18 GB；增量 cost 不可持续。本章描述 parquet 列存（**parquet column store / 列式存储**）格式，目标 ≥10× 压缩。

### 替换范围（全替换）

| 文件 | 原 JSON 大小（单 seed × 3000 building） | 替换后 |
|---|---|---|
| `WorldgenWorldBundles.v2.json` | 847 MB | `worldgen_world_bundles.parquet`（拆 6 张表） |
| `WorldgenSidecarRuntimeBundle.v2.json` | 1600 MB | `worldgen_sidecar_runtime.parquet`（1 张表） |
| `WorldgenNormativeProjection.v2.json` | 555 MB | `worldgen_normative_projection.parquet`（拆 3 张表） |

### 保持 JSON（≤ 1 MB 体量小，无收益）

- `WorldgenRegistryBundle.v2.json`（251 KB）
- `WorldgenSidecarContract.v2.json`（37 KB）
- `WorldgenFullCoverageValidation.v2.json`（1.2 KB）
- `RegulationProjectionSummary.v2.json` / `Samples.v2.json`（聚合 / 抽样产出，仍 JSON）

---

## 2. 总体决策（Design Decisions）

### 2.1 Decision A — pyarrow 直写（不引入 pandas）

仅用 `pyarrow.Table` + `pyarrow.parquet.write_table`，避免 pandas 大对象内存占用。所有 list/struct 列由 pyarrow 原生 type 表达。

### 2.2 Decision B — 嵌套字段（不规则 dict）一律 JSON-string 列存储

对于 schema 不固定的嵌套字段（如 `qualifiers` 每条 entry keys 不同；`derived_outcomes` 子 dict 内键名按 condition_class 变化）：直接 `json.dumps(..., sort_keys=True, ensure_ascii=False)` 序列化为 string 列存储，读时 `json.loads` 还原。

理由：
- 跨条目 schema 漂移 → struct/map 列无法干净表达
- 这类字段在下游聚合/过滤时极少作为列谓词（predicate），损失可忽略
- 列内字符串重复度高 → parquet dict encoding 仍有压缩
- 还原代码 1 行，无 schema 演进负担

### 2.3 Decision C — 顺序保持（list 顺序敏感）

`buildings`、`fragments` 等 list 顺序对 deterministic_key 不敏感（hash 算的是 sorted JSON），但对人工 review 体验有用。**所有表加 `seq_no` int64 列**记录原 list index；还原时按 (parent_id, seq_no) 排序。

### 2.4 Decision D — measurements 长形式（long form）

原 JSON 中 measurements 是 list，每条已经扁平。直接做 long-form 表，行数 = 总 measurement 数 ≈ 33 × building_count。

### 2.5 Decision E — sidecar 6 个 list 桶合并为 1 表，加 `entry_type` 列区分

`facts` / `runtime_markers` / `artifact_requirement_state` / `procedure_gate_state` / `supervision_runtime_state` / `completion_runtime_state` 全部并到 `sidecar_entries.parquet`，加 enum 列 `entry_type` 区分。

### 2.6 Decision F — basis_items 单独一张表

`basis_items` 每条 6 个 `basis_kind` 字段子集不一致（threshold_compare / bool_assertion / family_uncovered / world_origin / measurement_origin），不强分多表，全字段一张宽表，缺失字段填 null。

### 2.7 Decision G — Codec & 压缩

- 编码：`compression="zstd"`、`compression_level=3`（zstd 在 ratio/速度上双优；level 3 在 W0 数据上压缩率与解压速度最平衡）
- Row group size：`64 MB` per group（pyarrow 默认）— 兼顾大 batch 流式读
- Dictionary encoding：默认开（pyarrow 自动；slot_id / 各 ID 列重复度高）

### 2.8 Decision H — deterministic_key 不变

`deterministic_key` 是 `_hash_payload(...)` 算的，输入是 `_canonical_json(payload)` —— 跟存储格式无关。Parquet 改造**不影响 hash**。本章不改任何业务字段、不改 hash 算法。

---

## 3. 文件 layout

```
gen_seed_<N>/
# worldgen 块（9 张表，对应 parquet_io.py _WB_FILES）
├── worldgen_world_bundles_meta.parquet       # batch 级 metadata（1 行/batch）
├── buildings.parquet                          # building shell（1 行/building）
├── fragments.parquet                          # fragment context（4 行/building）
├── components.parquet                         # ComponentNode（~8 行/building）
├── locations.parquet                          # LocationNode（~6 行/building）
├── coverage_relations.parquet                 # CoverageRelation（~4 行/building）
├── fragment_states.parquet                    # drivers/mechanisms/conditions/repair_assessment 合表（~4 行/building × 4 类）
├── specialized_states.parquet                 # drainage/ubw/fire_safety 合表（变长）
├── measurements.parquet                       # MeasurementRecord 长形式（~33 行/building）
# sidecar 块（3 张表，对应 parquet_io.py _SC_FILES）
├── sidecar_runtime_meta.parquet               # sidecar bundle metadata
├── sidecar_records.parquet                    # SidecarRuntimeRecord 头（1 行/fragment）
├── sidecar_entries.parquet                    # 全 6 桶 entries 合表（~54 行/fragment）
# normative_projection 块（6 张表，对应 parquet_io.py _NP_FILES）
├── normative_projection_meta.parquet          # projection bundle metadata
├── projections.parquet                        # NormativeProjection 头（~4 行/building）
├── matched_families.parquet                   # ProjectionFamilyEval（每 projection 0..N 行）
├── threshold_evaluations.parquet              # ThresholdEval（每 family 0..N 行）
├── coverage_control_metadata.parquet          # per-world CoverageControlBatchMetadata（W2-007 批次 D，spec 11 §3.2 6 字段）
└── basis_items.parquet                        # ReportBasisItem（每 projection 0..N 行）
```

总 18 个 parquet 文件（worldgen 9 + sidecar 3 + normative_projection 6）+ 3 个保留的小 JSON。W2-007（批次 D，2026-05-21）将 coverage_control_metadata 加入 normative_projection 块独立子表（避免污染 meta 单行 batch meta / projections per-projection 列）。

---

## 4. 表定义

### 4.1 `worldgen_world_bundles_meta.parquet`（1 行）

| 列名 | 类型 | 说明 |
|---|---|---|
| `version` | string | `"worldgen.fullcoverage.building_worlds.v2"` |
| `generated_at` | string | ISO 时戳 |
| `registry_bundle_hash` | string | hash |
| `batch_config_hash` | string | hash |
| `deterministic_key` | string | hash（关键：跨格式不变） |

### 4.2 `buildings.parquet`（1 行/building）

| 列名 | 类型 | 说明 |
|---|---|---|
| `seq_no` | int64 | building 在原 list 中的 index |
| `world_id` | string | 主键 PK |
| `schema_version` | string | |
| `generator_version` | string | |
| `random_seed` | int64 | |
| `building_id` | string | FK 用 |
| `building_template_id` | string | |
| `building_name` | string | |
| `building_use` | string | |
| `structure_type` | string | |
| `age_years` | float64 | |
| `storey_count` | int64 | |
| `unit_count` | int64 | |
| `primary_materials` | list&lt;string&gt; | |
| `configuration_tags` | list&lt;string&gt; | |
| `occupancy_state` | string | |

### 4.3 `fragments.parquet`（4 行/building）

按 spec 04 §7 `FragmentContext` 9 字段 reference-based contract（顶层封口总则 §2 line 27 背书）落地。物理上下文字段（has_rebar / cover_depth_mm / section_thickness_mm / nominal_length_m / nominal_visible_area_m2 / material_system / structural_role / surface_position / fragment_scope / exposure_zone / component_type_id 等）一律 **不**列入本表 denormalized cache 列，由消费方按 §0.1 reference 反查路径从 `components.parquet`（§4.4）+ `locations.parquet`（§4.5）+ spec 03 §4.1 `component_type_registry` 查得；同上 `building_metadata_json` / `component_graph_*_json` / `location_graph_*_json` / `specialized_domains_json` 等"沿用 building 元信息冗余字段"也撤出本表（依然 reference 反查 `buildings.parquet` + 各专项域表）。

| 列名 | 类型 | 说明 |
|---|---|---|
| `world_id` | string | FK → buildings |
| `seq_no` | int64 | 还原顺序索引 |
| `fragment_id` | string | PK，spec 04 §7 #1 |
| `fragment_template_id` | string | spec 04 §7 #2 |
| `component_id` | string | spec 04 §7 #3；reference-based 反查上游 component 物理上下文用 FK |
| `location_id` | string | spec 04 §7 #4；reference-based 反查上游 location 表面/暴露用 FK |
| `fragment_role` | string | spec 04 §7 #5（`inspection_target / adjacent_context / excluded_context / technical_test_zone`）|
| `fragment_area_m2` | float64 | spec 04 §7 #6 |
| `fragment_length_m` | float64 (nullable) | spec 04 §7 #7 |
| `in_scope` | bool | spec 04 §7 #8 |
| `exclusion_reason` | string (nullable) | spec 04 §7 #9 |
| `coverage_relation_ids` | list&lt;string&gt; | fragment 与 coverage 关系的索引列表（与 spec 04 §8 CoverageRelation 反向 join 用，spec 04 §7 9 字段外但仍是 fragment-level identifier 索引；非物理 denormalization） |

### 4.4 `components.parquet`（~8 行/building）

按 spec 04 §5 `ComponentNode` 8 + 1 字段（含 §5 新增 `cover_depth_mm` RC-specific 物理参数字段）落地。fragments.parquet（§4.3）reference-based 反查物理上下文的主上游表。

| 列名 | 类型 | 说明 |
|---|---|---|
| `world_id` | string | FK |
| `seq_no` | int64 | |
| `component_id` | string | PK |
| `component_type` | string | spec 04 §5 |
| `parent_component_id` | string (nullable) | spec 04 §5 |
| `material_system` | string | spec 04 §5；`has_rebar` 等价 derive 输入（`material_system == reinforced_concrete`） |
| `structural_role` | string | spec 04 §5 |
| `location_id` | string | spec 04 §5；反查 location 表面/暴露 FK |
| `geometry_proxy_json` | string | dict → JSON 串（`{length_m, width_m, height_m, visible_area_m2, thickness_mm}`，对应 spec 06 §0.1 `nominal_visible_area_m2 / section_thickness_mm` reference 反查源） |
| `cover_depth_mm` | float64 (nullable) | spec 04 §5 新增 RC-specific 物理参数；`material_system == reinforced_concrete` 时非 null，其他材质 null；spec 06 §4 / §9.X.1 / §10.X.2 公式 reference 反查源 |
| `access_class` | string | spec 04 §5 |

### 4.5 `locations.parquet`（~6 行/building）

| 列名 | 类型 |
|---|---|
| `world_id` | string |
| `seq_no` | int64 |
| `location_id` | string |
| `location_class` | string |
| `exposure_zone` | string |
| `storey_band` | string |
| `spatial_tags` | list&lt;string&gt; |

### 4.6 `coverage_relations.parquet`

| 列名 | 类型 |
|---|---|
| `world_id` | string |
| `seq_no` | int64 |
| `coverage_id` | string |
| `coverage_relation_type` | string |
| `target_fragment_id` | string |
| `coverage_state` | string |
| `covered_area_m2` | float64 |
| `inspected_area_m2` | float64 |
| `obscuration_class` | string |

### 4.7 `fragment_states.parquet` — drivers / mechanisms / conditions / repair_assessment 合表

加 `state_type` enum 列区分。每类各保留自己原有字段；不存在的字段为 null。

| 列名 | 类型 | 说明 |
|---|---|---|
| `world_id` | string | FK |
| `seq_no` | int64 | |
| `state_type` | string | enum: `driver` / `mechanism` / `condition` / `repair_assessment` |
| `state_id` | string | driver_id / mechanism_state_id / condition_id / repair_assessment_id |
| `fragment_id` | string (nullable) | |
| `payload_json` | string | **完整原 dict** → JSON 串 |

**决策说明**：drivers / mechanisms / conditions / repair_assessment 4 类各自字段差异大、嵌套深（如 `derived_outcomes.risk_flags` 子 dict 键名按 condition_class 漂移），强行展平会暴 100+ 列且大量 null。**全 dict → JSON 串存储**，每行 ID 列加上 fragment_id 索引可保证 join 性能。读时 `json.loads(payload_json)` 还原。

实测：单 condition entry 的 `derived_outcomes` 嵌套 4-5 层字典，列出 ~30 个 outcome flag；JSON 串平均 700-1500 字节，dict encoding 后压缩率高。

### 4.8 `specialized_states.parquet` — drainage / ubw / fire_safety 合表

| 列名 | 类型 |
|---|---|
| `world_id` | string |
| `seq_no` | int64 |
| `state_type` | string | enum: `drainage` / `ubw` / `fire_safety` |
| `state_id` | string |
| `payload_json` | string |

### 4.9 `measurements.parquet`（长形式 ~33 行/building）

字段全展开（schema 固定，列谓词友好）：

| 列名 | 类型 |
|---|---|
| `world_id` | string |
| `seq_no` | int64 |
| `measurement_id` | string |
| `target_ref` | string |
| `measurement_family` | string |
| `slot_id` | string |
| `value_num` | float64 (nullable) |
| `value_bool` | bool (nullable) |
| `value_enum` | string (nullable) |
| `unit` | string (nullable) |
| `precision_class` | string |
| `method_class` | string (nullable) |
| `sample_count` | int64 (nullable) |
| `confidence_index` | float64 |
| `derivation_refs` | list&lt;string&gt; |
| `derivation_mode` | string |
| `upstream_refs` | list&lt;string&gt; |
| `origin_chain_refs` | list&lt;string&gt; |
| `derived_from_measurement_ids` | list&lt;string&gt; |
| `notes` | list&lt;string&gt; |

注：原 JSON 含 `value` 计算字段（pydantic computed_field）；写时直接 drop（还原后 pydantic 重算）。

### 4.10 `sidecar_runtime_meta.parquet`

| 列名 | 类型 |
|---|---|
| `version` | string |
| `generated_at` | string |
| `source_documents` | list&lt;string&gt; |

### 4.11 `sidecar_records.parquet`（1 行/SidecarRuntimeRecord，~4 行/building）

| 列名 | 类型 |
|---|---|
| `seq_no` | int64 |
| `runtime_id` | string |
| `world_id` | string |
| `projection_id` | string |
| `interface_ids` | list&lt;string&gt; |

### 4.12 `sidecar_entries.parquet`（合并 6 桶，~54 行/record）

| 列名 | 类型 | 说明 |
|---|---|---|
| `runtime_id` | string | FK → sidecar_records |
| `seq_no` | int64 | 在 (runtime_id, entry_type) 内顺序 |
| `entry_type` | string | enum: `facts` / `runtime_markers` / `artifact_requirement_state` / `procedure_gate_state` / `supervision_runtime_state` / `completion_runtime_state` |
| `slot_id` | string | |
| `value_json` | string | value 任意类型 → JSON 串（兼容 bool/float/str/null） |
| `qualifiers_json` | string | dict → JSON 串 |
| `time_anchor_key` | string (nullable) | |
| `source_refs` | list&lt;string&gt; | |
| `notes` | list&lt;string&gt; | |

### 4.13 `normative_projection_meta.parquet`

| 列名 | 类型 |
|---|---|
| `version` | string |
| `generated_at` | string |
| `registry_bundle_hash` | string |
| `deterministic_key` | string |

### 4.14 `projections.parquet`（每 fragment 1 行 ≈ 4 行/building）

| 列名 | 类型 |
|---|---|
| `world_id` | string | FK + 还原时 group key |
| `seq_no_in_world` | int64 |
| `projection_id` | string | PK |
| `projection_registry_id` | string |
| `projection_family` | string |
| `projection_version` | string |
| `selected_family` | string |
| `projection_status` | string |
| `required_slots` | list&lt;string&gt; |
| `unknown_reason_code` | string (nullable) |
| `sidecar_join_status` | string |
| `severity_band` | string |
| `required_world_core_slots` | list&lt;string&gt; |
| `required_measurement_slots` | list&lt;string&gt; |
| `required_qualifier_slots` | list&lt;string&gt; |
| `required_sidecar_interfaces` | list&lt;string&gt; |
| `matched_component_refs` | list&lt;string&gt; |
| `matched_measurement_ids` | list&lt;string&gt; |
| `coverage_status` | string |
| `notes` | list&lt;string&gt; |

### 4.15 `matched_families.parquet`（每 projection 0..N 行）

| 列名 | 类型 |
|---|---|
| `projection_id` | string | FK |
| `seq_no` | int64 |
| `family_id` | string |
| `applicability_score` | float64 |
| `applicability_state` | string |
| `trigger_ids` | list&lt;string&gt; |
| `rule_ids` | list&lt;string&gt; |
| `slot_role_map_json` | string | dict → JSON 串 |
| `verdict` | string |

### 4.16 `threshold_evaluations.parquet`（每 family 0..N 行）

| 列名 | 类型 |
|---|---|
| `projection_id` | string | FK |
| `family_id` | string | FK to matched_families（联合 join） |
| `family_seq_no` | int64 |
| `seq_no` | int64 |
| `rule_id` | string |
| `slot_id` | string |
| `operator` | string |
| `threshold_value_json` | string | union 类型 → JSON 串 |
| `observed_value_json` | string | union 类型 → JSON 串 |
| `regime_tag` | string |
| `pass_bool` | bool |

### 4.17 `coverage_control_metadata.parquet`（每 world 0..1 行）

W2-007（批次 D 2026-05-21）新增，承载 per-world `CoverageControlBatchMetadata`（spec 11 §3.2 6 字段）；bucket counts 用 JSON 字符串透传以避免 schema 强约束 5 个 bucket 名。老 batch 输出无此文件，read 路径需兼容 missing。

| 列名 | 类型 |
|---|---|
| `world_id` | string | PK / FK → buildings |
| `coverage_control_profile_id` | string |
| `raw_candidate_bucket_counts_json` | string | JSON 字典 |
| `accepted_bucket_counts_json` | string | JSON 字典 |
| `rejected_bucket_counts_json` | string | JSON 字典 |
| `bucket_definition_version` | string |
| `public_report_note` | string |

### 4.18 `basis_items.parquet`（每 projection 0..N 行）

宽表，所有 `basis_kind` 子集字段并列；缺失填 null。

| 列名 | 类型 |
|---|---|
| `projection_id` | string | FK |
| `seq_no` | int64 |
| `basis_kind` | string | enum |
| `basis_id` | string |
| `family_id` | string |
| `rule_id` | string |
| `slot_id` | string |
| `source_projection_id` | string |
| `operator` | string (nullable) |
| `threshold_value_json` | string (nullable) |
| `unit` | string (nullable) |
| `regime_tag` | string (nullable) |
| `expected_value_json` | string (nullable) |
| `statement_code` | string (nullable) |
| `reason_code` | string (nullable) |
| `candidate_known_families` | list&lt;string&gt; |
| `observed_value_json` | string (nullable) |
| `pass_bool` | bool (nullable) |
| `source_ref` | string |

---

## 5. 关键技术权衡

### 5.1 为什么不全字段展平到列？

`drivers` / `mechanisms` / `conditions` 各 4 类合表后字段总数 100+ 且高度稀疏，列谓词收益小（实际只在聚合时按 type 过滤）；JSON 串列降低 schema 维护成本，重复度高时 parquet dict encoding 仍能取得高压缩比。**结构体（STRUCT）列方案**被否决：pydantic class 演进时 schema 演进困难，跨版本兼容差。

### 5.2 还原路径

读 parquet → 按 (world_id, seq_no) 重组 list → 还原 JSON-string 列 → 走 pydantic `WorldBundle.model_validate(...)` 还原 dict。**等价性测试**保证 round-trip dict 完全相等。

### 5.3 跨格式 deterministic_key 不变性

deterministic_key 算的是 `_canonical_json(payload)` 的 SHA256，**生成路径完全不变**，存储格式切换不影响。集成测试会在 100 building × 1 seed 上对比新旧 hash。

---

## 6. 验收

1. ✅ 单元测试：parquet 写 → 读 → JSON 还原 → 与原 dict 等价（递归 dict 比较）
2. ✅ 集成测试：100 building × 1 seed 跑完整 pipeline，新旧 deterministic_key byte-identical
3. ✅ 现有 worldgen pytest 全 PASS
4. ✅ Benchmark 报告显示 ≥10× 压缩比

---

## 7. 后续维护提示

- 修改 worldgen `models.py` 添加新字段时，需同步更新 `worldgen/parquet_io.py` 的 schema 与 column list
- 严禁在 parquet schema 里"吞掉"未知字段：`json_to_table` / `table_to_json` 函数应在遇到陌生 key 时显式 raise，而非 silent drop
- migration 脚本 `migrate_json_to_parquet.py` 是一次性工具；新跑批次直接产 parquet 不再写 JSON
