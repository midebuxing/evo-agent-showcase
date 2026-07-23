# rule_card v2 数据系统现状注解（W2 端备忘）

> 本文件是 W2 端 rule_card v2 消费关系备忘，不是 rule_card v2 数据规格权威源。
>
> W2 正式 spec 只声明消费契约：manifest + 13 sub-file + `projection_runtime_mapping_v1.json`。rule_card v2 的字段 schema、卡片结构、fine family 归 rule_card v2 自身维护。
>
> 本文件不得用于改写 W2 16 family baseline，也不得把历史实现侧 13 entry 映射当作 W2 spec 权威。


**建立日期**：2026-05-13
**目的**：本注解文件**只描述 rule_card v2 数据系统的现状事实**，让任何看 W2 spec 的人不会拿错对账对象。按 D-4 决策"W2 spec 只描述消费契约，不复写 rule_card 数据规格"，本文件不是 rule_card 数据 spec，只是消费侧的现状注解。
**信息来源**：法规卡团队 2026-05-13 回复（路径 `团队文档/技术团队文档/rulecard工程/`）+ 实际 grep 确认（`agent_v1/regulations/rulecard_v2/mbis_cop_2023/`）。

---

## 1. 避坑警告（最重要）

### ⚠️ 不要把 `family_coverage_baseline_v1.json` 9 family 当成 rule_card 全量 family 清单

`family_coverage_baseline_v1.json` 是 **W0/worldgen 端覆盖就绪度 baseline**，记录的是部分 family 对 world slots / measurement slots / artifact-only / procedure-only 的建模需求，**不是 rule_card 端全量 family 清单**。

历史误读路径：W2 spec 包勘探阶段（2026-05-13）来源勘探报告 §10 拿这个文件做对账，导致一度推断"rule_card 端只有 9 family"，进而误判"历史实现侧 13 entry 是从 16 减到 13 的简化"。法规卡团队 2026-05-13 回复校正后明确：rule_card 端全量 ≠ 这个文件。

### ⚠️ 不要按 `family_coverage_baseline_v1.json` 推断"缺哪些 family"

按 family_coverage_baseline_v1 跟 W2 spec 06 §2 的 16 family 对账会得出"缺 7 个 family"的错误结论。实际这 7 个 family 中的 4 个（`inspection.fire_safety` / `inspection.ubw` / `investigation.structural_assessment_fsp` / `reporting.completion_report`）在 rule_card 端**有产料**，只是命名细粒度不一样。

---

## 2. rule_card v2 数据系统实际全量

按法规卡团队 2026-05-13 回复 + 实际 grep 确认，rule_card v2 数据系统包含以下文件（路径 `agent_v1/regulations/rulecard_v2/mbis_cop_2023/`）：

### 2.1 rule_card 主体

| 文件 | 数量 | 性质 |
|---|---|---|
| `rule_cards.json` | **397 张卡**（2026-05-13 batch_08 补卡前 353；补 §5.1/§5.2/§5.5/§6.5 四章共 44 张后 397）| rule_card v2 主体——法规卡团队全量手写 |
| `family_index.json` | **43 fine family**（补卡前 40；新增 3 个 fine family）| rule_card 端细粒度 family，按 `phase.actor.subject.action_cluster` 四元组切片 |
| `slot_index.json` | （索引）| rule_card 引用的 slot 索引 |
| `threshold_regime_index.json` | （索引）| rule_card 阈值索引 |
| `exception_definition_index.json` | （索引）| 例外条款索引 |

### 2.2 子注册表

| 文件 | 内容 |
|---|---|
| `semantic_slot_registry_v1.json` | rule_card 端语义 slot 注册表 |
| `measure_registry_v1.json` | rule_card 端测量注册表 |
| `artifact_semantics_registry_v1.json` | rule_card 端 artifact 注册表 |
| `time_anchor_registry_v1.json` | rule_card 端时间锚点 |
| `controlled_vocabularies_v1.json` | rule_card 端受控词表 |
| `projection_runtime_mapping_v1.json` | rule_card ↔ W0/W2 端映射 |

### 2.3 覆盖就绪度 baseline（W0/worldgen 端用，非 rule_card 全量）

| 文件 | 数量 | 性质 |
|---|---|---|
| `family_coverage_baseline_v1.json` | **9 family** | **W0/worldgen 端覆盖就绪度 baseline**（哪些 family 在 worldgen 端有 slot 建模能力），不是 rule_card 端全量 family |
| `coverage_baseline_v1.json` | （类似）| 同类覆盖 baseline |
| `coverage_差异_audit_v1.json` | （类似）| 覆盖差距审计 |

### 2.4 manifest

| 文件 | 内容 |
|---|---|
| `manifest.json` | rule_card v2 包顶层 manifest |

---

## 3. W2 16 family ↔ rule_card 40 family 的正确关系

按法规卡团队回复，W2 端 16 coarse family（法规章节级 baseline，来源 a4 §3）跟 rule_card 端 40 fine family（按 `phase.actor.subject.action_cluster` 切片）是 **1:N 的 coarse → fine 关系**：

```
W2 16 coarse family（法规章节级 baseline，来源 a4 §3）
       │
       ▼ 1:N 映射（完整对照表见 §4）
rule_card 40 fine family（family_index.json）
       │
       ▼ 1:N
rule_card 353 张卡（rule_cards.json）
```

**不是**这样的关系：

```
❌ W2 16 family --1:1--> family_coverage_baseline 9 family
```

---

## 4. W2 coarse 16 → rule_card fine 完整对照表（按法规卡团队 2026-05-13 两次回复合并）

按法规卡团队回复，卡数按当前 `family_index.json` / `rule_cards.json.source_section` 对账（若某个 fine family 跨多个 W2 coarse，只统计落入本 coarse 章节锚点的卡数）。

| # | W2 coarse family | rule_card fine family | 卡数 | 产料状态 |
|---|---|---|---|---|
| 1 | `mbis.scope.coverage_and_preinspection` | `mbis.scope.building.ri.coverage` + `mbis.preinspection.background.ri.review` | 25 + 23 = 48 | ✅ |
| 2 | `mbis.procedure.ri_notifications_and_submissions` | `mbis.reporting.inspection_report.ri.submit` + `mbis.reporting.ri_procedural_notifications.ri.submit` + `mbis.repair.prescribed_repair_inputs.ri.deliver` | 1 + 22 + 2 = 25 | ✅ |
| 3 | `mbis.inspection.external_components` | `covered_external_wall.ri.coverage` + `external_components.ri.record` + `external_defects.ri.identify` + `external_defects.ri.follow_up` + `scope.building.ri.coverage`（§3.3.2(G)(b) 内部 curtain wall 部分）| 6 + 2 + 7 + 2 + 2 = 19 | ✅ |
| 4 | `mbis.inspection.structural_components` | `structural_components.ri.coverage` + `structural_defects.ri.identify` + `structural_defects.ri.follow_up` | 23 + 10 + 2 = 35 | ✅ |
| 5 | `mbis.inspection.fire_safety` | `fire_safety_components.ri.coverage` + `identify` + `follow_up` | 25 | ✅ |
| 6 | `mbis.inspection.drainage` | `inspection.drainage.ri.coverage` + `identify` + `follow_up` + `investigation.drainage.ri.trigger` + `method` + `follow_up` + `repair.drainage.ri.repair` + `validate` | 7 + 9 + 7 + 5 + 4 + 1 + 11 + 7 = 51 | ✅（含 §3.6 / §4.4 / §5.6 全段）|
| 7 | `mbis.inspection.ubw` | `ubw_and_related_scope.ri.coverage` + `identify` + `follow_up` | 18 | ✅ |
| 8 | `mbis.investigation.gate_and_proposal` | `detailed_investigation.ri.trigger` + `gate` + `proposal` + `reporting.ri_procedural_notifications.ri.submit`（§2.1.3(n) 部分）| 2 + 9 + 6 + 2 = 19 | ✅ |
| 9 | `mbis.investigation.structural_assessment_fsp` | `detailed_investigation.ri.gate` + `trigger`（§4.3 相关）| 17 | ✅ |
| 10 | `mbis.repair.general_selection_and_classification`（§5.1, §5.2）| `mbis.repair.general_selection_and_classification.ri.select` | 20（§5.1 = 11 + §5.2 = 9）| ✅ 2026-05-13 batch_08 补齐 |
| 11 | `mbis.repair.external_structural_validation` | `external_structural_validation.ri.verify` + `follow_up` + `tile_pull_test.ri.validate` | 35 + 3 + 1 = 39 | ✅ |
| 12a | `mbis.repair.fire_safety_and_drainage`（§5.6 drainage 段）| `repair.drainage.ri.repair` + `validate`（已计入 #6）| 18 | ✅ |
| 12b | `mbis.repair.fire_safety_and_drainage`（§5.5 fire 段）| `mbis.repair.fire_safety_components.ri.repair` | 22 | ✅ 2026-05-13 batch_08 补齐 |
| 13 | `mbis.supervision.ri_minimum_and_site_controls` | `ri_minimum_and_site_controls.ri.control` + `submit` + `supervision.site_records.ri_team.keep` + `site_visit_frequency.ri_team.minimum` | 21 + 2 + 2 + 1 = 26 | ✅ |
| 14 | `mbis.supervision.rc_controls`（§6.5）| `mbis.supervision.rc_controls.rc.control` | 2 | ✅ 2026-05-13 batch_08 补齐 |
| 15 | `mbis.reporting.inspection_report` | `inspection_report.ri.schema` | 24 | ✅ |
| 16 | `mbis.reporting.completion_report` | `completion_report.ri.schema` | 11 | ✅ |

**16 family 完整对账结论**（2026-05-13 batch_08 补卡后闭环）：
- **16 个 W2 coarse family 全部有产料**（其中 #6 drainage 51 卡是单一 W2 coarse 下最多）
- **2026-05-13 batch_08 补卡前 3 个 W2 coarse family + 1 半段 真 0 卡**（#10 / #12b / #14；详见 §5）——已由法规卡团队当日补齐 44 张卡 + 3 个 fine family，详见 §5 批次报告
- **W2 spec 16 family 法规依据成立**——每个 family 都能在 MBIS §3-§7 章节找到独立锚点，跟 rule_card 端 43 fine family 形成完整 1:N coarse → fine 映射

---

## 5. 4 章 0 卡 → 已补齐（2026-05-13 batch_08 闭环）

**状态**：✅ 4 章 0 卡已闭环——法规卡团队 2026-05-13 当日补齐 44 张卡 + 3 个 fine family（batch_08，路径 `agent_v1/regulations/rulecard_v2/mbis_cop_2023/reviewed_batches/batch_08_coverage_debt_reviewed/`）。

下表保留补卡前的法规事实清单（用作 batch_08 补卡的 trace 依据 + 后续审计追溯）。补卡后实际卡数见每章"当前 rule_card 卡数"行。

补卡前后的事实清单：

### 5.1 §5.1（`mbis.repair.general_selection_and_classification` 前半段）

| 项 | 事实 |
|---|---|
| 法规条文性质 | 实操类 / 程序类混合 |
| 法规原文（§5.1.1-§5.1.7）| RI 选择合适修葺方法 / 制定纠正及修葺建议 / 确保修葺成效不逊于既有标准 / 按批准图则或已提交图则施工 / 区分小型工程 / 豁免工程与需 BA 批准同意的其他工程 / 在 inspection report 内注明需定期维修的构件 |
| 补卡前 review 记录 | 没找到明确 review / 不入卡决定 |
| 当前 rule_card 卡数 | **11**（2026-05-13 batch_08 补；归 `mbis.repair.general_selection_and_classification.ri.select`，跟 §5.2 共 20 张同一 fine family）|

### 5.2 §5.2（`mbis.repair.general_selection_and_classification` 后半段）

| 项 | 事实 |
|---|---|
| 法规条文性质 | 实操类 checklist / 原则化选择准则 |
| 法规原文 | RI 决定修葺方法时考虑：用途及设计使用年限 / 外露严重程度 / 现况 / 缺陷成因 / 对住户 / 公众 / 楼宇 / 环境的影响 / 成效和耐久性 / 材料与结构配合 / 安全及卫生标准等因素 |
| 补卡前 review 记录 | 没找到明确 review / 不入卡决定 |
| 当前 rule_card 卡数 | **9**（2026-05-13 batch_08 补；归 `mbis.repair.general_selection_and_classification.ri.select`，跟 §5.1 共 20 张同一 fine family）|

### 5.3 §5.5（`mbis.repair.fire_safety_and_drainage` fire 段，#12b）

| 项 | 事实 |
|---|---|
| 法规条文性质 | 实操类 |
| 法规原文（§5.5.1-§5.5.4）| 消防安全构件修葺要求：更换出口指示牌 / 清除障碍物 / 修葺防火门 / 恢复防火分隔 / 挡火物 / 通知业主维护防火门和逃生路线等 |
| 补卡前 review 记录 | `reviewed_batches/` 中有 §3.5 fire safety inspection 卡 / §5.6 drainage repair 卡，**未找到 §5.5 / `s5_5` 对应 repair fire safety 卡**，也未找到明确"不入卡"理由 |
| 当前 rule_card 卡数 | **22**（2026-05-13 batch_08 补；归新建 fine family `mbis.repair.fire_safety_components.ri.repair`）|

### 5.4 §6.5（`mbis.supervision.rc_controls`）

| 项 | 事实 |
|---|---|
| 法规条文性质 | 实操类 / 程序类 |
| 法规原文（§6.5.1-§6.5.2）| §6.5.1 RC 对工人进行 continuous supervision，并要求修葺及纠正工程符合《建筑物条例》及规例；§6.5.2 RC 就准备工作和纠正 / 修葺工程检查，向 RI 给予充足预先通知 |
| 补卡前 review 记录 | 没找到明确 review / 不入卡决定 |
| 当前 rule_card 卡数 | **2**（2026-05-13 batch_08 补；归新建 fine family `mbis.supervision.rc_controls.rc.control`）|

### 5.5 4 章 0 卡闭环报告（2026-05-13 batch_08）

**法规卡团队补卡报告完整内容**（按法规卡团队 2026-05-13 第三次回复）：

| 项 | 值 |
|---|---|
| 批次 | `batch_08_coverage_debt_reviewed`（路径 `agent_v1/regulations/rulecard_v2/mbis_cop_2023/reviewed_batches/batch_08_coverage_debt_reviewed/`）|
| 新增卡数 | 44（§5.1 = 11 + §5.2 = 9 + §5.5 = 22 + §6.5 = 2）|
| 新增 fine family | 3（`mbis.repair.general_selection_and_classification.ri.select` 20 张 + `mbis.repair.fire_safety_components.ri.repair` 22 张 + `mbis.supervision.rc_controls.rc.control` 2 张）|
| canonical bundle 规模 | 40 fine family / 353 卡 → **43 fine family / 397 卡** |
| 引用与可追溯性 | 44 张全部含 `source_section` / `source_quote` / `source_quote.page` / `source_quote.language` 4 字段；`missing_source_refs = 0` |
| 验证 | `pytest test_rulecard_v2.py` 6 passed；`pytest test_normative_projection_builder.py test_execute_projection_batch_v2.py` 23 passed；`validate_rulecard_bundle()` 通过；`slot_index` / `threshold_regime_index` / `exception_definition_index` 跟 `rebuild_derived_indexes()` 一致 |
| 边界说明 | 本批次只关闭明确发现的 §5.1 / §5.2 / §5.5 / §6.5 coverage 差异，**不等价于宣称全 MBIS CoP 2023 无遗漏**；若需"全法规无缺口"结论，需另跑一次全文章节级 coverage audit |

**判明问题层**（按 memory `feedback_diagnose_before_fix.md`）—— 补卡前后对照：
- ❌ 不是 spec 真缺失（W2 spec 06 §2 已列这 4 段 family）
- ❌ 不是 spec 错位（spec 跟法规对齐）
- ❌ 不是 spec 含糊（法规条文明示是实操类）
- ✅ **rule_card 端覆盖未完成（已闭环）**——法规明文要 RI / RC 做实操类工作；2026-05-13 用户拍板派工法规卡团队补卡；同日批次 batch_08 补齐 44 张卡 + 3 fine family，闭环

---

## 6. 跟 W2 spec 其他章节的 cross-ref

| 本文件位置 | W2 spec 章节 | 关系 |
|---|---|---|
| §1 避坑警告 | `02_输入合约与W0_W1依赖.md` §4 rule_card v2 sub-file 清单 | spec 02 §4 文件清单注释里 `family_coverage_baseline_v1.json` 行已加路牌指本文件 |
| §3 关系图 + §4 完整对照表 | `06_canonical_slots与projection_binding.md` §2 16 family baseline | spec 06 §2 表已加注：rule_card 端 1:N 关系（详见本文件 §3 + §4）|
| §5 4 章 0 卡法规事实 | `06_canonical_slots与projection_binding.md` §2 + `团队文档/我的笔记/技术与研究债.md` DEBT-031 差异 15 | rule_card 端覆盖 差异 trace，待用户决策处置 |
| §2 数据系统全量 | `_拆分说明.md` 备忘 1 "rule_card v2 独立 spec 文档化" | 备忘段已加注：实际数据系统 schema 看本文件 §2 + 后续 rule_card team 主动立 spec 时再展开 |

---

## 7. 代码端 `_W0_FAMILY_TO_RULECARD_PREFIXES` 13 entry 的性质

代码 `agent_v1/src/workflow_engine/regulation_thresholds.py` L83-L129 的 `_W0_FAMILY_TO_RULECARD_PREFIXES` 字典是 **W2 coarse family → rule_card fine family prefix 的不完整 crosswalk**，当前 13 entry。

由 2026-05-06 commit `e3494cb`（F1+F2 历史修订）引入。commit message 自报"W0 spec 整合多 rule_card family 为单个"——这句话是当时的误读（拿 family_coverage_baseline_v1 当 rule_card 全量），实际上 13 entry 是按当时作者能查到的 rule_card prefix 写的 partial crosswalk。

**修法**（已登记 DEBT-031 差异 6）：法规卡团队 2026-05-13 已回复完整 16 coarse → N fine 对照表（详见本文件 §4），历史实现侧 13 entry 可按本文件 §4 表扩到完整 crosswalk（独立工程跟踪）。

---

## 8. 来源

- 法规卡团队 2026-05-13 第一次回复（family baseline 性质校正 + 7 family 例子）
- 法规卡团队 2026-05-13 第二次回复（剩 9 family 完整对照 + 4 章 0 卡法规事实核查）
- 法规卡团队 2026-05-13 第三次回复（batch_08 coverage debt closure report：补 44 张卡 + 3 fine family，§5.1 / §5.2 / §5.5 / §6.5 四章 0 卡闭环）—— 三次回复消息内嵌于 W2 规格包建立会话
- 实际 grep 确认：`agent_v1/regulations/rulecard_v2/mbis_cop_2023/` 目录文件清单 + `family_index.json` 43 family（含 batch_08 新增 3 个）+ `rule_cards.json` 397 卡（含 batch_08 新增 44 张）+ batch_08 路径 `reviewed_batches/batch_08_coverage_debt_reviewed/`
- W2 规格包来源勘探报告 §10：`杂物箱/文件包/W2_法规映射层_来源勘探_2026_05_13.md` §10 章节（已含修订注，本文件是修订后的 canonical 现状描述）
- a4 旧蓝图 §3：`杂物箱/文件包/W0全量设计重构包_正式版/一拖上传/06_a4_canonical_slot_universe_权威旧蓝图.md` §3（16 family × 5 列大表）
- MBIS_CoP_2023 法规原文：`agent_v1/regulations/markdown/MBIS_CoP_2023.md`（§3-§7 章节对应 16 family）
- 用户 2026-05-13 D-4 决策：rule_card v2 数据系统不复写规格只描述消费契约
- DEBT-031 差异 6（历史实现侧 13 entry crosswalk 不完整，法规卡团队已提供完整 16 → 43 对照表）+ DEBT-031 差异 15（rule_card 4 章 0 卡，2026-05-13 batch_08 闭环）

---

## ⏳ 遗留 trace

### trace 1：W2 coarse 16 → rule_card fine crosswalk ✅ 已完整（2026-05-13 闭环）

法规卡团队 2026-05-13 两次回复完成全 16 W2 coarse family → N fine family 完整对照，详见 §4 表。

### trace 2：rule_card §5.1 / §5.2 / §5.5 / §6.5 四章 0 卡处置 ✅ 闭环（2026-05-13 batch_08）

2026-05-13 用户拍板派工法规卡团队补卡 → 同日 batch_08 补齐 44 张卡 + 3 新建 fine family + 全套测试 / 校验通过（详见 §5.5）。本 trace 闭环。

回填动作全完成（5 处）：
- ✅ 本文件 §2 数据规模（397 卡 / 43 fine family）
- ✅ 本文件 §4 表 #10 / #12b / #14 行更新到实际 fine family + 卡数 + ✅
- ✅ 本文件 §5.1 / §5.2 / §5.3 / §5.4 各章"当前 rule_card 卡数"行更新
- ✅ 本 trace 状态 🟡 → ✅
- 待做：DEBT-031 差异 15 + 跟踪表 + W2 spec 06 §2 状态列同步（外部文件，下面 §6 同步）

**边界说明**：本批次只关闭明确发现的 §5.1 / §5.2 / §5.5 / §6.5 coverage 差异，**不等价于全 MBIS CoP 2023 无遗漏**；若需"全法规无缺口"结论，需另跑全文章节级 coverage audit（属法规卡团队责任域的长期工作，不在 W2 规格包任务范围）。

### trace 3：rule_card v2 数据系统独立 spec 立项

按 D-4 决策当前不立项，等法规卡团队主动需要或项目阶段触发时再说。本注解文件**只描述消费契约 + 现状事实**，不替代 rule_card v2 数据系统独立 spec。

### trace 4：代码 `_W0_FAMILY_TO_RULECARD_PREFIXES` 13 entry 扩到完整 crosswalk ⏳ 独立工程跟踪

法规卡团队回复的完整对照表已在 §4 落字，代码可按 §4 表扩到 16 entry（DEBT-031 差异 6）。属独立工程跟踪，不阻塞当前 W2 spec 包。
