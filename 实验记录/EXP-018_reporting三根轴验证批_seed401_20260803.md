# EXP-018：reporting 三根轴世界侧补产·验证批（seed 401）

**日期**：2026-08-03（深夜）
**批目录**：`agent_v1/experiments/reporting_axes_seed401_20260803`
**池**：`agent_v1/experiments/qa_reports/_reporting_axes_50x1_seed401/gen_seed_401`（seed 401）
**库**：`s25smoke`（隔离库；首栋 `--wipe` 重灌）
**档位**：确定性地板档（`--llm` 关；本批验证的是**世界侧供给**，不是判定能力）
**上游裁定链**：规格 `规格_reporting三根轴世界侧补产_v1_20260803.md`（决策门三问全 C）→
seed 分叉决策门（grok＋qwen3.8-max 两家族收敛：乙／401／零改码）→
审核门丁后三件（kimi 过门＋grok 平行同判；欠账六件＋三尾巴已修，其中 crosswalk 按「降级」处置——见其 docstring：构建/测试期护栏、设计上无运行时消费者）。

## 🔴 与全部历史批不可比

世界侧新增 4 个 `reporting.*` 轴槽（23 组合轴积采样）⇒ 池语义已换。四锚
（池摘要／code_state／commit／池指针）与历史批机械不同。批根目录有
`INCOMPARABLE_不可比声明.md`。**本批禁止拿旧真值（S00301）跑条款覆盖/验收③**
——真值按裸 `building_id` 联结会静默错对齐（两家族独立指出）；批前硬闸实测
**交集为空**（`assert_pool_truth_disjoint.py`，seed 401 的 50 栋 vs 真值 10 栋）。

## 结果：30/30 栋完成，`check_batch_acceptance` 全部硬项通过

**规格 §6 六条验收判据逐条实测**：

| # | 判据 | 实测 |
|---|---|---|
| 1 | 四槽真被采样（看事实包不是登记表） | ✅ 30/30 栋：`submitted` 390＝13 组合×30／`delivered` 240＝8×30／`record.submitted` 30／`signed` 30——**逐槽等于轴积×栋数** |
| 2 | 角色对照断言有牙齿 | ✅ 变异测试在册（`test_actor_role_crosswalk.py`；删一项必拒） |
| 3 | 卡引用不再落「槽不存在」类码 | ✅ 绑四槽义务 **2,396 条，零** `slot_not_supplied`/`missing_fact`；分布见下 |
| 4 | 时限仍不可判（正向判据） | ✅ 无一条落 `missing_time_anchor` 之外的时限伪判定（本批四槽义务无 deadline 类，符合「只补状态布尔」） |
| 5 | 两表对账 | ✅ ownership 与 bool 采样表对四槽一致 |
| 6 | 不可比标注 | ✅ 批根声明文件＋本记录＋台账三处 |
| 限定符 | 二元 `(artifact_key, actor_role_key)` | ✅ 690/690 齐（`signed` 按规格无角色轴） |

**额外里程碑**：批清单 `code_state_selfcheck.equal = True`——「重算==清单」自检
**首次在正式批上取得**（此前 CLAUDE.md 记门④ 该项从未取得）。
批清单并含**桶表摘要锚**（`bucket_binding_registry_digest`，审核门必办①的首次落批）。

## 绑四槽义务的原因码分布（2,396 条，诚实拆账）

| 条数 | 状态/码 | 解读 |
|---:|---|---|
| 1,140 | `open/artifact_state_not_valid_evidence` | **供给到位、消费通道未裁**：新事实按分类器锚①（carrier_domain=artifact）落进证据许可闸。**这不是缺陷**——「呈交/送达/签署状态可否确立对应义务」按丁的框架属**逐绑定裁定**，是下一步的活 |
| 880 | `blocked/missing_rule_edge` | 上游触发器堵死的继承（与批 I 同形） |
| 201 | `blocked/ambiguous_fact_binding` | 卡引用未带限定符 ⇒ 13 行候选收不窄（卡侧待补限定符） |
| 175 | `blocked/artifact_not_modeled_upstream` | ~~键不在 23 组合内~~ **🔴 2026-08-04 探查更正：六键全在 23 组合内**——真因是闭包侧 `for_submission` 桶分支的 `resolve_artifact_slot` 对 reporting.* 键返回 None（通道不认新轴），详 `键归属核对_175条_20260804.md` |

⚠️ **不承诺也未发生 unknown 降幅**（规格明写）：本批交付的是**供给侧闭环**——
「世界没建」这一类根因对四槽清零；把供给变成判定还差「逐绑定裁定+许可通道」一步。

## 下一步（不在本批内）

1. 1,140 条的消费通道：对「`reporting.artifact.submitted=true` 可否确立『须呈交』义务」
   做逐绑定裁定（正是丁新码文案里「改接能确立义务的证据通道后重新裁定」的入口）；
2. 201 条 ambiguous：卡侧补 `(artifact_key, actor_role_key)` 限定符；
3. 175 条 not_modeled：核那些 artifact_key 是否该并入轴积（对中文原文逐条）。

## 复算入口

- 批清单：`reporting_axes_seed401_20260803/batch_manifest.json`
- 验收探针：本记录同日会话（四槽计数／义务拆账各一段 python）
- 硬闸：`assert_pool_truth_disjoint.py`／`compare_world_core_parquet.py`
  （后者对旧池 FAIL 属**对照混杂**：旧 301 池是 7-29 代码生成，含五天获批演进
  ——+20 fragments 与供给侧片段修复相符；building_id 集合与列结构一致）
