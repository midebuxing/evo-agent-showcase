# W2 输出契约 — NormativeProjection

`NormativeProjection` 是 W2 法规映射层的 per-fragment 主输出对象。其字段权威归本章；W0 04 §§18-21 只保留迁出 stub。

W2 输出的是 reference truth，不是人类巡检最终决定。

## 1. 输出对象总览

```text
NormativeProjection
  ├── matched_families: List[ProjectionFamilyEval]
  │      └── threshold_evaluations: List[ThresholdEval]
  └── basis_items: List[ReportBasisItem]
```

## 2. `NormativeProjection` 字段合约

| 字段 | 类型 | 必填 | 取值 / 约束 | 语义 |
|---|---|---|---|---|
| `projection_id` | str | Y | `NP-<world_id>-<fragment_id>-<index>` | per-fragment projection instance id |
| `projection_registry_id` | str | Y | existing registry id or `NP_UNKNOWN_<fragment_id>` | 引用 W2 `normative_projection_registry` record |
| `world_id` | str | Y | existing W1 world id | 关联 W1 输出 |
| `fragment_id` | str | Y | existing W1 fragment id | 关联 W1 fragment |
| `projection_version` | str | Y | semver or dated spec version | W2 projection contract 版本 |
| `projection_family` | str | Y | 16 family + `unknown` | 当前 projection 所属 family |
| `matched_families` | List[`ProjectionFamilyEval`] | Y | 0..N | candidate family 评估结果 |
| `selected_family` | str | Y | 16 family + `unknown` | conflict 解析后选中 family |
| `projection_status` | str | Y | `covered` / `uncovered` / `conflict` | family 覆盖状态 |
| `expected_verdict` | str | Y | `pass` / `fail` / `unknown` / `not_applicable` | W2 reference truth；不是最终人工决定 |
| `required_slots` | List[str] | Y | slot ids | selected family 所需 slot union |
| `required_world_core_slots` | List[str] | Y | slot ids | world truth slots |
| `required_measurement_slots` | List[str] | Y | slot ids | W0 measurement / sidecar numeric slots |
| `required_qualifier_slots` | List[str] | Y | slot ids | qualifier slots |
| `required_sidecar_interfaces` | List[str] | Y | sidecar interface ids | artifact / procedure / supervision / completion / facts 接口 |
| `matched_component_refs` | List[str] | Y | component ids | matched W1 component refs |
| `matched_measurement_ids` | List[str] | Y | measurement ids | matched W1 measurement refs |
| `coverage_status` | str | Y | `world_core_ready` / `unsupported` | 世界端核心 slot 到位状态 |
| `sidecar_join_status` | str | Y | `available` / `partial` / `unavailable` | sidecar join 完整性 |
| `unknown_reason_code` | str / null | Y | 13 reason code or null | `expected_verdict=unknown` 或 `selected_family=unknown` 时必填 |
| `severity_band` | str | Y | `emergency` / `severe` / `moderate` / `minor` / `none` | severity 离散档 |
| `basis_items` | List[`ReportBasisItem`] | Y | 1..N | 判定依据；C025 必非空 |
| `notes` | List[str] | N | non-authoritative | 仅作解释性注释，不进入判定逻辑 |

## 3. `expected_verdict` 派生规则

`expected_verdict` 是 W2 输出的主标签，固定 4 枚举：

| 值 | 使用条件 |
|---|---|
| `pass` | selected known family 的必要 threshold / bool assertion 均通过 |
| `fail` | selected known family 至少一项必要 threshold / bool assertion 不通过 |
| `unknown` | selected family unknown、required slot 缺失、binding / unit / sidecar / conflict 无法解决 |
| `not_applicable` | family / slot 对当前 fragment 不适用 |

派生顺序：

1. `selected_family=unknown` → `expected_verdict=unknown`，且 `unknown_reason_code` 必填。
2. `projection_status=conflict` 且无法由 conflict selector 选出 known family → `expected_verdict=unknown`。
3. selected family 的 `ProjectionFamilyEval.verdict ∈ {pass, fail, unknown, not_applicable}` → `expected_verdict` 取该值。
4. `basis_items` 为空时不得输出该 projection。

禁止：

- 不得输出 `expected_verdict=pending`。
- 不得输出 `expected_verdict=final_decision` 或任何最终人工决定语义。

## 4. `ProjectionFamilyEval` 字段合约

| 字段 | 类型 | 必填 | 取值 / 约束 | 语义 |
|---|---|---|---|---|
| `family_id` | str | Y | 16 family + `unknown` | candidate family id |
| `applicability_score` | float | Y | [0, 1] | family 适用性分数 |
| `applicability_state` | str | Y | `applicable` / `neighbor` / `inapplicable` / `uncovered` | 适用性状态 |
| `trigger_ids` | List[str] | Y | rule_card ids | trigger rule ids |
| `rule_ids` | List[str] | Y | rule_card ids; unknown 时必须空 | family 关联 rule ids |
| `slot_role_map` | Dict[str, str] | Y | role enum | slot 到 role 的映射 |
| `threshold_evaluations` | List[`ThresholdEval`] | Y | 0..N | threshold 评估 |
| `verdict` | str | Y | `pass` / `fail` / `unknown` / `not_applicable` | family-level verdict |

`pending` 不属于当前封口版 `verdict` enum。

## 5. `ThresholdEval` 字段合约

| 字段 | 类型 | 必填 | 取值 / 约束 |
|---|---|---|---|
| `rule_id` | str | Y | rule_card id |
| `slot_id` | str | Y | W0 canonical measurement / sidecar numeric slot id |
| `operator` | str | Y | `<=` / `<` / `>=` / `>` / `==` / `!=` / `in` / `not_in` |
| `threshold_value` | float / bool / str / list | Y | rule-specific |
| `observed_value` | float / bool / str | Y | W1/W0 observed value |
| `regime_tag` | str | Y | `far_below` / `near_below` / `exact_threshold` / `near_above` / `far_above` / `not_numeric` |
| `pass_bool` | bool | Y | operator 评估结果 |

`regime_tag` 与 `pass_bool` 是正交维度，不得互相替代。

## 6. `ReportBasisItem` 字段合约

`basis_kind` 固定 5 kind：

| `basis_kind` | 必填字段 |
|---|---|
| `threshold_compare` | `basis_kind` / `basis_id` / `family_id` / `rule_id` / `slot_id` / `source_projection_id` / `operator` / `observed_value` / `threshold_value` / `unit` / `regime_tag` / `pass_bool` |
| `bool_assertion` | `basis_kind` / `basis_id` / `family_id` / `rule_id` / `slot_id` / `source_projection_id` / `observed_value` / `expected_value` / `pass_bool` / `statement_code` |
| `family_uncovered` | `basis_kind` / `basis_id` / `family_id=unknown` / `rule_id=null` / `slot_id` / `source_projection_id` / `reason_code` / `candidate_known_families` |
| `world_origin` | `basis_kind` / `basis_id` / `family_id` / `slot_id` / `source_projection_id` / `observed_value` |
| `measurement_origin` | `basis_kind` / `basis_id` / `family_id` / `rule_id` / `slot_id` / `source_projection_id` / `observed_value` / `unit` |

`basis_items` 是 HiddenGold 删除后的可追溯依据结构。不得复制到 HiddenGold，不得新建 GoldLabeler。

## 7. 输出红线

| ID | 断言 | 触发口径 |
|---|---|---|
| C023 `UNKNOWN_NO_RULE_IDS` | selected_family=`unknown` 时 `rule_ids=[]` | unknown 不挂具体 rule id |
| C024 `KNOWN_SINGLE_CONFLICT_GROUP` | 同一 conflict group 不能多选 known family，除已授权 selector 特例 | 防止 family 冲突静默通过 |
| C025 `BASIS_NONEMPTY` | `basis_items` 必须 1..N | basis 空则不得输出 projection |
| C026 `NO_PENDING_OUTPUT` | `expected_verdict` 与 family `verdict` 不得为 `pending` | 当前封口版无 pending |
| C027 `NO_SIDECAR_DERIVATION_FAILED` | 不得输出 `sidecar_derivation_failed` | 该概念已撤回 |
| C028 `REFERENCE_TRUTH_NOT_FINAL_DECISION` | 不得输出最终人工决定字段 | W2 不替代人类巡检员 |

## 8. 来源

- 旧蓝图 a12 projection / threshold / basis 结构。
- W2 `06_canonical_slots与projection_binding.md`：16 family / binding / required slots。
- W2 `07_threshold_regime与冲突回退.md`：threshold regime / conflict group / C023-C025。
- W2 `08_unknown策略.md`：13 unknown reason code。
- 顶层 `../_封口总则_字段权威源与负向不变量.md`：字段权威源与负向不变量。
