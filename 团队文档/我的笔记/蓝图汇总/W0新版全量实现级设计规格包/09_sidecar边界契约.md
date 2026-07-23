# Sidecar 边界契约

## 1. Sidecar 的目的

Sidecar boundary contract 划定 W0 物理 / 技术世界（building / component / measurement / defect / risk）与行政过程状态（artifact / procedure / supervision）的**容器边界**：两者写到不同 bundle、不同 slot 命名空间，便于法规映射层按需 join。**两者都由 worldgen 生成**——sidecar 不依赖任何外部 admin record，用建筑物理状态 + sidecar 自家分布参数自洽采样产出。

> 历史背景（2026-05-09 修订）：原 §1 把 sidecar 写成"W0 不持有 / 等外部 admin record 注入 / 缺失时 projection emit `sidecar_missing`"，这是把 B 类 slot 的**语义**（描述过去行政状态）误读成了**生成路径**（必须从外部送入）。本数据生成项目并不存在外部 admin record 的供给方，所有 truth（含 B 类）都由算法生成。本版统一为：sidecar bundle 是 worldgen 的派生层之一，与 WorldBundle 同源、同时输出。

本文件覆盖 sidecar 边界定义（§2、§5、§7、§8）和 sidecar bundle 生成 / projection 消费规则（§1.2、§3、§4、§6）。

来源：`01_a12_权威旧蓝图.md`:L1894-L1936；`03_a11_权威旧蓝图.md`:L159-L173；用户口径（2026-05-09）"B 类数据跟 A 类数据一样，根据建筑物理状态 + 推荐分布参数直接生成，没有等外部送文件这回事"。

## 1.1 B 类 slot 小口（语义分类，不是生成路径分类）

`01_设计原则与本体边界.md` §1.1 把 canonical slot 按 **slot 语义所描述的对象类别** 分两类。B 类语义指"行政过程 / 历史合规状态"，A 类语义指"楼宇物理 / 测量 / 派生事实"。**两类的生成路径相同**——都由 worldgen 按"建筑物理 state + recommended_distribution"采样；区别只在写入哪个 bundle。

### 1.1.1 已实质存在的 B 类（语义 = 过去行政过程状态）

| slot cluster | 例 | slot 语义 |
| --- | --- | --- |
| Procedure / gate | `procedure.ri.appointment.completed`、`procedure.investigation.intention_notified`、`procedure.repair.prescribed.completed` 等 | 程序节点是否完成（过去行政状态） |
| Supervision | `supervision.site_visit.performed`、`supervision.record.completed_and_retained` | 监管动作是否完成（过去监管状态） |
| Artifact / evidence | `artifact.form.mbi*`、`artifact.report.inspection`、`artifact.proposal.repair` 等 | 行政文件是否提交（过去文档状态） |
| Sidecar qualifiers | `qual.actor_role`、`qual.artifact_field_group` | 行政角色 / 文档字段分组（actor 维度） |

这些 slot 的值由 worldgen sidecar 派生层生成（具体路径见 §1.2）：bool / categorical slot 按 `sidecar_bool_slot_registry.prevalence` 采样（marginal-only baseline；后续可加 `conditional_formula` 让楼龄 / defect 等 W0 state 调制概率），numeric slot 按 `sidecar_measurement_registry.recommended_distribution` 采样。

来源：`06_a4_canonical_slot_universe_权威旧蓝图.md`:L109-L164；`03_a11_权威旧蓝图.md`:L220-L240。

### 1.1.2 本版新归位的 B 类

`fire_safety.upgrade_outstanding` 在旧 a4 中被记为 `world_truth_slot`，新版按"语义 = 行政状态（BD statutory order open or closed）"归 B 类，写入 sidecar bundle。物理消防缺陷由 `FireSafetyState.deficiency_present` 承担，不混入此 slot。生成路径仍是 worldgen 自家采样（按 building 楼龄 / fire_safety_state condition 推 statutory order open 概率）。

来源：`06_a4_canonical_slot_universe_权威旧蓝图.md`:L61-L61；`03_a11_权威旧蓝图.md`:L232-L240。

### 1.1.3 边界（不可越线）

1. B 类 slot 不进 `WorldBundle`，写入独立的 `SidecarRuntimeBundle`；
2. sidecar 派生层与 worldgen core 一样守 rule-blind：不读 `normative_projection_registry`、不调法规 family / rule_ids；
3. sidecar 派生层可读 `WorldBundle`（共用 building 物理 state 作 conditional 采样的输入）+ `sidecar_measurement_registry.recommended_distribution`（numeric）+ `sidecar_bool_slot_registry.prevalence` 和 `conditional_formula`（bool / categorical）；
4. sidecar 派生失败（如 fragment 不适用 → not_applicable）时，对应 slot emit `unknown` / `not_applicable`，**不伪造**；不存在"sidecar 缺失"这一态——sidecar bundle 总是生成，只是某 slot 可能 not_applicable。

## 1.2 Sidecar bundle 生成路径（2026-05-09 修订）

```text
WorldGenerator pipeline (per building):
  1. generate_world_batch → WorldBundle (A 类 slot)
  2. _build_sidecar_runtime_bundle_for_buildings(building_worlds, registries)
      → SidecarRuntimeBundle (B 类 slot)
      双路径采样（按 slot value_type 分流）：
        a) numeric slot (duration / interval / inspection_coverage / inspection_plan)
           → sidecar_measurement_registry.recommended_distribution
           → _sample_value_for_slot 采样
        b) bool / categorical slot (procedure.* / artifact.* / supervision.* / qual.*)
           → sidecar_bool_slot_registry.prevalence (+ optional conditional_formula)
           → bernoulli (bool) / multinomial (enum) 采样
      按 carrier_domain 派发到对应桶：
        procedure_gate_state / artifact_requirement_state / supervision_runtime_state /
        completion_runtime_state / facts
  3. build_normative_projections_for_world(WorldBundle, SidecarRuntimeBundle)
      → NormativeProjection (法规映射层 join 两个 bundle)
```

**两类 slot schema 边界**：

| slot 类型 | 主 registry | partition / ownership |
|---|---|---|
| numeric (duration / ratio / count / length / time) | `sidecar_measurement_registry` (recommended_distribution / mean / sigma / bounds) | `sidecar_ownership_registry` |
| bool / categorical (procedure 完成性 / artifact 提交性 / supervision 执行性 / qual 角色) | `sidecar_bool_slot_registry` (prevalence / conditional_inputs / conditional_formula) | `sidecar_ownership_registry` |

`sidecar_ownership_registry` 只管 ownership / partition / carrier / join_keys / projection_consumable，**不含**生成参数；这与对应的 sidecar_measurement_registry / sidecar_bool_slot_registry 形成单一职责拆分。

**禁止**：任何"等外部 SidecarInput 注入"的接口；任何"sidecar 缺失时 emit sidecar_missing marker 占位"的路径。这两个都是旧版基于错误前提的产物，本版废止。

## 2. Ownership map

| Slot / object group                                           | owner                  | projection 可消费 | world truth? | 新版处理          | 来源                                 |
| ------------------------------------------------------------- | ---------------------- | ----------------: | -----------: | ----------------- | ------------------------------------ |
| building / component / location / material                    | worldgen core          |                 Y |            Y | W0 生成           | `01_a12_权威旧蓝图.md`:L1896-L1910 |
| condition / defect / drainage / UBW / fire physical state     | worldgen core          |                 Y |            Y | W0 生成           | 同上                                 |
| geometry measurements                                         | worldgen measurement   |                 Y |            Y | W0 生成           | 同上                                 |
| coverage / sampling measurements                              | worldgen measurement   |                 Y |            Y | W0 生成           | 同上                                 |
| technical validation measurements                             | worldgen measurement   |                 Y |            Y | W0 生成           | 同上                                 |
| assessment measurements                                       | worldgen measurement   |                 Y |            Y | W0 生成           | 同上                                 |
| derived risk / repair / verification flags                    | worldgen derived layer |                 Y |   Y, derived | W0 派生           | 同上                                 |
| artifact / report / form / log / photo / certificate          | sidecar artifact layer |    Y through join |            N | sidecar           | 同上                                 |
| procedure / appointment / submission / recognition / deadline | procedure sidecar      |    Y through join |            N | sidecar           | 同上                                 |
| supervision / team / site visit / SP1 / SP2 / witness         | supervision sidecar    |    Y through join |            N | sidecar           | 同上                                 |
| actor roles                                                   | sidecar qualifier      |    Y through join |            N | sidecar qualifier | 同上                                 |

## 3. Projection consume contract

```text
ProjectionExecutorConsumes:
  worldgen_core:
    - WorldBundle
    - MeasurementRecord[]
    - DerivedFlags

  worldgen_sidecar:
    - SidecarRuntimeBundle
        - procedure_gate_state
        - artifact_requirement_state
        - supervision_runtime_state
        - completion_runtime_state
        - facts (qualifier 通用桶)

  merge_key:
    - world_id
    - building_id
    - fragment_id
    - component_id
    - slot_id
```

来源：`01_a12_权威旧蓝图.md`:L1912-L1930（结构沿用，sidecar 改为 worldgen 自家派生层）；用户口径（2026-05-09）。

规则：

1. `WorldBundle` 与 `SidecarRuntimeBundle` 在 worldgen pipeline 中**成对生成**，projection executor 可同时消费。
2. sidecar 派生失败（slot not_applicable 或采样无解）时，对应 slot 输出 `unknown` / `not_applicable`，不伪造其他值。
3. sidecar 不得改写 world truth（A 类 slot owner 仅 worldgen core）。
4. 法规映射层不得反向写入 `WorldBundle` 或 `SidecarRuntimeBundle`。

## 4. Contract vs runtime convenience

旧 `a12` 在 contract vs runtime convenience 表中包含 `HiddenGold`，新版删除该行。其余字段保留以下口径：

| 字段                                     | research contract |   runtime convenience | 新版处理                                         | 来源                                                                 |
| ---------------------------------------- | ----------------: | --------------------: | ------------------------------------------------ | -------------------------------------------------------------------- |
| `world_id`,`fragment_id`,`slot_id` |                 Y |                     Y | 保留                                             | `01_a12_权威旧蓝图.md`:L1938-L1949                                 |
| `registry_version`                     |                 Y |                     Y | 保留                                             | 同上                                                                 |
| `generator_debug_trace`                |                 N |                     Y | 不作为 research contract；不得进入规格包正式输出 | 同上                                                                 |
| `raw_rng_draws`                        |                 N |                     Y | 不作为 research contract；不得进入正式 QA gold   | 同上                                                                 |
| `projection_cache`                     |                 N |                     Y | runtime convenience only                         | 同上                                                                 |
| `basis_items`                          |                 Y |                     Y | 保留为 `NormativeProjection`正式输出           | 同上                                                                 |
| `sidecar_join_status`                  |                 Y |                     Y | 保留                                             | 同上                                                                 |
| `HiddenGold`                           |          旧稿为 Y | 旧稿称 runtime 不暴露 | 新版删除                                         | `01_a12_权威旧蓝图.md`:L1940-L1949；`09_用户原则说明.md`:L20-L25 |

## 5. Sidecar-only slot clusters

### 5.1 Procedure / gate

Sidecar procedure slots 包括：

```text
qual.actor_role
qual.method_class
procedure.ri.appointment.completed
procedure.temp_ri_nomination.completed
procedure.temp_ri_nomination.terminated
procedure.ri_role.terminated
procedure.supervision_representative.planned
procedure.supervision_team.submitted
procedure.supervision_team.changed
procedure.inspection.prescribed.completed
procedure.investigation.intention_notified
procedure.investigation.proposal.submitted
procedure.investigation.proposal.recognized
procedure.investigation.started
procedure.repair.revision_required
procedure.repair.prescribed.started
procedure.repair.prescribed.completed
procedure.completed_work.final_inspection_performed
procedure.rc.pre_notification_given
supervision.site_visit.performed
supervision.record.completed_and_retained
```

来源：`06_a4_canonical_slot_universe_权威旧蓝图.md`:L109-L135。

### 5.2 Artifact / evidence

Sidecar artifact slots 包括：

```text
qual.artifact_field_group
artifact.form.mbi1
artifact.form.mbi2
artifact.notice.investigation_intention
artifact.proposal.detailed_investigation
artifact.report.inspection
artifact.form.mbi3_or_mbi3a
artifact.proposal.repair
artifact.proposal.repair_revision
artifact.report.completion
artifact.form.mbi4
artifact.form.mbi5
artifact.record.inspection_log
artifact.record.supervision_log_sp1
artifact.record.nonconformity_sp2
artifact.record.test_or_material_witness
artifact.photo.annotated
artifact.plan.annotated
artifact.certificate.material_or_product
artifact.statement.scope_and_order_coverage
artifact.statement.extra_works_separated
```

来源：`06_a4_canonical_slot_universe_权威旧蓝图.md`:L137-L164。

## 6. Sidecar 派生异常时 projection 输出策略

SidecarRuntimeBundle 由 W1 sidecar 派生层产出后，对 W2 只读。W2 不补派生、不重派生、不伪造 sidecar fact。

封口版 sidecar join 只有三态：

| `sidecar_join_status` | 含义 |
|---|---|
| `available` | 所需 sidecar 桶与 key 均可 join |
| `partial` | 部分 sidecar 接口可 join，部分缺失 |
| `unavailable` | 所需 sidecar 接口不可用 |

sidecar 派生异常不新增字段、不新增 reason code、不输出 `sidecar_derivation_failed`。需要进入 unknown 时，W2 使用 `unknown_reason_code=sidecar_only_fact_pattern`。


## 7. 不建时序引擎

当前阶段不建事件链 / 不建时序引擎。Time-related fields 只能作为 scalar qualifiers，不生成 temporal reasoning engine。（来源：`01_a12_权威旧蓝图.md`:L1951-L1962）

因此：

* `duration.notification.deadline`
* `duration.submission.deadline`
* `duration.delivery.deadline`
* `duration.site_visit.interval`

这些虽然在 canonical slot universe 中是 measurement_slot，但 carrier 是 procedure / supervision，因此进入 sidecar，不进入 W0 world core。（来源：`06_a4_canonical_slot_universe_权威旧蓝图.md`:L83-L86；`03_a11_权威旧蓝图.md`:L220-L230）

## 7.1 inspection_execution 域 sidecar slot（DEBT-025 closure 2026-05-06 增订）

下列 5 个 slot 描述的是"监管执行过程数据"（检验覆盖比例 / 抽样频率 / 抽查计划），是巡检/监管动作的数值参数，不是楼宇物理状态本身。归类决议依据：用户主导的 rule_card 审计（详见 `杂物箱/文件包/DEBT-025_rule_card_审计/AUDIT_20260506_missing_w0_slots.md` §F2）判定：检验执行性质数据应留 sidecar inspection_execution，不入 W0 technical_measurement。生成路径与其他 sidecar slot 相同——worldgen sidecar 派生层按 `sidecar_measurement_registry.recommended_distribution` 采样。

`sidecar_measurement_registry.carrier_domain` 因此扩充为 `procedure / supervision / inspection_execution` 三类：

| slot_id | family | unit | bounds | carrier_slot | rule_basis_refs |
|---|---|---|---|---|---|
| `ratio.external_wall_area.inspected`           | inspection_coverage | ratio | `[0, 1]`   | `inspection.external_wall.coverage_evidence` | MBIS COP 2023 §3.3.2(J)(c) |
| `ratio.covered_structure_area.inspected`       | inspection_coverage | ratio | `[0, 1]`   | `inspection.structural.coverage_evidence`    | MBIS COP 2023 §3.4.2(C)(a)、§3.4.2(B)(a) |
| `count.canopy.check_locations.minimum`         | inspection_plan     | count | `[0, 50]`  | `inspection.canopy.check_plan`               | MBIS COP 2023 §3.4.2(B)(e) |
| `length.canopy.check_location.interval`        | inspection_plan     | m     | `[0, 100]` | `inspection.canopy.check_plan`               | MBIS COP 2023 §3.4.2(B)(e) |
| `count.private_premises_access.floor_interval` | inspection_plan     | floor | `[1, 50]`  | `inspection.private_premises.access_plan`    | MBIS COP 2023 §3.6.2(A)(b)-(c) |

**与 spec 04 §17 的关系**：本节 5 个 slot 由 spec 04 §17 表中迁出（spec 04 §17 早期把它们归为 W0 technical_measurement family=coverage_sampling，DEBT-025 closure 2026-05-06 推翻该归类）。

## 8. 明确禁止

| 禁止项                                                                                | 理由                                | 来源                                  |
| ------------------------------------------------------------------------------------- | ----------------------------------- | ------------------------------------- |
| 将 artifact/report/form/log/photo/certificate 写入 `WorldBundle`                    | artifact 不是 world truth；归 sidecar bundle | `01_a12_权威旧蓝图.md`:L1907-L1908  |
| 将 procedure / appointment / submission / recognition / deadline 写入 `WorldBundle` | procedure 是 sidecar 桶              | `01_a12_权威旧蓝图.md`:L1908-L1909  |
| 将 supervision workflow 写入 `WorldBundle`                                          | supervision 是 sidecar 桶            | `01_a12_权威旧蓝图.md`:L1909-L1910  |
| sidecar 派生层读 `normative_projection_registry` / 调法规 family / rule_ids       | sidecar 与 worldgen core 同守 rule-blind | 用户原则（2026-05-09）              |
| sidecar 派生层依赖外部 admin record / SidecarInput 注入                              | 数据生成项目无外部供给方；统一 worldgen 自家采样 | 用户口径（2026-05-09）            |
| sidecar 派生写入伪造值 / 中点 fallback / threshold ± noise anchor                    | sidecar 与 A 类 measurement 同守 Layer 4 禁令 | `01_设计原则与本体边界.md` §1.1.1 |
| 用 sidecar 生成 HiddenGold / episode                                                  | 新版删除巡检员模拟 / benchmark gold | `09_用户原则说明.md`:L5-L8、L20-L25 |

---
