# W0 静态资源层全量实现级设计规格包

状态：数据生成层封口版。

跨包权威源与负向不变量先读：`../_封口总则_字段权威源与负向不变量.md`。

如本包正文与该总则冲突，以总则和字段所属包的权威章节为准。

W0 是数据生成层的静态资源层，负责 19 张 registry、实例对象字段、measurement slot contract、sidecar boundary contract、surrogate / formula 与约束口径。W0 不生成具体建筑实例，不生成法规映射参考真值，不消费 rule_card v2，不承接 evo-agent 训练逻辑。

封口阅读顺序：

1. 先读 `../_封口总则_字段权威源与负向不变量.md`，确认跨包权威源与负向不变量。
2. 再读本包 `00_范围与过滤决策.md` / `01_设计原则与本体边界.md`。
3. registry 以 `02_资源域与19张注册表.md` 与 `11_registry_entries_inventory.md` 为准。
4. W0 实例对象字段以 `04_生成实例与法规映射参考真值字段合约.md` §§3-17 为准。
5. `NormativeProjection` / `ProjectionFamilyEval` / `ThresholdEval` / `ReportBasisItem` 字段权威已迁出至 W2 `09_输出契约_NormativeProjection.md`；W0 04 §§18-21 只保留迁出 stub。

本包不记录实现状态、测试状态或工程推进状态；这些内容不属于封口 spec 权威源。

## 2. 来源文件

本规格包生成时使用过一组上传别名。阅读本包时，不应把这些别名当作原始路径；真实源文档如下：

| 本包引用别名 | 原始源文档 | 角色 |
| --- | --- | --- |
| `01_a12_权威旧蓝图.md` | `团队文档/研究团队文档/pro-answer/a12.md` | registry schema、生成实例对象、法规映射参考对象、生成函数、约束、projection、sidecar、batch / QA / version 主源 |
| `02_a10_权威旧蓝图.md` | `团队文档/研究团队文档/pro-answer/a10.md` | 机理、测量、surrogate、旧 HiddenGold thin-copy 与 seed constraints 补充源 |
| `03_a11_权威旧蓝图.md` | `团队文档/研究团队文档/pro-answer/a11.md` | full-coverage worldgen 扩容、资源域、sidecar ownership、slot ownership 来源 |
| `04_a9_权威旧蓝图.md` | `团队文档/研究团队文档/pro-answer/a9.md` | rule-blind world truth、NormativeProjection、旧 Observation / QueryEpisode / Adjudication 删除依据 |
| `05_a8_权威旧蓝图.md` | `团队文档/研究团队文档/pro-answer/a8.md` | 五层因果生成、measurement 派生、compatibility / exclusion / dependency 背景来源 |
| `06_a4_canonical_slot_universe_权威旧蓝图.md` | `团队文档/技术团队文档/rulecard工程/answer/a4.md` | canonical normative slot registry、regulation-family coverage、world ontology baseline、sidecar 分类来源 |
| `07_a5_权威旧蓝图.md` | `团队文档/研究团队文档/pro-answer/a5.md` | 旧 LatentCase 混合结构、认识状态、typed unknown / missing / conflict / not_applicable 来源 |
| `08_W0全量实现级设计文档_当前新版整理稿.md` | `团队文档/我的笔记/蓝图汇总/W0 全量实现级设计文档.md` | 当前人工整理稿来源 |
| `09_用户原则说明.md` | `杂物箱/文件包/W0全量设计重构包_正式版/一拖上传/09_用户原则说明.md` | 巡检员模拟整块删除、HiddenGold / observation / episode / adjudication 删除原则 |

引用格式仍保留生成时的上传别名，例如 `来源：01_a12_权威旧蓝图.md:Lx-Ly`。需要回查原文时，先按上表把别名映射回原始源文档。特别注意：本包中的 `a4` 指 `团队文档/技术团队文档/rulecard工程/answer/a4.md`，不是 `团队文档/研究团队文档/pro-answer/a4.md`。

## 3. 与旧蓝图的关系

旧蓝图中可保留为新版“资源驱动生成 + 法规映射参考真值”的主线是：

```text
WorldBundle
  -> FragmentContext
  -> DriverState
  -> MechanismState
  -> ConditionState / DamageState
  -> MeasurementRecord
  -> DerivedFlags
  -> NormativeProjection
```

这条链不是说 W0 静态资源层本身输出 `NormativeProjection`；它表示 W0 registry / surrogate / formula / constraint 支撑生成某个具体 `WorldBundle`，再由 法规映射层对该实例产出 `NormativeProjection` 参考真值。`a12` 明确将对象层扩展到 building / component / location / coverage / condition / drainage / UBW / fire-safety / repair / assessment / technical measurement，并冻结 registry、surrogate、constraint、QA 与版本合约；但旧稿同时保留 `HiddenGold` thin-copy projection 的 gold 标尺，这一点在新版中删除。（来源：`01_a12_权威旧蓝图.md`:L3-L11、L31-L44、L541-L566）

新版系统原则明确：删除“巡检员模拟 / investigator simulation”整块功能，不迁移到后续层，也不另建 simulator / episode / benchmark / evaluation 规格保留；凡专门服务于 inspector / investigator / observation / evidence / episode / HiddenGold / adjudication / benchmark gold 的内容均删除或标为删除依据。（来源：`09_用户原则说明.md`:L3-L8、L20-L25）

## 4. 阅读顺序

建议按以下顺序阅读：

1. `00_术语表与名词解释.md`：先统一名词，尤其是 W0 / projection / sidecar / benchmark / HiddenGold / registry / slot / QA 的区别。
2. `00_范围与过滤决策.md`：先看新版保留 / 删除边界。
3. `99_来源索引.md`：先看冲突与人工确认问题，避免后续误读。
4. `01_设计原则与本体边界.md`：理解 W0、W1/W2+、world truth、measurement truth、normative truth、sidecar 的关系。
5. `02_资源域与19张注册表.md`（正式正文；`02_资源域与17张注册表.md` 为旧路径 stub）：理解 6 大资源域 + 1 项边界契约与 19 张 registry。
6. `08_normative_projection与canonical_slots.md`：查 canonical slot universe、regulation family coverage 与 projection 填表依据。
7. `09_sidecar边界契约.md`：查 sidecar ownership / consume contract / 派生层生成路径（2026-05-09 修订：sidecar B 类 slot 由 worldgen 派生层生成，不依赖外部 admin record）。
8. `04_生成实例与法规映射参考真值字段合约.md`：查生成实例对象与 法规映射参考真值对象字段。
9. `03_registry_schema_matrix.md`：查 registry 主键、字段、约束和跨表引用。
10. `05_生成流程与依赖.md`：查生成顺序和依赖图。
11. `06_surrogate公式噪声与unknown策略.md`：查公式、噪声、threshold regime 与 unknown 策略。
12. `07_约束与失败策略.md`：查 C001-C026、P0-P3 与 fallback。
13. `10_规格版本与发布口径.md`：查 batch、QA、seed、version 与封口发布口径；`10_批次QA版本与实现缺口.md` 为旧路径 stub。

## 5. 新版一句话定位

严格的 W0 是 **rule-blind 的静态资源层** ：它提供 19 张 registry、surrogate / formula / constraint、canonical slot 与 sidecar boundary 等资源；参考生成流程使用这些资源生成建筑片段级物理真相、技术测量真相、风险 / 修缮 / 验证派生事实；法规映射层再基于某个具体 `WorldBundle` 与 `normative_projection_registry` 产出 `NormativeProjection` 参考真值。新版系统不生成巡检员观察、证据暴露计划、query episode、HiddenGold、adjudication 或巡检员模拟评测 gold。（来源：`08_W0全量实现级设计文档_当前新版整理稿.md`:L5-L23；`09_用户原则说明.md`:L5-L8、L22-L25）

---
