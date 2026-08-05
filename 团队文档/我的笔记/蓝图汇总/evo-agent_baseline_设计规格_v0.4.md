# evo-agent baseline 全量实现级设计规格包

版本：v0.4  
日期：2026-05-22  
状态：baseline 实现级规格；已按 round-2 深审清单与 round-3 验收 C-1~C-4 收尾修订；后续代码以本规格为准，代码不得反向改写本规格。  
适用范围：香港 MBIS 场景下，不带 evo 的合规助手代理系统 baseline。

---

## 0. 开工 sanity check、round-2 修订边界与 round-3 收尾补丁

### 0.1 材料确认

`evo-agent_baseline_spec_proagent_round3.zip` 已解压为：

```text
proagent_uploads/原件/
```

实际可读 **8 个目录、78 个文件**：

| 目录 | 文件数 | 本规格中的使用方式 |
|---|---:|---|
| `v0.2_spec/` | 1 | v0.2-pro-round2 规格，本轮在其基础上只做 C-1~C-4 收尾修订 |
| `审计/` | 4 | v0.2 验收报告与历史审计材料；本轮只处理验收报告 C-1~C-4 |
| `数据契约/` | 7 | 固定上游权威契约；只消费，不重写 |
| `法规/` | 4 | 法规原文事实源 |
| `rule_card_v2/` | 51 | 当前 rule card v2 权威卡片包 |
| `memory/` | 5 | 项目硬约束，等同本规格 §1.0 八条原则的展开 |
| `设计参考/` | 2 | 参考资料，非 spec |
| `闭包验证旧原件/` | 4 | 闭包验证器 MVP 参考，非 spec |

### 0.2 本次交付物

本文件是《evo-agent baseline 全量实现级设计规格包》v0.3。它保留 v0.2-pro-round2 的主体结构，只按 v0.2 验收报告 C-1~C-4 做收尾修订；未重写 round-1 / v0.2 已验收主体。它定义：

1. 双源 KG-RAG 的 Neo4j 属性图 schema；
2. W0/W1 事实产出、sidecar、法规原文、rule_card v2 到 Neo4j 的灌库设计；
3. 闭包验证器的 `ObligationSet` schema、义务推导、确定性检查、`allow_stop` 规则与新载体；
4. agent 三层控制体系：System Prompt / Skills / Hooks；
5. 评测闭环：如何用 W2 `NormativeProjection` / `expected_verdict` 独立阅卷；
6. evo 预留接口：Skill 节点、生命周期、沉淀回 KG 的占位机制；
7. self-check：逐条对照最高优先级原则、round-2 punch list 与 round-3 C-1~C-4。

### 0.3 固定上游，不可改

以下对象在本 baseline 中均视为固定输入，不重新设计、不修改契约：

- W0/W1/W2 数据生成层；
- `WorldBundle`、`SidecarRuntimeBundle`、parquet schema、`worldgen_models.py`；
- W2 `NormativeProjection` 输出契约、`regulation_projection_models.py`；
- 法规原文；
- rule_card v2 的 397 张卡、43 个 fine family、13 个子文件和各注册表；
- `memory/` 中关于 evo-agent blind、闭包验证归属、spec→code 单向、旧概念退役的硬约束。

### 0.4 round-2 必改项处理摘要

| 审计问题 | v0.2 处理 |
|---|---|
| `evaluate_obligation_node` 缺失 | 新增 §6.3.10，完整定义 `obligation_graph.nodes` 与 `edges` 的义务推导、依赖传播、闭包 / 满足性判定 |
| `(:RuleThreshold)` 漏 `formula` | §3.4.3 补 `formula_json`；§4.3.3 补 loader 落库；§6.3.5 补 `n^2-2n+3` 白名单 deterministic handler |
| schema 字段漂移 | §3 / §4 对 `Component`、`Measurement`、`ConditionState.derived_outcomes`、`RuleCard.neighbor_families`、`SourceQuote`、`TriggerCondition` 等逐项修订 |
| blind 第二道防线不完整 | §2.2.3 禁止属性名补齐 7 个 W2 字段，并禁止 `projection_id` 暴露到 agent KG |
| seed Skill 口径矛盾 | §4.5 / §7.2 / 附录 B 统一为 baseline 加载 4 个手工 seed Skill；Skill 只约束流程，不覆盖 verifier |
| sidecar `projection_id` hash 口径 | §1.3 D-003、§3.3.5、§4.2.4 统一为 loader 临时使用后彻底丢弃，不留 hash |
| artifact slot 白名单不对齐 | §6.3.6 改为 rule_card `artifact_key` ↔ sidecar `artifact.*` alias map，不再使用旧 `reporting.artifact.*` 白名单 |
| §12.1 指向悬空 | §1.0 正式写入八条原则，§12.1 对照该清单 |

### 0.5 round-3 收尾修订摘要

**[v0.3]** 本轮只处理 v0.2 验收报告 C-1~C-4，其他 v0.2 主体不动：

| 验收项 | v0.3 处理 |
|---|---|
| C-1 artifact alias map 覆盖不全 | §6.3.6 按 `rule_cards.json` 实测 25 个 `artifact_key` 重建全量 alias map；删除 `form.mbi1` / `form.mbi2` 死条目；取消 prefix fallback；新增 map 完整性断言 |
| C-2 `RuleThreshold.family_id` 来源标注遗漏 | §3.4.3 明确 `family_id` 是 loader 从父 `RuleCard.family_id` 派生，`threshold_regimes[]` 本身无该 key |
| C-3 `Measurement` 字段来源分栏不齐 | §3.3.4 拆分 `来源` / `规则`，将上游字段、loader 派生字段、loader 序列化字段分开 |
| C-4 函数名 / 签名不一致 | §6.3.10 与 §6.6 统一为 `evaluate_obligation_node(card, obligation_node, fact_index, trigger_active)` 和 `evaluate_obligation_edges(card, edges, node_obligations, fact_index)` |


### 0.6 已废旧概念处理

旧 `QueryEpisode`、`HiddenGold`、investigator simulation / 巡检员模拟、latent case、旧版 regex 从 rule 文本抽 slot 的做法均不进入 v0.3。闭包验证器载体为 §5.1 的 `ComplianceAssessmentRun`。

# 1. 项目原则、架构总览、章节大纲、关键设计决策、未决问题

## 1.0 项目八条原则（最高优先级）

本节是本规格的最高优先级约束，来源于 round-2 / round-3 任务说明与 `memory/` 五个项目硬约束文件。若后续工程便利与本节冲突，改工程设计，不改本节。

| # | 原则 | 实现约束 |
|---:|---|---|
| 1 | 副驾驶定位 | 系统只输出指定建筑的闭包验证情况与辅助审查报告，不输出最终合规裁决 |
| 2 | 闭包验证属于合规助手代理本身 | closure verifier 是 agent runtime 的底线层组件，从法规 / rule_cards + 建筑事实自行推导义务，不属于 W2 |
| 3 | evo-agent blind | W2 `NormativeProjection` / `expected_verdict` 是 evaluator-only reference truth；不得成为 agent 输入、KG、检索源或 verifier 输入 |
| 4 | W0/W1/W2 是已封口固定上游 | baseline 只消费固定契约，不重新设计数据生成层，不修改上游字段口径 |
| 5 | 确定性底线层防幻觉 | `allow_stop` 只能由 deterministic verifier 输出；LLM 不可自行宣布资料闭合或合规 |
| 6 | baseline 不带 evo，但留接口 | baseline 不实现 skill 自进化；只加载人工 seed Skill，并预留未来 Skill 写回 KG |
| 7 | 旧设计资料只作参考 | 旧闭包验证器可继承概念骨架，但不继承已废 `QueryEpisode` / `HiddenGold` / investigator simulation |
| 8 | spec→code 单向 | 本规格是代码唯一权威；代码实现与本规格冲突时改代码，不能用代码反推规格 |

## 1.1 baseline 总览

baseline 是一个 **不带 evo 的合规助手代理系统**。它不是最终裁决系统，而是人工审查员副驾驶：

```text
用户指定 building_id / world_id
        │
        ▼
ComplianceAssessmentRun 新建
        │
        ├── Fact KG-RAG：读取 W0/W1 WorldBundle + SidecarRuntimeBundle
        │
        ├── Rule-Skill KG-RAG：读取法规原文 + rule_card v2 + 4 个 baseline 手工 seed Skill
        │
        ▼
RuleSlice + FactPack 构造
        │
        ▼
确定性闭包验证器
        │      ├── 自行从 rule_card + facts 推导 ObligationSet
        │      ├── 每条 obligation 输出 closed / open / blocked
        │      ├── 同时输出 satisfied / violated / unknown / not_applicable
        │      └── 给出 allow_stop
        ▼
LLM 只在 allow_stop 允许的边界内生成辅助审查报告
        │
        ▼
独立 evaluator 读取 W2 NormativeProjection / expected_verdict 阅卷
```

最关键的隔离：

```text
agent-visible:
  - worldgen worldgen 块
  - worldgen sidecar 块（不含 projection_id 暴露字段）
  - 法规原文
  - rule_card v2
  - baseline 手工 seed skills

evaluator-only:
  - normative_projection_meta.parquet
  - projections.parquet
  - matched_families.parquet
  - threshold_evaluations.parquet
  - coverage_control_metadata.parquet
  - basis_items.parquet
  - W2 expected_verdict / NormativeProjection / basis_items
```

agent 侧不得出现 `NormativeProjection` 节点、`expected_verdict` 属性、W2 projection 表、W2 basis item 或任何 per-building 参考答案。

## 1.2 章节大纲

| 章节 | 内容 |
|---|---|
| §2 | 权威边界与数据流隔离 |
| §3 | Neo4j 属性图 schema |
| §4 | 灌库设计 |
| §5 | ComplianceAssessmentRun 与 KG-RAG 检索策略 |
| §6 | 闭包验证器实现级规格 |
| §7 | agent 三层：System Prompt / Skills / Hooks |
| §8 | 评测闭环 |
| §9 | evo 预留接口 |
| §10 | 模块划分与落代码路径 |
| §11 | 测试与验收 |
| §12 | self-check |

## 1.3 关键设计决策

### D-001：agent KG 与 evaluator truth store 物理隔离

- agent 使用 Neo4j database：`evo_agent_baseline`
- evaluator 使用独立 store：建议 `evo_eval_truth`，可为 Neo4j 独立 database、DuckDB 或 parquet 直读
- agent 服务账号无权访问 evaluator store
- evaluator 可读 agent 产物，但 agent 不可读 evaluator 产物

### D-002：不建 `NormativeProjection` agent 节点

即使 W2 输出字段契约在材料中存在，agent KG 也不得建立：

- `(:NormativeProjection)`
- `(:ProjectionFamilyEval)`
- `(:ThresholdEval)`，若该 ThresholdEval 来自 W2 输出
- `(:ReportBasisItem)`，若该 basis 来自 W2 输出
- `expected_verdict`
- `projection_status`
- `selected_family`
- `basis_items`

rule_card 自身的 `threshold_regimes` 可建为 `(:RuleThreshold)`，因为它是法规卡结构，不是具体建筑答案。

### D-003：sidecar 是 agent-visible fact，但 `projection_id` 必须彻底丢弃

`SidecarRuntimeBundle` 是 worldgen 派生层事实，可进事实 KG。`sidecar_records.parquet` 中的 `projection_id` 字段不得作为 `NormativeProjection` 关系使用，也不得以原值或 hash 形式暴露给 agent 查询层。loader 唯一允许的行为是：

1. 在单行解析期间把 `projection_id` 当作临时 reconstruction key；
2. 解析出 `world_id` / `runtime_id` / sidecar entry 关系；
3. 写图前丢弃；
4. 不创建任何 `Projection` 类节点、关系或属性。

禁止属性包括 `projection_id`、`raw_projection_ref_hash`、`projection_ref_hash`。

### D-004：闭包状态与满足性状态分离

旧 MVP 的 `supported/contradicted/unknown/blocked` 被拆为两轴：

```text
closure_status:
  closed | open | blocked

satisfaction_status:
  satisfied | violated | unknown | not_applicable
```

含义：

- `closed + violated`：证据足够闭合，但显示该义务未满足；可以 `allow_stop=true`，但报告必须提示人工审查风险。
- `open + unknown`：证据不足，还不能停。
- `blocked + unknown`：映射、schema、单位、比较器或事实载体不支持；不能停。

### D-005：baseline 加载 4 个手工 seed Skill，但不带 skill 自进化

baseline 不实现 skill 自进化，不自动生成、提升或淘汰 Skill。baseline **必须加载** §7.2 定义的 4 个手工 seed Skill：

1. `skill.mbis.building_assessment_workflow`
2. `skill.mbis.fact_kg_retrieval`
3. `skill.mbis.rule_obligation_derivation`
4. `skill.mbis.auxiliary_report_writer`

这些 Skill 是流程手册与检索 / 报告约束，不改变 deterministic verifier 的输入、输出或判定。未来 evo 阶段可把成熟 Skill 以同构 KG 节点写回 Rule-Skills KG。

### D-006：report 是辅助审查报告，不是最终裁决

LLM 输出中禁止：

- “最终合规裁决”
- “本建筑合规 / 不合规，结案”
- “final decision”
- 将 W2 `expected_verdict` 语义包装成人类结论

允许：

- “闭包验证显示证据已闭合”
- “存在疑似未满足项，建议人工审查”
- “资料不足，不能停止”
- “本报告为人工审查辅助材料”

## 1.4 未决问题清单

| ID | 需要负责人拍板的点 | 本规格默认 |
|---|---|---|
| O-001 | Neo4j 连接参数、database 名、账号权限 | 使用 `evo_agent_baseline` / `evo_eval_truth` 占位 |
| O-002 | 是否使用向量检索 | baseline 必须支持 fulltext + graph；vector index 可选 |
| O-003 | sidecar `projection_id` 是否在实际数据中为唯一 fragment 锚 | 仅作 loader 内存临时字段，写图前彻底丢弃，不留 hash |
| O-004 | 评测 store 技术选型 | 默认 parquet/DuckDB 直读；若用 Neo4j 必须分库分账号 |
| O-005 | 第一批手工 Skill seed 是否需要填内容 | v0.2 已定：加载 4 个手工 seed Skill；内容见 §7.2 |
| O-006 | rule_card fine family 与 W2 coarse family 的 crosswalk 是否进入 agent KG | 不进入 agent KG；仅 evaluator 使用；接口见 §8.3.2 |

# 2. 权威边界与数据流隔离

## 2.1 数据源分级

| 数据源 | agent 可见 | evaluator 可见 | 说明 |
|---|---:|---:|---|
| `WorldBundle` / worldgen parquet 9 表 | 是 | 是 | 建筑事实 |
| `SidecarRuntimeBundle` / sidecar parquet 3 表 | 是 | 是 | 行政过程事实，但不是答案；`projection_id` 写图前丢弃 |
| 法规原文 | 是 | 是 | 法规事实 |
| rule_card v2 | 是 | 是 | 结构化法规知识 |
| baseline Skill KG | 是 | 是 | baseline 加载 4 个手工 seed Skill |
| W2 `NormativeProjection` | 否 | 是 | 参考真值 |
| W2 `expected_verdict` | 否 | 是 | 参考答案标签 |
| W2 `threshold_evaluations` 输出 | 否 | 是 | 参考答案中的阈值评估结果 |
| W2 `basis_items` 输出 | 否 | 是 | 阅卷依据，不给 agent |

## 2.2 agent loader 白名单 / 黑名单

### 2.2.1 agent fact loader 允许读取

```python
AGENT_WORLDGEN_ALLOWLIST = {
    "worldgen_world_bundles_meta.parquet",
    "buildings.parquet",
    "fragments.parquet",
    "components.parquet",
    "locations.parquet",
    "coverage_relations.parquet",
    "fragment_states.parquet",
    "specialized_states.parquet",
    "measurements.parquet",
    "sidecar_runtime_meta.parquet",
    "sidecar_records.parquet",
    "sidecar_entries.parquet",
}
```

### 2.2.2 agent fact loader 禁止读取

```python
AGENT_NORMATIVE_DENYLIST = {
    "normative_projection_meta.parquet",
    "projections.parquet",
    "matched_families.parquet",
    "threshold_evaluations.parquet",
    "coverage_control_metadata.parquet",
    "basis_items.parquet",
}
```

如果 agent loader 的输入目录包含 denylist 文件，不报错；但必须记录 audit warning 并跳过。若调用方显式把 denylist 文件传给 agent loader，则 hard fail。

### 2.2.3 agent KG 禁止 label / 属性名

agent KG 中任何节点 / 关系禁止出现以下 label：

```text
NormativeProjection
ProjectionFamilyEval
ThresholdEval        # 若来源是 W2 threshold_evaluations
ReportBasisItem      # 若来源是 W2 basis_items
ExpectedVerdict
EvalProjection
EvalTruth
```

agent KG 中任何节点 / 关系禁止出现下列属性名：

```text
# W2 reference truth / projection answer fields
expected_verdict
selected_family
projection_status
basis_items
unknown_reason_code
regime_tag            # 若来源是 W2 输出；rule_card threshold source 不使用该字段名
pass_bool             # 若来源是 W2 输出；verifier 可输出 comparator_result

# W2 NormativeProjection 顶层字段，作为 blind 第二道防线禁止进入 agent KG
projection_id
projection_registry_id
projection_family
projection_version
required_world_core_slots
required_measurement_slots
required_qualifier_slots
required_sidecar_interfaces
matched_component_refs
matched_measurement_ids
coverage_status

# sidecar projection_id 的任何 hash / ref 变体也禁止
raw_projection_ref_hash
projection_ref_hash
```

说明：

1. `world_id`、`fragment_id`、`severity_band` 是 W0/W1 事实层原生字段，可以进 agent KG；W2 复用同名字段不改变其事实层来源。
2. agent 侧闭包验证器的 `Obligation.applicability_state` 是自有字段，枚举为 `applicable/not_applicable/uncertain`，与 W2 `ProjectionFamilyEval.applicability_state` 的枚举与语义不同，二者互不派生。
3. 若未来 agent 侧需要表达 coverage 概念，属性名必须用 `coverage_state` 或 `fact_coverage_state`，不得使用 W2 风险字段名 `coverage_status`。
4. rule_card v2 中存在 `threshold_regimes`，它是法规卡阈值定义，不是 W2 `ThresholdEval`；可进入 KG，但标签与属性名必须命名为 `RuleThreshold` / `threshold_value_json` / `operator` / `formula_json`，不得伪装成 W2 `ThresholdEval`。

## 2.3 evaluator-only store

evaluator 读取 W2 输出时，使用独立配置：

```yaml
eval_truth_store:
  mode: duckdb_or_separate_neo4j
  input_tables:
    - normative_projection_meta.parquet
    - projections.parquet
    - matched_families.parquet
    - threshold_evaluations.parquet
    - coverage_control_metadata.parquet
    - basis_items.parquet
  readable_by_agent: false
  readable_by_evaluator: true
```

若 evaluator 使用 Neo4j，必须满足：

```cypher
// 不在 agent database 内执行
CREATE DATABASE evo_eval_truth IF NOT EXISTS;
```

agent runtime credential 不得拥有 `ACCESS` 或 `MATCH` 权限。

## 2.4 run 级 provenance 规则

每次 `ComplianceAssessmentRun` 必须保存 agent-visible provenance。样例：

```json
{
  "run_id": "CAR-...",
  "world_id": "WB-...",
  "building_id": "BLD-...",
  "kg_snapshot_id": "KGS-...",
  "agent_visible_sources": [
    "worldgen_world_bundles_meta.parquet",
    "buildings.parquet",
    "fragments.parquet",
    "components.parquet",
    "locations.parquet",
    "coverage_relations.parquet",
    "fragment_states.parquet",
    "specialized_states.parquet",
    "measurements.parquet",
    "sidecar_runtime_meta.parquet",
    "sidecar_records.parquet",
    "sidecar_entries.parquet",
    "MBIS_CoP_2023.md",
    "MBIS_MWIS_CoP_2012_Legacy.md",
    "MBIS_MWIS_Operation_Note.md",
    "PNBI10_CoP_2023.md",
    "rule_cards.json",
    "family_index.json",
    "slot_index.json",
    "threshold_regime_index.json",
    "semantic_slot_registry_v1.json",
    "measure_registry_v1.json",
    "artifact_semantics_registry_v1.json",
    "time_anchor_registry_v1.json",
    "controlled_vocabularies_v1.json",
    "exception_definition_index.json",
    "projection_runtime_mapping_v1.json"
  ],
  "evaluator_only_sources_seen_and_skipped": [
    "projections.parquet",
    "matched_families.parquet",
    "threshold_evaluations.parquet",
    "basis_items.parquet"
  ],
  "forbidden_source_check_passed": true
}
```

provenance 规则：

- `agent_visible_sources` 只能列 §2.2.1 允许表、法规、rule_card v2 与 seed Skill 文件。
- 如果输入目录包含 W2 denylist 文件，只能出现在 `evaluator_only_sources_seen_and_skipped`。
- 任一 W2 denylist 文件出现在 `agent_visible_sources` 时，run 必须 hard fail，`stop_reason=forbidden_reference_truth_detected`。

# 3. Neo4j 属性图 schema

## 3.1 设计原则

1. fact KG 与 rule-skill KG 同库但不同 label namespace；evaluator truth 不在 agent database 内。
2. 上游字段与 loader 派生字段在表述上明确区分；派生字段不得伪装成上游契约字段。
3. 所有 JSON 字段统一以 canonical JSON string 存储；verifier 读取前必须 `json.loads`。
4. rule_card v2 的结构化子对象必须落为节点 / 边，不允许只把整张卡塞入 JSON。
5. 禁止创建任何 W2 reference truth label、属性或桥接边。

## 3.2 命名约定

| 对象 | 约定 |
|---|---|
| 节点 label | PascalCase，例如 `RuleCard` |
| 关系 type | UPPER_SNAKE_CASE，例如 `HAS_THRESHOLD` |
| 属性 | snake_case |
| 合成主键 | `<parent_id>::<local_id>` |
| JSON 字段 | 以 `_json` 结尾，值为 canonical JSON string |

## 3.3 事实侧 KG schema

### 3.3.1 核心节点

#### `(:World)`

| 属性 | 类型 | 必填 | 来源 | 说明 |
|---|---|---:|---|---|
| `world_id` | string | Y | 上游 | W0/W1 world id |
| `schema_version` | string | Y | 上游 | from `worldgen_world_bundles_meta.parquet` / bundle meta |
| `generator_version` | string | Y | 上游 | W1 generator version |
| `random_seed` | integer | Y | 上游 | 可复现 seed |
| `deterministic_key` | string/null | N | 上游 | 来自 meta，若存在 |
| `source_kind` | string | Y | loader 合成 | 固定 `synthetic_worldgen` |
| `kg_snapshot_id` | string | Y | loader 合成 | 本次灌库快照 |
| `loaded_at` | string | Y | loader 合成 | ISO timestamp |

关系：

```text
(:World)-[:HAS_BUILDING]->(:Building)
```

#### `(:Building)`

| 属性 | 类型 | 必填 | 来源 | 说明 |
|---|---|---:|---|---|
| `building_id` | string | Y | `BuildingContext` | `BLD-*` |
| `world_id` | string | Y | parquet FK | FK；`BuildingContext` 本身无此字段，来自 `buildings.parquet` 分区 / 行字段 |
| `building_use` | string | Y | `BuildingContext` | residential/commercial/... |
| `structure_type` | string | Y | `BuildingContext` | rc_frame/... |
| `age_years` | float | Y | `BuildingContext` | 楼龄 |
| `storey_count` | integer | Y | `BuildingContext` | 层数 |
| `primary_materials` | list<string> | Y | `BuildingContext` | 材料 |
| `configuration_tags` | list<string> | Y | `BuildingContext` | 配置标签 |
| `occupancy_state` | string | Y | `BuildingContext` | occupied/vacant/... |
| `building_template_id` | string/null | N | `BuildingMetadata` | generator 内部 metadata；W2 不消费 |
| `building_name` | string/null | N | `BuildingMetadata` | human-readable label；W2 不消费 |
| `unit_count` | integer/null | N | `BuildingMetadata` | generator / reporting metadata；W2 不消费 |

说明：`BuildingContext` 权威契约只有 8 个业务字段；`building_template_id` / `building_name` / `unit_count` 属 `BuildingMetadata`，但 parquet 合表存储，故 KG 可放在 `(:Building)` 上，必须标记为 metadata 来源。

#### `(:Component)`

| 属性 | 类型 | 必填 | 来源 | 说明 |
|---|---|---:|---|---|
| `component_id` | string | Y | 上游 | PK |
| `world_id` | string | Y | parquet FK | FK |
| `component_type` | string | Y | 上游 | 构件类型 |
| `parent_component_id` | string/null | N | 上游 | 父构件 |
| `material_system` | string | Y | 上游 | 材料系统 |
| `structural_role` | string | Y | 上游 | 结构角色 |
| `location_id` | string | Y | 上游 | FK |
| `geometry_proxy_json` | string | Y | 上游 | `geometry_proxy` canonical JSON |
| `cover_depth_mm` | float/null | N | 上游 | RC-specific 物理参数 |
| `access_class` | string | Y | 上游 | 可达性 |
| `length_m` | float/null | N | loader 派生 | 从 `geometry_proxy.length_m` 抽取，缺失填 null |
| `width_m` | float/null | N | loader 派生 | 从 `geometry_proxy.width_m` 抽取，缺失填 null |
| `height_m` | float/null | N | loader 派生 | 从 `geometry_proxy.height_m` 抽取，缺失填 null |
| `visible_area_m2` | float/null | N | loader 派生 | 从 `geometry_proxy.visible_area_m2` 抽取，缺失填 null |
| `thickness_mm` | float/null | N | loader 派生 | 从 `geometry_proxy.thickness_mm` 抽取，缺失填 null |

关系：

```text
(:Building)-[:HAS_COMPONENT]->(:Component)
(:Component)-[:PARENT_OF]->(:Component)
(:Component)-[:LOCATED_AT]->(:Location)
```

派生列规则：loader 只做 shallow key extraction，不推导新几何；任一 key 不存在或值无法 cast 为数值时填 `null` 并保留原 `geometry_proxy_json`。

#### `(:Location)`

| 属性 | 类型 | 来源 |
|---|---|---|
| `location_id` | string | 上游 |
| `world_id` | string | parquet FK |
| `location_class` | string | 上游 |
| `exposure_zone` | string | 上游 |
| `storey_band` | string | 上游或 loader 派生；若上游缺失则 null |
| `spatial_tags` | list<string> | 上游或 payload；若上游缺失则 [] |

关系：

```text
(:Building)-[:HAS_LOCATION]->(:Location)
```

#### `(:Fragment)`

| 属性 | 类型 | 来源 |
|---|---|---|
| `fragment_id` | string | 上游 |
| `world_id` | string | parquet FK |
| `fragment_template_id` | string | 上游 |
| `component_id` | string | 上游 FK |
| `location_id` | string | 上游 FK |
| `fragment_role` | string | 上游 |
| `fragment_area_m2` | float | 上游 |
| `fragment_length_m` | float/null | 上游 |
| `in_scope` | boolean | 上游 |
| `exclusion_reason` | string/null | 上游 |

关系：

```text
(:Building)-[:HAS_FRAGMENT]->(:Fragment)
(:Fragment)-[:OF_COMPONENT]->(:Component)
(:Fragment)-[:AT_LOCATION]->(:Location)
```

#### `(:CoverageRelation)`

| 属性 | 类型 |
|---|---|
| `coverage_id` string |
| `world_id` string |
| `coverage_relation_type` string |
| `coverage_state` string |
| `covered_area_m2` float |
| `inspected_area_m2` float |
| `obscuration_class` string |

关系：

```text
(:Fragment)-[:HAS_COVERAGE]->(:CoverageRelation)
(:CoverageRelation)-[:COVERS_FRAGMENT]->(:Fragment)
```

注意：agent 侧 coverage 字段统一叫 `coverage_state`，不得使用 W2 `coverage_status`。

### 3.3.2 状态节点

#### `(:DriverState)`

抽取字段：

```text
driver_id, world_id, fragment_id,
service_load_ratio, restraint_level, moisture_ingress_index,
chloride_exposure_index, carbonation_index,
workmanship_deficit_index, maintenance_deficit_index,
drainage_fault_propensity, alteration_propensity,
fire_safety_deficit_index, repair_quality_index,
payload_json
```

关系：

```text
(:Fragment)-[:HAS_DRIVER_STATE]->(:DriverState)
```

#### `(:MechanismState)`

抽取字段：

```text
mechanism_state_id, world_id, fragment_id,
mechanism_family, active, severity_index,
primary_mechanism_id, crack_mechanism_kind,
corrosion_active, delamination_active,
drainage_fault_kind, ubw_signal_kind,
fire_safety_deficiency_kind,
assessment_origin_kind, verification_origin_kind,
cause_tags, payload_json
```

关系：

```text
(:Fragment)-[:HAS_MECHANISM_STATE]->(:MechanismState)
(:MechanismState)-[:DERIVED_FROM_DRIVER]->(:DriverState)
```

`activated_mechanisms` 建为子节点：

#### `(:MechanismActivation)`

```text
mechanism_activation_id = mechanism_state_id + "::" + mechanism_id
mechanism_state_id, world_id, mechanism_id, mechanism_family,
activation_score, derived_from_driver_ids, notes
```

关系：

```text
(:MechanismState)-[:HAS_ACTIVATION]->(:MechanismActivation)
(:MechanismActivation)-[:DERIVED_FROM_DRIVER]->(:DriverState)
```

`DERIVED_FROM_DRIVER` 的边源为 `MechanismActivation.derived_from_driver_ids[]`。若列表为空，不建边；若 id 不存在，写入 loader warning，不创建悬空节点。

#### `(:ConditionState)`

抽取字段：

```text
condition_id, world_id, fragment_id, mechanism_state_id,
condition_class, severity_band, severity_index,
extent_area_m2, extent_length_m, depth_mm, count,
uncertainty_flag,
condition_classes, source_tags,
derived_outcomes_json,
risk_flags_json, repair_flags_json, verification_flags_json, assessment_flags_json,
risk_index_values_json, fallback_reasons_json,
payload_json
```

关系：

```text
(:Fragment)-[:HAS_CONDITION]->(:ConditionState)
(:ConditionState)-[:CAUSED_BY]->(:MechanismState)
```

`derived_outcomes` 处理规则：

1. loader 从 `payload_json.derived_outcomes` 解析 `risk_flags`、`repair_flags`、`verification_flags`、`assessment_flags`、`risk_index_values`、`fallback_reasons` 六组字段；
2. 六组字段以 canonical JSON string 单独落在 `ConditionState` 上，供 verifier 直接解析；
3. verifier 构建 FactPack 时必须把每个 `*_flags` entry 展成 `FactAtom(slot_id=<flag_key>, value_json=<flag_value>, carrier_type="condition")`；
4. `fallback_reasons` 不用于判定 satisfied/violated，只用于解释 `unknown` 或 `not_applicable`；
5. 若 `derived_outcomes` 缺失，相关 derived flag fact 视为 missing，不得静默当作 false。

`manifestation_flags` 建为：

#### `(:ManifestationFlag)`

```text
manifestation_flag_id = condition_id + "::" + slot_id + "::" + hash(qualifiers)
condition_id, world_id, slot_id, value_json, qualifier_ids, notes
```

关系：

```text
(:ConditionState)-[:HAS_MANIFESTATION_FLAG]->(:ManifestationFlag)
(:ManifestationFlag)-[:REALIZES_SLOT]->(:SemanticSlot)   // 若 slot_id 在 rule_card slot registry 存在
```

#### `(:RepairAssessmentState)`

```text
repair_assessment_id, world_id, fragment_id,
repair_quality_index, repair_required, maintenance_required,
verification_failed, safe_until_next_cycle, residual_risk_index,
notes, payload_json
```

关系：

```text
(:Fragment)-[:HAS_REPAIR_ASSESSMENT]->(:RepairAssessmentState)
```

### 3.3.3 专项状态节点

#### `(:DrainageState)`

```text
drainage_id, world_id, component_id, segment_type,
connection_state, blockage_index, leakage_index,
misconnection_present, public_health_risk_index,
payload_json
```

关系：

```text
(:Component)-[:HAS_DRAINAGE_STATE]->(:DrainageState)
```

#### `(:UBWState)`

```text
ubw_id, world_id, component_id, alteration_type,
authorization_status_proxy, present,
subdivided_unit_sign_present,
structural_impact_index, structural_impact,
payload_json
```

关系：

```text
(:Component)-[:HAS_UBW_STATE]->(:UBWState)
```

#### `(:FireSafetyState)`

```text
fire_state_id, world_id, component_id,
fire_component_class, deficiency_class,
deficiency_present, severity_index,
record_status_proxy, component_deficiency_present,
payload_json
```

关系：

```text
(:Component)-[:HAS_FIRE_SAFETY_STATE]->(:FireSafetyState)
```

`specialized_states.parquet` 只有 `state_type` + `payload_json`；loader 必须从 payload 中读取 `component_id` 后建立上述关系。若 `component_id` 缺失或找不到 `(:Component)`，节点仍落库，但关系不建并记录 warning。

### 3.3.4 Measurement 节点

#### `(:Measurement)`

**[v0.3-C-3]** 本表按 §3.3.1 口径拆分 `来源` 与 `规则`，避免把上游字段和 loader 派生字段混在同一列。

| 属性 | 类型 | 必填 | 来源 | 规则 |
|---|---|---:|---|---|
| `measurement_id` | string | Y | 上游 `MeasurementRecord.measurement_id` | 原样落库 |
| `world_id` | string | Y | parquet FK | 由 `measurements.parquet.world_id` 写入 |
| `target_ref` | string | Y | 上游 `MeasurementRecord.target_ref` | 原样落库；关系解析见 §4.2.7 |
| `target_kind` | string | Y | loader 派生 | 由 `target_ref` 解析为 `fragment/component/condition/unknown` |
| `measurement_family` | string | Y | 上游 `MeasurementRecord.measurement_family` | 原样落库 |
| `slot_id` | string | Y | 上游 `MeasurementRecord.slot_id` | 可能对应 `Measure.measure_key` 或 `SemanticSlot.slot_id` |
| `value_num` | float/null | N | 上游 `MeasurementRecord.value_num` | 原样落库 |
| `value_bool` | bool/null | N | 上游 `MeasurementRecord.value_bool` | 原样落库 |
| `value_enum` | string/null | N | 上游 `MeasurementRecord.value_enum` | 原样落库 |
| `value_json` | string | Y | loader 派生 | 从 `value_bool/value_num/value_enum` canonicalize；规则见下方代码 |
| `unit` | string/null | N | 上游 `MeasurementRecord.unit` | 原样落库 |
| `precision_class` | string | Y | 上游 `MeasurementRecord.precision_class` | 原样落库 |
| `method_class` | string/null | N | 上游 `MeasurementRecord.method_class` | 原样落库 |
| `sample_count` | integer/null | N | 上游 `MeasurementRecord.sample_count` | 原样落库 |
| `confidence_index` | float | Y | 上游 `MeasurementRecord.confidence_index` | 原样落库 |
| `derivation_refs` | list<string> | Y | 上游 + loader canonicalize | 合并 `derivation_refs/upstream_refs/origin_chain_refs/derived_from_measurement_ids` 后 stable_unique |
| `derivation_mode` | string | Y | 上游 `MeasurementRecord.derivation_mode` | 原样落库 |
| `qualifiers_json` | string | Y | loader 派生 | `MeasurementRecord.qualifiers` canonical JSON |
| `notes` | list<string> | Y | 上游 `MeasurementRecord.notes` | 原样落库 |

关系：

```text
(:Fragment)-[:HAS_MEASUREMENT]->(:Measurement)
(:Component)-[:HAS_MEASUREMENT]->(:Measurement)
(:ConditionState)-[:HAS_MEASUREMENT]->(:Measurement)
(:Measurement)-[:MEASURES_SLOT]->(:Measure)        // 若 slot_id 对应 measure key
(:Measurement)-[:REALIZES_SLOT]->(:SemanticSlot)  // 若 slot_id 对应 semantic slot
```

值解析规则：

```python
if value_bool is not None: value_json = json.dumps(value_bool)
elif value_num is not None: value_json = json.dumps(value_num)
elif value_enum is not None: value_json = json.dumps(value_enum)
else: value_json = "null"
```

`qualifiers_json` 读取规则：verifier 构建 FactAtom 时必须 `json.loads(measurement.qualifiers_json)` 得到 `FactAtom.qualifiers`，`qualifiers_match(required, observed)` 在 dict 上执行，不得直接字符串比较。

`measurements.parquet` 还包含 `upstream_refs`、`origin_chain_refs`、`derived_from_measurement_ids` 三个迁移期别名列。loader 处理：

```python
derivation_refs = stable_unique(
    derivation_refs + upstream_refs + origin_chain_refs + derived_from_measurement_ids
)
```

若上游 validator 已同步四列，loader 只取 `derivation_refs` 也不丢信息；但实现必须显式记录该处理策略。

### 3.3.5 Sidecar 节点

#### `(:SidecarRuntimeRecord)`

| 属性 | 类型 | 说明 |
|---|---|---|
| `runtime_id` | string | 主键 |
| `world_id` | string | FK |
| `interface_ids` | list<string> | sidecar interfaces |
| `source_kind` | string | 固定 `worldgen_sidecar` |

关系：

```text
(:World)-[:HAS_SIDECAR_RECORD]->(:SidecarRuntimeRecord)
```

禁止关系 / 属性：

```text
(:SidecarRuntimeRecord)-[:FOR_PROJECTION]->(:NormativeProjection)  // 禁止
SidecarRuntimeRecord.projection_id                                  // 禁止
SidecarRuntimeRecord.raw_projection_ref_hash                         // 禁止
```

`sidecar_records.parquet.projection_id` 只允许 loader 在内存中临时读取；写入 Neo4j 的 props 中不得包含该字段或 hash。

#### `(:SidecarEntry)`

| 属性 | 类型 |
|---|---|
| `sidecar_entry_id` string = `runtime_id + "::" + entry_type + "::" + seq_no` |
| `runtime_id` string |
| `world_id` string |
| `entry_type` string |
| `slot_id` string |
| `value_json` string |
| `qualifiers_json` string |
| `time_anchor_key` string/null |
| `source_refs` list<string> |
| `notes` list<string> |

关系：

```text
(:SidecarRuntimeRecord)-[:HAS_SIDECAR_ENTRY]->(:SidecarEntry)
(:SidecarEntry)-[:REALIZES_SLOT]->(:SemanticSlot)
(:SidecarEntry)-[:REALIZES_MEASURE]->(:Measure)
(:SidecarEntry)-[:USES_TIME_ANCHOR]->(:TimeAnchor)
(:SidecarEntry)-[:SOURCED_FROM]->(:Fragment | :Component | :Building)  // 若 source_refs 可解析
```

## 3.4 法规-Skills 侧 KG schema

### 3.4.1 法规原文节点

#### `(:RegulationDocument)`

```text
document_id, title, version, source_path, loaded_at, text_hash
```

#### `(:RegulationClause)`

```text
clause_id = document_id + "::" + section_id
section_id, document_id, heading, level, text, text_hash,
page_start, page_end
```

关系：

```text
(:RegulationDocument)-[:HAS_CLAUSE]->(:RegulationClause)
(:RegulationClause)-[:PARENT_OF]->(:RegulationClause)
(:RegulationClause)-[:NEXT_CLAUSE]->(:RegulationClause)
```

### 3.4.2 rule_card v2 节点

#### `(:RuleCard)`

| 属性 | 类型 | 来源 / 规则 |
|---|---|---|
| `rule_card_id` | string | 上游 |
| `source_document_id` | string | 上游 |
| `normalized_rule_text` | string | 上游 |
| `family_id` | string | 上游 |
| `phase` | string | `applicability.phase` |
| `subject` | string | `applicability.subject` |
| `regime` | string | `applicability.regime` |
| `actors` | list<string> | `applicability.actors` |
| `component_scope` | list<string> | `applicability.component_scope` |
| `building_scope` | list<string> | `applicability.building_scope` |
| `neighbor_families` | list<string> | 上游 `neighbor_families`，card-level |
| `primary_actor` | string/null | `workflow_operands.primary_actor` |
| `primary_action` | string/null | `workflow_operands.primary_action` |
| `method_keys_allowed` | list<string> | `workflow_operands.method_keys_allowed` |
| `version_authoring_revision` | string | `version.authoring_revision` |
| `version_interpretation_revision` | integer | `version.interpretation_revision` |
| `provenance_json` | string | `provenance` canonical JSON |
| `source_quote_texts` | list<string> | loader 派生：`source_quote[].text` 展平，用于 fulltext index |

关系：

```text
(:RuleFamily)-[:HAS_RULE_CARD]->(:RuleCard)
(:RuleCard)-[:SOURCED_FROM_DOCUMENT]->(:RegulationDocument)
(:RuleCard)-[:SOURCED_FROM_CLAUSE]->(:RegulationClause)
(:RuleCard)-[:HAS_SOURCE_QUOTE]->(:SourceQuote)
(:RuleCard)-[:CARD_NEIGHBOR_OF]->(:RuleFamily)      // 来自 card.neighbor_families[]
```

`source_quote_texts` 是派生字段；上游没有同名纯文本数组。若某 quote 无 text，跳过该 quote 的 text，但仍建 `SourceQuote` 节点。

#### `(:RuleFamily)`

```text
family_id, family_name, phase, actor, subject,
action_cluster, deprecated_family_ids, card_count
```

关系：

```text
(:RuleFamily)-[:NEIGHBOR_OF {source: "card_neighbor_families", card_count}]->(:RuleFamily)
```

`NEIGHBOR_OF` 是由所有 card-level `neighbor_families[]` 聚合出的 family-level 派生边：对每个 `(source_family_id, neighbor_family_id)` 统计引用卡数，`card_count` 为该 pair 出现次数。

### 3.4.3 rule card 子结构节点

#### `(:SourceQuote)`

```text
source_quote_id = rule_card_id + "::" + quote_local_id
rule_card_id, quote_local_id, text, page, language
```

`quote_local_id` 的生成规则：若上游 quote 对象有稳定 id，用该 id；否则按 `source_quote` 数组顺序生成 `sq%02d`。禁止使用自指公式 `quote_id = rule_card_id + "::" + quote_id`。

#### `(:ApplicabilityPredicate)`

```text
applicability_id = rule_card_id + "::applicability"
rule_card_id, regime, actors, phase, subject, component_scope,
building_scope, exclusions_json
```

关系：

```text
(:RuleCard)-[:HAS_APPLICABILITY]->(:ApplicabilityPredicate)
```

#### `(:TriggerCondition)`

```text
trigger_condition_id = rule_card_id + "::trigger::" + condition_id
rule_card_id, condition_id, predicate_kind, slot_ref_id,
operator, expected_value_json
```

`expected_value_json` 是上游 `expected_value` 的 canonical JSON。关系：

```text
(:RuleCard)-[:HAS_TRIGGER]->(:TriggerCondition)
(:TriggerCondition)-[:REFERS_TO_SLOT_REF]->(:SlotRef)
```

#### `(:SlotRef)`

`slot_role_map` 的每一行建一个 `SlotRef`，因为同一 `slot_id` 可以通过不同 qualifiers 与 roles 扮演不同语义。

```text
slot_ref_id, rule_card_id, slot_id,
qualifiers_json, roles, required
```

关系：

```text
(:RuleCard)-[:HAS_SLOT_REF]->(:SlotRef)
(:SlotRef)-[:REFERS_TO_SEMANTIC_SLOT]->(:SemanticSlot)
```

#### `(:RuleThreshold)`

来自 rule_card `threshold_regimes` 或 `threshold_regime_index.json`，不是 W2 `ThresholdEval`。

```text
threshold_regime_id, rule_card_id, family_id,
measure_key, operator, threshold_value_json,
unit, qualifiers_json, time_anchor_key,
source_quote_refs, formula_json
```

映射：

- **[v0.3-C-2]** `family_id` = loader 从父 `RuleCard.family_id` 派生；上游 `threshold_regimes[]` 对象本身没有 `family_id` key。
- `threshold_value_json` = 上游 `value` 的 canonical JSON；若 key 缺失则为 `null`。
- `qualifiers_json` = 上游 `qualifiers` canonical JSON。
- `formula_json` = 上游 `formula` canonical JSON；无 formula 时为 `null`。

关系：

```text
(:RuleCard)-[:HAS_THRESHOLD]->(:RuleThreshold)
(:RuleThreshold)-[:REFERS_TO_MEASURE]->(:Measure)
(:RuleThreshold)-[:USES_TIME_ANCHOR]->(:TimeAnchor)
(:RuleThreshold)-[:SUPPORTED_BY_QUOTE]->(:SourceQuote)
```

#### `(:ObligationNode)`

来自 rule_card `obligation_graph.nodes`。

```text
obligation_node_id, rule_card_id, node_kind,
actor, action, recipient_ids,
artifact_ids, deadline_ids,
trigger_condition_ids
```

关系：

```text
(:RuleCard)-[:HAS_OBLIGATION_NODE]->(:ObligationNode)
(:ObligationNode)-[:TRIGGERED_BY]->(:TriggerCondition)
(:ObligationNode)-[:REQUIRES_ARTIFACT]->(:WorkflowArtifact)
(:ObligationNode)-[:HAS_DEADLINE]->(:WorkflowDeadline)
(:ObligationNode)-[:SENT_TO]->(:WorkflowRecipient)
```

#### `(:ObligationEdge)`

来自 rule_card `obligation_graph.edges[]`，实测字段为 `{relation, source_node_id, target_node_id}`。

```text
obligation_edge_id = rule_card_id + "::edge::" + source_node_id + "::" + relation + "::" + target_node_id
rule_card_id, source_node_id, target_node_id, relation
```

关系：

```text
(:RuleCard)-[:HAS_OBLIGATION_EDGE]->(:ObligationEdge)
(:ObligationEdge)-[:FROM_OBLIGATION_NODE]->(:ObligationNode)
(:ObligationEdge)-[:TO_OBLIGATION_NODE]->(:ObligationNode)
(:ObligationNode)-[:OBLIGATION_EDGE {relation, obligation_edge_id}]->(:ObligationNode)
```

允许的 `relation` 基线：

```text
if_failed_then
if_unable_then
```

未知 relation 不丢弃，仍落 `ObligationEdge`，但 verifier 处理为 `blocked + unsupported_obligation_edge_relation`。

#### workflow operand nodes

```text
(:WorkflowRecipient {recipient_id, rule_card_id, recipient_type, recipient_key, delivery_mode})
(:WorkflowArtifact {artifact_id, rule_card_id, artifact_type, artifact_key})
(:WorkflowDeadline {deadline_id, rule_card_id, relation, offset_value, offset_unit, time_anchor_key})
```

`workflow_operands.primary_actor`、`primary_action`、`method_keys_allowed` 落在 `RuleCard` 属性上；`audiences` 当前为空数组，loader 若发现非空，写 warning 并透传到 `RuleCard.audiences_json`。

#### `(:EvidenceRequirement)`

```text
evidence_requirement_id, rule_card_id,
bucket, kind, required, description,
artifact_ids, slot_ref_ids, measure_keys,
required_field_groups
```

`bucket` 允许值：

```text
for_matching
for_submission
for_completion
```

关系：

```text
(:RuleCard)-[:HAS_EVIDENCE_REQUIREMENT]->(:EvidenceRequirement)
(:EvidenceRequirement)-[:REQUIRES_SLOT_REF]->(:SlotRef)
(:EvidenceRequirement)-[:REQUIRES_MEASURE]->(:Measure)
(:EvidenceRequirement)-[:REQUIRES_WORKFLOW_ARTIFACT]->(:WorkflowArtifact)
(:EvidenceRequirement)-[:REQUIRES_ARTIFACT_TYPE]->(:Artifact)   // artifact_key 可解析到 registry 时
```

### 3.4.4 registries

#### `(:SemanticSlot)`

```text
slot_id, semantic_domain, allowed_roles, semantic_meaning
```

#### `(:Measure)`

```text
measure_key, quantity_family, unit,
allowed_operators, semantic_meaning
```

#### `(:Artifact)`

```text
artifact_key, artifact_family, semantic_meaning
```

#### `(:TimeAnchor)`

```text
time_anchor_key, semantic_meaning
```

#### `(:VocabularyTerm)`

```text
vocab_id = vocabulary_name + "::" + value
vocabulary_name, value
```

`(:VocabularyTerm)` 是 loader 从 `controlled_vocabularies_v1.json` 的 `vocabularies: {vocabulary_name: [value...]}` 展平派生的 term-level 节点；上游 registry 本身没有逐条 term 对象。

#### exception / definition

```text
(:ExceptionDefinition {definition_id, term_key, definition_text, scope_note, source_quote_refs, family_id, rule_card_id})
```

## 3.5 Skill KG schema

baseline 阶段必须加载 §7.2 的 4 个手工 seed Skill，同时 schema 预留 evo 写回。

#### `(:Skill)`

| 属性 | 类型 | 说明 |
|---|---|---|
| `skill_id` | string | `skill.<domain>.<name>` |
| `name` | string | 可读名 |
| `description` | string | 触发描述 |
| `status` | string | `manual_seed` / `candidate` / `validated` / `retired` |
| `origin` | string | `manual` / `evo` |
| `version` | string | semver |
| `allowed_in_baseline` | boolean | baseline 是否可用 |
| `content_md` | string | Skill 手册正文 |
| `notes` | string | 备注 |

#### `(:SkillTrigger)`

```text
trigger_id, skill_id, trigger_kind, pattern_json, priority, enabled
```

#### `(:SkillValidationRecord)`

```text
validation_id, skill_id, eval_set_id, metric_name,
metric_value, passed, created_at, notes
```

## 3.6 桥接关系

### 3.6.1 alias nodes

#### `(:SlotAlias)`

```text
alias_id = source_namespace + "::" + source_slot_id
source_namespace, source_slot_id, target_slot_id, confidence, source_file
```

关系：

```text
(:SlotAlias)-[:ALIAS_OF]->(:SemanticSlot)
```

#### `(:MeasureAlias)`

```text
alias_id = source_namespace + "::" + source_measure_key
source_namespace, source_measure_key, target_measure_key, confidence, source_file
```

关系：

```text
(:MeasureAlias)-[:ALIAS_OF]->(:Measure)
```

### 3.6.2 fact-to-rule bridge

允许桥接：

```text
(:Measurement)-[:MEASURES_SLOT]->(:Measure)
(:Measurement)-[:REALIZES_SLOT]->(:SemanticSlot)
(:SidecarEntry)-[:REALIZES_SLOT]->(:SemanticSlot)
(:SidecarEntry)-[:REALIZES_MEASURE]->(:Measure)
(:ManifestationFlag)-[:REALIZES_SLOT]->(:SemanticSlot)
```

### 3.6.3 禁止桥接

```text
(:Building|:Fragment|:Component)-[:HAS_NORMATIVE_PROJECTION]->(:NormativeProjection)  // 禁止
(:RuleCard)-[:EXPECTED_VERDICT_FOR]->(:Building)                                      // 禁止
(:ThresholdEval)-[:FOR_MEASUREMENT]->(:Measurement)                                   // 若来自 W2，禁止
```

## 3.7 Neo4j constraints and indexes

### 3.7.1 constraints

```cypher
CREATE CONSTRAINT world_id_unique IF NOT EXISTS
FOR (n:World) REQUIRE n.world_id IS UNIQUE;
CREATE CONSTRAINT building_id_unique IF NOT EXISTS
FOR (n:Building) REQUIRE n.building_id IS UNIQUE;
CREATE CONSTRAINT component_id_unique IF NOT EXISTS
FOR (n:Component) REQUIRE n.component_id IS UNIQUE;
CREATE CONSTRAINT location_id_unique IF NOT EXISTS
FOR (n:Location) REQUIRE n.location_id IS UNIQUE;
CREATE CONSTRAINT fragment_id_unique IF NOT EXISTS
FOR (n:Fragment) REQUIRE n.fragment_id IS UNIQUE;
CREATE CONSTRAINT coverage_id_unique IF NOT EXISTS
FOR (n:CoverageRelation) REQUIRE n.coverage_id IS UNIQUE;
CREATE CONSTRAINT measurement_id_unique IF NOT EXISTS
FOR (n:Measurement) REQUIRE n.measurement_id IS UNIQUE;
CREATE CONSTRAINT sidecar_runtime_id_unique IF NOT EXISTS
FOR (n:SidecarRuntimeRecord) REQUIRE n.runtime_id IS UNIQUE;
CREATE CONSTRAINT sidecar_entry_id_unique IF NOT EXISTS
FOR (n:SidecarEntry) REQUIRE n.sidecar_entry_id IS UNIQUE;
CREATE CONSTRAINT rule_card_id_unique IF NOT EXISTS
FOR (n:RuleCard) REQUIRE n.rule_card_id IS UNIQUE;
CREATE CONSTRAINT rule_family_id_unique IF NOT EXISTS
FOR (n:RuleFamily) REQUIRE n.family_id IS UNIQUE;
CREATE CONSTRAINT source_quote_id_unique IF NOT EXISTS
FOR (n:SourceQuote) REQUIRE n.source_quote_id IS UNIQUE;
CREATE CONSTRAINT slot_ref_id_unique IF NOT EXISTS
FOR (n:SlotRef) REQUIRE n.slot_ref_id IS UNIQUE;
CREATE CONSTRAINT trigger_condition_id_unique IF NOT EXISTS
FOR (n:TriggerCondition) REQUIRE n.trigger_condition_id IS UNIQUE;
CREATE CONSTRAINT rule_threshold_id_unique IF NOT EXISTS
FOR (n:RuleThreshold) REQUIRE n.threshold_regime_id IS UNIQUE;
CREATE CONSTRAINT obligation_node_id_unique IF NOT EXISTS
FOR (n:ObligationNode) REQUIRE n.obligation_node_id IS UNIQUE;
CREATE CONSTRAINT obligation_edge_id_unique IF NOT EXISTS
FOR (n:ObligationEdge) REQUIRE n.obligation_edge_id IS UNIQUE;
CREATE CONSTRAINT evidence_requirement_id_unique IF NOT EXISTS
FOR (n:EvidenceRequirement) REQUIRE n.evidence_requirement_id IS UNIQUE;
CREATE CONSTRAINT semantic_slot_id_unique IF NOT EXISTS
FOR (n:SemanticSlot) REQUIRE n.slot_id IS UNIQUE;
CREATE CONSTRAINT measure_key_unique IF NOT EXISTS
FOR (n:Measure) REQUIRE n.measure_key IS UNIQUE;
CREATE CONSTRAINT artifact_key_unique IF NOT EXISTS
FOR (n:Artifact) REQUIRE n.artifact_key IS UNIQUE;
CREATE CONSTRAINT time_anchor_key_unique IF NOT EXISTS
FOR (n:TimeAnchor) REQUIRE n.time_anchor_key IS UNIQUE;
CREATE CONSTRAINT regulation_document_id_unique IF NOT EXISTS
FOR (n:RegulationDocument) REQUIRE n.document_id IS UNIQUE;
CREATE CONSTRAINT regulation_clause_id_unique IF NOT EXISTS
FOR (n:RegulationClause) REQUIRE n.clause_id IS UNIQUE;
CREATE CONSTRAINT skill_id_unique IF NOT EXISTS
FOR (n:Skill) REQUIRE n.skill_id IS UNIQUE;
CREATE CONSTRAINT skill_trigger_id_unique IF NOT EXISTS
FOR (n:SkillTrigger) REQUIRE n.trigger_id IS UNIQUE;
```

### 3.7.2 btree indexes

```cypher
CREATE INDEX fragment_world_idx IF NOT EXISTS
FOR (n:Fragment) ON (n.world_id);
CREATE INDEX component_world_type_idx IF NOT EXISTS
FOR (n:Component) ON (n.world_id, n.component_type);
CREATE INDEX component_geometry_idx IF NOT EXISTS
FOR (n:Component) ON (n.visible_area_m2, n.thickness_mm, n.length_m, n.width_m, n.height_m);
CREATE INDEX location_world_class_idx IF NOT EXISTS
FOR (n:Location) ON (n.world_id, n.location_class);
CREATE INDEX measurement_world_slot_idx IF NOT EXISTS
FOR (n:Measurement) ON (n.world_id, n.slot_id);
CREATE INDEX measurement_target_ref_idx IF NOT EXISTS
FOR (n:Measurement) ON (n.target_ref);
CREATE INDEX sidecar_world_slot_idx IF NOT EXISTS
FOR (n:SidecarEntry) ON (n.world_id, n.slot_id);
CREATE INDEX condition_world_class_idx IF NOT EXISTS
FOR (n:ConditionState) ON (n.world_id, n.condition_class);
CREATE INDEX condition_severity_idx IF NOT EXISTS
FOR (n:ConditionState) ON (n.world_id, n.severity_band, n.severity_index);
CREATE INDEX rule_card_family_idx IF NOT EXISTS
FOR (n:RuleCard) ON (n.family_id);
CREATE INDEX rule_card_phase_subject_idx IF NOT EXISTS
FOR (n:RuleCard) ON (n.phase, n.subject);
CREATE INDEX rule_threshold_measure_idx IF NOT EXISTS
FOR (n:RuleThreshold) ON (n.measure_key);
CREATE INDEX rule_threshold_operator_idx IF NOT EXISTS
FOR (n:RuleThreshold) ON (n.operator);
CREATE INDEX slot_ref_slot_idx IF NOT EXISTS
FOR (n:SlotRef) ON (n.slot_id);
CREATE INDEX evidence_bucket_idx IF NOT EXISTS
FOR (n:EvidenceRequirement) ON (n.bucket, n.kind);
CREATE INDEX obligation_edge_relation_idx IF NOT EXISTS
FOR (n:ObligationEdge) ON (n.relation);
CREATE INDEX skill_status_idx IF NOT EXISTS
FOR (n:Skill) ON (n.status, n.allowed_in_baseline);
```

### 3.7.3 fulltext indexes

```cypher
CREATE FULLTEXT INDEX regulation_clause_text_ft IF NOT EXISTS
FOR (n:RegulationClause) ON EACH [n.heading, n.text];
CREATE FULLTEXT INDEX rule_card_text_ft IF NOT EXISTS
FOR (n:RuleCard) ON EACH [n.normalized_rule_text, n.source_quote_texts];
CREATE FULLTEXT INDEX skill_text_ft IF NOT EXISTS
FOR (n:Skill) ON EACH [n.name, n.description, n.content_md, n.notes];
```

### 3.7.4 optional vector indexes

若实现 embedding RAG，可加：

```cypher
CREATE VECTOR INDEX rule_card_embedding_idx IF NOT EXISTS
FOR (n:RuleCard) ON (n.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: "cosine"
}};
```

baseline 不依赖 vector index；没有 embedding 时不得降级为读 W2。

# 4. 灌库设计

## 4.1 loader 总览

```text
ingest/
  fact_loader.py
  sidecar_loader.py
  regulation_loader.py
  rulecard_loader.py
  skill_loader.py
  eval_truth_loader.py      # evaluator-only，agent 不 import
  guard.py
  cypher_schema.py
```

## 4.2 agent fact loader

### 4.2.1 输入

```yaml
input:
  parquet_run_dir: gen_seed_<N>/
  required_tables:
    - buildings.parquet
    - fragments.parquet
    - components.parquet
    - locations.parquet
    - coverage_relations.parquet
    - fragment_states.parquet
    - specialized_states.parquet
    - measurements.parquet
    - sidecar_records.parquet
    - sidecar_entries.parquet
  optional_tables:
    - worldgen_world_bundles_meta.parquet
    - sidecar_runtime_meta.parquet
```

### 4.2.2 启动 guard

```python
def assert_agent_safe_input(run_dir: Path, explicit_targets: set[str] | None = None) -> None:
    files = {p.name for p in run_dir.glob("*.parquet")}
    forbidden = files & AGENT_NORMATIVE_DENYLIST
    if explicit_targets and (explicit_targets & AGENT_NORMATIVE_DENYLIST):
        raise SecurityError(f"agent loader cannot read normative projection tables: {explicit_targets & AGENT_NORMATIVE_DENYLIST}")
    audit.warn_skipped(forbidden)

    for table in REQUIRED_AGENT_TABLES:
        if table not in files:
            raise ContractError(f"missing required agent-visible table: {table}")
```

### 4.2.3 merge semantics

所有 loader 使用 `MERGE`，幂等写入：

```cypher
MERGE (w:World {world_id: $world_id})
SET w += $props
```

不得使用 `CREATE` 导致重复节点。每个 batch 产生 `:KGSnapshot`：

```text
(:KGSnapshot {kg_snapshot_id, loaded_at, input_root, source_hashes_json, loader_version})
(:KGSnapshot)-[:LOADED_WORLD]->(:World)
(:KGSnapshot)-[:LOADED_RULE_BUNDLE]->(:RuleCardBundle)
```

### 4.2.4 parquet → graph 映射

| parquet | graph 写入 | 特别规则 |
|---|---|---|
| `worldgen_world_bundles_meta.parquet` | `World` meta | optional；缺失时 loader 生成 `schema_version="unknown"` 并 warning |
| `buildings.parquet` | `World`, `Building`, `HAS_BUILDING` | `BuildingMetadata` 三字段可落在 Building，但标 metadata |
| `fragments.parquet` | `Fragment`, `HAS_FRAGMENT`, `OF_COMPONENT`, `AT_LOCATION` | 按上游 FK 建边 |
| `components.parquet` | `Component`, `HAS_COMPONENT`, `PARENT_OF`, `LOCATED_AT` | `geometry_proxy_json` shallow extract 出 5 个派生列，缺失填 null |
| `locations.parquet` | `Location`, `HAS_LOCATION` | 无法解析 spatial_tags 时填 [] |
| `coverage_relations.parquet` | `CoverageRelation`, `HAS_COVERAGE`, `COVERS_FRAGMENT` | 字段名用 `coverage_state`，禁止 `coverage_status` |
| `fragment_states.parquet` | 按 `state_type` 分派为 Driver/Mechanism/Condition/RepairAssessment | Condition 要抽 `derived_outcomes_*_json` |
| `specialized_states.parquet` | 按 `state_type` 分派为 Drainage/UBW/FireSafety | 从 `payload_json.component_id` 建 `HAS_*_STATE` 边 |
| `measurements.parquet` | `Measurement` + target ref relationship | 合并 ref 别名列；parse qualifiers_json |
| `sidecar_runtime_meta.parquet` | sidecar meta provenance | optional |
| `sidecar_records.parquet` | `SidecarRuntimeRecord` | 读取后丢弃 `projection_id`，不留 hash |
| `sidecar_entries.parquet` | `SidecarEntry` + slot/measure/time anchor relationships | `entry_type` 保留；source_refs 可解析则建 `SOURCED_FROM` |

### 4.2.5 `fragment_states.parquet` 分派

```python
STATE_TYPE_LABEL = {
    "driver": "DriverState",
    "mechanism": "MechanismState",
    "condition": "ConditionState",
    "repair_assessment": "RepairAssessmentState",
}
```

每行：

1. `payload = json.loads(payload_json)`；
2. 以对应状态 id 为主键；
3. 抽取本规格 §3.3.2 所列高频字段；
4. 原 dict 存 `payload_json`；
5. 对 `state_type="condition"`，必须执行：

```python
derived = payload.get("derived_outcomes") or {}
props["derived_outcomes_json"] = canonical_json(derived)
for key in ["risk_flags", "repair_flags", "verification_flags", "assessment_flags", "risk_index_values", "fallback_reasons"]:
    props[f"{key}_json"] = canonical_json(derived.get(key, {}))
```

### 4.2.6 `specialized_states.parquet` 分派

```python
SPECIALIZED_STATE_LABEL = {
    "drainage": "DrainageState",
    "ubw": "UBWState",
    "fire_safety": "FireSafetyState",
}
```

每行从 `payload_json` 解析：

```python
payload = json.loads(payload_json)
component_id = payload.get("component_id")
```

关系建立：

```text
DrainageState  -> (:Component)-[:HAS_DRAINAGE_STATE]->(:DrainageState)
UBWState       -> (:Component)-[:HAS_UBW_STATE]->(:UBWState)
FireSafetyState-> (:Component)-[:HAS_FIRE_SAFETY_STATE]->(:FireSafetyState)
```

若 `component_id` 缺失或找不到 component，节点仍写入，`component_id=null`，记录 `target_unresolved` warning；不得创建占位 Component。

### 4.2.7 Measurement target 解析

```python
def resolve_target_ref(tx, world_id, target_ref):
    if exists(Fragment.fragment_id == target_ref): return ("Fragment", target_ref)
    if exists(Component.component_id == target_ref): return ("Component", target_ref)
    if exists(ConditionState.condition_id == target_ref): return ("ConditionState", target_ref)
    return ("Unknown", target_ref)
```

关系：

```text
Fragment       -> (:Fragment)-[:HAS_MEASUREMENT]->(:Measurement)
Component      -> (:Component)-[:HAS_MEASUREMENT]->(:Measurement)
ConditionState -> (:ConditionState)-[:HAS_MEASUREMENT]->(:Measurement)
Unknown        -> 不建 target 边；Measurement.target_kind="unknown"
```

若 `Unknown`，closure verifier 仍可通过 `slot_id` / `measure_key` 检索该事实，但 target scoped obligation 绑定时标记 `target_unresolved`。

### 4.2.8 sidecar `projection_id` 丢弃规则

```python
def build_sidecar_runtime_props(row):
    # row contains projection_id in parquet, but agent KG must never receive it.
    props = {
        "runtime_id": row["runtime_id"],
        "world_id": row["world_id"],
        "interface_ids": row.get("interface_ids") or [],
        "source_kind": "worldgen_sidecar",
    }
    assert "projection_id" not in props
    assert "raw_projection_ref_hash" not in props
    return props
```

禁止实现：

```python
props["projection_id"] = row["projection_id"]             # forbidden
props["raw_projection_ref_hash"] = sha256(row["projection_id"])  # forbidden
```

## 4.3 rule_card loader

### 4.3.1 输入文件

来自 `rule_card_v2/mbis_cop_2023/`：

```text
manifest.json
rule_cards.json
family_index.json
slot_index.json
threshold_regime_index.json
exception_definition_index.json
semantic_slot_registry_v1.json
measure_registry_v1.json
artifact_semantics_registry_v1.json
time_anchor_registry_v1.json
controlled_vocabularies_v1.json
projection_runtime_mapping_v1.json
coverage_baseline_v1.json                 # 默认不进 agent KG
family_coverage_baseline_v1.json          # 默认不进 agent KG
coverage_gap_audit_v1.json                 # 默认不进 agent KG
```

注意：`family_coverage_baseline_v1.json` 是 worldgen 覆盖就绪度 baseline，不是 rule_card 全量 family 清单；不得用它覆盖 `family_index.json` 的 43 fine family。

### 4.3.2 rule card bundle record

```text
(:RuleCardBundle {
  bundle_id,
  schema_version,
  source_document_id,
  canonical_file,
  card_count = 397,
  family_count = 43,
  loaded_at
})
```

关系：

```text
(:RuleCardBundle)-[:HAS_RULE_FAMILY]->(:RuleFamily)
(:RuleCardBundle)-[:HAS_RULE_CARD]->(:RuleCard)
```

### 4.3.3 rule card parsing

对每张 card：

```python
card = {
  "rule_card_id": ...,
  "source_document_id": ...,
  "source_section": [...],
  "source_quote": [...],
  "normalized_rule_text": ...,
  "family_id": ...,
  "applicability": {...},
  "trigger_conditions": {...},
  "workflow_operands": {...},
  "slot_role_map": [...],
  "threshold_regimes": [...],
  "exceptions": [...],
  "definitions": [...],
  "obligation_graph": {"nodes": [...], "edges": [...]},
  "neighbor_families": [...],
  "evidence_requirements": {...},
  "version": {...},
  "provenance": {...}
}
```

必须逐项落图，不允许只把整张卡塞进 JSON 而不建子节点。闭包验证器依赖结构化子节点。

关键落库规则：

```python
rule_card.source_quote_texts = [q.get("text", "") for q in card["source_quote"] if q.get("text")]
rule_card.neighbor_families = card.get("neighbor_families", [])
rule_card.primary_actor = card.get("workflow_operands", {}).get("primary_actor")
rule_card.primary_action = card.get("workflow_operands", {}).get("primary_action")
rule_card.method_keys_allowed = card.get("workflow_operands", {}).get("method_keys_allowed", [])

for idx, q in enumerate(card["source_quote"]):
    quote_local_id = q.get("quote_id") or f"sq{idx+1:02d}"
    source_quote_id = f"{rule_card_id}::{quote_local_id}"

for trig in card["trigger_conditions"].get("items", []):
    trigger_condition_id = f"{rule_card_id}::trigger::{trig['condition_id']}"
    expected_value_json = canonical_json(trig.get("expected_value"))

for thr in card.get("threshold_regimes", []):
    props["threshold_value_json"] = canonical_json(thr.get("value"))
    props["formula_json"] = canonical_json(thr.get("formula")) if thr.get("formula") is not None else None

for edge in card.get("obligation_graph", {}).get("edges", []):
    obligation_edge_id = f"{rule_card_id}::edge::{edge['source_node_id']}::{edge['relation']}::{edge['target_node_id']}"
```

`neighbor_families` 落库路径：

1. `RuleCard.neighbor_families` 保存原 list；
2. 对每个 neighbor id 建 `(:RuleCard)-[:CARD_NEIGHBOR_OF]->(:RuleFamily)`；
3. 按 `(source_family_id, target_family_id)` 聚合建 `(:RuleFamily)-[:NEIGHBOR_OF {source:"card_neighbor_families", card_count}]->(:RuleFamily)`。

`obligation_graph.edges` 落库路径：

1. 建 `(:ObligationEdge)`；
2. 建 `RuleCard-HAS_OBLIGATION_EDGE->ObligationEdge`；
3. 若 source/target node 均存在，建 `ObligationEdge-FROM/TO->ObligationNode` 与 `ObligationNode-OBLIGATION_EDGE->ObligationNode`；
4. 若任一端缺失，`ObligationEdge` 仍落库，标记 `edge_resolution_state="unresolved"`，verifier 输出 `blocked + missing_obligation_edge_target`。

### 4.3.4 source section to clause

`source_section.section_id` 与法规原文章节可能格式差异。loader 使用归一化：

```python
normalize_section_id("2.1.3(o)") -> "2.1.3(o)"
normalize_section_id("s2_1_3_o") -> "2.1.3(o)"
```

无法匹配时：

- `RuleCard` 仍加载；
- `SOURCED_FROM_CLAUSE` 不建；
- 在 `RuleCard.unresolved_source_sections` 记录；
- quality gate 不 fail，但出 warning。

## 4.4 regulation loader

### 4.4.1 markdown clause 切分

法规 markdown 按标题层级切分为 `RegulationClause`：

```python
heading_pattern = r"^(#{1,6})\s+(.+)$"
level = number_of_hashes
section_id = extract_leading_section_number_or_slug(heading)
```

每个 clause 的 `text` 包含本标题到下一个同级或更高级标题前的正文。

### 4.4.2 document IDs

| 文件 | document_id |
|---|---|
| `MBIS_CoP_2023.md` | `MBIS_CoP_2023` |
| `MBIS_MWIS_CoP_2012_Legacy.md` | `MBIS_MWIS_CoP_2012_Legacy` |
| `MBIS_MWIS_Operation_Note.md` | `MBIS_MWIS_Operation_Note` |
| `PNBI10_CoP_2023.md` | `PNBI10_CoP_2023` |

### 4.4.3 fulltext preparation

每个 clause 计算：

```text
text_hash = sha256(canonical_text)
embedding = optional
```

baseline 必须能在无 embedding 时使用 fulltext index。

## 4.5 skill loader

baseline 必须加载 4 个手工 seed Skill：

```yaml
skills:
  load_manual_seed: true
  skill_seed_dir: skills_seed/
  required_seed_skill_ids:
    - skill.mbis.building_assessment_workflow
    - skill.mbis.fact_kg_retrieval
    - skill.mbis.rule_obligation_derivation
    - skill.mbis.auxiliary_report_writer
```

每个 Skill 目录格式：

```text
skills_seed/<skill_id>/
  skill.yaml
  content.md
```

`skill.yaml` 最小 schema：

```yaml
skill_id: skill.mbis.auxiliary_report_writer
name: MBIS auxiliary review report writer
description: Writes auxiliary review report from closure verifier output.
status: manual_seed
origin: manual
version: 0.2.0
allowed_in_baseline: true
triggers:
  - trigger_kind: required_input
    pattern:
      required_input: ClosureValidationResult
```

loader 必须把 `content.md` 全文写入 `Skill.content_md`，并为 triggers 建 `SkillTrigger` 节点。baseline 不允许 Skill 修改 verifier 输出，不允许 Skill 读取 evaluator-only truth。

## 4.6 evaluator truth loader

### 4.6.1 输入

```text
normative_projection_meta.parquet
projections.parquet
matched_families.parquet
threshold_evaluations.parquet
coverage_control_metadata.parquet
basis_items.parquet
```

### 4.6.2 输出

若使用 DuckDB：

```sql
CREATE TABLE eval_projections AS SELECT * FROM read_parquet('projections.parquet');
CREATE TABLE eval_matched_families AS SELECT * FROM read_parquet('matched_families.parquet');
CREATE TABLE eval_threshold_evaluations AS SELECT * FROM read_parquet('threshold_evaluations.parquet');
CREATE TABLE eval_basis_items AS SELECT * FROM read_parquet('basis_items.parquet');
```

若使用 Neo4j evaluator database，标签必须带 `Eval` 前缀，并且不在 agent database：

```text
(:EvalNormativeProjection)
(:EvalProjectionFamilyEval)
(:EvalThresholdEval)
(:EvalBasisItem)
```

任何 evaluator label 不得出现在 `evo_agent_baseline` database。

## 4.7 ingestion quality gates

| gate | hard fail 条件 |
|---|---|
| G-001 denylist table | agent loader 显式读取 W2 denylist 表 |
| G-002 forbidden property | agent KG 写入 §2.2.3 禁止属性名 |
| G-003 rulecard child completeness | 任一 RuleCard 缺 `ApplicabilityPredicate` 或 `ObligationNode` 子结构 |
| G-004 threshold formula preservation | `operator="formula"` 且上游有 `formula` 时，`RuleThreshold.formula_json` 为空 |
| G-005 obligation edge preservation | 上游 `obligation_graph.edges[]` 非空但未落 `ObligationEdge` |
| G-006 sidecar projection scrub | `SidecarRuntimeRecord` props 含 `projection_id` 或 hash 变体 |
| G-007 source quote key | `SourceQuote` 不含 `source_quote_id` |
| G-008 seed skills | 4 个 baseline seed Skill 任一未加载或 `allowed_in_baseline=false` |

# 5. ComplianceAssessmentRun 与 KG-RAG 检索策略

## 5.1 新载体：`ComplianceAssessmentRun`

旧 `QueryEpisode` 不再使用。baseline 的一次评估会话载体为 `ComplianceAssessmentRun`。

### 5.1.1 schema

```python
class ComplianceAssessmentRun(BaseModel):
    run_id: str                       # CAR-<timestamp>-<hash>
    run_type: Literal["baseline_building_review"]
    world_id: str
    building_id: str
    requested_at: str
    completed_at: Optional[str] = None
    status: Literal[
        "created",
        "retrieving_facts",
        "retrieving_rules",
        "verifying_closure",
        "report_ready",
        "blocked",
        "failed",
    ]
    kg_snapshot_id: str
    agent_version: str
    verifier_version: str
    rulecard_bundle_id: str
    input_guard_result: Dict[str, Any]
    retrieval_summary: Dict[str, Any] = {}
    closure_result_ref: Optional[str] = None
    report_ref: Optional[str] = None
    allow_stop: Optional[bool] = None
    notes: List[str] = []
```

Neo4j 可选节点：

```text
(:ComplianceAssessmentRun {run_id, ...})
(:ComplianceAssessmentRun)-[:ASSESSING]->(:Building)
(:ComplianceAssessmentRun)-[:USES_KG_SNAPSHOT]->(:KGSnapshot)
```

## 5.2 运行流程

```text
1. validate input building_id / world_id
2. create ComplianceAssessmentRun
3. hook pre_run_guard
4. retrieve building fact subgraph
5. retrieve candidate rule families/cards
6. assemble FactPack + RuleSlice
7. deterministic closure verifier
8. if allow_stop=false:
      LLM may output "资料未闭合的辅助说明"，不得输出完整审查报告
   else:
      LLM writes auxiliary review report using verifier output
9. hook pre_output_guard
10. persist run artifacts
11. evaluator later reads artifacts and W2 truth to score
```

## 5.3 Fact KG-RAG 检索

### 5.3.1 building shell

```cypher
MATCH (b:Building {building_id: $building_id})<-[:HAS_BUILDING]-(w:World)
RETURN w, b;
```

### 5.3.2 fragment/component/location subgraph

```cypher
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)
OPTIONAL MATCH (f)-[:OF_COMPONENT]->(c:Component)
OPTIONAL MATCH (f)-[:AT_LOCATION]->(l:Location)
RETURN f, c, l
ORDER BY f.fragment_id;
```

### 5.3.3 conditions / states

```cypher
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)
OPTIONAL MATCH (f)-[:HAS_DRIVER_STATE]->(d:DriverState)
OPTIONAL MATCH (f)-[:HAS_MECHANISM_STATE]->(m:MechanismState)
OPTIONAL MATCH (f)-[:HAS_CONDITION]->(cond:ConditionState)
OPTIONAL MATCH (f)-[:HAS_REPAIR_ASSESSMENT]->(ra:RepairAssessmentState)
RETURN f.fragment_id, collect(d), collect(m), collect(cond), collect(ra);
```

### 5.3.4 measurements

```cypher
MATCH (b:Building {building_id: $building_id})-[:HAS_FRAGMENT]->(f:Fragment)
OPTIONAL MATCH (f)-[:HAS_MEASUREMENT]->(msr:Measurement)
RETURN f.fragment_id, collect(msr)
ORDER BY f.fragment_id;
```

component-level and condition-level measurements:

```cypher
MATCH (b:Building {building_id: $building_id})-[:HAS_COMPONENT]->(c:Component)
OPTIONAL MATCH (c)-[:HAS_MEASUREMENT]->(msr:Measurement)
RETURN c.component_id, collect(msr);
```

### 5.3.5 sidecar entries

```cypher
MATCH (b:Building {building_id: $building_id})<-[:HAS_BUILDING]-(w:World)
MATCH (w)-[:HAS_SIDECAR_RECORD]->(r:SidecarRuntimeRecord)-[:HAS_SIDECAR_ENTRY]->(e:SidecarEntry)
RETURN r.runtime_id, e
ORDER BY r.runtime_id, e.entry_type, e.sidecar_entry_id;
```

## 5.4 Rule KG-RAG 检索

### 5.4.1 slot-driven candidate cards

从 FactPack 的 `slot_id` 集合开始：

```cypher
MATCH (s:SemanticSlot)<-[:REFERS_TO_SEMANTIC_SLOT]-(sr:SlotRef)<-[:HAS_SLOT_REF]-(rc:RuleCard)
WHERE s.slot_id IN $slot_ids
RETURN rc, count(sr) AS slot_hits
ORDER BY slot_hits DESC, rc.rule_card_id;
```

measure-driven：

```cypher
MATCH (m:Measure)<-[:REFERS_TO_MEASURE]-(t:RuleThreshold)<-[:HAS_THRESHOLD]-(rc:RuleCard)
WHERE m.measure_key IN $measure_keys
RETURN rc, count(t) AS threshold_hits
ORDER BY threshold_hits DESC, rc.rule_card_id;
```

### 5.4.2 applicability-driven candidate cards

根据 building facts / component facts：

```cypher
MATCH (fam:RuleFamily)-[:HAS_RULE_CARD]->(rc:RuleCard)-[:HAS_APPLICABILITY]->(ap:ApplicabilityPredicate)
WHERE ap.regime = "mbis"
  AND (
    size(ap.building_scope) = 0 OR
    any(scope IN ap.building_scope WHERE scope IN $building_scope_tags)
  )
RETURN rc, fam;
```

component scope：

```cypher
MATCH (rc:RuleCard)-[:HAS_APPLICABILITY]->(ap:ApplicabilityPredicate)
WHERE size(ap.component_scope) = 0
   OR any(x IN ap.component_scope WHERE x IN $component_scope_tags)
RETURN rc;
```

### 5.4.3 graph expansion

候选 cards 扩展一跳，并保留 rule_card v2 原嵌套 DTO 所需的全部子结构：

```cypher
MATCH (rc:RuleCard)
WHERE rc.rule_card_id IN $candidate_rule_card_ids
OPTIONAL MATCH (rc)-[:HAS_SLOT_REF]->(sr:SlotRef)-[:REFERS_TO_SEMANTIC_SLOT]->(slot:SemanticSlot)
OPTIONAL MATCH (rc)-[:HAS_THRESHOLD]->(thr:RuleThreshold)-[:REFERS_TO_MEASURE]->(mea:Measure)
OPTIONAL MATCH (thr)-[:USES_TIME_ANCHOR]->(ta:TimeAnchor)
OPTIONAL MATCH (rc)-[:HAS_EVIDENCE_REQUIREMENT]->(er:EvidenceRequirement)
OPTIONAL MATCH (rc)-[:HAS_OBLIGATION_NODE]->(on:ObligationNode)
OPTIONAL MATCH (rc)-[:HAS_OBLIGATION_EDGE]->(oe:ObligationEdge)
OPTIONAL MATCH (on)-[:REQUIRES_ARTIFACT]->(wa:WorkflowArtifact)
OPTIONAL MATCH (on)-[:HAS_DEADLINE]->(wd:WorkflowDeadline)
OPTIONAL MATCH (on)-[:SENT_TO]->(wr:WorkflowRecipient)
OPTIONAL MATCH (rc)-[:HAS_TRIGGER]->(tc:TriggerCondition)
OPTIONAL MATCH (rc)-[:HAS_SOURCE_QUOTE]->(sq:SourceQuote)
RETURN rc,
       collect(DISTINCT sr), collect(DISTINCT slot),
       collect(DISTINCT thr), collect(DISTINCT mea), collect(DISTINCT ta),
       collect(DISTINCT er),
       collect(DISTINCT on), collect(DISTINCT oe),
       collect(DISTINCT wa), collect(DISTINCT wd), collect(DISTINCT wr),
       collect(DISTINCT tc), collect(DISTINCT sq)
ORDER BY rc.rule_card_id;
```

DTO builder 必须把扁平子图还原为 `rule_cards.json` 的原嵌套结构：`trigger_conditions.items[]`、`workflow_operands.artifacts[]/deadlines[]/recipients[]`、`slot_role_map[]`、`threshold_regimes[]`、`obligation_graph.nodes[]/edges[]`、`evidence_requirements.{for_matching,for_submission,for_completion}[]`。

### 5.4.4 retrieval ranking

候选规则排序分数：

```text
score =
  5.0 * exact_slot_hit_count
+ 4.0 * exact_measure_hit_count
+ 2.0 * applicability_match_count
+ 1.5 * source_clause_fulltext_score
+ 1.0 * neighbor_family_hit_count
- 3.0 * explicit_exclusion_match_count
```

规则：

- 排名只影响 LLM context 顺序，不影响闭包验证器的确定性候选全集；
- verifier 使用 candidate cutoff 前必须记录 cutoff policy；
- 默认 verifier 候选集取所有 `score > 0` 且 applicability 未明确排除的 RuleCard；
- 若候选数过大，按 family 分桶，每个 family 取 top K，同时保留所有与已命中 slot/measure 精确相连的卡。

## 5.5 FactPack schema

```python
class FactAtom(BaseModel):
    fact_id: str
    world_id: str
    building_id: str
    carrier_type: Literal[
        "building", "component", "location", "fragment",
        "driver", "mechanism", "condition",
        "drainage", "ubw", "fire_safety",
        "repair_assessment", "measurement", "sidecar_entry"
    ]
    carrier_id: str
    target_ref: Optional[str]
    slot_id: Optional[str]
    measure_key: Optional[str]
    value_json: str
    value_type: Literal["number", "boolean", "string", "enum", "object", "null"]
    unit: Optional[str]
    qualifiers: Dict[str, Any] = {}
    confidence_index: Optional[float] = None
    source_path: str
    source_node_id: str
    provenance: Dict[str, Any] = {}
```

`FactPack`：

```python
class FactPack(BaseModel):
    run_id: str
    world_id: str
    building_id: str
    facts: List[FactAtom]
    slot_index: Dict[str, List[str]]       # slot_id -> fact_id list
    measure_index: Dict[str, List[str]]    # measure_key -> fact_id list
    carrier_index: Dict[str, List[str]]
    source_tables: List[str]
```

## 5.6 RuleSlice schema

```python
class RuleSlice(BaseModel):
    run_id: str
    rulecard_bundle_id: str
    candidate_rule_cards: List[RuleCardDTO]
    rule_families: List[RuleFamilyDTO]
    semantic_slots: List[SemanticSlotDTO]
    measures: List[MeasureDTO]
    artifacts: List[ArtifactDTO]
    time_anchors: List[TimeAnchorDTO]
    source_quotes: List[SourceQuoteDTO]
    retrieval_policy: Dict[str, Any]
```

DTO 结构要求：

1. `RuleCardDTO` 必须保留 rule_card v2 原嵌套形态，而不是只给扁平节点列表。
2. `RuleCardDTO` 至少包含以下字段：

```python
class RuleCardDTO(BaseModel):
    rule_card_id: str
    source_document_id: str
    source_section: list[dict]
    source_quote: list[dict]
    normalized_rule_text: str
    family_id: str
    applicability: dict
    trigger_conditions: dict          # {logic, items[]}
    workflow_operands: dict           # primary_actor/action, artifacts[], deadlines[], recipients[], method_keys_allowed[]
    slot_role_map: list[dict]
    threshold_regimes: list[dict]     # includes formula when present
    exceptions: list[dict]
    definitions: list[dict]
    obligation_graph: dict            # {nodes[], edges[]}
    neighbor_families: list[str]
    evidence_requirements: dict       # for_matching / for_submission / for_completion
    version: dict
    provenance: dict
```

3. `RuleThresholdDTO.formula` 必须从 `RuleThreshold.formula_json` 还原，不能丢失。
4. `SourceQuoteDTO` 主键字段统一为 `source_quote_id`，同时保留 `quote_local_id`。
5. DTO 不得包含 §2.2.3 禁止属性名；尤其不得包含任何 W2 `projection_*` 字段、`expected_verdict` 或 `coverage_status`。

---

# 6. 闭包验证器实现级规格

## 6.1 组件定位

闭包验证器是 agent runtime 的底线层组件：

```text
module: closure/
owner: evo-agent baseline runtime
input: RuleSlice + FactPack
forbidden input: NormativeProjection / expected_verdict / W2 basis_items / W2 threshold_evaluations
output: ClosureValidationResult
```

它不属于数据生成层，不消费 W2 reference truth。它从 rule_card v2 + 法规 KG + 建筑事实 KG 自行推导 obligation，并逐条确定 `closure_status` / `satisfaction_status`。

## 6.2 新 `ObligationSet` schema

### 6.2.1 enums

```python
ObligationKind = Literal[
    "scope",
    "trigger",
    "prerequisite",
    "definition",
    "exception",
    "evidence",
    "artifact",
    "deadline",
    "threshold",
    "method",
    "supervision",
    "report_field",
    "action",
    "prohibition",
    "escalation",
]

ClosureStatus = Literal["closed", "open", "blocked"]

SatisfactionStatus = Literal[
    "satisfied",
    "violated",
    "unknown",
    "not_applicable",
]

BlockedReasonCode = Literal[
    "missing_rule_edge",
    "missing_obligation_edge_target",
    "unsupported_obligation_edge_relation",
    "unsupported_predicate_kind",
    "unsupported_operator",
    "unsupported_formula",
    "unsupported_deadline_relation",
    "unit_mismatch",
    "ambiguous_fact_binding",
    "schema_contract_violation",
    "target_unresolved",
    "qualifier_conflict",
    "missing_artifact_mapping",
    "artifact_not_modeled_upstream",
    "internal_error",
]

OpenReasonCode = Literal[
    "missing_fact",
    "null_observed_value",
    "missing_sidecar_entry",
    "missing_measurement",
    "missing_artifact_evidence",
    "missing_time_anchor",
    "missing_required_qualifier",
    "missing_required_field_group",
    "applicability_uncertain",
    "depends_on_open_trigger",
]
```

### 6.2.2 `Obligation`

```python
class Obligation(BaseModel):
    obligation_id: str
    run_id: str
    world_id: str
    building_id: str
    fragment_id: Optional[str] = None
    component_id: Optional[str] = None

    source_rule_card_id: str
    source_family_id: str
    source_clause_ids: List[str] = []
    source_quote_ids: List[str] = []

    kind: ObligationKind
    obligation_node_id: Optional[str] = None
    obligation_edge_ids: List[str] = []
    actor: Optional[str] = None
    action: Optional[str] = None
    recipient_ids: List[str] = []
    slot_ref_ids: List[str] = []
    slot_ids: List[str] = []
    measure_keys: List[str] = []
    artifact_ids: List[str] = []
    artifact_keys: List[str] = []
    deadline_ids: List[str] = []
    time_anchor_keys: List[str] = []

    required: bool = True
    applicability_state: Literal["applicable", "not_applicable", "uncertain"] = "applicable"
    # This is verifier-owned and unrelated to W2 ProjectionFamilyEval.applicability_state.

    depends_on_open_trigger: bool = False
    trigger_dependency_ids: List[str] = []
    trigger_state: Literal["active", "inactive", "open", "blocked", "not_evaluated"] = "not_evaluated"

    closure_status: ClosureStatus
    satisfaction_status: SatisfactionStatus

    operator: Optional[str] = None
    expected_value_json: Optional[str] = None
    threshold_value_json: Optional[str] = None
    observed_value_json: Optional[str] = None
    unit: Optional[str] = None
    comparator_result: Optional[bool] = None

    evidence_fact_ids: List[str] = []
    evidence_node_refs: List[str] = []

    open_reason_code: Optional[OpenReasonCode] = None
    blocked_reason_code: Optional[BlockedReasonCode] = None
    notes: str = ""
```

validator 规则：

```python
if closure_status == "closed":
    assert blocked_reason_code is None
    assert open_reason_code is None
    assert satisfaction_status in {"satisfied", "violated", "not_applicable"}

if closure_status == "open":
    assert open_reason_code is not None
    assert blocked_reason_code is None
    assert satisfaction_status == "unknown"

if closure_status == "blocked":
    assert blocked_reason_code is not None
    assert satisfaction_status == "unknown"

if depends_on_open_trigger:
    assert trigger_dependency_ids
    assert closure_status in {"open", "blocked"} or open_reason_code == "depends_on_open_trigger"
```

### 6.2.3 `ObligationSet`

> ⚠️ **identity-v5 现网键切换增补**：`ObligationSet` 升级为容器 `obligation_set_v2` + 身份 `obligation_identity_v5`，新增 `obligation_set_schema` / `obligation_identity_schema` / `canonical_profile_id` / `identity_key_policy` / `identity_manifest`（`obligations` 仍是 v1 扁平 `Obligation`，身份材料旁挂 manifest）。字段与语义见 `spec_identity_v5现网键切换增补_20260717.md` §4.2。

```python
class ObligationSet(BaseModel):
    obligation_set_id: str
    run_id: str
    world_id: str
    building_id: str
    created_at: str
    rulecard_bundle_id: str
    verifier_version: str
    obligations: List[Obligation]
    derivation_policy: Dict[str, Any]
```

### 6.2.4 `ClosureSummary`

```python
class ClosureSummary(BaseModel):
    total_obligations: int
    closed_count: int
    open_count: int
    blocked_count: int

    satisfied_count: int
    violated_count: int
    unknown_count: int
    not_applicable_count: int

    open_reason_counts: Dict[str, int]
    blocked_reason_counts: Dict[str, int]
    rule_card_count: int
    family_count: int
    fragment_count: int

    allow_stop: bool
    stop_reason: str
```

### 6.2.5 `ClosureValidationResult`

```python
class ClosureValidationResult(BaseModel):
    run_id: str
    obligation_set: ObligationSet
    closure_summary: ClosureSummary
    allow_stop: bool
    allow_report_generation: bool
    high_risk_items: List[dict]
    machine_readable_report: Dict[str, Any]
```

## 6.3 义务推导逻辑

### 6.3.1 总体原则

闭包验证器从 `RuleSlice + FactPack` 推导义务，不读 W2。义务来源包括：

1. `RuleCard.applicability`
2. `RuleCard.trigger_conditions`
3. `RuleCard.slot_role_map`
4. `RuleCard.threshold_regimes`
5. `RuleCard.workflow_operands`
6. `RuleCard.obligation_graph.nodes`
7. `RuleCard.obligation_graph.edges`
8. `RuleCard.evidence_requirements`
9. `RuleCard.exceptions`
10. `RuleCard.definitions`

生成顺序固定：applicability → triggers → slot roles → thresholds → obligation_graph nodes / edges → evidence requirements → exceptions → definitions → sort/dedupe。

### 6.3.2 适用性评估

```python
def evaluate_applicability(card, fact_pack) -> ApplicabilityResult:
    # deterministic only
    # Uses building_use, component_type, location_class, spatial_tags,
    # fragment.in_scope, component_scope, building_scope, actors/regime.
```

结果：

```python
class ApplicabilityResult(BaseModel):
    state: Literal["applicable", "not_applicable", "uncertain"]
    matched_facts: List[str]
    reasons: List[str]
```

规则：

- `regime != "mbis"` → `not_applicable`
- `building_scope` 与 building facts 明确冲突 → `not_applicable`
- `component_scope` 非空且无任何 component/fragment 匹配 → `not_applicable`
- 所需 scope fact 缺失 → `uncertain`
- 否则 `applicable`

`not_applicable` 的 card 不生成 mandatory obligations，但生成一条 `scope` audit obligation：

```text
closure_status=closed
satisfaction_status=not_applicable
kind=scope
```

`uncertain` 生成：

```text
closure_status=open
satisfaction_status=unknown
open_reason_code=applicability_uncertain
```

### 6.3.3 trigger obligations

对 `trigger_conditions.items` 每项生成 `kind=trigger` obligation。

支持：

```text
predicate_kind=slot
operators: ==, !=, in, not_in, <, <=, >, >=
logic: all / any
```

若 predicate_kind 不支持：

```text
closure_status=blocked
blocked_reason_code=unsupported_predicate_kind
```

若 slot fact 缺失：

```text
closure_status=open
open_reason_code=missing_fact
```

trigger false 的处理：

- trigger evidence 存在且为 false：`closed + not_applicable`，该 rule 的下游 action obligations 不激活；
- trigger true：下游 obligations 激活；
- trigger open/blocked：下游 obligations 仍生成，但字段 `depends_on_open_trigger=true`，`trigger_dependency_ids` 指向相关 trigger obligation，`allow_stop=false`。

#### `aggregate_trigger_logic`

输入为 card 的 `trigger_conditions.logic` 与 trigger obligation 列表，输出四态：`True / False / "open" / "blocked"`。

```python
def aggregate_trigger_logic(logic: str, trigger_obligations: list[Obligation]):
    states = [trigger_state(o) for o in trigger_obligations]
    # trigger_state: true if closed+satisfied, false if closed+not_applicable or closed+violated,
    # open if closure_status=open, blocked if closure_status=blocked
    if any(s == "blocked" for s in states):
        return "blocked"
    if not states:
        return True
    if logic == "all":
        if any(s is False for s in states): return False
        if any(s == "open" for s in states): return "open"
        return True
    if logic == "any":
        if any(s is True for s in states): return True
        if any(s == "open" for s in states): return "open"
        return False
    return "blocked"
```

下游 obligation 标记：

| aggregate result | 下游处理 |
|---|---|
| `True` | 正常评估 |
| `False` | 生成一条 `scope`/`trigger` not_applicable audit obligation 后跳过 action obligations |
| `"open"` | 下游 obligations 生成为 `open + depends_on_open_trigger`，除非自身也发现更具体 open reason |
| `"blocked"` | 下游 obligations 生成为 `blocked + missing_rule_edge` 或继承 trigger blocked 信息 |

### 6.3.4 slot role obligations

对 `slot_role_map` 中 `required=true` 的 slot ref：

| role | obligation kind |
|---|---|
| `trigger` | `trigger` |
| `prerequisite` | `prerequisite` |
| `evidence` | `evidence` |
| `definition_reference` | `definition` |
| 其他未知 role | `evidence`，notes 记录 role |

每条义务必须带 `slot_ref_id`、`slot_id`、`qualifiers_json`。

qualifier 匹配：

```python
def qualifiers_match(required: dict, observed: dict) -> bool:
    # required must be subset of observed unless runtime_mapping says ignore
    for k, v in required.items():
        if observed.get(k) != v:
            return False
    return True
```

`observed` 来自 `FactAtom.qualifiers`，该字段由 `Measurement.qualifiers_json`、`SidecarEntry.qualifiers_json`、`ManifestationFlag.qualifier_ids` 等解析而来。

多个 fact 命中：

- 若所有命中值一致：closed，使用全部 evidence refs；
- 若值冲突：blocked，`ambiguous_fact_binding`；
- 若 qualifiers 无法判定：blocked，`qualifier_conflict`。

### 6.3.5 threshold obligations

每个 `threshold_regime` 生成 `kind=threshold` obligation。

输入：

```text
measure_key, operator, value, unit, qualifiers, time_anchor_key, formula
```

fact binding 顺序：

1. exact `measure_key`；
2. `projection_runtime_mapping_v1.measure_aliases` alias；
3. measurement `slot_id` exact；
4. sidecar numeric entry exact；
5. sidecar measure target from `measure_targets`。

比较器：

```python
COMPARATORS = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
    "in": lambda observed, expected: observed in expected,
    "not_in": lambda observed, expected: observed not in expected,
}
```

`operator="formula"`：baseline 不实现通用公式解释器，但实现一个白名单 deterministic handler。

#### formula handler 白名单

允许公式仅限：

```json
{
  "expression": "n^2 - 2n + 3",
  "variables": [{"measure_key": "count.pull_test.failed_cumulative", "symbol": "n"}]
}
```

适用输出 measure：

```text
count.pull_test.additional_after_failure
```

handler：

```python
def handle_pull_test_additional_after_failure(threshold, fact_index):
    formula = json.loads(threshold.formula_json)
    assert formula["expression"].replace(" ", "") in {"n^2-2n+3", "n**2-2*n+3"}
    n_fact = bind_measure("count.pull_test.failed_cumulative", threshold.qualifiers, fact_index)
    if n_fact is missing: return open(missing_measurement)
    n = int(parse_json_number(n_fact.value_json))
    expected = n * n - 2 * n + 3
    observed = bind_measure("count.pull_test.additional_after_failure", threshold.qualifiers, fact_index)
    if observed is missing: return open(missing_measurement)
    return compare(observed, ">=", expected)
```

任何其他 formula：

```text
closure_status=blocked
blocked_reason_code=unsupported_formula
```

单位规则：

```python
if threshold.unit and fact.unit and canonicalize(threshold.unit) != canonicalize(fact.unit):
    blocked(unit_mismatch)
elif threshold.unit and not fact.unit:
    open(missing_measurement)
```

结果：

- comparison 成功且 true：`closed + satisfied`
- comparison 成功且 false：`closed + violated`
- observed null：`open + null_observed_value`
- missing fact：`open + missing_measurement`

### 6.3.6 artifact / evidence obligations

`workflow_operands.artifacts` 与 `evidence_requirements.{for_matching,for_submission,for_completion}` 生成 `artifact` 或 `evidence` obligation。三类 bucket 都必须消费：

| bucket | 义务语义 | kind |
|---|---|---|
| `for_matching` | rule applicability / trigger 匹配所需证据 | `evidence` |
| `for_submission` | 提交 / 递交类 artifact 证据 | `artifact` 或 `evidence` |
| `for_completion` | 完成 / 记录 / 报告内容类证据 | `artifact` 或 `evidence` |

artifact binding 不使用旧 `reporting.artifact.*` 白名单；改为 rule_card `artifact_key` 到 sidecar `artifact.*` slot 的确定性映射。

#### artifact alias map

**[v0.4-C-1]** v0.3 把 25 个 `artifact_key` 全部绑到 sidecar slot，其中 8 个无真对应 slot 的 key 被「粗桥接」到最近的现有 slot。**实测推翻这个做法**：sidecar 的 `artifact_requirement_state` 条目（实测 120 万条）qualifiers **不带 `artifact_key`**（只有 `fragment_id` + `carrier_domain`），靠 `qualifiers.artifact_key` 消歧的保险永远走不到 —— 粗桥接会让多个语义不同的 artifact 义务读同一个事实、产出假 `satisfied`，破坏底线层（原则 #5）。

v0.4 收口规则：**一个 sidecar slot 至多被一个 `artifact_key` 绑定**（无消歧手段下的唯一安全规则）。25 个 `artifact_key` 拆两组 —— 17 个有唯一专属 slot 的精确绑定；8 个会与他人共用 slot 的列入 `ARTIFACT_KEYS_NOT_MODELED`，对应义务判 `blocked + artifact_not_modeled_upstream`，不桥接。根因是上游词表缺口（rule_card 引用 25 种 artifact，W0 sidecar 只建模 20 个 slot 且条目无 `artifact_key` 限定词），已登记 DEBT；将来 W0/W1 扩 sidecar artifact 建模后可把这 8 个移回精确绑定。`qual.artifact_field_group` 不是 artifact presence slot，不得作 alias target。`form.mbi1` / `form.mbi2` 虽是 sidecar slot 但无对应 `artifact_key`，不入 map。

```python
# keys 源：rule_cards.json 的 workflow_operands.artifacts[].artifact_key
#         + evidence_requirements.*[].artifact_ids 解析出的 artifact_key（实测 25 个 distinct）。
# values 源：W0_09 §5.2 的 artifact.* slot（实测 sidecar_entries.parquet 确认当前 20 个）。
# 17 个精确绑定 —— 每个 key 独占一个 slot，slot 互不共享。
ARTIFACT_KEY_TO_SIDECAR_SLOT = {
    "certificate.material_compliance": "artifact.certificate.material_or_product",
    "drawing.annotated_location_plan": "artifact.plan.annotated",
    "form.mbi3_or_mbi3a": "artifact.form.mbi3_or_mbi3a",
    "form.mbi4": "artifact.form.mbi4",
    "form.mbi5": "artifact.form.mbi5",
    "notice.detailed_investigation_intention": "artifact.notice.investigation_intention",
    "photo.annotated_defect": "artifact.photo.annotated",
    "proposal.detailed_investigation": "artifact.proposal.detailed_investigation",
    "proposal.repair": "artifact.proposal.repair",
    "proposal.repair_revision": "artifact.proposal.repair_revision",
    "record.inspection_log": "artifact.record.inspection_log",
    "record.nonconformity_correction_sp2": "artifact.record.nonconformity_sp2",
    "report.completion": "artifact.report.completion",
    "report.inspection": "artifact.report.inspection",
    "report.test_result": "artifact.record.test_or_material_witness",
    "statement.mbis_repairs_separated_from_additional_upgrades": "artifact.statement.extra_works_separated",
    "statement.outstanding_order_scope_included": "artifact.statement.scope_and_order_coverage",
}

# 8 个无专属 slot —— 5 个 notice 本会共用 artifact.notice.investigation_intention，
# 3 个本会共用 artifact.record.supervision_log_sp1。sidecar 无 artifact_key 限定词无法消歧，
# 一律判 blocked + artifact_not_modeled_upstream，不桥接、不假 satisfied。
ARTIFACT_KEYS_NOT_MODELED = {
    "notice.representative_appointment_intended",
    "notice.ri_appointment",
    "notice.ri_cessation",
    "notice.ri_temporary_nomination",
    "notice.temporary_ri_nomination_cessation",
    "proposal.supervision",
    "record.site_visit_log",
    "record.supervision_checklist",
}
```

完整性与安全断言、slot 解析（禁止 prefix fallback）：

```python
RULE_CARD_ARTIFACT_KEYS = extract_artifact_keys(rule_cards_json)   # 实测 25 个 distinct
W0_09_ARTIFACT_SLOTS = {
    "artifact.certificate.material_or_product", "artifact.form.mbi1", "artifact.form.mbi2",
    "artifact.form.mbi3_or_mbi3a", "artifact.form.mbi4", "artifact.form.mbi5",
    "artifact.notice.investigation_intention", "artifact.photo.annotated", "artifact.plan.annotated",
    "artifact.proposal.detailed_investigation", "artifact.proposal.repair", "artifact.proposal.repair_revision",
    "artifact.record.inspection_log", "artifact.record.nonconformity_sp2", "artifact.record.supervision_log_sp1",
    "artifact.record.test_or_material_witness", "artifact.report.completion", "artifact.report.inspection",
    "artifact.statement.extra_works_separated", "artifact.statement.scope_and_order_coverage",
}

assert len(ARTIFACT_KEY_TO_SIDECAR_SLOT) == 17
assert len(ARTIFACT_KEYS_NOT_MODELED) == 8
assert set(ARTIFACT_KEY_TO_SIDECAR_SLOT) | ARTIFACT_KEYS_NOT_MODELED == RULE_CARD_ARTIFACT_KEYS   # 25 全覆盖
assert set(ARTIFACT_KEY_TO_SIDECAR_SLOT) & ARTIFACT_KEYS_NOT_MODELED == set()                    # 两组不相交
assert len(set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values())) == 17     # 每 slot 至多一个 key —— 无共享
assert set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values()) <= W0_09_ARTIFACT_SLOTS
assert "form.mbi1" not in ARTIFACT_KEY_TO_SIDECAR_SLOT and "form.mbi2" not in ARTIFACT_KEY_TO_SIDECAR_SLOT

def resolve_artifact_slot(artifact_key):
    if artifact_key in ARTIFACT_KEY_TO_SIDECAR_SLOT:
        return ARTIFACT_KEY_TO_SIDECAR_SLOT[artifact_key]          # 精确绑定
    if artifact_key in ARTIFACT_KEYS_NOT_MODELED:
        return None                                                # → blocked + artifact_not_modeled_upstream
    raise SchemaContractError(f"unknown artifact_key {artifact_key!r} — rule_card 出现 spec 未登记的新 key")
```

binding 条件（仅 17 个精确绑定的 key）：

```text
SidecarEntry.slot_id == ARTIFACT_KEY_TO_SIDECAR_SLOT[artifact_key]
AND value_json canonicalize 后为 truthy / falsy
```

truthy canonicalization：

```python
truthy_values = {True, "true", "present", "submitted", "delivered", "completed", "available", "yes"}
falsy_values = {False, "false", "absent", "missing", "not_submitted", "no"}
```

结果：

- 精确绑定 key，required artifact fact truthy → `closed + satisfied`
- 精确绑定 key，required artifact fact falsy → `closed + violated`
- 精确绑定 key，required artifact missing → `open + missing_artifact_evidence`
- key ∈ `ARTIFACT_KEYS_NOT_MODELED` → `blocked + artifact_not_modeled_upstream`（上游 sidecar 未建模该 artifact，结构性无法验证；不桥接、不假 satisfied）
- key 既不在 map 也不在 NOT_MODELED（rule_card 出现 spec 未登记的新 key）→ `blocked + missing_artifact_mapping`

`required_field_groups` 处理：若 evidence requirement 要求字段组，verifier 必须在 sidecar `qual.artifact_field_group` 或 artifact entry qualifiers 中找到对应字段组；缺失则 `open + missing_required_field_group`。

### 6.3.7 deadline obligations

从 `workflow_operands.deadlines` 生成 `deadline` obligation。

输入字段：

```text
deadline_id, relation, offset_value, offset_unit, time_anchor_key
```

支持 relation：

| relation | 判定规则 |
|---|---|
| `within` | 绑定 duration measure，要求 `observed_duration <= offset_value` |
| `before` | 绑定 event timestamp 与 anchor timestamp，要求 `event_time < anchor_time`；若 baseline 只有 precomputed duration，则要求 `observed_duration <= offset_value` |
| `same_day_as` | 绑定 event date 与 anchor date，要求同一 calendar date；若只有 precomputed boolean sidecar，则 truthy 即 satisfied |

绑定来源优先级：

1. sidecar numeric duration entries：`duration.notification.deadline`、`duration.submission.deadline`、`duration.delivery.deadline`、`duration.site_visit.interval`；
2. sidecar time anchor entries：`time_anchor_key` exact match；
3. `RuleThreshold` 中 `duration.*` measure；
4. measurement `slot_id` / `measure_key` exact。

baseline 不建通用时序引擎。若 relation 需要 timestamp 但只有 duration，可按上表 fallback；若两者均缺失：

```text
closure_status=open
open_reason_code=missing_time_anchor
```

未知 relation：

```text
closure_status=blocked
blocked_reason_code=unsupported_deadline_relation
```

### 6.3.8 exception obligations

若 card.exceptions 非空：

- 每个 exception 生成 `kind=exception`；
- exception triggered 且有证据：`closed + not_applicable` 或 `closed + violated`，取决于 exception 是排除义务还是违反条件；
- exception 语义若无法由 rule_card 结构判断：`blocked + missing_rule_edge`。

baseline 默认：

```text
exceptions 空：不生成 exception obligation
exceptions 非空但结构缺 required fields：blocked
```

### 6.3.9 definition obligations

definition 用于确认术语 / scope / field group 可解释。

- definition slot 有事实或 source quote → `closed + satisfied`
- definition 引用缺失 → `blocked + missing_rule_edge`
- definition 所需事实缺失 → `open + missing_fact`

### 6.3.10 `evaluate_obligation_node(card, obligation_node, fact_index, trigger_active)` / `evaluate_obligation_edges(card, edges, node_obligations, fact_index)`

本节定义 `evaluate_obligation_node(card, obligation_node, fact_index, trigger_active)` 与 `evaluate_obligation_edges(card, edges, node_obligations, fact_index)`。这是闭包验证器最核心的义务源，必须实现。

#### 6.3.10.1 输入

**[v0.3-C-4]** 本节函数签名与 §6.6 伪代码统一：`evaluate_obligation_node(card, obligation_node, fact_index, trigger_active)`；`trigger_active` 是 card-level trigger 聚合结果，node-level `trigger_condition_ids` 仍按本节规则进一步约束。

每个 node 来自 rule_card：

```python
class ObligationNodeDTO(BaseModel):
    obligation_node_id: str
    node_kind: Literal["obligation", "prohibition", "escalation"]
    actor: str
    action: str
    recipient_ids: list[str]
    artifact_ids: list[str]
    deadline_ids: list[str]
    trigger_condition_ids: list[str]
```

每个 edge 来自 rule_card：

```python
class ObligationEdgeDTO(BaseModel):
    source_node_id: str
    target_node_id: str
    relation: Literal["if_failed_then", "if_unable_then"]
```

#### 6.3.10.2 node_kind → ObligationKind

| `node_kind` | `Obligation.kind` | baseline 语义 |
|---|---|---|
| `obligation` | `action`，若 action 属报告字段则 `report_field`，若 artifact_ids 非空也派生 `artifact` 子义务 | actor 应执行 action |
| `prohibition` | `prohibition` | actor 不得执行 / 不得遗漏某禁止事项 |
| `escalation` | `escalation` | 上游失败、不能执行或触发条件成立后升级动作 |

`action` 到 kind 的 refinement：

```python
if action.startswith("submit") or action.startswith("deliver"):
    base_kind = "artifact"
elif "report" in action or action.startswith("include_"):
    base_kind = "report_field"
elif action.startswith("conduct_supervision") or "supervision" in action:
    base_kind = "supervision"
elif "method" in action or action in {"perform_detailed_investigation_method", "conduct_validation_test"}:
    base_kind = "method"
else:
    base_kind = {"obligation": "action", "prohibition": "prohibition", "escalation": "escalation"}[node_kind]
```

#### 6.3.10.3 基础 obligation 生成

每个 node 至少生成 1 条 node-level obligation：

```python
obl = Obligation(
    kind=base_kind,
    obligation_node_id=node.obligation_node_id,
    actor=node.actor,
    action=node.action,
    recipient_ids=node.recipient_ids,
    artifact_ids=node.artifact_ids,
    deadline_ids=node.deadline_ids,
    trigger_dependency_ids=node.trigger_condition_ids,
    source_rule_card_id=card.rule_card_id,
    source_family_id=card.family_id,
)
```

此外：

- 对 `artifact_ids[]`，调用 §6.3.6 artifact binding 生成或合并 artifact 子义务；
- 对 `deadline_ids[]`，调用 §6.3.7 deadline binding 生成或合并 deadline 子义务；
- 对 `recipient_ids[]`，检查 `WorkflowRecipient` 是否存在；缺失为 `blocked + missing_rule_edge`；存在则记录在 obligation，不单独要求事实闭包；
- 对 `method_keys_allowed[]` 非空且 action 表示 method/test/investigation，生成 `kind=method` 义务，绑定 `qual.method_class` 或 measurement `method_class`。

#### 6.3.10.4 node-level closure / satisfaction

node-level obligation 的判定按以下优先级：

1. 若 `trigger_condition_ids` 对应 trigger 聚合为 false：`closed + not_applicable`；
2. 若任一对应 trigger open：`open + depends_on_open_trigger`，`depends_on_open_trigger=true`；
3. 若任一对应 trigger blocked：`blocked + missing_rule_edge` 或继承 blocked reason；
4. 若 node 引用的 artifact / deadline / recipient id 不存在：`blocked + missing_rule_edge`；
5. 若 action 可由 artifact / evidence / sidecar fact 绑定：按绑定结果给出 `closed/open/blocked`；
6. 若 action 是纯专业判断类动作（如 `exercise_professional_judgment`）且 rule_card 只提供 source_quote、无可绑定 fact：生成 `evidence` obligation，要求 evidence_requirement 或 sidecar record；缺失则 `open + missing_fact`，不得默认 satisfied；
7. 若 `node_kind="prohibition"`：找到 prohibited fact truthy → `closed + violated`；找到 falsy → `closed + satisfied`；缺失 → `open + missing_fact`；
8. 若无任何可绑定 artifact / evidence / deadline / slot / measure 且 source quote 存在：`open + missing_fact`，notes 写 `action_not_fact_bound`，不得 satisfied。

**[v0.4-DEBT-073] node 满足通道解析（2026-07-26）**：`action` 是动作词，**不是事实
槽名**，不得再执行 `canonical_slot(action)`。node-level obligation 只消费卡中已声明且能
确定归属到该 node 的满足通道：

1. `slot_role_map[]` 是卡级表、没有 `obligation_node_id` 外键。仅当该卡
   `obligation_graph.nodes[]` **恰有一个 node** 时，`required=true` 且
   `roles[0] == 'evidence'` 的 slot ref 才能确定归属到该 node；
2. 在同一单 node 边界内，`node.artifact_ids[]` 与 `node.deadline_ids[]` 按既有 artifact /
   deadline binding 求值。多 node 卡即使共享 artifact，也不得据此同时关闭多个 node 主义务；
3. `trigger_condition_ids[]` 只控制激活，不能作为动作已完成的证据；`recipient_ids[]`
   只做引用存在性检查，也不能作为满足通道；`definition_reference` / `prerequisite` 角色
   不得冒充 evidence；
4. 普通动作的多个必需通道按合取聚合：任一 blocked → `blocked + unknown`，否则任一
   open → `open + unknown`，全部 closed 后任一 falsy / violated → `closed + violated`，
   否则 `closed + satisfied`。禁止节点只允许唯一 evidence 满足槽；truthy → violated、
   falsy → satisfied，无法唯一定位则缺省拒绝；
5. 卡侧没有可确定满足通道 → `open + missing_satisfaction_binding`。有通道但没有事实仍用
   `missing_fact` / `missing_artifact_evidence` / `missing_time_anchor`；限定符不匹配仍为
   `blocked + qualifier_conflict`。绝不把“查不到”改成 satisfied；
6. node 产物必须用现有结构字段落盘绑定证据：`slot_ref_ids` / `slot_ids` /
   `artifact_ids` / `artifact_keys` / `deadline_ids` / `evidence_fact_ids`，并在 notes 写稳定的
   `satisfaction_bindings=[...]`。不新增 `satisfaction_slot_ref_id`，避免与多通道事实冲突；
7. node identity blueprint 必须把上述 evidence slot（含 qualifier 指纹）灌入
   `slot_bindings`。否则 slot / qualifier 改变判定却不改变 `canonical_identity_hash`，违反
   身份材料完整性。

#### 6.3.10.5 edges 处理

edges 表达义务间条件依赖。verifier 在所有 node-level obligations 初评后处理 edges。

| edge relation | 激活条件 | target 处理 |
|---|---|---|
| `if_failed_then` | source obligation `closed + violated`，或 source threshold / test comparator_result=false | target 激活；若 target 未激活前为 not_applicable，改为按自身事实重新评估 |
| `if_unable_then` | source obligation `open`、`blocked`、或 action fact 表示 unable/cannot | target 激活；source open/blocked 不被 target 消除，仍影响 allow_stop |
| unknown | 无 | source 与 target 均生成 `blocked + unsupported_obligation_edge_relation` audit obligation |

edge target 激活规则：

```python
def evaluate_obligation_edges(card, edges, node_obligations, fact_index):
    nodes_by_id = {
        node.obligation_node_id: node
        for node in card.obligation_graph.get("nodes", [])
    }
    for edge in sorted(edges, key=edge_key):
        if edge.source_node_id not in nodes_by_id or edge.target_node_id not in nodes_by_id:
            add_blocked_edge_obligation(edge, "missing_obligation_edge_target")
            continue
        source_state = summarize_node_state(node_obligations.get(edge.source_node_id, []))
        if edge.relation == "if_failed_then":
            active = source_state.has_violation_or_failed_test
        elif edge.relation == "if_unable_then":
            active = source_state.has_open_or_blocked_or_unable_fact
        else:
            add_blocked_edge_obligation(edge, "unsupported_obligation_edge_relation")
            continue
        mark_target_activation(edge.target_node_id, active, edge.obligation_edge_id)
```

若 target 未激活：生成一条 `closed + not_applicable` audit obligation，`notes="inactive_by_obligation_edge"`。若 target 激活：target 的 artifact/deadline/evidence obligations 必须正常闭包。

#### 6.3.10.6 与其他义务源的去重 / 合并

`obligation_graph` node 可能与 `workflow_operands`、`evidence_requirements`、`threshold_regimes` 指向同一 artifact / deadline / measure。去重规则：

- 相同 `rule_card_id + obligation_node_id + kind + artifact_ids/deadline_ids/measure_keys/slot_ref_ids` 视为同一 obligation；
- node-level obligation 与 evidence requirement 若引用同一 artifact_id，不丢弃 evidence requirement，合并 `evidence_node_refs` 与 `source_quote_ids`；
- 若一个 obligation 来源多个源，`notes` 记录 `sources=[obligation_graph,evidence_requirements,...]`；
- 合并时状态取最保守：`blocked > open > closed`；closed 内若任一 violated，则 satisfaction 为 `violated`。

## 6.4 Fact binding 详细规则

### 6.4.1 fact indexes

verifier 初始化：

```python
slot_index: Dict[str, List[FactAtom]]
measure_index: Dict[str, List[FactAtom]]
carrier_index: Dict[str, List[FactAtom]]
artifact_index: Dict[str, List[FactAtom]]
method_index: Dict[str, List[FactAtom]]
alias_index: Dict[str, List[str]]
```

FactPack 构建必须把以下节点转为 FactAtom：

- `Measurement`：slot / measure fact；`qualifiers_json` parse 为 dict；
- `SidecarEntry`：B 类行政事实；`slot_id` 可为 `artifact.*`、`procedure.*`、`duration.*` 等；
- `ManifestationFlag`：condition manifestation slot；
- `ConditionState.derived_outcomes`：每个 derived flag 与 risk index 展成 fact；
- `DrainageState` / `UBWState` / `FireSafetyState` / `RepairAssessmentState`：高频 bool / enum / numeric fields 展成 fact。

### 6.4.2 canonicalization

```python
canonical_slot(slot_id):
    if slot_id in slot_aliases: return canonical
    return slot_id

canonical_measure(measure_key):
    if measure_key in measure_aliases: return canonical
    return measure_key
```

JSON canonicalization：对象 key 排序、去空白；数值按 Python decimal / float tolerance 处理。

### 6.4.3 target scoping

优先级：

1. fragment-specific fact
2. component-specific fact for fragment.component_id
3. building/world-level sidecar fact
4. global rule fact

如果 rule obligation 有 fragment context，但只找到 building-level fact：

- 若 slot registry 允许 building-level carrier → 可用；
- 否则 `open + missing_fact`。

### 6.4.4 conflict handling

```python
if len(bound_facts) == 0: open
elif all(values equivalent): closed
else: blocked(ambiguous_fact_binding)
```

equivalent 规则：

- numeric：差值小于 `numeric_tolerance`，默认 `1e-9`
- bool/string：完全相等
- object：canonical JSON 相等

## 6.5 `allow_stop` 规则

### 6.5.1 基本规则

```python
allow_stop = (
    open_count == 0
    and blocked_count == 0
    and schema_validation_passed
    and forbidden_source_check_passed
)
```

重要：`violated_count > 0` 不会自动导致 `allow_stop=false`。违反义务说明证据足够显示疑似不满足，报告可以停止并交给人工审查。

### 6.5.2 stop_reason

| 条件 | stop_reason |
|---|---|
| no open/blocked, no violated | `all_applicable_obligations_closed_and_satisfied` |
| no open/blocked, violated > 0 | `all_applicable_obligations_closed_with_violations_for_human_review` |
| open > 0 | `open_obligations_remain` |
| blocked > 0 | `blocked_obligations_remain` |
| forbidden source | `forbidden_reference_truth_detected` |
| schema fail | `schema_validation_failed` |

### 6.5.3 report gate

```python
allow_report_generation = allow_stop
```

若 `allow_stop=false`，LLM 只能输出 “闭包未完成说明”，格式固定：

```text
本次资料闭包验证未通过，不能生成完整辅助审查报告。
未闭合项如下：...
建议人工补充 / 检查资料：...
```

## 6.6 deterministic pseudocode

> ⚠️ **identity-v5 现网键切换增补**：活动 `validate_building_closure` 新增 **keyword-only 必填** `identity_blueprint_catalog` 显式入参（无默认、无回退，缺则 hard-fail），并在组 `ObligationSet` 前执行绑定全集闸（任一义务未绑蓝图 → hard-fail `unbound_live_obligation`）。签名与闸见 `spec_identity_v5现网键切换增补_20260717.md` §5.2 / §6.3 步 8。下方伪代码为 **v1 历史形态**；判定分支 / 状态公式零改，v5 只换关联键与编号。

```python
def validate_building_closure(rule_slice: RuleSlice, fact_pack: FactPack, config: VerifierConfig) -> ClosureValidationResult:
    assert_no_forbidden_sources(fact_pack, rule_slice)

    fact_index = build_fact_index(fact_pack)
    obligations = []

    for card in sorted(rule_slice.candidate_rule_cards, key=lambda c: c.rule_card_id):
        applicability = evaluate_applicability(card, fact_pack)

        if applicability.state == "not_applicable":
            obligations.append(make_scope_not_applicable(card, applicability))
            continue

        if applicability.state == "uncertain":
            obligations.append(make_scope_open(card, applicability))

        trigger_results = []
        for trigger in sorted(card.trigger_conditions.get("items", []), key=lambda x: x.condition_id):
            obl = evaluate_trigger(card, trigger, fact_index)
            obligations.append(obl)
            trigger_results.append(obl)

        trigger_active = aggregate_trigger_logic(card.trigger_conditions.get("logic", "all"), trigger_results)

        if trigger_active is False:
            obligations.append(make_rule_not_applicable_by_trigger(card, trigger_results))
            continue

        for slot_ref in sorted(card.slot_role_map, key=lambda x: x.slot_ref_id):
            if slot_ref.required:
                obligations.append(evaluate_slot_role(card, slot_ref, fact_index, trigger_active))

        for threshold in sorted(card.threshold_regimes, key=lambda x: x.threshold_regime_id):
            obligations.append(evaluate_threshold(card, threshold, fact_index, trigger_active))

        node_obligations = {}
        for obligation_node in sorted(card.obligation_graph.get("nodes", []), key=lambda x: x.obligation_node_id):
            node_out = evaluate_obligation_node(card, obligation_node, fact_index, trigger_active)
            obligations.extend(node_out)
            node_obligations[obligation_node.obligation_node_id] = node_out

        edge_obligations = evaluate_obligation_edges(card, card.obligation_graph.get("edges", []), node_obligations, fact_index)
        obligations.extend(edge_obligations)

        # [v0.4-D-2] §6.3.6 / §6.3.7 显式要求 workflow_operands.artifacts /
        # workflow_operands.deadlines 必须作为独立 obligation 源消费；
        # 早期 §6.6 伪代码遗漏了这两个循环，闭包验证器会少产几百条 obligation。
        for item in sorted(card.workflow_operands.get("artifacts", []), key=lambda x: stable_json_key(x)):
            obligations.append(evaluate_workflow_artifact(card, item, fact_index, trigger_active))

        for item in sorted(card.workflow_operands.get("deadlines", []), key=lambda x: stable_json_key(x)):
            obligations.append(evaluate_workflow_deadline(card, item, fact_index, trigger_active))

        for bucket_name, reqs in sorted(card.evidence_requirements.items()):
            for req in sorted(reqs, key=lambda x: x.evidence_requirement_id):
                if req.required:
                    obligations.append(evaluate_evidence_requirement(card, bucket_name, req, fact_index, trigger_active))

        for exc in sorted(card.exceptions, key=lambda x: stable_json_key(x)):
            obligations.append(evaluate_exception(card, exc, fact_index))

        for definition in sorted(card.definitions, key=lambda x: stable_json_key(x)):
            obligations.append(evaluate_definition(card, definition, fact_index))

    obligations = sort_and_dedupe_obligations(obligations)
    summary = summarize(obligations)
    allow_stop = compute_allow_stop(summary, guard_result=config.guard_result)

    return ClosureValidationResult(
        run_id=fact_pack.run_id,
        obligation_set=ObligationSet(...),
        closure_summary=summary,
        allow_stop=allow_stop,
        allow_report_generation=allow_stop,
        high_risk_items=find_high_risk_items(obligations),
        machine_readable_report=build_machine_report(obligations, summary),
    )
```

### 6.6.1 `sort_and_dedupe_obligations`

> ⚠️ **此为 v1 历史只读**（identity-v5 现网键切换后）：下方 `dedupe_key` tuple 键为 **v1 历史键**（改名 `dedupe_key_v1`，只读、**不接活路径**）。活动去重键已切 v5 = 规范身份哈希 `canonical_identity_hash`，见 `spec_identity_v5现网键切换增补_20260717.md` §6（§6.1–6.3）；**状态合并仍由 v1 `_merge_two`**（只换键，判定语义零改）。

```python
def dedupe_key(o: Obligation):
    return (
        o.source_rule_card_id,
        o.kind,
        o.fragment_id or "",
        o.component_id or "",
        tuple(sorted(o.slot_ref_ids)),
        tuple(sorted(o.slot_ids)),
        tuple(sorted(o.measure_keys)),
        tuple(sorted(o.artifact_ids)),
        tuple(sorted(o.deadline_ids)),
        o.obligation_node_id or "",
        tuple(sorted(o.obligation_edge_ids)),
    )
```

合并规则：

```text
blocked > open > closed
closed: violated > satisfied > not_applicable
lists: stable_unique(sorted)
notes: concatenate with source tags
```

排序键：

```python
sort_key = (
  source_family_id,
  source_rule_card_id,
  kind,
  fragment_id or "",
  component_id or "",
  obligation_node_id or "",
  obligation_id,
)
```

IT-004 deterministic repeatability 要求同一输入重复运行 `obligation_set.json` byte-identical。

### 6.6.2 `find_high_risk_items`

`high_risk_items` 是结构化列表，不是自由文本：

```python
class HighRiskItem(BaseModel):
    obligation_id: str
    severity: Literal["high", "medium", "low"]
    reason: str
    source_rule_card_id: str
    source_family_id: str
    evidence_fact_ids: list[str]
```

判据：

- `closure_status="closed"` 且 `satisfaction_status="violated"` → high；
- `kind in {"threshold", "prohibition", "escalation"}` 且 violated → high；
- `closure_status="blocked"` 且 `blocked_reason_code` in `{unit_mismatch, ambiguous_fact_binding, unsupported_formula}` → medium；
- `closure_status="open"` 且 reason 与 artifact/deadline/evidence 有关 → medium；
- 其他 open → low。

### 6.6.3 `build_machine_report`

LLM 只能基于该结构写报告：

```python
machine_readable_report = {
  "run_id": run_id,
  "world_id": world_id,
  "building_id": building_id,
  "allow_stop": allow_stop,
  "stop_reason": summary.stop_reason,
  "closure_summary": summary.model_dump(),
  "rule_slice_summary": {
    "rule_card_count": summary.rule_card_count,
    "family_count": summary.family_count,
  },
  "obligations": [o.model_dump() for o in obligations],
  "high_risk_items": high_risk_items,
  "open_items": [o.model_dump() for o in obligations if o.closure_status == "open"],
  "blocked_items": [o.model_dump() for o in obligations if o.closure_status == "blocked"],
  "violated_items": [o.model_dump() for o in obligations if o.satisfaction_status == "violated"],
  "source_guard": {
    "forbidden_source_check_passed": True,
    "forbidden_sources": [],
  },
}
```

禁止包含 W2 `expected_verdict`、`projection_status`、`basis_items` 或 evaluator-only table path。

## 6.7 obligation_id deterministic key

> ⚠️ **此为 v1 历史只读**（identity-v5 现网键切换后）：下方 obligation_id 拼串哈希为 **v1 历史编号**（改名 `compute_obligation_id_v1`，只读、**不接活路径**）。活动编号已切 v5 = 规范身份 + 运行信封 `compute_obligation_id_v2`，见 `spec_identity_v5现网键切换增补_20260717.md` §6（§6.1 / §6.2）。

```python
obligation_id = sha256_hex(
    "|".join([
        run_id,
        source_rule_card_id,
        kind,
        fragment_id or "",
        component_id or "",
        ",".join(sorted(slot_ref_ids)),
        ",".join(sorted(measure_keys)),
        ",".join(sorted(artifact_ids)),
        ",".join(sorted(deadline_ids)),
        obligation_node_id or "",
        ",".join(sorted(obligation_edge_ids)),
    ])
)[:24]
```

Display ID:

```text
OBL-<rule_card_short>-<kind>-<hash8>
```

## 6.8 closure artifacts

> ⚠️ **identity-v5 现网键切换增补**：切键后产物版本化——`run_audit` 增身份版本字段（`obligation_set_schema` / `obligation_identity_schema` / `canonical_profile_id` / `identity_catalog_sha256` / `identity_key_policy` / `legacy_v1_key_used=false` 等），`obligation_set.json` 携 `identity_manifest`。见 `spec_identity_v5现网键切换增补_20260717.md` §7 / §4.2。旧缺字段产物按 v1 只读，**不补写 / 不降级重写**（§4.3）。

每次 run 输出：

```text
runs/<run_id>/
  fact_pack.json
  rule_slice.json
  obligation_set.json
  closure_validation_result.json
  auxiliary_review_report.md       # only if allow_stop=true
  incomplete_closure_notice.md     # if allow_stop=false
```

## 6.9 verifier tests

> ⚠️ **identity-v5 现网键切换增补**：验收扩充——新 schema 测试（`obligation_identity_v5` 双哈希 / 碰撞、两审计 channel `structural_scope_audit` / `trigger_aggregation_audit` 判别式）、scope-aware fragment 物化锚，以及 30 楼 fragment 现网路径对账（`allow_stop` 30/30 零翻转 + open/blocked 存在性 + 状态字段逐源零差）。见 `spec_identity_v5现网键切换增补_20260717.md` §9 / §10 步 7 / §10 步 10。旧楼级锚（如 2306 / 2310）保留为 v1 历史锚，**不冒充 fragment 现网锚**。

| test | 断言 |
|---|---|
| `test_blind_inputs` | RuleSlice / FactPack 含禁止字段时 hard fail |
| `test_formula_json_preserved` | 3 个 formula threshold 能读到 `formula_json` |
| `test_formula_handler_pull_test` | `n^2-2n+3` handler 输出确定值 |
| `test_obligation_node_derivation` | 每个 `obligation_graph.nodes[]` 至少生成一条 obligation |
| `test_obligation_edges` | 4 张含 edge 卡生成 edge obligations，关系语义可复现 |
| `test_for_matching_evidence` | `for_matching` bucket 被消费 |
| `test_artifact_alias_map` | `report.inspection` 等 artifact_key 能绑定 sidecar `artifact.*` slot |
| `test_derived_outcomes_fact_atoms` | `ConditionState.derived_outcomes` 展成 FactAtom |
| `test_deterministic_repeatability` | 同输入两次输出 byte-identical |

# 7. agent 三层控制体系

## 7.1 System Prompt

以下为 baseline agent 的系统级常驻规则文本。

```text
你是 evo-agent baseline 的 MBIS 合规审查辅助代理。你的角色是人工审查员的副驾驶，不是最终裁决者。

最高规则：
1. 你只能为指定 building_id / world_id 生成闭包验证情况和辅助审查报告。
2. 你不得输出最终合规裁决，不得宣称“本建筑最终合规/不合规/结案”。
3. 你不得读取、请求、引用或推断 W2 NormativeProjection、expected_verdict、projections.parquet、matched_families.parquet、threshold_evaluations.parquet、basis_items.parquet 或任何 per-building 参考真值。
4. 你必须通过 KG-RAG 获取事实和法规依据。事实来自 WorldBundle / SidecarRuntimeBundle；法规来自法规原文和 rule_card v2；Skill 仅作任务手册，不得覆盖法规。
5. 你不得自行宣布资料已足够。是否可停止必须由确定性闭包验证器给出 allow_stop。
6. 若 closure verifier 返回 allow_stop=false，你只能输出“闭包未完成说明”，列出 open/blocked obligations 和建议补充资料，不得生成完整辅助审查报告。
7. 若 closure verifier 返回 allow_stop=true，你可以基于 verifier 的 machine-readable output 生成辅助审查报告；报告必须保留证据链、规则来源、未满足项、人工复核建议。
8. 任何数字阈值、义务、证据引用必须能追溯到 rule_card / 法规条文 / KG fact node。不得编造。
9. 若发现输入上下文中出现 reference truth 或 evaluator-only 字段，立即停止并上报 forbidden_reference_truth_detected。
10. 输出语言使用中文；法规原文引用可保留英文/繁中原文短句。
```

## 7.2 Skills baseline（Anthropic Agent Skills 协议）

**[v0.4-E-2] 本节 v0.4 集成阶段重写**。v0.4 初版采用 `skill.yaml + content.md`
双文件自创格式（含 `skill_id` / `status` / `origin` / `version` /
`allowed_in_baseline` / `triggers` 等 11 个字段），无业界标准依据。v0.4 集成
阶段对齐 [Anthropic Agent Skills 协议](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)：
**单 SKILL.md** + **frontmatter 仅 `name` + `description` 2 字段** + 业界标准
目录结构。

baseline 必须加载 4 个手工 seed Skill。它们是 LLM 的**指令资产**（任务手册 +
Examples + Guidelines），参与 agent 的流程控制与报告写作，但**不得改变
deterministic verifier 的 obligation、状态或 `allow_stop`**。

### 7.2.0 协议要点

- **目录命名**：`<name>/`，name 小写连字符，≤64 字符，禁含 `anthropic` /
  `claude`；
- **唯一必需文件**：`<name>/SKILL.md`；
- **frontmatter 必需 2 字段**：`name`（同目录名）+ `description`（≤1024
  字符，说"做什么"+"何时用"，禁含 XML 标签）；
- **正文**：建议结构 `Instructions` / `Examples` / `Guidelines` 三段（非
  强制；保持 <500 行，超出用 `references/` 子目录补）；
- **触发机制**：description 语义匹配（不是显式 trigger 白名单）；
- **可选子目录**：`scripts/`（Claude 通过 bash 执行的脚本）/ `references/`
  （补充文档）/ `assets/`（模板 / 图标）；
- **不属于 Skill 层**：权限管理（由 spec D-001 凭据 / hook §7.3 控制）；
  tool 定义（由 §7.5 LLM Tool Interface 独立定义；Skill 内可在指令里 *引用*
  tool 名字，但 tool schema 不在 Skill）。

### 7.2.1 `mbis-building-assessment-workflow`

`mbis-building-assessment-workflow/SKILL.md`：

```markdown
---
name: mbis-building-assessment-workflow
description: Orchestrate one MBIS compliance assessment run for a user-specified building. Use when user asks to "review / assess / closure-verify a specific building (building_id + world_id)". Output: ComplianceAssessmentRun with either auxiliary review report (allow_stop=true) or incomplete-closure notice (allow_stop=false).
---

# MBIS building assessment workflow

## Instructions

Use only for a user-specified `world_id` + `building_id`. Procedure:

1. Validate that the user request names exactly one building. Do not infer a
   building from W2 truth.
2. Create `ComplianceAssessmentRun(run_type="baseline_building_review")`.
3. Call `retrieve_building_facts` tool to build `FactPack`.
4. Call `retrieve_applicable_rules` tool to build `RuleSlice`.
5. Call `run_closure_verification` tool — `allow_stop` is decided here.
6. If `allow_stop=false`, call `finalize_report` with an incomplete-closure
   notice (see `mbis-auxiliary-report-writer` Skill for structure).
7. If `allow_stop=true`, call `finalize_report` with a full auxiliary review
   report.
8. For high-quality reports, before `finalize_report`, also call
   `query_open_obligations`, `inspect_obligation`, `lookup_rule_card`, and
   `lookup_clause` so the report cites real obligation ids and regulation
   text instead of fabricating.

## Guidelines

- Never read or request `NormativeProjection`, `expected_verdict`, W2
  projection tables, or evaluator outputs.
- `allow_stop` is decided by the deterministic verifier — never override it.
- All five hooks (`pre_run_input_guard` / `pre_retrieval_query_guard` /
  `post_retrieval_source_audit` / `post_verifier_stop_gate` /
  `pre_output_language_guard`) are hard gates; do not try to bypass.
```

### 7.2.2 `mbis-fact-kg-retrieval`

`mbis-fact-kg-retrieval/SKILL.md`：

```markdown
---
name: mbis-fact-kg-retrieval
description: Retrieve WorldBundle and SidecarRuntimeBundle facts for a building to build a FactPack. Use when an MBIS assessment workflow needs the fact subgraph before rule derivation. Returns FactPack with slot/measure/carrier/artifact/method indexes. Never includes W2 projection truth.
---

# MBIS fact KG retrieval

## Instructions

Allowed sources:

- `World`, `Building`, `Fragment`, `Component`, `Location`
- State nodes: `DriverState`, `MechanismState`, `ConditionState`,
  `RepairAssessmentState`, `DrainageState`, `UBWState`, `FireSafetyState`
- `Measurement`
- `SidecarRuntimeRecord`, `SidecarEntry`

Procedure:

1. Retrieve the building shell.
2. Retrieve all fragments, components and locations.
3. Retrieve all condition / state nodes; parse
   `ConditionState.derived_outcomes_*_json` into facts.
4. Retrieve measurements; parse `qualifiers_json` into dict qualifiers.
5. Retrieve sidecar entries; do not expose or reconstruct `projection_id`.
6. Build FactAtoms and indexes: `slot_index`, `measure_index`,
   `carrier_index`, `artifact_index`, `method_index`.
7. Run forbidden source audit and fail if any W2 property / table appears.

## Guidelines

- Output must not contain `projection_id`, `expected_verdict`,
  `coverage_status`, `basis_items`, or evaluator-only paths.
- LLM agents trigger this via the `retrieve_building_facts` tool (§7.5.2).
```

### 7.2.3 `mbis-rule-obligation-derivation`

`mbis-rule-obligation-derivation/SKILL.md`：

```markdown
---
name: mbis-rule-obligation-derivation
description: Construct a RuleSlice (candidate rule cards + families + slot/measure/artifact registries + source quotes) for a given FactPack. Use after fact retrieval and before deterministic closure verification. Never decides obligation closure — that is the verifier's job.
---

# MBIS rule obligation derivation

## Instructions

Procedure:

1. Use FactPack slots, measures, artifact slots and component / building
   scope tags to retrieve candidate RuleCards.
2. Expand every candidate card to original rule_card v2 nested shape.
3. Include `threshold_regimes[].formula` from `RuleThreshold.formula_json`
   when present.
4. Include `obligation_graph.nodes[]` and `obligation_graph.edges[]`.
5. Include all evidence requirement buckets: `for_matching`,
   `for_submission`, `for_completion`.
6. Include source quotes with `source_quote_id` and `quote_local_id`.

## Guidelines

- Never include W2 family verdicts, projections, threshold evaluations or
  basis items.
- This skill constructs `RuleSlice` only — it does not decide obligation
  closure; the deterministic verifier does.
- LLM agents trigger this via the `retrieve_applicable_rules` tool (§7.5.2).
```

### 7.2.4 `mbis-auxiliary-report-writer`

`mbis-auxiliary-report-writer/SKILL.md`：

```markdown
---
name: mbis-auxiliary-report-writer
description: Write a non-final auxiliary review report (or incomplete-closure notice) from a ClosureValidationResult. Use after deterministic closure verification. Never says "最终裁决/合规/不合规/结案"; always cites real rule_card and evidence facts. Output is a markdown file approved by pre_output_language_guard hook.
---

# MBIS auxiliary review report writer

## Instructions

Input: `ClosureValidationResult.machine_readable_report` only.

Rules:

1. If `allow_stop=false`, write only an incomplete-closure notice. Do not
   write the full report.
2. If `allow_stop=true`, write an auxiliary review report using the fixed
   structure below.
3. Preserve every high-risk / violated item and cite its rule card, clause
   and evidence facts. Use `lookup_rule_card` and `lookup_clause` tools
   (§7.5.2) to fetch real regulation text; never fabricate clause numbers
   or quote text.
4. Say "疑似未满足 / 建议人工复核", not "最终不合规".
5. Never mention or infer W2 `expected_verdict`.

## Guidelines

- LLM agents trigger this via the `finalize_report` tool (§7.5.2); the tool
  runs `pre_output_language_guard` (§7.3.6) on the submitted markdown.
- If the report fails the guard, rewrite and retry; after 3 failures the
  orchestrator falls back to a deterministic template (§7.5.5).

## Fixed report structure

```text
# MBIS 辅助审查报告（非最终裁决）

## 1. 报告声明
## 2. 建筑与资料范围
## 3. 适用法规 / rule card 切片
## 4. 闭包验证摘要
## 5. 逐项义务闭包表
## 6. 疑似未满足 / 风险项
## 7. 证据链与来源
## 8. 建议人工复核点
## 9. 限制与未覆盖范围
```
```

## 7.3 Hooks

### 7.3.1 hook event list

| hook | 时机 | hard/soft |
|---|---|---|
| `pre_run_input_guard` | 创建 run 后、检索前 | hard |
| `pre_retrieval_query_guard` | 每次 KG query 前 | hard |
| `post_retrieval_source_audit` | FactPack/RuleSlice 构造后 | hard |
| `post_verifier_stop_gate` | verifier 返回后 | hard |
| `pre_output_language_guard` | LLM 输出前 | hard |

### 7.3.2 `pre_run_input_guard`

检查：

```text
- 输入必须有 building_id / world_id
- 输入不得包含 W2 table path 或 forbidden property name
- 输入不得要求“直接给最终合规裁决”
```

### 7.3.3 `pre_retrieval_query_guard`

拒绝任何包含以下片段的查询：

```regex
NormativeProjection|ExpectedVerdict|ProjectionFamilyEval|ThresholdEval|ReportBasisItem
expected_verdict|selected_family|projection_status|basis_items|coverage_status
required_world_core_slots|required_measurement_slots|required_qualifier_slots|required_sidecar_interfaces
matched_component_refs|matched_measurement_ids
projections\.parquet|matched_families\.parquet|threshold_evaluations\.parquet|basis_items\.parquet
```

注意：`RuleThreshold` 是允许 label；`ThresholdEval` 是禁止 label。

### 7.3.4 `post_retrieval_source_audit`

对 FactPack / RuleSlice：

```python
forbidden_names = AGENT_FORBIDDEN_PROPERTIES | AGENT_FORBIDDEN_LABELS
if any(name in serialized_payload for name in forbidden_names):
    raise SecurityError("forbidden_reference_truth_detected")
```

白名单例外：`world_id`、`fragment_id`、`severity_band` 作为 W0 事实字段允许；`applicability_state` 作为 verifier-owned 字段允许，但不得来自 W2。

### 7.3.5 `post_verifier_stop_gate`

```python
if not closure_result.allow_stop:
    force_template("incomplete_closure_notice")
else:
    allow_template("auxiliary_review_report")
```

LLM 不能覆盖 `allow_stop`。

### 7.3.6 `pre_output_language_guard`

禁止话术（**断言式**，下表为被阻断的核心子串）：

```text
最终裁决
最终合规
最终不合规
结案
本建筑已合规
本建筑不合规
according to expected_verdict
based on NormativeProjection
```

若**断言式**出现，输出阻断并要求重写。

**[v0.4-D-1] 否定语境豁免**：附录 A.4 显式列出"允许替代表述"，含否定式免责声明
（如"本报告为人工审查辅助材料，非最终裁决…"）；§7.4 / 附录 C 强制的报告
抬头也是 "# MBIS 辅助审查报告（非最终裁决）"。因此禁止话术若**直接紧贴**在下列
**否定前缀白名单**之后出现，属合规免责声明，**不阻断**：

```text
非           # "本报告……非最终裁决"
不是         # "你不是最终裁决者"
不构成       # "不构成最终合规裁决"
不输出       # "不输出最终合规裁决"
```

判定算法：对每条禁止话术 `phrase`，在输出文本里每一次出现 `phrase` 的起点位置 `pos`，
检查 `text[:pos]` 是否以白名单中任一前缀结尾。落入白名单的命中放行；其它命中阻断。

白名单约束：

1. 每个前缀必须在 `report_writer` / `system_prompt` 中存在**直接紧贴禁话术**的真实文案。
2. 间接修饰（如"不得输出最终合规裁决"里"不得"中间隔了"输出"）由更近的前缀
   ("不输出") 救；不需要把"不得"也加进白名单。
3. 文案不含禁话术（如"不替代人工审查员最终判断"，"最终判断"不在禁话术列表）
   则根本无需豁免。
4. 实现处 `agent/hooks.py:OUTPUT_NEGATION_PREFIXES`，每条由
   `test_agent_control.test_pre_output_language_guard_allows_each_negation_prefix`
   独立单测覆盖。

新增前缀必须同时满足上述 4 条；不允许预防性扩展。

口径：§7.3.6 拦截的是 **断言式最终裁决**，不是 **声明本报告非最终裁决**。

判定算法：对每条禁止话术 `phrase`，在输出文本里找 `phrase` 每一次出现的
起点位置，检查该位置紧邻的前置最长非空白前缀是否落在否定前缀白名单内。
落入白名单的命中放行；其它命中阻断。

实现位置：`agent/hooks.py` 的 `OUTPUT_NEGATION_PREFIXES`。

口径：§7.3.6 拦截的是 **断言式最终裁决**，不是 **声明本报告非最终裁决**。

## 7.4 报告格式（report contract v3）

**[v0.4-E-3] 本节 2026-07-13 激活报告契约 v3**。v2 已把模型职责收窄到唯一
叙述槽位；三臂 D20 与语义盲审进一步坐实 Markdown 启发式切分、禁话术前缀
白名单及“模型只吐纯文本、不真调工具”是结构性不稳定源。因此 v3 只升级提交
格式、逐点证据绑定、叙述内容闸与审计，不改确定性报告骨架、判定权或 blind 边界。

`report_contract_version = 3`。报告成品仍由程序依据闭包验证产物确定性渲染骨架，
并把通过 §7.5.9 的结构化点列渲染后插入唯一指定槽位。LLM 不得生成、覆盖、
删改或重排骨架中的权威字段。真 tool call 与模型纯文本合成路径必须归一为同一
对象信封：

```json
{"points":[{"text":"...","evidence_aliases":["O1","R2"]}]}
```

程序渲染的骨架至少包含：

1. 按 `allow_stop` 分支确定的标题与文档类型；
2. 非最终裁决/不替代人工复核的免责说明；
3. run、building、source scope；
4. 权威闭包概览（total/closed/open/blocked、状态分布及 `allow_stop`）；
5. 未闭合项表或"open/blocked 为 0"的确定性确认；
6. violated/high-risk 项及其程序计数；
7. 法规引用、rule card 短引文与事实证据引用；
8. LLM 分析节槽位；
9. 必要的人工复核提示。

所有标题、免责文本、表格行、计数、义务状态、`allow_stop`、法规引用及事实
引用均从程序持有的权威对象渲染；LLM 只提供结构化分析点。权威计数不得从 LLM
文本提取、汇总或回填。v3 的 `text` 限单行且按字面转义，不能注入 H1/H2、
列表、表格或代码围栏来伪造权威章节。

### 7.4.1 allow_stop=true

程序输出完整的"辅助审查报告"骨架。LLM 槽位节名固定为：

`分析与建议（模型生成）`

该节可以解释已列示风险、证据之间的关系和人工复核优先级，但不得作最终裁决，
不得引入证据包外实体或事实。

### 7.4.2 allow_stop=false

程序输出"不完整闭包告知书"骨架，明确"本次资料闭包验证未通过，不能生成完整
辅助审查报告"，并确定性列示 open/blocked 项与建议补充/检查的资料。LLM 槽位
节名固定为：

`未闭合原因与补充资料建议（模型生成）`

该分支成品不得使用完整报告标题，不得包含暗示闭包已通过或报告已完整生成的
措辞；模型分析只能解释未闭合原因并提出与证据包相连的补充资料建议，不得冒充
完整报告。

### 7.4.3 版本适用范围与确定性点列渲染【v0.4-E-3】

`report_contract_version=3` 由 LLM 组合报告支线的 `run_audit` 写入；确定性地板档
（无 LLM 主链）仍按 v1 报告形状运行并写 `report_contract_version=1`。未带版本号
的历史产物按 v1 解释，不回填新审计字段；v2 历史产物继续按 v2 的四叙述字段与
旧拒码解释，不回填 v3 六个提交审计字段。

两条 v3 提交路径只在来源标记上不同：真 tool call 直接接收上述对象信封；合成
路径须按 §7.5.3/§7.5.9 的单围栏严格文法解出同一对象信封。内容接纳后、别名
展开前的规范对象是审计与哈希对象。程序按提交顺序固定一点一行渲染：

```markdown
- {转义且展开合法别名后的 text}（证据：[R2:真实ID]）
```

正文中已合法绑定的裸写或方括号别名由 `expand_narrative_aliases` 就地展开为
`[O1:真实ID]`；尾部只列该点结构绑定中未在正文合法展开的补充别名，无补充时
省略尾部。点序和别名序保持不变；`[O1:xxx]` 等伪展开不解释、不采信，整块按
字面 Markdown 转义，相应真实绑定仍在尾部展示。报告骨架、权威字段及标题不因
点列内容改变。评测器须按“版本号 + 对应版本审计字段”成对消费，v1/v2/v3
禁止跨版本混算（详见 §7.5.7）。

### 7.4.4 消费者可读性结构【v0.4-E-4，2026-07-23 新增】

**动机**：v3 骨架把全部 open/blocked 义务逐条列入未闭合项表，实测单栋报告
1200+ 行、其中未闭合项表 + 人工复核提示占 70-82%、纯行级 id 倾倒，答辩/接手者
无法在合理时间定位主要结论（消费者验收契约 A/D 门失败）。本小节在**不删除、
不重排、不改任何权威字段**的前提下增补可读性结构；§7.4 九项骨架及其权威性
一字不改，本节只规定**呈现形态**。

**E-4.1 主视图 + 完整台账二层**：未闭合项表（骨架第 5 项）与人工复核提示的
**完整逐条内容仍程序渲染、一条不少**，但组织为二层：

1. **主视图**：在完整表之前，程序确定性渲染一个**聚合概览**——按
   `(source_rule_card_id, closure_status, reason_code)` 分组，每组一行显示
   计数 + 目标范围摘要 + 稳定编号（见 E-4.2）。聚合与计数**全部程序完成**，
   不经 LLM，不改判定。
2. **完整台账**：原逐条未闭合项表、疑似未满足表与人工复核提示**整体置于 HTML
   `<details>` 折叠块内**（默认收起、可展开），或等价地移入同报告的"详细台账"
   章节。完整表**留在同一文件**，逐条内容与权威字段与折叠前逐字节一致。
   **⚠️PDF/打印导出注意（2026-07-23 codex 审出）**：HTML→PDF 打印关闭状态的
   `<details>` 通常只输出 `<summary>`，折叠内容可能不进 PDF。故 **PDF 消费路径须
   先展开全部 `<details>` 再导出**（或用"详细台账"章节形态）；markdown 源文件与
   JSON 产物始终含完整逐条内容，纯文本/程序消费不受影响。此为**已知导出限制**，
   不影响完整留存（数据在源文件与 JSON 里齐全）。

判据：折叠/聚合后，主视图（`<details>`/详细台账之外）应能让读者不展开完整表
即回答"是否闭包 / 各态计数 / 前 N 原因 / 前 N 复核动作 / 去哪下钻"。

**E-4.2 稳定展示编号 `display_ref`**：报告面向人的每条义务引用**增设**纯展示
编号 `display_ref`，由 `canonical_identity_hash`/`dedupe_key`（或规范语义键）
**确定性派生、不含 `run_id`**，跨批稳定（如 `OB-<短哈希>`）。原始产物 JSON
**继续保留完整 `obligation_id`**；`display_ref` **仅用于人读呈现，绝不**
替代 `obligation_id` 成为身份键、绝不进入 dedupe/identity 计算（identity-v5
不变）。每报告落一份 `display_ref → obligation_id → canonical_identity_hash`
映射供下钻。运行期哈希 `obligation_id` 从人读主视图移除、保留在映射与完整
台账/JSON 中。

**E-4.3 规则内容确定性呈现**：报告"法规引用与证据"节已确定性渲染每个 `[Rn]`
的权威条文原文。模型分析点**不得复述或转译规则卡要求内容**（实测自撰释义
11.6% 严重错位，EXP-015 第九轮）；模型点引用 `[Rn]` 仅作指针 + 描述事实
限制/缺口/风险/复核动作。规则要求内容一律以"法规引用与证据"节的程序渲染
原文为唯一来源。此约束由 §7.5.9 叙述内容闸 + 提示词共同承载；模型点若仍
夹带规则释义，**渲染层不负责纠正语义**（渲染层只忠实展开绑定），故本约束
的达标以受控批实测的严重错位率为准，不以"提示词已写"为准。

**E-4.4 不变性要求**：E-4.1/E-4.2 是**渲染层改动**，可用"离线重渲染"验证
（从存盘 `closure_validation_result` + `accepted_payload` 重渲染，除报告文本
与新 `display_ref` 映射外所有既有 JSON 逐字节不变）+ 全链不变性（`allow_stop`/
`closure_summary`/逐义务语义键/eval 指标全部与冻结权威一致）。报告文本 hash
允许变，判定/义务/阅卷数字不允许变。

## §7.4.5 报告契约 v4：无自由文本的结构化提交（Gate C 严格 0 严重错释）

**[v0.4-E-5] 2026-07-23 新增（codex gpt-5.6-sol 决策门推荐 A+，session 019f8ca3 后续讨论）**。

**病灶**：报告契约 v3 允许模型提交任意 `text` 自由文本，程序只验证别名与状态一致性，
**无法验证自然语言是否正确解释了规则**。EXP-015 实证：模型自撰规则释义会把罐头释义
贴错相邻别名（"完成报告含材料证书"贴到"检查范围"规则）。提示词修复（option a）把
真·规则内容转译从 25% 压到 6%，**但不能归零**——只要模型能写规则散文，错释义就可能
残留。消费者验收 Gate C（叙述语义可信）因此无法判严格绿。

**根治原则**：**让模型失去生成规则语义的能力**。规则、状态、原因、证据值、可展示句子
**全部由程序从权威对象确定性组装**；模型只提交"选择与分类"，不提交任何需 NLP 判真假
的句子。错释义按构造不可能存在。

**E-5.1 v4 提交契约**：模型每点只提交四字段，`additionalProperties: false`：

```json
{
  "contract": "report_contract_v4",
  "points": [
    { "obligation_alias": "O12", "analysis_code": "EVIDENCE_GAP",
      "selected_fact_aliases": ["F7"], "review_action_code": "OBTAIN_MISSING_EVIDENCE" }
  ]
}
```

**严格禁止字段**（Schema 闸整篇拒绝）：`text` / `gap_description` / `rule_alias` /
`rule_summary` / `reason_code` / `status` / `observed_value` / `threshold` / 任意额外字段。

**E-5.2 字段权力划分**（表内"程序派生/权威"的一律不接受模型输入）：

| 内容 | 来源 | 模型 |
|---|---|---|
| obligation | 模型从证据包选 `O*` | 能选、不能造 |
| rule card / rule quote | 程序经 O→source rule 派生 / 权威法规辑录 | 不能 |
| closure status / reason_code | closure result / obligation 权威字段 | 不能 |
| fact 值/slot/unit | FactPack | 不能 |
| selected facts | 模型从**该 O 的允许集合**选子集 | 只能选子集 |
| review action | 有限枚举 + 兼容性校验 | 有限选 |
| 最终中文句子 | 确定性模板 | 不能自由撰写 |

**E-5.3 `analysis_code` 不得成为第二套判定**：它只表报告组织意图（如
`EVIDENCE_GAP`/`AMBIGUITY_REVIEW`/`APPLICABILITY_REVIEW`/`MEASUREMENT_REVIEW`），
**程序必须校验它与权威 `status + reason_code` 的兼容矩阵**（如 `missing_measurement`
才允许 `MEASUREMENT_REVIEW`），不匹配整篇拒绝——不能让模型经 analysis_code 重定义状态。

**E-5.4 四阶段原子接纳**（保持 v3 整篇原子接纳，更易证明）：
①**Schema 闸**：字段类型/枚举/数量/`additionalProperties:false`，彻底拒绝自由文本。
②**关系闸**：`obligation_alias ∈ 本包 O 别名`；`selected_fact_aliases ⊆ 该 O.fact_aliases`；
  action/analysis code 与权威 reason/status 兼容；禁重复 O；R 别名始终经 O→rule 派生。
③**全篇预渲染**：内存中解析全部 O/R/facts/quote/模板，**任一条目缺权威映射/模板/quote
  → 整篇不接纳、进确定性 fallback**，不局部渲染。
④**一次性提交**：schema+关系+全篇渲染+输出守卫全过，才同时写 `accepted_payload`/
  `accepted_payload_sha256`/`accepted_point_count`/分析槽位/audit。

**E-5.5 确定性渲染（[v0.4-E-5c] 2026-07-23 聚合修订，codex 设计商议定稿）**：
每点**先完整解析**全部权威对象（状态/原因/证据/quote/模板；任一失败仍整篇
fallback，E-5.4③ 原子性不变），随后**确定性聚合展示**——按语义四元组
`(status, analysis_code, reason_key, review_action_code)` 聚组：主视图每组三行
（组标题+计数 / 义务入口清单 / 共享的状态·原因·动作各一次），逐义务明细（所选
证据+法规逐字引文）折进组内 `<details>`。组序 violated→open→blocked；**义务入口
与分片按提交顺序，折叠明细按 `rule_card_id`→提交顺序**（两处排序刻意不同：入口
保模型选点次序，明细便于按卡对照）；单组成员 >8 按同签名确定性分片，
**绝不为降组数跨签名合并**；跨规则卡
的组只是"同状态/同原因/同处置组"，**法规语义仍逐义务展示**（每个 O 紧邻自己的
R 与逐字引文，防"共享法规要求"视觉误导）。动机：A 门实证逐点展开形态 24 点批
主视图 ~325 行/重复 ~30%（硬门 180 行/5%），聚合后 ~152 行/≤3%。配套：评估范围
的 family 明细表在 v4 收官形态折叠（主视图留一行索引）；E-5.3 兼容矩阵补
**status↔reason 维度**（原因码只允许出现在其所属状态，违者整篇拒绝）。
渲染层次仍全部来自权威对象与审定模板：当前状态（来自 closure）/ 原因
（`reason_code → 中文模板`）/ 现有证据（FactPack）/ 建议动作（经兼容校验的
action code）/ 法规依据（逐字取程序辑录权威条文）。**⚠️ reason_code 中文模板只
解释"系统为何 open/blocked"，不得偷渡规则卡释义**：可以
`missing_artifact_evidence → 尚未取得用于核验该义务的材料证据`；**不可以**
`→ 尚未取得规则要求的材料证书`（后者又在声称具体规则要求）。

**E-5.6 中文规则释义（可选）**：若消费者必须看中文规则释义，新增**人工审定、版本化**的
`authoritative_plain_zh`（字段：`rule_card_id`/`source_quote_sha256`/`authoritative_plain_zh`/
`review_status=approved`/`translation_version`）；**只有 quote hash 完全匹配且 approved 才
展示，否则只展示英文原文**。绝不在报告运行期让模型翻译规则。

**E-5.7 不变量（写入红线）**：报告中任何关于**法规要求/义务状态/阈值/事实值/原因**的
陈述，必须由权威运行产物或经审定静态模板生成；**模型输出不得作为这些内容的数据源**。
判定权红线不变（review action 只产"建议复核/补证"措辞，不得升级为 satisfied/violated；
缺权威映射 fail-closed）。

**E-5.8 验收**：v4 批跑逐点离线核对**模型提交物是否含任何规则语义句子**（应为 0，
按构造）；严重错释义应**结构性归零**（非靠免责声明）；判定层不变性（同 v3，20/20）；
消费者可读性不劣于 v4 前（Gate D 盲测复跑）。

**E-5.9 激活与版本冻结（[v0.4-E-5b] 2026-07-23 实现期定案；copilot gpt-5.6-sol
九轮审核门收敛落地 ec6fe95；本节措辞经 codex gpt-5.6-sol 对照实现逐条校正）**：

1. **激活方式**：环境变量 `EVO_REPORT_CONTRACT=v4` 门控（其余取值一律落 v3）；
   缺省仍选择 v3 契约，v3 提交与渲染契约保持兼容（共享/v3 引导措辞有非语义性修订）。
2. **版本冻结（红线级）**：契约版本在**会话创建时冻结一次**进
   `LLMSessionState.contract_version`，会话内以它为唯一权威：系统提示词、工具
   schema、证据包 payload、提交引导、格式/共享回执、提交分派、守卫标签与回退渲染
   一律读冻结值。**禁止会话内业务路径重读环境**——运行中环境翻转曾可使 v4 会话
   接纳 v3 自由文本而终稿仍标 v4（审核实证），突破 E-5.7 不变量。边界澄清：各选择
   函数保留 `None→读环境` 兜底**仅供会话外场景**；外层 RunOrchestrator 初始审计
   版本另读一次环境，但终值由会话冻结值回填覆盖；接纳稿渲染分派检查
   `accepted_payload.contract`——在线不变量（v4 会话只可能接纳 v4 载荷）保证其与
   冻结值恒一致。
3. **分派按冻结版本，不看提交物自述**：通过共享格式层（遗留输入/解析错误在此先拒）
   的所有提交，在 v4 会话下一律进 v4 闸，以 `wrong_contract` / `missing_fields` /
   `additional_properties` 等拒绝码拒绝非契约形状；禁止按 `payload.contract` 分派
   （模型可借 v3 形状绕闸）。
4. **回退稿版本一致性**：v4 会话的确定性回退稿与二次守卫降级稿仍标 v4（版本表达
   "会话契约"而非"是否接纳"）；audit、report kind、报告横幅、降级稿各处必须同版本。
5. **B 门一致性闸**（`check_report_authority`，硬失败判定器）：
   - 核验对象＝按目录序**最新一个含 closure 产物**的 run；产物一致性以
     `run_audit` 为权威。
   - `llm_narrative_accepted` 必须为**显式布尔**（缺失/类型异常＝硬伤，不得默认
     当未接纳——混合批中会形成空核假绿）。
   - audit 称接纳 ⇒ 载荷必须存在、非空、顶层恰含 `contract+points`、逐点恰四字段
     且类型正确；audit 版本缺失/未知、版本与载荷形状矛盾 ⇒ 硬伤失败。
   - **点数/SHA 纵深校验**（E-5.4④ 的消费端闭环）：载荷点数必须等于 audit
     `accepted_point_count`，载荷 canonical 哈希（sort_keys+紧凑分隔+utf-8）必须
     等于 `accepted_payload_sha256`；缺字段或不符 ⇒ 硬伤失败。
   - 无采纳叙述（合法回退）＝空核**明示**，计数仍验、不算失败但不计入绑定核验；
     全批零绑定/全批跳过 ⇒ 非零退出，禁止宣绿。
6. **离线重渲染闸**（`offline_rerender_report`，fail-closed 渲染工具——语义与 B 门
   **有意不同**：它负责安全再现报告，硬失败判定交给 B 门）：
   - 遍历**全部** run 重渲染；`llm_narrative_accepted` 非显式布尔 ⇒ 该栋计失败。
   - v4 形状载荷渲染前必须重过 `validate_submission_payload_v4`（在线等价闸）；
     校验失败、版本矛盾（落盘 4 + v3 形状）、点数/SHA 不符 ⇒ **封闭降级**确定性
     叙述且不标模型接纳，禁止把 v3 自由文本以 v4 标签渲染（历史兼容：v4 形状铁证
     优先于 hardcoded-3 时代的错误落盘值）。
   - 单栋处理异常 ⇒ 批以非零退出；零渲染（空批/错路径）⇒ 非零退出。

**[v0.4-E-1] 本节为 v0.4 集成阶段新增**。v0.4 初版 §7.1-§7.4 把 Skill 当作 LLM
的"操作手册"看待（参考 spec §7.2 4 个 Skill 的 markdown 描述），但未正式定义
LLM 如何**主动调用 deterministic 函数**获取数据 / 触发闭包验证 / 写报告。
v0.4 初版集成出来的 baseline 因此只能"deterministic backbone + 模板报告"，
**不是 user 期望的"LLM 作为大脑做分析编排"**。

本节正式定义 LLM tool interface，把"LLM 调函数获取数据"作为 baseline 一等公民
能力，跟 hook（hard gate）和 Skill（指令资产）形成清晰三层：

**[v0.4-E-3] 2026-07-13 激活补充**：本节所有报告提交、叙述闸、fallback、
审计与 evaluator 识别以 report contract v3 为现行语义；v1/v2 只作历史解释。

```
┌─────────────────────────────────────────────────────┐
│  Skill (§7.2)：指令资产 (SKILL.md)                  │
│    给 LLM 看的任务手册 + Examples + Guidelines       │
│    LLM 读完知道"该按什么流程做事"                    │
└─────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  LLM Tool (§7.5)：可调用函数 (OpenAI / Anthropic)   │
│    LLM 主动调，拿数据 / 触发动作                     │
│    每次 tool 调用过 hook 守卫                        │
└─────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  Hook (§7.3)：hard gate                              │
│    pre_*/ post_* 在 tool 入参 / 返回处守卫           │
│    LLM 不可绕过                                      │
└─────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│  Deterministic backbone (§5.2 / §6)                  │
│    retrieval / closure / report_writer 真实实现     │
│    allow_stop 唯一权威 = 闭包验证器                  │
└─────────────────────────────────────────────────────┘
```

### 7.5.1 设计原则

1. **LLM 是大脑、不是统治者**：LLM 通过 tool 编排顺序 + 提交结构化**分析点列**
   （契约 v3，§7.4）；`allow_stop` / `closure_status` /
   `satisfaction_status` 仍由 deterministic verifier 决定（§1.0 原则 1），
   LLM 不可覆盖。
2. **tool 协议中立**：tool schema 用 OpenAI function calling 格式（业界事实
   标准）；同一套 tool 可被 OpenAI / Anthropic / Ollama 兼容协议直调，也可
   一层封装成 MCP server 给 Claude Desktop 用。
3. **每个 tool 是 deterministic 函数的可调用入口**：tool 不在 LLM 侧做决策，
   只把 §5.3 / §5.4 / §6.6 已有的 deterministic 函数包装成可被 LLM 调度的
   接口；同时给 LLM 看到的是**摘要 / 子图 / 原文**而不是完整对象（防 context
   爆 + W2 泄漏风险）。
4. **hook 全程守卫**：每次 tool 输入过 `pre_tool_call_guard`（复用 §7.3.3
   `pre_retrieval_query_guard` 的 forbidden 字段检查）；每次 tool 返回过
   `post_tool_result_audit`（复用 §7.3.4 `post_retrieval_source_audit` 的
   forbidden_names 拦截 + §2.2.3 二次防线 strip）。
5. **deterministic fallback 兜底**：LLM 卡住 / 超循环上限 / 提交格式或内容
   过不了 §7.5.9 时，程序骨架照常渲染、槽位改填确定性叙述模板，保证
   run 不失败（§1.0 原则 5）；骨架与权威表格不因叙述失败降级或重算。

### 7.5.2 baseline tool 清单（11 个）

11 个 tool 分两组：**主流程 5 个**（任何 run 必经）+ **KG 检索深入 6 个**
（让 LLM 真的能看到法规原文 / 义务详情 / 子图）。

#### 7.5.2.1 主流程 5 tool

| tool name | 入参 | 返回 LLM 摘要 |
|---|---|---|
| `retrieve_building_facts` | （无） | fact_count / by_carrier_type / top_slots / source_tables（FactPack 摘要） |
| `retrieve_applicable_rules` | （无） | candidate_rule_card_count / family_count / family 分布 / slot/measure/artifact 数（RuleSlice 摘要） |
| `run_closure_verification` | （无） | total / closed / open / blocked / 各 reason count / allow_stop（ClosureValidationResult.closure_summary） |
| `query_open_obligations(limit)` | limit | top-N open 义务的 id 列表 + rule_card_id + kind + open_reason |
| `submit_analysis(points)` | `{"points":[{"text":...,"evidence_aliases":[...]}]}` | `status=analysis_received` + `report_contract_version=3` + `accepted_point_count`；只提交模型分析点列，触发 §7.5.9；重复提交幂等返回 `analysis_already_accepted` |

**[v0.4-E-3]** 新 system prompt、Skill 与 tool schema 只暴露
`submit_analysis(points)`。旧字符串字段 `analysis_markdown` 与旧工具
`finalize_report(report_markdown)` 均为迁移期只识别、不解析、不接纳的 legacy
输入：命中即返回 `legacy_input_unsupported` 结构化格式回执并记录
`deprecated_submission_input` 事件；除 `empty_points` 特例外，它会占用本 run
唯一一次实质格式修复预算，但不增加 `llm_narrative_attempts`，也不得再映射为
叙述候选。两旧入口不得重新暴露给新提示词。

#### 7.5.2.2 KG 检索深入 6 tool

| tool name | 入参 | 返回 LLM 摘要 |
|---|---|---|
| `inspect_obligation(obligation_id)` | obligation_id（首 12 字符前缀亦可） | 单条义务全字段（不含 §2.2.3 W2 字段） |
| `lookup_clause(clause_id)` | clause_id | 法规章节原文（heading + text，text 截断到 3000 字） |
| `lookup_rule_card(rule_card_id)` | rule_card_id | 单卡核心字段 + 所有 source_quote 原文 + cited_clauses |
| `search_regulation(query, top_k)` | query / top_k≤20 | 法规 fulltext 检索 top-K 命中（含 score / preview 300 字） |
| `query_fragment(fragment_id)` | fragment_id | fragment + 关联 component / location / state_counts / conditions |
| `get_facts_by_slot(slot_id, top_k)` | slot_id / top_k≤50 | 该 slot 的具体 fact 列表（value_json / unit / qualifiers / carrier） |

### 7.5.3 tool 调用契约

每个 tool 接受 JSON 入参 + 返回 JSON 字符串，符合 OpenAI / Anthropic
function calling 协议。返回 JSON 结构约定：

- **正常返回**：直接返回业务数据（dict / list）的 JSON。
- **错误返回**：`{"error": "<人话错误说明>"}`。LLM 收到 error 应自行决定补救
  （换参数 / 跳过 / 终止）。
- **next-action hint**（推荐）：复杂 tool 返回 `{"data": ..., "next_actions":
  ["建议下一步用 lookup_rule_card 取法规原文"]}`，帮助小模型推进流程。

**[v0.4-E-3] 提交协议特例**：真 tool call 的 `args` 与合成路径最终解出的值
必须都是 `{"points":[...]}` 对象信封。合成路径只接受一个独占行、已闭合的
Markdown 代码围栏；围栏外仅空白，语言标记只能为空或小写 `json`；围栏内只
允许一个可被严格 `json.loads` 完整消费的 JSON 值，任意层重复 key、尾随 token、
JSON5、注释、尾逗号、裸数组、从散文抓子串或自动修补一律拒绝。解析成功后与真
tool call 进入同一载荷校验器；两路径不得保留不同信封或不同接纳语义。精确文法、
Schema 与多错顺序见 §7.5.9 及 §7.5.13 引用的冻结附件 1/2/4。

### 7.5.4 跟 §7.3 hook 的关系

- `pre_run_input_guard` —— LLM 接入前在编排器入口跑一次；LLM 看不到失败语义；
- `pre_retrieval_query_guard` —— 检索类 tool 调 deterministic retrieval 时
  在内部自动跑，LLM 不感知；
- `post_retrieval_source_audit` —— 同上，retrieval 返回 FactPack/RuleSlice
  时自动跑；同时 KG 检索深入 6 tool 各自在返回前过一次 `_strip_forbidden`
  二次防线；
- `post_verifier_stop_gate` —— `run_closure_verification` tool 内部调
  `validate_building_closure` 后自动跑，allow_stop 写入 LLM 看到的 closure
  摘要里；LLM 不可改；
- `pre_output_language_guard` —— **[v0.4-E-3] v3 按来源分区生效**：模型点列
  在 `submit_analysis` 处消费 §7.5.9 的三类叙述规则与内容层检查；程序骨架/
  确定性模板继续走既有整稿白名单机制。组合终稿守卫分别校验两区，旧白名单不得
  复检模型槽位，新规则不得放宽骨架。组合守卫失败不回写 verifier 结果，改用
  安全的确定性组合终稿（§7.5.5 / §7.5.9）。

**[v0.4-E-3] b 件催交时序**：`run_closure_verification` 返回且
`NarrativeEvidencePack` 首次就绪后，编排器在**同轮全部 tool result 入队之后、
下一次模型推理之前**追加一次证据索引型定向用户消息；不得插在并行 tool result
中间。消息保留“下一条只输出 JSON 点列（提交）”，并内联本 run `key_items`
的裸别名及逐项一行 `category/kind/reason/slots/可绑定别名` 摘要，明确
“不要交空 points；先为每个重点项写一点”“每点最多绑定 8 个别名，条目多就拆点”
以及“text 提及 token 必须属于本点 evidence_aliases”。每 run 最多注入一次；
重复调用 closure 工具不得重复催交；不新增自由阅读推理轮，不改变工具轮次、
成本或叙述预算口径。

### 7.5.5 deterministic fallback 兜底

**[v0.4-E-3] v3 语义：格式或叙述失败只降级槽位，不降级骨架。**

下列任一情况触发**叙述槽位 fallback**（槽位改填与 `allow_stop` 分支对应的
确定性叙述模板）：

- LLM 在 `max_tool_iterations` 内未产生可用 v3 提交；
- 一次实质格式修复预算已用后再次出现非 `empty_points` 格式错误
  （`submission_format_exhausted`）；
- 叙述节候选达到局部重试上限仍未过闸（§7.5.9）；
- 直接绑定的 obligation ID 在闭包结果中存在冲突权威状态
  （`status_authority_ambiguous`）；
- LLM 抛出未预期异常（超时 / 模型崩溃 / SDK 错误）。

fallback 行为：
1. 编排器确保 deterministic backbone 已跑完（缺哪步自动补跑 retrieval /
   closure）；
2. 程序骨架照常渲染（`auxiliary_review_report.md` / `incomplete_closure_notice.md`
   已从"整篇 fallback 模板"升级为程序骨架模板，另为两个 `allow_stop` 分支各
   提供确定性叙述槽位模板）；权威表格与计数不因叙述失败降级或重算；
3. 审计写入 §7.5.10 的四个叙述字段与六个 v3 提交字段。`llm_forced_finalize` 保持原义 =
   "LLM 在轮内未调用提交工具、由编排器强制结束"（调用兼容别名视同调用提交
   工具），**不得复用它表示叙述未过闸**。

`narrative_fallback_reason` 正常 v3 状态机冻结枚举（7 值，顺序固定）：
`no_analysis_submitted` / `narrative_rejected_no_retry` /
`narrative_guard_exhausted` / `combined_output_guard_rejected` /
`composed_guard_degraded` / `submission_format_exhausted` /
`status_authority_ambiguous`；接纳模型叙述时为 `null`。外围未预期异常另记
`orchestrator_exception`，它是异常审计哨兵，不计入正常状态机 7 值枚举。

覆盖优先级单调：`submission_format_exhausted`、`status_authority_ambiguous`
及其他基础 fallback < `combined_output_guard_rejected` <
`composed_guard_degraded`；低级原因不得回盖高级原因。组合守卫第二次失败进入
`guard_safe_data` 降级——数据正文降为 ID 引用后重渲染。组合回退发生后必须
清空 `accepted_via`、`accepted_point_count` 与 `accepted_payload_sha256`，
不得让审计残留伪装成终稿仍采用了模型点列。

字段组合关系（防误读）：`no_analysis_submitted` 不必然等于
`llm_forced_finalize=true`（模型调了提交工具但载荷为空时 forced=false、
叙述 attempts=0）；反之，模型直接输出严格围栏 JSON、由编排器合成提交时，可出现
`llm_narrative_accepted=true` 且 `llm_forced_finalize=true` 的组合。
`empty_points` 每次仍记格式校验与失败事件并返回带证据包的格式回执，但
`repair_budget_consumed=false`，不消耗唯一修复预算；反复只交空点列直到主循环
上限时走 `no_analysis_submitted`，不得误记 `submission_format_exhausted`。

### 7.5.6 实现位置

- `agent/llm_client.py`：LLM 客户端封装（OpenAI 兼容协议 + env 配置 + 模型
  无关）。默认 Ollama `http://127.0.0.1:11434/v1` + `qwen3.5:latest`；env
  `EVO_AGENT_LLM_*` 覆盖。
- `agent/llm_orchestrator.py`：tool use 主循环 + 11 tool dispatcher + 卡住
  retry + deterministic fallback；session state 维护重对象（FactPack /
  RuleSlice / ClosureValidationResult）+ Neo4jClient 引用（供深入查询）。
- `agent/run_orchestrator.py`：`llm_mode: bool = False` 构造参数；True 时主
  流程委托 `run_llm_orchestration`，False 时走 §5.2 deterministic 11 步。

### 7.5.7 evaluator 侧识别【v0.4-E-3】

> ⚠️ **identity-v5 现网键切换增补**：evaluator / `EvoRunTrace` 统计序列**必须按 `obligation_identity_schema` 分区**，禁止跨身份模式（v1 拼串键 vs `obligation_identity_v5`）混算不变量。见 `spec_identity_v5现网键切换增补_20260717.md` §7 / §11。

evaluator（§8）必须能区分：

- **v1 / deterministic-only run**：`report_contract_version=1`，或历史产物
  未带版本号；`run_audit.llm_turns` 缺失。不得回填 v2/v3 审计字段；
- **v1 / LLM 历史 run**：只允许按旧 `llm_forced_finalize` +
  `fallback_reason` 口径解释，不得拿它推断 v2/v3 的接纳路径；
- **v2 历史 run**：`report_contract_version=2` 且 §7.5.10 的四个叙述字段
  齐全；拒码仍可含历史 `missing_evidence_handle`，不得要求 v3 六字段；
- **v3 LLM-driven run**：`report_contract_version=3`，四个叙述字段与六个
  提交审计字段齐全；`llm_turns` / `llm_tool_log` /
  `llm_iterations_used` / `llm_tool_call_count` 继续标识 LLM 主链；
- **v3 LLM-driven with fallback**：仍按 `report_contract_version=3` + 上述
  十字段解释，`narrative_fallback_reason` 可取正常 7 值；不得以旧
  `fallback_reason`、是否存在 rejected raw 文件或是否存在
  `accepted_payload.json` 单独反推接纳。

版本号与对应字段形状不匹配时，evaluator 必须标为契约识别异常并隔离，不能猜测
补齐或并入任一版本统计。EvoRunTrace 兼容 DTO 即使把新 reason 映射进旧
`fallback_reason` 字段，评测也不得反向消费该映射。v1/v2/v3 的接纳率、拒码率、
格式耗尽率、重试次数及语义盲审指标均不得混算。

三种 run 都遵循 §8 评测同一套指标；评测对 LLM-driven run 额外加：

- `llm_iteration_efficiency` = `tool_call_count / iterations_used`
- `llm_lookup_coverage` = LLM 在终局提交前调过 `lookup_rule_card` /
  `lookup_clause` / `search_regulation` 的次数 / open_count（衡量 LLM 是否
  真的查了法规原文）
- 这些指标只用于 baseline 分析，不进入 §8.4 verdict / leakage 6 项核心 KPI。

### 7.5.8 叙述证据包与短别名（NarrativeEvidencePack）【v0.4-E-3】

在允许调用 `submit_analysis` 前，程序必须从已完成的 deterministic
retrieval/closure 产物构造 `NarrativeEvidencePack`。证据包至少包含：

1. 权威 closure summary；
2. 重点 violated、open、blocked 项（high-risk 为已选项上的旗标，不是独立
   选择类别）；
3. 与重点项关联的 rule card 短引文；
4. 支撑上述项的 fact refs；
5. 明确未取得、不可用或被截断的资料/证据项。

选择与截断（默认值，工程侧已追认）：类别顺序 violated → open → blocked，
类内按 obligation_id 字典序；**每类最多 8 项**；rule card 短引文每条最多
200 字符；每项最多 3 条 fact；一切截断计入 `truncated` 且不得被表述为全量。
总 `token`/字符预算尚未实现，属待定项（§7.5.12 待定清单）。

证据包对模型使用短别名：obligation `[O1]`、rule/rule card `[R2]`、fact
`[F3]`。每个 key item 附带**展示性派生字段 `copyable_handle`**（如
`[O3]（关联规则 [R2]；相关事实 [F4, F5]）`）：只由本项短别名确定性拼装、
供模型直接复制，不得夹带任何判断/结论/裁决措辞。别名由程序按本次 run 建立
到真实 ID 的单向映射并落入审计产物；
**发给模型的载荷必须剥除全部真实 ID 字段，并把正文字符串中的真实 ID 替换为
别名**（防编造边界）。模型只引用别名，不得自行构造真实 ID，也不得引用别名表
外 token。最终渲染器把合法别名展开为 `[短别名:真实ID]` 格式（保留短别名便于
人工回查）；规范显示名与法规引用由确定性"法规引用与证据"节承载，不写进展开
token。

v3 中 `copyable_handle` 只作证据包展示与催交摘要；接纳绑定的唯一权威是每点
`evidence_aliases` 结构字段。模型在 `text` 中自然提及的别名 token 必须是同点
绑定的精确子集，不能用正文提及替代结构绑定，也不能由程序自动补绑。

证据包只来自 agent 可见的 RuleSlice、FactPack、ClosureValidationResult 与
允许的法规/rule card 资料，不得引入 W2/evaluator 输入。重点项的选择、排序、
截断和"未取到项"标记必须由程序完成并可审计。

### 7.5.9 提交格式状态机、叙述节闸与局部重试【v0.4-E-3】

v3 把格式病与叙述病分账。每个候选先过严格解析和载荷格式校验；只有格式有效的
规范对象信封才进入 `narrative_guard`。格式错误不增加
`llm_narrative_attempts`，不产生叙述拒码；内容层任一点失败则整篇原子拒绝，
不得逐点采纳。

**A. 严格解析与统一信封。** 真 tool call 直接校验 `args`；合成路径只接受：

1. 围栏外仅空白，恰好一个独占行代码围栏且必须闭合；
2. 语言标记为空或严格小写 `json`；
3. 围栏体是一个完整 JSON 值，`json.loads` 一次成功且无尾随 token；任意层
   重复对象 key 拒绝；
4. 根值只接受 `{"points":[...]}` 对象，裸数组拒绝；不支持 JSON5、注释、
   尾逗号、散文子串抽取、最长字符串挑选或猜测修补。

单围栏等价 EBNF、fullmatch 正则、parser 判定序与测试锚以 §7.5.13 引用的冻结
附件 2/5 为规范。两路径从此处起共用同一校验器与规范化输出。

**B. 载荷格式约束。**

- `points` 为 1–24 个对象；额外根/点字段可输入但被规范化输出丢弃；
- `text` 经 Python `strip()` 后为 1–500 个 Unicode 码点且限单行。`Cf`
  归 `point_field_type`；`splitlines()!=1` 或含 `Cc/Zl/Zp`（含
  U+2028/U+2029）归 `text_multiline`；
- `evidence_aliases` 为 1–8 个不重复字符串，每项严格匹配区分大小写的 ASCII
  `[ORF][0-9]+`；空数组是格式错误；
- 从 `text` 检出的别名 token 集合必须是同点 `evidence_aliases` 的子集。
  候选识别覆盖 ASCII 小写、全角及混合宽度形态，但比较不作 NFKC、大小写或
  宽度折叠；变体和未绑定 token 均报 `alias_in_text`，程序不得自动补绑、
  改写、去重或截断。

**C. 格式重试状态机。** 每个候选都做格式校验，校验次数本身不限；全 run 共享
**1 次实质性格式定向修复预算**。首次非 `empty_points` 格式错误消耗预算并返回
结构化回执；预算已用后再次出现此类错误即
`submission_format_exhausted`。内容重试仍须重新过格式校验，但格式有效时不耗
预算，且内容重试不重置预算。`empty_points` 每次记校验次数和失败事件，但
`repair_budget_consumed=false`，既不占预算也不触发格式耗尽。

每次格式失败记事件
`{"attempt_index":n,"via":"tool_call"|"synthesized_json","errors":[...]}`；
`errors[]` 固定五字段：`error_code/json_pointer/expected/actual/fix_hint`。
`actual` 只给实际类型与长度，不回显原文；解析层 `json_pointer=""`；按
root → points → 点数 → 点序（每点 text 后 aliases）发现序最多返回 5 错。
`alias_in_text` 的 hint 只回显相对同点绑定集的去重差集 token。

格式码冻结为以下 **19 个**，不得增删或混入叙述拒码：
`invalid_json` / `no_fence` / `multi_fence` /
`bad_fence_language` / `trailing_tokens` / `duplicate_key` /
`root_not_object` / `missing_points` / `points_type` / `empty_points` /
`too_many_points` / `point_field_missing` / `point_field_type` /
`text_too_long` / `text_multiline` / `alias_count` /
`alias_duplicate` / `alias_in_text` / `legacy_input_unsupported`。
精确触发条件和多错优先级见 §7.5.13 冻结附件 4。

数值口径（已追认的实现政策）：不设通用"编造数值"拒绝器；仅当模型声称
open/blocked/violated 为零而权威计数非零时记 `false_zero_count_warnings`
（WARN 级，不拒绝、不消耗重试）；其余数字靠提示词与证据把手约束。

**D. 内容层检查。**

1. **别名解析与原子接纳**：`evidence_aliases` 中语法有效但不在本 run
   `alias_map` 的别名报 `unresolved_alias`。空数组已属格式层；`alias_map`
   为空的 run 不邀请模型生成无把手点，直接以 `no_analysis_submitted` 走
   确定性模板。任一点内容失败即整篇拒绝。
2. **防编造与泄漏**：逐点拒绝包外 ID、裸真实 ID、伪日期、错 building ID、
   伪 obligation/rule-card/fact ID 及 W2/forbidden source 词元；引号、代码样式、
   Unicode/Markdown 变体不提供豁免。

3. **三类叙述规则**（NFKC 后逐点、逐分句）：
   - 安全/泄漏词元无条件 fail-closed；
   - 最终裁决与分支冒充按“主体 + 状态谓词 + 极性/模态”状态机判定。分句字符
     为 `。！？!?；;` 与换行，转折边界为
     `但是/然而/不过/可是/但/却/仍然/仍/而`，谓词前最长作用距离 12 个 Unicode
     码点；否定最长优先、非重叠计数，奇负偶正。命中不确定性模态则按非断言放行，
     `allow_stop=false` 时正向声称资料齐全、闭包通过或完整报告形成报
     `branch_inconsistent`；
   - 提及式元评论按有限共现形状独立报 `meta_commentary`：自指主体 + 输出行为，
     或任务规则词 + 合规行为，或敏感词 + 元语言标记。引号不豁免，回执要求删除
     任务规则说明、只保留实质性分析。

提示词只描述允许的点类型——事实限制、疑似风险、证据缺口、人工复核动作——
不得再枚举禁词或暴露内部豁免清单。v2 的 Markdown 要点切分、20 字/冒号/总结段
豁免、`_analysis_points` 与前缀白名单机制在 v3 全部停用。

4. **四之二：状态一致性检查（内容层第五检查）**。只直接绑定的 `O[0-9]+`
   别名携带义务状态权威；R/F 别名不携带。义务 `closure_status` 为
   `open/blocked` 时以其为权威状态，否则取 `satisfaction_status`。检查方向
   恒为收紧叙述，不修改 verifier 状态或重算闭包。

   同一 obligation ID 若在闭包结果中出现两个及以上不同权威状态（冻结实证
   `DEBT-054` 撞 ID），属于内部权威歧义而非模型叙述病：在增加
   `llm_narrative_attempts` 之前停止内容校验，`accepted_payload=null`，
   `narrative_fallback_reason=status_authority_ambiguous`，走确定性叙述模板；
   不产生 `status_escalation`，不烧叙述预算，并在
   `submission_audit_events` 记录 `event/attempt_index/details`（点序、ID、
   aliases、冲突 statuses）。

   **规则 A（升级禁令）**：命中断言式义务违规，而本点没有直接 O 状态权威，
   或任一直接绑定 O 的唯一权威状态不严格等于 `violated`，均以
   `status_escalation` 拒绝。因此 violated 与 open/blocked 等混绑时不能用组句
   宣称“相关义务已违反”；只有所有直接绑定 O 均为 violated 才允许违规断言。
   冻结义务违规原子共 11 个：
   `缺失即违规/无法满足/未满足/未达标/不符合/不合格/违反/违背/逾期/超期/缺失`。
   原子按长度降序整体匹配，`无法满足` 不得被拆成“无法”否定来洗白。词法闸先
   复用规则 2 的句号/换行/转折切分，再以 `，,：:、` 切专用子句；条件豁免
   仅认子句首 `^(如果|一旦|仅当|除非|若(?!干))`，不跨子句传播且“若干”不
   豁免。谓词前 12 码点内不确定模态、谓词后同子句 12 码点内
   `可能性/待核实/待确认/风险/嫌疑/与否` 按非现实断言放行。

   “缺失”只有在其紧邻前驱以
   `证据链/证据/记录/材料/资料/文件/数据/测量/事实` 之一结尾时按证据缺口
   放行；设施、门、结构等义务对象缺失仍为断言。子句尾
   `并不成立/不成立/并非如此` 作为一次后置极性翻转参与奇偶计数。若谓词前
   同时有至少两次否定，且含
   `尚无法/尚不能/无法/不能 + 确认/认定/判定` 的冻结组合，纯词法无法可靠
   约简时向放行侧兜底。该闸不承诺解析任意中文否定、指代或主语多义；彻底消除
   此天花板须未来引入 `status_subject_alias/asserted_status` 结构字段。

   **规则 B（同质性）**：一点直接绑定多个 O 时，只要状态集合含
   `satisfied`，又含 `violated/open/blocked/not_applicable` 任一项，即以
   `status_escalation` 原子拒绝并提示“拆点或按状态分组绑定”。该规则不依赖
   text 是否用了转折或分别描述；结构混绑本身即不合格。

v3 叙述拒码按冻结顺序共 **11 个**：
`unresolved_alias` / `fabricated_date` / `wrong_building_id` /
`fake_obligation_id` / `fake_rule_card_id` / `fake_fact_id` /
`raw_evidence_id` / `forbidden_phrase` / `branch_inconsistent` /
`meta_commentary` / `status_escalation`。`missing_evidence_handle` 只属于
v2 历史口径，在 v3 因非空结构绑定已由格式层强制而结构性不可达。
`llm_narrative_rejection_codes` 按尝试顺序平铺、允许跨尝试重复；
`submission_format_error` 与 19 个格式码均不得写入该列表。

局部重试：内容层失败时，只把拒绝码、必要的修正提示和证据包别名表返回模型，
要求重交完整 JSON 点列；每次重交先重新过格式校验。配置值表示“局部重试次数”
（不含首次候选），默认 2、允许范围 [1,2]、越界 clamp 不报配置错误——即默认
最多校验 3 个格式有效内容候选。内容重试计入叙述审计但不消耗格式修复预算；
不得重跑检索、规则适用性、义务派生或闭包验证。

达到重试上限仍不通过，或 LLM 超时/异常/未提交可用分析时，按 §7.5.5 走叙述
槽位 fallback；骨架及权威表格照常由程序渲染。

渲染器完成“确定性骨架 + 已接纳点列的确定性渲染/确定性叙述模板 + 别名展开”
后，必须按来源分区执行组合终稿守卫。组合守卫失败不得回写或改变 verifier
结果；应拒绝模型槽位并采用安全的确定性组合终稿（含 `guard_safe_data` 二级
降级，§7.5.5）。

不变量：程序骨架与两条确定性叙述模板必须**按构造即输出守卫洁净**——渲染器
新增任何免责/告知文案时，须同步维护 §7.3.6 否定前缀白名单使其覆盖该文案，
杜绝"守卫拦截确定性兜底稿 → 无终稿可用"的自指循环。

### 7.5.10 v3 提交与叙述审计【v0.4-E-3】

> ⚠️ **identity-v5 现网键切换增补**：本地验尸 / 回放产物 + `run_audit` 携身份版本字段（§7），回放与统计**按 `obligation_identity_schema` 分区**（禁跨身份模式混算）。见 `spec_identity_v5现网键切换增补_20260717.md` §7 / §11。

`run_audit` 保留四个叙述字段：

- `llm_narrative_accepted: bool`：最终是否采用通过叙述节闸的 LLM 分析；采用
  确定性叙述模板时为 `false`；
- `llm_narrative_attempts: int`：本次 run 实际校验的模型叙述候选次数；
- `llm_narrative_rejection_codes: list[str]`：按尝试顺序平铺记录的稳定拒绝码
  （允许重复）；无拒绝时为空数组；
- `narrative_fallback_reason: string | null`：未采用模型叙述时的明确原因；
  正常 v3 枚举 7 值见 §7.5.5，`status_authority_ambiguous` 为新增第 7 值；
  采用模型叙述时为 `null`。

v3 另新增并冻结以下**六个提交审计字段**：

- `submission_format_attempts: int`：全部格式校验次数，含通过的候选；
- `submission_format_repairs_used: 0 | 1`：实质格式修复预算消耗；空点回执
  单独带 `repair_budget_consumed=false`；
- `submission_format_events: list[object]`：逐次格式失败事件，结构与 §7.5.9
  一致；成功校验不记事件；
- `accepted_via: "tool_call" | "synthesized_json" | null`：终局接纳来源；
- `accepted_point_count: int | null`：终局接纳点数；
- `accepted_payload_sha256: string | null`：终局规范载荷哈希。

`accepted_payload_sha256` 的哈希对象是内容接纳后、别名展开前的规范对象信封
`{"points":[...]}`；`text` 使用实际渲染的 trim 后值，未知根/点字段已丢弃，
点序与别名数组顺序保留。规范化固定为
`json.dumps(sort_keys=True,separators=(",",":"),ensure_ascii=False)`，
再以 UTF-8 编码做 SHA-256，输出 64 位小写 hex。该纯字符串/数组/对象载荷范围
内与 JCS（RFC 8785）等价，但不得泛化宣称对任意含数字 JSON 等价。

`llm_forced_finalize` 原义与字段组合关系见 §7.5.5。evaluator 对 v3 run 必须以
`report_contract_version=3` + 四叙述字段 + 六提交字段识别路径；旧字段只为
v1 历史兼容，v2 仍按其四字段历史口径解释。

本地验尸/回放产物（不属于模型侧回执字段）：

- 每次格式失败把模型原始提交落为
  `submission_format_rejected_raw_attempt_{attempt_index}.txt`；文件名必须含
  `rejected_raw`，原文不得进入接纳载荷、组合终稿或 `run_audit`；
- 仅当内容层成功接纳且组合回退未清除接纳时，在 run 目录落
  `accepted_payload.json`。文件固定包含
  `{"payload":{"points":[...]},"accepted_payload_sha256":"<64hex>"}`，
  供离线回放精确定位载荷并与 `run_audit.accepted_payload_sha256` 对账；它
  不替代版本号或六字段判路；
- `status_authority_ambiguous` 的冲突明细写入条件性
  `submission_audit_events`，不伪装成第七个提交审计字段。

审计不变量：格式错误永不增加叙述 attempts/codes；格式耗尽前已有内容拒绝时，
既有叙述审计原样保留；终局未接纳或组合守卫降级时三个 `accepted_*` 字段为
`null`。由版本号、十个字段及条件性事件必须能无歧义重建真 tool call、合成
JSON、格式耗尽、权威歧义、内容耗尽或接纳终局。

### 7.5.11 判定权与 blind 不变量（v3 原文继承）【v0.4-E-3】

**[v0.4-E-3] 以下判定权/blind 红线逐字继承 v2，不作改写：**

报告契约 v2 不改变任何判定与数据边界：

1. `allow_stop`、适用性、obligation 状态、closure 状态及其 reason code 仍只
   由 deterministic verifier 产生；
2. rule-blind/W2/evaluator 隔离规则不变，证据包与模型均不得读取或推断
   forbidden sources；
3. total/closed/open/blocked/violated/high-risk 等权威计数只由程序从权威对象
   计算和渲染，模型文本永不成为计数来源；
4. LLM 分析只具有解释与建议作用，不得覆盖状态、补齐缺失证据、将要求当事实或
   作最终裁决；
5. 叙述校验、局部重试和 fallback 均不得触发闭包重算或污染评测输入。

### 7.5.12 兼容、迁移与待定清单【v0.4-E-3】

1. LLM 组合报告支线的新 run 显式写入 `report_contract_version=3`；确定性
   地板档暂按 v1；未带版本的历史产物按 v1 解释，不回填新审计字段。
2. 新提示词、4 个 seed Skill、tool schema、示例和测试只出现
   `submit_analysis(points)` 与 v3 对象信封；`analysis_markdown` 和
   `finalize_report(report_markdown)` 只在 dispatcher 迁移识别层存在。
3. 两旧入口命中均不解析正文、不映射为候选，统一返回
   `legacy_input_unsupported` 格式回执并记录
   `deprecated_submission_input`；旧客户端不得借此覆盖确定性骨架。
4. `auxiliary_review_report.md` 与 `incomplete_closure_notice.md` 从"整篇
   fallback 模板"升级为程序骨架模板；另为两个 `allow_stop` 分支各提供确定性
   叙述槽位模板。
5. 旧 `llm_forced_finalize` 和 `fallback_reason` 保持 v1 可读；v2 保持四
   叙述字段历史口径；v3 写四叙述 + 六提交字段。`llm_forced_finalize` 仍只
   表达“未在轮内调用提交入口”。历史报表不得跨版本混算。
6. 验收至少覆盖：两条 `allow_stop` 分支、权威计数不可被模型覆盖、别名合法
   展开、两路径同信封同哈希、19 格式码、11 叙述拒码、唯一格式修复预算、
   `empty_points` 不耗预算、Rule A/Rule B、权威撞 ID 兜底、局部重试不重跑
   闭包、`accepted_payload.json`、确定性 fallback、组合终稿输出守卫及 blind
   forbidden 字段零泄漏。
7. 兼容层移除条件与版本不得凭空补写；以 §7.5.13 冻结附件 6 的建议边界保留，
   在正式拍板前仍是待定迁移项。

**待定清单**（不阻塞契约生效；落定前不得表述为"已有默认值"）：

- `NarrativeEvidencePack` 总 `token`/字符预算（当前未实现，仅有分类上限）；
- 拒绝码与叙述审计的 evaluator 展示口径（按尝试分组还是平铺去重）；
- `finalize_report` 兼容别名的移除版本/日期，及旧客户端迁移完成的判定门槛。

### 7.5.13 report contract v3 激活门规范附录【v0.4-E-3】

**激活裁定（2026-07-13）**：逐点结构化提交契约 v3 自本修订起为生效权威规格。
七项激活门附件以留档文件
[`spec草案_逐点提交契约v3_20260713.md`](../spec草案_逐点提交契约v3_20260713.md)
中 `## 激活门附件（冻结版）` 及其 `## 实现冻结记录` 为本规格的规范性引用，
视同本节附录正文：

1. **附件 1**：提交载荷 Draft 2020-12 JSON Schema 全文及 `x-*` 实现约束；
2. **附件 2**：单围栏 EBNF、fullmatch 正则、严格 JSON/重复 key 判定序；
3. **附件 3**：20 字符 Markdown 转义表、裸写/方括号别名展开与尾绑规则；
4. **附件 4**：root → points → 点序校验序、多错优先级与 19 格式码触发表；
5. **附件 5**：parser、载荷、叙述闸、渲染、状态机、审计、fallback 与两条
   `allow_stop` 分支的真实验收用例矩阵；
6. **附件 6**：兼容层移除条件。当前冻结内容仍明确为待拍板建议，不得写成
   已实现版本/阈值；本次激活只冻结“不得把建议冒充实现事实”的边界；
7. **附件 7**：两条 `allow_stop` 分支复用
   `render_deterministic_narrative` 的模板文本与 SHA-256 版本锚。

适用优先级：草案早期概括与其实现冻结记录/冻结附件冲突时，以后两者为准；
状态一致性闸的 11 拒码、Rule A/Rule B、义务违规词表、
`status_authority_ambiguous` 和 `accepted_payload.json` 以本次激活正文记录的
最新冻结实现为准。附件 6 的退出版本仍待拍板，不反向削弱 v3 当前生效性。
本附录只冻结报告提交与叙述支线，不改变 §7.5.11 的判定权/blind 红线。

# 8. 评测闭环

## 8.1 原则

评测程序独立于 agent。它可以读取：

- agent run artifacts；
- W2 `NormativeProjection` / `expected_verdict`；
- W2 basis / threshold outputs；
- rule_card crosswalk。

agent 不可读取 evaluator 的任何输入或中间产物。

## 8.2 evaluator 输入

```yaml
agent_outputs:
  - closure_validation_result.json
  - obligation_set.json
  - auxiliary_review_report.md 或 incomplete_closure_notice.md
  - run_audit.json

reference_truth:
  - projections.parquet
  - matched_families.parquet
  - threshold_evaluations.parquet
  - basis_items.parquet
  - normative_projection_meta.parquet
```

## 8.3 evaluator mapping

### 8.3.1 agent obligation → family verdict

对同一 `(world_id, fragment_id, family)` 聚合：

```python
if any(obligation.closure_status in {"open", "blocked"}):
    agent_family_verdict = "unknown"
elif any(obligation.satisfaction_status == "violated"):
    agent_family_verdict = "fail"
elif all(obligation.satisfaction_status in {"satisfied", "not_applicable"}):
    agent_family_verdict = "pass_or_not_applicable"
else:
    agent_family_verdict = "unknown"
```

`pass_or_not_applicable` 再结合 applicability audit：

- scope not_applicable → `not_applicable`
- otherwise → `pass`

### 8.3.2 fine family → W2 coarse family

evaluator 使用独立 crosswalk。该 crosswalk 是 evaluator 配置，**不进入 agent KG**，也不进入 agent 检索上下文。

权威来源与接口：

```text
source: rule_card_v2/_rule_card_v2现状注解.md §4
content: W2 coarse 16 → rule_card fine 43 的完整 1:N 对照表
materialization: evaluator/config/family_crosswalk_v1.json
owner: 项目侧从现状注解抽取；本 baseline spec 不重新产出完整表
```

`family_crosswalk_v1.json` 格式：

```json
{
  "schema_version": "family_crosswalk_v1",
  "source_note": "rule_card_v2/_rule_card_v2现状注解.md §4",
  "mappings": [
    {
      "coarse_family_id": "mbis.inspection.drainage",
      "fine_family_ids": [
        "mbis.inspection.drainage.ri.coverage",
        "mbis.inspection.drainage.ri.identify",
        "mbis.inspection.drainage.ri.follow_up",
        "mbis.investigation.drainage.ri.trigger",
        "mbis.investigation.drainage.ri.method",
        "mbis.investigation.drainage.ri.follow_up",
        "mbis.repair.drainage.ri.repair",
        "mbis.repair.drainage.ri.validate"
      ],
      "notes": "example; full 16 coarse mappings are project-side materialized from the cited source"
    }
  ]
}
```

evaluator 启动时 hard requirements：

```python
assert crosswalk.schema_version == "family_crosswalk_v1"
assert len({m.coarse_family_id for m in mappings}) == 16
assert all(m.fine_family_ids for m in mappings)
```

若 crosswalk 缺失，evaluator 不能给 family-level score，只能输出 `evaluation_status="blocked_missing_crosswalk"`；agent run 不受影响。

## 8.4 metrics

> ⚠️ **identity-v5 现网键切换增补**：metrics 统计序列（verdict / coverage / threshold / closure / leakage）**必须按 `obligation_identity_schema` 分区**，禁止跨身份模式（v1 vs `obligation_identity_v5`）混算。见 `spec_identity_v5现网键切换增补_20260717.md` §7 / §11。

### 8.4.1 verdict metrics

| metric | 定义 |
|---|---|
| `expected_verdict_accuracy` | agent family verdict 与 W2 expected_verdict exact match |
| `pass_fail_macro_f1` | 只在 pass/fail 子集上算 macro F1 |
| `unknown_recall` | W2 unknown 的召回 |
| `not_applicable_accuracy` | not_applicable exact match |
| `severity_weighted_accuracy` | 按 W2 severity_band 加权 |

### 8.4.2 family / rule coverage

| metric | 定义 |
|---|---|
| `family_recall` | W2 selected/matched family 中 agent 覆盖比例 |
| `family_precision` | agent family 中 W2 相关 family 比例 |
| `rule_card_recall_proxy` | W2 matched rule_ids 与 agent retrieved rule_card_ids overlap |
| `slot_requirement_recall` | W2 required_slots 被 agent obligations 覆盖比例 |

### 8.4.3 threshold metrics

比较 agent threshold obligations 与 W2 threshold_evaluations：

| metric | 定义 |
|---|---|
| `threshold_operator_match` | operator exact |
| `threshold_value_match` | threshold canonical JSON exact |
| `observed_value_tolerance_match` | numeric tolerance 或 exact |
| `threshold_pass_bool_match` | agent comparator_result vs W2 pass_bool |
| `unit_match` | unit exact/canonical |

### 8.4.4 closure metrics

| metric | 定义 |
|---|---|
| `allow_stop_precision` | allow_stop=true 时是否 W2 可评估且 agent 无 open/blocked |
| `allow_stop_recall` | W2 pass/fail/not_applicable 中 agent allow_stop=true 比例 |
| `open_when_reference_unknown_rate` | W2 unknown 时 agent open/blocked 的比例 |
| `blocked_rate_by_reason` | blocked reason 分布 |
| `closed_violated_detection_rate` | W2 fail 中 agent closed+violated 检出比例 |

### 8.4.5 leakage metrics

| metric | fail 条件 |
|---|---|
| `forbidden_source_loaded` | run_audit 中 forbidden_sources_loaded 非空 |
| `forbidden_label_in_kg` | agent database 出现 forbidden label |
| `forbidden_property_in_kg` | agent database 出现 forbidden property |
| `expected_verdict_text_leak` | 报告直接引用 W2 expected_verdict 字段名或 projection id |
| `basis_item_id_leak` | 报告出现 W2 basis_id |
| `evaluator_store_access` | agent credential 访问 evaluator store |

任何 leakage metric fail，则该 run 评测成绩作废，标记 `invalid_due_to_answer_leakage`。

## 8.5 evaluator 输出

```json
{
  "eval_run_id": "EVAL-...",
  "agent_run_id": "CAR-...",
  "world_id": "WB-...",
  "building_id": "BLD-...",
  "valid": true,
  "invalid_reasons": [],
  "metrics": {
    "expected_verdict_accuracy": 0.0,
    "pass_fail_macro_f1": 0.0,
    "family_recall": 0.0,
    "threshold_pass_bool_match": 0.0,
    "allow_stop_precision": 0.0
  },
  "per_fragment_results": [],
  "leakage_audit": {
    "forbidden_source_loaded": false,
    "forbidden_property_in_kg": false,
    "expected_verdict_text_leak": false
  }
}
```

## 8.6 evaluator 不反写

evaluator 不得把 score、truth、错题原因写回 agent KG。baseline 阶段只生成离线报告。evo 阶段若使用 reward，也必须通过明确的 evo trainer 通道，而非把答案塞给 agent runtime。

---

# 9. 为 evo 预留的接口

## 9.1 Skill 生命周期

```text
empty_seed/manual_seed
        │
        ▼
candidate       # evo 生成或人工提议
        │
        ▼
validated       # 通过离线评测与 leakage audit
        │
        ▼
active          # 可被 baseline/evo runtime 使用
        │
        ▼
retired         # 被替换或证伪
```

baseline 只读取：

```text
manual_seed + allowed_in_baseline=true
active + allowed_in_baseline=true
```

默认无 active evo skill。

## 9.2 Skill 写回 KG 占位

未来 evo 成熟 Skill 写回：

```python
def promote_skill_to_kg(skill_candidate, validation_records):
    assert validation_records.no_leakage
    assert validation_records.metric_delta >= threshold
    assert skill_candidate.grounding_rule_refs
    MERGE (:Skill {skill_id})
    MERGE triggers
    MERGE grounding edges
    SET status = "active"
```

禁止：

- 修改 `RuleCard` 节点正文；
- 修改 `RuleThreshold` 阈值；
- 修改法规原文；
- 将 W2 expected_verdict 写入 Skill content；
- 将 per-building answer pattern 固化为 Skill。

## 9.3 Skill 与闭包验证器边界

Skill 可以影响：

- 检索排序；
- 报告写作结构；
- 人工复核建议；
- 未来 evo 中的候选推理策略。

Skill 不可以影响：

- threshold comparator；
- `closure_status`；
- `satisfaction_status`；
- `allow_stop`；
- W2 reference truth 可见性。

## 9.4 Skill validation records

每个 promoted Skill 必须挂：

```text
(:Skill)-[:VALIDATED_BY]->(:SkillValidationRecord)
```

最低字段：

```text
eval_batch_id
metric_name
metric_before
metric_after
metric_delta
leakage_pass
human_approved
```

---

# 10. 模块划分与落代码路径

建议代码结构：

```text
evo_agent_baseline/
  config/
    kg.yaml
    guard.yaml
    evaluator.yaml
  ingest/
    cypher_schema.py
    fact_loader.py
    sidecar_loader.py
    regulation_loader.py
    rulecard_loader.py
    skill_loader.py
    guard.py
  kg/
    neo4j_client.py
    queries.py
    dto.py
  retrieval/
    fact_retriever.py
    rule_retriever.py
    pack_builder.py
  closure/
    schema.py
    fact_binding.py
    applicability.py
    obligation_deriver.py
    threshold_eval.py
    validator.py
  agent/
    system_prompt.txt
    skills/
      skill.mbis.building_assessment_workflow/
      skill.mbis.fact_kg_retrieval/
      skill.mbis.rule_obligation_derivation/
      skill.mbis.auxiliary_report_writer/
    hooks.py
    report_writer.py
    run_orchestrator.py
  eval/
    truth_loader.py
    mapper.py
    metrics.py
    leakage_audit.py
    report.py
  tests/
```

依赖方向：

```text
ingest -> kg
retrieval -> kg
closure -> retrieval DTO only
agent -> retrieval + closure
eval -> agent artifacts + W2 truth
agent -X-> eval
closure -X-> eval
ingest.agent -X-> W2 normative tables
```

---

# 11. 测试与验收

## 11.1 unit tests

| package | tests |
|---|---|
| ingest | allowlist/denylist、schema constraints、idempotent MERGE |
| rulecard_loader | 397 cards、43 families、子节点对账 |
| regulation_loader | clause parsing、source_section linking |
| retrieval | fact subgraph completeness、candidate rule retrieval |
| closure | statuses、threshold、artifact、deadline、qualifier、allow_stop |
| hooks | forbidden query、forbidden output |
| eval | metrics、leakage audit、fine→coarse mapping |

## 11.2 integration tests

### IT-001 safe ingestion

输入完整 run dir，agent loader 只读 12 张 agent-visible 表，跳过 6 张 W2 表。

验收：

```text
MATCH (n) WHERE "NormativeProjection" IN labels(n) RETURN count(n) = 0
MATCH (n) WHERE exists(n.expected_verdict) RETURN count(n) = 0
```

### IT-002 building assessment run

输入某 `building_id`：

1. 生成 FactPack；
2. 生成 RuleSlice；
3. closure verifier 输出；
4. 根据 `allow_stop` 生成对应报告。

验收：

```text
closure_validation_result.json schema valid
run_audit.forbidden_sources_loaded == []
```

### IT-003 evaluator blind scoring

evaluator 读取 agent outputs + W2 truth，输出 metrics。agent run artifacts 中不得包含 W2 table paths。

### IT-004 deterministic repeatability

同一 KG snapshot、同一 building、同一 config 运行两次：

```text
sha256(canonical_json(obligation_set.json)) 相同
sha256(canonical_json(closure_validation_result.json)) 相同
```

LLM 报告可不 byte-identical，但结构字段必须一致。

## 11.3 Definition of Done

baseline 完成需满足：

1. Neo4j schema 全部约束和索引可创建；
2. agent loader 对 denylist hard guard 生效；
3. rule_card v2 397 卡 / 43 fine family 成功入库；
4. 指定 building 可完成 KG-RAG → closure verifier → report/notice；
5. verifier 无 LLM 依赖；
6. `allow_stop=false` 时报告生成被 hook 阻断；
7. evaluator 可用 W2 truth 阅卷；
8. leakage audit 全绿；
9. self-check 8 条原则全部满足。

---

# 12. self-check

## 12.1 对照 §1.0 八条原则

### 原则 1：副驾驶定位

设计将系统输出限定为“闭包验证情况 + 辅助审查报告”。System Prompt、报告模板、output guard 均禁止最终裁决话术。`closed + violated` 只表示证据闭合且存在疑似未满足项，必须交给人工审查。

### 原则 2：闭包验证属于合规助手代理本身

§6.1 明确 closure verifier 是 agent runtime 的底线层组件，输入只有 `RuleSlice + FactPack`，由 rule_card + 建筑事实自行推导义务集。它不属于 W2，也不消费 W2 reference truth。

### 原则 3：evo-agent blind

agent 数据流、agent KG、RuleSlice、FactPack、closure verifier、seed Skill、LLM report 均不得读取或包含 `NormativeProjection`、`expected_verdict`、W2 projection tables、W2 basis items、W2 threshold evaluations。§2.2.2 禁止整表，§2.2.3 禁止 label/property，§7.3 hooks 运行时阻断。`required_world_core_slots`、`required_measurement_slots`、`required_qualifier_slots`、`required_sidecar_interfaces`、`matched_component_refs`、`matched_measurement_ids`、`coverage_status` 已补入禁止属性名。

### 原则 4：W0/W1/W2 固定上游

v0.3 不重写 W0/W1/W2，只修正 agent-side schema 对上游字段的映射。`Component` 几何列、`Measurement.qualifiers_json`、`ConditionState.derived_outcomes`、`RuleThreshold.formula_json` 等均按固定上游消费，不修改上游契约。

### 原则 5：确定性底线层防幻觉

`allow_stop` 由 §6 deterministic verifier 计算。LLM 只能读取 `machine_readable_report` 写辅助报告，不能修改 obligation 状态、不能覆盖 `allow_stop`。

### 原则 6：baseline 不带 evo，但留接口

baseline 加载 4 个手工 seed Skill，但不做自动 skill 生成、提升、淘汰。§9 保留 Skill lifecycle、SkillValidationRecord 与未来写回 KG 的位置。

### 原则 7：旧设计资料只作参考

旧闭包验证器只继承“确定性 ObligationSet”思想，不继承 `QueryEpisode` 载体、investigator simulation、`HiddenGold` 或旧 regex 抽 slot。新载体是 `ComplianceAssessmentRun`。

### 原则 8：spec→code 单向

本规格为后续代码唯一权威；若实现与本规格冲突，改实现。新增 formula handler、artifact alias map、obligation edge 处理均已先落规格，再允许实现。

## 12.2 全部假设

| ID | 假设 |
|---|---|
| A-001 | Neo4j 本地实例可用，但连接参数由部署配置提供 |
| A-002 | `rule_cards.json` 当前为 397 卡、43 fine family；loader 仍以 manifest / 文件内容为准，不硬编码数量作业务判断 |
| A-003 | `family_crosswalk_v1.json` 由项目侧从 `rule_card_v2/_rule_card_v2现状注解.md §4` 抽取；本规格只定义接口 |
| A-004 | sidecar artifact slots 使用 W0_09 §5.2 的 `artifact.*` 命名空间；当前 25 个 rule_card `artifact_key` 必须全部通过 §6.3.6 显式 alias map 绑定，禁止 prefix fallback |
| A-005 | baseline 不建通用时序引擎；deadline 只支持 `within/before/same_day_as` 与 precomputed duration / sidecar anchor |
| A-006 | formula baseline 只支持 `n^2-2n+3` 白名单 handler；其他 formula blocked |
| A-007 | seed Skill 是流程手册，不具有覆盖 verifier 的权限 |

## 12.3 未决点 / 负责人需拍板

| ID | 未决点 | v0.3 默认 |
|---|---|---|
| O-001 | Neo4j URI / database / credential | 配置占位，不硬编码 |
| O-002 | evaluator store 用 DuckDB 还是独立 Neo4j | 默认 DuckDB/parquet 直读 |
| O-003 | 是否启用 vector index | 可选；baseline 不依赖 |
| O-004 | 完整 `family_crosswalk_v1.json` 文件由谁维护 | 项目侧从现状注解抽取维护 |
| O-005 | artifact alias map 是否需覆盖未来新增 artifact_key | loader quality gate 要求 map 覆盖当前 rule_cards 全量 key；未来新增 key 未入 map 时 hard fail / blocked，并登记 alias map 增订需求 |
| O-006 | `before/same_day_as` 是否将来升级为时序引擎 | baseline 不建，后续另立规格 |

## 12.4 已废旧概念排除确认

确认未引入：

```text
QueryEpisode
HiddenGold
investigator simulation
巡检员模拟
latent case
adjudicator
旧 rule_card v1 regex 抽 slot
closure_validator 挂在数据生成层
NormativeProjection 作为 agent 输入
expected_verdict 作为 agent 输入
```

## 12.5 round-2 punch list 完成确认

两份深审清单的每一条均已在 v0.2 处理，详见配套文件《evo-agent baseline v0.2 逐条处理说明》。v0.3 未重写这些已验收主体，只处理验收报告 C-1~C-4。高优先两项已落到实现级：

1. §6.3.10 新增 `evaluate_obligation_node` 与 `obligation_graph.edges` 规则；
2. §3.4.3 / §4.3.3 / §6.3.5 补 `RuleThreshold.formula_json`、loader 落库与 deterministic formula handler。

## 12.6 round-3 C-1~C-4 完成确认

**[v0.3-self-check]** 验收报告 C-1~C-4 均已处理：

| 项 | 处理确认 |
|---|---|
| C-1 | §6.3.6 收口（v0.4）：粗桥接拆为 `ARTIFACT_KEY_TO_SIDECAR_SLOT` 17 精确绑定 + `ARTIFACT_KEYS_NOT_MODELED` 8 个判 `blocked + artifact_not_modeled_upstream`；删 `form.mbi1/mbi2` 死条目；删 prefix fallback；删粗桥接（实测 sidecar artifact 条目无 `artifact_key` 限定词、桥接会假 satisfied、破坏底线层）|
| C-2 | §3.4.3 明确 `RuleThreshold.family_id` 是 loader 从父 `RuleCard.family_id` 派生，不来自上游 `threshold_regimes[]` |
| C-3 | §3.3.4 `Measurement` 字段表已拆分 `来源` / `规则`，与 §3.3.1 对齐 |
| C-4 | §6.3.10 与 §6.6 的 `evaluate_obligation_node` / `evaluate_obligation_edges` 函数名和签名已统一 |

C-1 覆盖自检：

```python
assert len(ARTIFACT_KEY_TO_SIDECAR_SLOT) == 17
assert len(ARTIFACT_KEYS_NOT_MODELED) == 8
assert set(ARTIFACT_KEY_TO_SIDECAR_SLOT) | ARTIFACT_KEYS_NOT_MODELED == RULE_CARD_ARTIFACT_KEYS
assert set(ARTIFACT_KEY_TO_SIDECAR_SLOT) & ARTIFACT_KEYS_NOT_MODELED == set()
assert len(set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values())) == 17
assert set(ARTIFACT_KEY_TO_SIDECAR_SLOT.values()) <= W0_09_ARTIFACT_SLOTS
assert "form.mbi1" not in ARTIFACT_KEY_TO_SIDECAR_SLOT
assert "form.mbi2" not in ARTIFACT_KEY_TO_SIDECAR_SLOT
```

原则复核：v0.3 只改 agent-side artifact binding、schema 字段来源标注、函数签名一致性，不引入任何 W2 `NormativeProjection` / `expected_verdict` / projection 字段到 agent 输入、KG、检索或 verifier；不触碰 W0/W1/W2 数据生成层；不引入 `QueryEpisode`、`HiddenGold`、巡检员模拟、latent case 等旧废概念；v0.2 已验收主体未被重写。

# 附录 A：禁止项清单

## A.1 agent database 禁止 labels

```text
NormativeProjection
ProjectionFamilyEval
ThresholdEval        # 若来自 W2 threshold_evaluations
ReportBasisItem      # 若来自 W2 basis_items
ExpectedVerdict
EvalNormativeProjection
EvalProjectionFamilyEval
EvalThresholdEval
EvalBasisItem
HiddenGold
QueryEpisode
InvestigatorSimulation
```

## A.2 agent database 禁止属性名

```text
expected_verdict
selected_family
projection_status
basis_items
unknown_reason_code
regime_tag
pass_bool
projection_id
projection_registry_id
projection_family
projection_version
required_world_core_slots
required_measurement_slots
required_qualifier_slots
required_sidecar_interfaces
matched_component_refs
matched_measurement_ids
coverage_status
raw_projection_ref_hash
projection_ref_hash
```

## A.3 agent database 禁止 files

```text
normative_projection_meta.parquet
projections.parquet
matched_families.parquet
threshold_evaluations.parquet
coverage_control_metadata.parquet
basis_items.parquet
```

## A.4 agent output 禁止话术

```text
最终裁决
最终合规
最终不合规
结案
本建筑已合规
本建筑不合规
according to expected_verdict
based on NormativeProjection
```

允许替代表述：

```text
闭包验证显示...
疑似未满足，建议人工复核...
本报告为人工审查辅助材料，非最终裁决...
```

# 附录 B：最小配置样例

```yaml
neo4j:
  agent_database: evo_agent_baseline
  eval_database: evo_eval_truth
  uri: bolt://localhost:7687
  agent_user: evo_agent_runtime
  ingest_user: evo_agent_ingest
  eval_user: evo_eval_runner

ingestion:
  allow_agent_tables:
    - worldgen_world_bundles_meta.parquet
    - buildings.parquet
    - fragments.parquet
    - components.parquet
    - locations.parquet
    - coverage_relations.parquet
    - fragment_states.parquet
    - specialized_states.parquet
    - measurements.parquet
    - sidecar_runtime_meta.parquet
    - sidecar_records.parquet
    - sidecar_entries.parquet
  deny_agent_tables:
    - normative_projection_meta.parquet
    - projections.parquet
    - matched_families.parquet
    - threshold_evaluations.parquet
    - coverage_control_metadata.parquet
    - basis_items.parquet
  forbidden_agent_properties:
    - expected_verdict
    - selected_family
    - projection_status
    - basis_items
    - unknown_reason_code
    - regime_tag
    - pass_bool
    - projection_id
    - required_world_core_slots
    - required_measurement_slots
    - required_qualifier_slots
    - required_sidecar_interfaces
    - matched_component_refs
    - matched_measurement_ids
    - coverage_status
    - raw_projection_ref_hash

closure:
  verifier_version: baseline_closure_v0.3
  allow_formula_handlers: true
  formula_handler_allowlist:
    - pull_test_additional_after_failure_n2_minus_2n_plus_3
  numeric_tolerance: 1.0e-9
  allow_stop_requires_no_open: true
  allow_stop_requires_no_blocked: true

agent:
  report_language: zh
  allow_full_report_only_when_allow_stop: true
  skills_enabled: true
  manual_skill_seed_enabled: true
  required_seed_skill_ids:
    - skill.mbis.building_assessment_workflow
    - skill.mbis.fact_kg_retrieval
    - skill.mbis.rule_obligation_derivation
    - skill.mbis.auxiliary_report_writer

evaluator:
  readable_by_agent: false
  fail_on_leakage: true
  family_crosswalk_path: evaluator/config/family_crosswalk_v1.json
```

---

# 附录 C：最小报告模板

```markdown
# MBIS 辅助审查报告（非最终裁决）

> 本报告由 evo-agent baseline 生成，仅供人工审查员辅助使用，不构成最终合规裁决。

## 1. 建筑与资料范围

- world_id:
- building_id:
- KG snapshot:
- 事实来源:
- 法规 / rule card 版本:

## 2. 闭包验证摘要

- allow_stop:
- closed:
- open:
- blocked:
- satisfied:
- violated:
- not_applicable:

## 3. 适用法规与 rule card 切片

| family | rule_card_count | source clauses |
|---|---:|---|

## 4. 逐项义务闭包表

| obligation_id | target | rule_card | kind | closure | satisfaction | evidence |
|---|---|---|---|---|---|---|

## 5. 疑似未满足项

| obligation_id | rule_card | observed | required | note |
|---|---|---|---|---|

## 6. 人工复核建议

- ...

## 7. 限制

- 本报告不读取 W2 参考真值。
- 本报告不替代人工审查员最终判断。
```
