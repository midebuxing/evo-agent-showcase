# Unknown 策略（W2 法规映射层）

W2 法规映射层 phase 3 主循环对每个 fragment 评估 family 时，遇 family conflict 无解 / required slot 缺 / binding 不兼容 / sidecar 派生异常 等场景，输出走 **`unknown` / `not_applicable` / `sidecar` 派生异常 fallback** 三种路径之一。本章列三态语义边界 + 13 条 `unknown_reason_code` 完整枚举（**2026-05-13 重审撤回原计划新增的第 14 条 `sidecar_derivation_failed`**——sidecar join 不可用 fallback 沿用现有 13 条之一兜底，详见 §3）+ W2 范围之外的 fallback 边界。

**与 W0 规格 06 §16.1-§16.5 的关系**：W0 规格 06 §16.1-§16.2 列 unknown 设计原则（"unknown 不是兜底垃圾桶"）+ unknown surrogate 公式（留 W0），§16.3-§16.5 列 projection unknown reason codes + `not_applicable` 语义 + sidecar join 不可用 fallback（**法规映射层**，迁出本章）。W0 规格 06 闭环后留 stub 引本章。

**与本包其他章节的关系**：

- **`unknown_reason_code` 在 `NormativeProjection` 字段中的位置**：详见 `09_输出契约_NormativeProjection.md` §1.1（按 W0 规格 04 §18 锚定）
- **`multi_family_conflict` 触发场景**：详见 `07_threshold_regime与冲突回退.md` §4.3 情况 5
- **C023 `UNKNOWN_NO_RULE_IDS` 约束**：详见 `07_threshold_regime与冲突回退.md` §5.1

## 1. unknown / not_applicable / fallback 三态语义

按 W0 规格 06 §16.1-§16.2 + a12 §13.3 projection compile logic + a11 §35-§42：W2 端输出 NormativeProjection 含三种"非 covered"语义，**互斥不混用**——

### 1.1 三态语义对照

| 状态 | 物理含义 | `NormativeProjection.projection_status` | `NormativeProjection.unknown_reason_code` | `NormativeProjection.selected_family` |
|---|---|---|---|---|
| **`unknown`** | worldgen 宇宙中存在事实，但当前 normative family set **无法稳定投影**（信息不足 / 已知未知 / binding 不兼容）| `uncovered` 或 `conflict` | 必填（13 枚举之一，详见 §2）| `unknown` |
| **`not_applicable`** | slot 对当前 world / component / family **业务上不适用**（无 drainage state 时 drainage risk = `not_applicable` / 无 assessment 时 FSP flag = `not_applicable` 等）| `covered`（family 适用但 slot N/A）/ `uncovered`（family 全 N/A）| 空（None 或不填）| 选中的 family 或 `unknown` |
| **fallback（派生异常 fallback 路径）** | sidecar 派生层 / W1 派生 flag 派生失败 / 数据加载异常等**派生异常**——projection 不得伪造事实，按 unknown / not_applicable 兜底输出 | 同 unknown | 沿用现有 13 条之一（sidecar 派生失败用 `sidecar_only_fact_pattern`，priority 13，扩义为"sidecar 不能支撑事实"，详见 §3）| `unknown` 或选中的 family |

### 1.2 三态边界

- **unknown vs not_applicable 边界**：unknown 是"信息不足"（**有事实但不能投影**），not_applicable 是"业务不适用"（**根本无事实**）。例：
  - drainage 检查域 family `mbis.inspection.drainage` 对一个 fragment 评估
  - 该 fragment 是 `external_wall`（外牆构件）：drainage family 业务上不适用 → `not_applicable`
  - 该 fragment 是 `drainage_stack`（排水管）但缺 `DrainageState` 数据：family 业务上适用但信息不足 → `unknown`
- **unknown vs fallback 边界**：unknown 是 family / slot evaluator 评估失败的语义状态；fallback 是"派生层异常时不得伪造"的执行原则，输出仍走 unknown / not_applicable 通道（不引入新状态）。fallback 不是独立第三态，而是 unknown / not_applicable 触发条件的子集
- **三态不混用**：单 fragment 单 family 评估同时只在三态之一；W2 不输出 "unknown + not_applicable 混合态"

### 1.3 unknown 设计原则继承（按 W0 规格 06 §16.1）

按 a10 seed v1 立下的"unknown 必须显式枚举、不能笼统"原则（a10 实现本身已被 a12 全量取代，但原则继承）：

- **unknown 必须显式枚举**：不允许笼统兜底为 `unknown` 不填 reason_code；每条 unknown 必须挂 13 枚举之一
- **unknown 不是兜底垃圾桶**：用 unknown 必须能从 13 priority 路由确定具体原因
- **unknown 扩展需登记**：新版扩展后 unknown 含义是"事实存在但 family set 无法稳定投影 / sidecar-only / uncovered domain / registry/binding/unit/method 不能支持 projection"；新增 reason 需扩 13 枚举（按勘探报告 §12.1 长期 trace）

## 2. unknown_reason_code 完整枚举（13 条）

按 W0 规格 06 §16.3 line 1097-1111 + a12 §11.3 line 1674-1691 + 现役代码 `regulation_projection_executor.py::UNKNOWN_REASON_CODES`（L143-L157）：当前 spec 端 完整枚举段 + code 端 enum 均为 **13 条**。

### 2.1 13 条 reason_code 详细列表

按代码 `derive_unknown_reason_code`（L180-L242）的 priority order（most specific → most generic）：

| priority | `unknown_reason_code` | 触发场景 | 业务含义 |
|---|---|---|---|
| 1 | `multi_family_conflict` | `resolve_family_conflict` 行 8 兜底（同组 multiple applicable 但 selector 不允许 multi）| 多 family 同组竞争且无法解析；详见 `07_threshold_regime与冲突回退.md` §4.3 情况 5 |
| 2 | `no_known_family_match` | candidates 空 / required_slots_present 全 False | 当前 fragment 没有 known family applicable（如 mechanism_family 无 mapping / severity_index 太低）|
| 3 | `coverage_unimplemented_domain` | physical state 属未来域但 registry 未覆盖 | family 涉及 W2 当前未实施的业务域（如未来扩展的子域）|
| 4 | `binding_registry_gap` | required slot 中有 registry 未绑定 | `normative_projection_registry` schema 无法绑定某 slot（registry 缺记录 / slot 不在 universe）|
| 5 | `measurement_family_unimplemented` | measurement family 未实施 | measurement_family 名在 W2 当前 phase 不支持（如 a12 §11.2 表里未列）|
| 6 | `method_class_unimplemented` | test method 未实施 | technical_validation 的 method_class 在 W2 当前 phase 不支持 |
| 7 | `unsupported_material_system` | material / component 不被 binding 支持 | family applicability 要求某 material（如 RC），但 fragment material 不在 binding 支持范围 |
| 8 | `unsupported_component_type` | component_type 不被 binding 支持 | family applicability 要求某 component_type（如 structural_member），但 fragment component_type 不在 binding 支持范围 |
| 9 | `unsupported_damage_pattern` | condition_class 无 binding | condition_class 不在 family applicability 支持范围（如 family 不投影某 DC 类）|
| 10 | `unsupported_location_context` | location 不被 binding 支持 | location_class 不在 family applicability 支持范围 |
| 11 | `unit_incompatible` | 单位不匹配 | measurement unit 跟 binding expected unit 不一致（如 family 期望 `mm` 但 measurement 是 `m`）|
| 12 | `projection_binding_incompatible` | required slots present 但 unit/method 兼容但其它绑定问题 | 单位 + 方法都兼容，但 binding 还有其他不能解析的问题（兜底）|
| 13 | `sidecar_only_fact_pattern` | worldgen core 无事实但 sidecar 有事实 | 全部事实属 sidecar-only 域，worldgen core 无法支撑 projection 评估 |

### 2.2 reason_code priority 派生公式

按代码 `derive_unknown_reason_code` 实施：

```text
context = {
    "multi_family_conflict": bool,
    "has_known_family_match": bool (default True),
    "coverage_unimplemented_domain": bool,
    "binding_registry_gap": bool,
    "measurement_family_unimplemented": bool,
    "method_class_unimplemented": bool,
    "unsupported_material_system": bool,
    "unsupported_component_type": bool,
    "unsupported_damage_pattern": bool,
    "unsupported_location_context": bool,
    "unit_incompatible": bool,
    "projection_binding_incompatible": bool,
    "sidecar_only_fact_pattern": bool,
}

按 priority 1-13 顺序检查；第一个 True 触发的 reason_code 返回；
全部 False（且 has_known_family_match=True）返回 None（family 已 covered）。
```

### 2.3 触发条件 detector helpers

按 W2 unknown detector helpers：

| detector | 触发条件 | 输出 |
|---|---|---|
| `has_known_family_match(candidate_families)` | 至少一个 candidate 含 `required_slots_present=True` | bool |
| `is_sidecar_only_fact_pattern(world_facts_present, sidecar_facts_present)` | worldgen core 无事实但 sidecar 有事实 | bool |
| `detect_binding_registry_gap(required_slots, available_slot_bindings)` | required slot 中有 registry 未绑定 | bool |
| `detect_unit_incompatible(measurement_units, expected_units)` | measurement unit 跟 binding expected unit 不匹配 | bool |

其他 priority 3 / 5 / 6 / 7 / 8 / 9 / 10 / 12 的 detector 由 caller 端按 spec 13 priority 提供完整 context。

## 3. sidecar 派生异常封口口径

sidecar 派生异常不新增 unknown reason code，不输出 `sidecar_derivation_failed`。

### 3.1 处理规则

- sidecar 部分可用：`sidecar_join_status=partial`
- sidecar 不可用：`sidecar_join_status=unavailable`
- 若需要 unknown reason：`unknown_reason_code=sidecar_only_fact_pattern`

### 3.2 `sidecar_join_status` 字段处置

`sidecar_join_status` 固定 3 枚举：

| 枚举 | 含义 |
|---|---|
| `available` | 所需 sidecar 接口均可 join |
| `partial` | 部分所需 sidecar 接口可 join，部分不可用 |
| `unavailable` | 所需 sidecar 接口不可用 |

sidecar 派生异常不形成独立 enum。若该异常导致 projection unknown，使用 `unknown_reason_code=sidecar_only_fact_pattern`。


## 4. 不在 W2 范围的 fallback

按 W0 规格 06 §16.4 + a5 §108-§117 + W1 规格 07 §3 P3 不在 W1 章节：W2 范围之外的 fallback 处理路径——

### 4.1 W1 派生 not_applicable（不在 W2 范围）

按 W1 规格 07 §3 P3 / W0 规格 06 §11.X derived flag table 的 `unknown_policy` 列：

- W1 实例生成层 Step 9 派生 9 条 derived flag 时（按本包 `06_canonical_slots与projection_binding.md` §1.1 world_truth_slot 类），每条 flag 含 `unknown_policy` 列
- 例：`drainage_misconnection_present` 的 `unknown_policy = no drainage → not_applicable`——当 fragment 没有 DrainageState 时 W1 派生 flag 输出 `not_applicable`
- **这是 W1 派生层 fallback，不在 W2 范围**——W2 phase 3 主循环消费 W1 输出时如读到 W1 已派生 flag 值 `not_applicable`，W2 端按"该 slot 对当前 fragment N/A"处理，不重新评估
- W2 端**不主动** derive W1 flag 的 not_applicable——W2 只读 W1 输出

### 4.2 W0 surrogate unknown subtype（不在 W2 范围）

按 W0 规格 06 §16.2 + a10 seed v1 范围：

- W0 surrogate 公式（crack / spall / corrosion / drainage / UBW / fire-safety / coverage / FSP）含 `unknown_raw` + `unsupported_severity_index` 派生（按 a10 / W0 规格 06 §16.2 `unsupported_masonry_crack` / `moisture_surface_anomaly` 等 unknown subtype）
- 这是 W0 surrogate 层的 unknown subtype，**不在 W2 范围**——W2 phase 3 消费 W1 输出时只读已派生 ConditionState / MeasurementRecord，不重新跑 W0 surrogate
- W2 端**不主动** derive unknown surrogate subtype——W0 surrogate 是 W1 派生层使用，W2 只读结果

### 4.3 evo-agent 训练侧 fallback（不在 W2 范围）

按 W2 规格 00 §4.4 + W2 规格 01 §4：

- evo-agent 训练侧可能有 fallback 路径（如 query 缺数据时 model fallback 推理 / RAG 检索失败时 fallback 等）
- 这些 fallback **不在 W2 范围**——W2 输出 NormativeProjection 是 evo-agent 训练 / 评估的输入之一，不参与 evo-agent 内部 fallback 逻辑

### 4.4 rule_card v2 数据系统 fallback（不在 W2 范围）

按用户 2026-05-13 D-4 决策：

- rule_card v2 数据系统自身可能有 fallback 路径（如 rule_card 解析失败 / threshold 不存在 / family 不存在 / 等）
- 这些 fallback **不在 W2 范围**——W2 只消费 rule_card 数据，不维护 rule_card 数据系统的 fallback 逻辑（属 rule_card 团队责任）

## 5. 封口正文边界

本章 unknown reason code 固定 13 条。`sidecar_derivation_failed` 已撤回，不得作为第 14 条、字段名、sidecar status、basis kind 或占位值。

本章不记录实现状态或工程推进记录。


## 6. 来源

- unknown / not_applicable / fallback 三态语义：W0 规格 06 §16.1-§16.2 + a12 §13.3 + a11 §35-§42
- unknown 设计原则（"unknown 不是兜底垃圾桶"）：W0 规格 06 §16.1 + a10 seed v1 原则继承
- 13 条 `unknown_reason_code` 完整枚举：W0 规格 06 §16.3 line 1097-1111 + a12 §11.3 line 1674-1691
- `derive_unknown_reason_code` priority 派生 + detector helpers：W2 代码 `regulation_projection_executor.py` L180-L279（按 spec 不写代码现状原则只引方法语义，行号不进 spec）
- `not_applicable` 语义：W0 规格 06 §16.4 + a12 §13.3 + a5 §108-§117
- sidecar join 不可用 fallback：W0 规格 06 §16.5 + W0 规格 09 §6；封口版使用 `sidecar_join_status=partial|unavailable` + `unknown_reason_code=sidecar_only_fact_pattern`
- `sidecar_derivation_failed` 撤回：见顶层封口总则黑名单与本章 §3。
- W2 范围之外的 fallback 边界：W1 规格 07 §3 + W0 规格 06 §11.X / §16.2 + 用户 2026-05-13 D-4 决策
