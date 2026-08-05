# 审核结论：波次二 #22「rng 隔离 1a 全序」实施（官方独立线）

**日期**：2026-08-05 / **性质**：独立代码审核，非转述 —— 四点必审项全部自己实算
**受审对象**：未提交改动的 worldgen 侧（`git diff` 的 `workflow_engine/worldgen/*` ＋
新建 `rng_domains.py` / `verify_rng_isolation_pairing.py` / `tests/test_rng_isolation.py`）
**依据链**：`实施记录_rng隔离1a_20260805.md` ＋ `核清_rng隔离1a_20260805.md` ＋
台账「rng 隔离案完整门闭合＋实施卡定稿」「1a 全序落地」两节
**审核基线**：HEAD `8c386907`（工作树 dirty）；未连 Neo4j；全部池落 scratchpad（仓库外）；
本审核**零仓库改动**（除本文件；`git worktree` 已在收尾撤销）

---

## 总结论

**通过。** 四步与实施卡逐项相符；实施的四条核心宣称我逐条独立复算，**全部成立**：
①S4「7 处不是 2 处」订正为真且其「漏改则假隔离而字节锚照样绿」的推论结构上成立；
②「只解流不解锚」兑现（`deterministic_key` 逐位不变，包哈希仍锚池身份）；
③七道字节锚我在实施留下的真实中间池上**逐道重放，全 PASS，明细数字逐条相符**；
④15 条性质测试确在，全量 1,454 通过 / 2 xfailed / 0 失败。

**发现 9 条，无一推翻实施本身**，全部落在「证据陈述精度」与「测试护栏覆盖面」两类。
其中 **F1 / F2 两条须修**——它们是**护栏空洞**，会让 1a-i′ 这一步将来的回归**无声通过**。

**建议**：F1 / F2 补完即可提交；F3 / F4 是台账与实施记录的措辞收窄（不动代码）；
F5–F8 记为脚本与仓库的遗留项；F9 是我自己的作业事故披露。

---

## 一、必审项①：四步与实施卡逐项相符 / S4 七处订正

### 我做了什么

对 `generator.py` 跑 AST 全函数扫描（不是 grep 字符串），把每一个 `rng` 名字按
**所属函数 / 是否形参 / 是否局部赋值 / 所在循环体 / 与赋值点的支配关系**四维分类。

### 结论：相符，且 S4 订正为真

| 阶段 | 函数 | `rng` 形参 | 子流赋值行 | 该函数内 `rng` 读取行 | 是否全在同一片段循环体且在赋值之后 |
|---|---|---|---|---|---|
| S1 | `generate_coverage_relations` | **已删** | :1361 | :1374 / :1376 | ✅ 循环 @1359-1392 |
| S2 | `generate_coverage_sampling_measurements` | **已删** | :1874 | :1878 / :1887 | ✅ 循环 @1873-1889 |
| S3 | `generate_technical_validation_measurements` | **已删** | :1918 | :1927 / :1947 / :1956 | ✅ 循环 @1917-1958 |
| S4 | `generate_structural_assessment_measurements` | **已删** | :2105 | :2307 / :2424 / :2427 / :2434 / :2442 / :2491 / :2507 | ✅ 循环 @2092-2532 |

- **S4 的主 rng 读取点实测 7 个**，与实施记录列的「核清漏的 5 处 ＋ 核清列的 2 处」逐一对上
  （行号因新增注释整体下移，对应关系：:2307←旧:2247、:2424←:2364、:2427←:2367、
  :2434←:2374、:2442←:2382、:2491←:2431、:2507←:2441）。**核清 §1.1 记的 2 处确为漏记。**
- **子流建在两个 guard 之后**：:2094-2095（`mechanism is None or not mechanism.active → continue`）
  与 :2099-2100（`component is None → continue`）都在 :2105 之前 ⇒ 被跳过的片段不建无用子流。✅
- **「照核清只改 2 处则隔离是假的、而字节锚照样会绿」——结构上成立**。
  `generate_world_bundle` 里主 rng 的**最后一次**消费在 :3118，而四阶段调用在
  :3127 / :3134 / :3139 / :3149。四阶段之后主 rng 再无消费者 ⇒ 残留消费造成的位移
  在任何产物上都显现不出来，字节锚检不到。**这条订正是本次实施最有价值的一处自纠。**
- **零漏网旁证**：全文件只剩两处 `random.Random(...)` 裸构造——:746（ctcov 局部子流，
  既有）与 :3049（逐栋主 rng）；无任何 `random.random()` 之类的模块级随机源。
- `_select_fragment_templates` 对主 rng 消费**归零**（唯一 `randrange` 走 ctcov 局部子流），
  两处 `rng.shuffle` 已换 `sorted(key=stable_sort_key(...))`，`rng` 形参已删。✅

---

## 二、必审项②：1a-0 解绑的「只解流不解锚」

### 实查 `deterministic_key` 构成（`validation.py:341-353`）

载荷 = `generator_version` ＋ `registry_bundle_hash` ＋ `random_seed` ＋
`batch_config_hash` ＋ `schema`，**本次一个字节未动**；`registry_bundle_hash` 的载荷
（`version` ＋ `source_documents` ＋ `registries.model_dump`）同样未动。

### 别处是否还在用旧种子：无

全仓 grep：`sidecar_rng` 与 `deterministic_key[` **只在 `validation.py:366` 的沿革注释里各出现一次**，
活代码零命中。sidecar 五个函数与 `validation.py` 的 `rng` 形参已一并删除，
连带消掉 `rng=None → random.Random()` 这个非确定性缺省。
`experiments/audit_archive_20260803/_audit_axes_smoke_20260803.py` 的调用点也已同步（不传 `rng`）。

### 实跑证据（我自己跑的 50 栋池）

| | `deterministic_key` | `registry_bundle_hash` |
|---|---|---|
| HEAD（worktree 8c38690） | `923f9e48…656afffd` | `76caf0af…8170de3` |
| 当前工作树（最终码） | **`923f9e48…656afffd`（逐位相同）** | **`76caf0af…（相同）`** |
| 最终码 ＋ 惰性注册表变异 | `d2a2ee91…7883c71a`（**换了**） | `c8e9e22e…`（换了） |

⇒ **改流不换锚、改注册表仍换锚**，两侧都对。端到端配对里 `world.meta` 逐字节相同。

---

## 三、必审项③：配对脚本七道判据的如实性

### 判据集本身核过：与记录逐条相符

23 个比较单元；各 step 的「须相同」个数：`identity` 23 / `1a-0` 16 /
`registry-mutation` 21 / `1a-i` **12** / `1a-i-prime` **16** / `1a-ii` 4 ——与记录报的一致。

### 我把七道验证在**实施留下的真实中间池**上逐道重放

（中间池 `pool_B0_head` / `pool_B1_1a0` / `pool_B2_1ai` / `pool_B3_1aip` / `pool_B4_1aii` /
`pool_B4_rerun` / `pool_B5_final` 仍在 scratchpad，故步间锚可独立复算——这一点比我预期的好）

| # | 步骤 | 结果 | 我实测的明细 | 与记录 |
|---|---|---|---|---|
| ① | identity 生产池→HEAD | **PASS 23/23** | 340 键 / 11,318 阈值行 / 0 翻判 | 符 |
| ② | 1a-0 | **PASS 16/16** | sidecar 8,299/19,090；翻判 100/340＝29.4%；pass_bool 818 | **逐条符** |
| ③ | registry-mutation（1a-0 后） | **PASS 21/21** | 三项全 0 | 符 |
| ④ | 1a-i（持 sidecar 锚） | **PASS 12/12** | cov_rel 270/340；meas 2,450/6,105；cond.derived 148/340；RAS 回写 30/340；翻判 71/340＝20.9%；阈值行 11,318→11,401 | **逐条符** |
| ⑤ | 1a-i′（持四阶段锚） | **PASS 16/16** | sidecar 8,199/19,090；翻判 101/340＝29.7%；pass_bool 841/11,401 | **逐条符** |
| ⑥ | 1a-ii | **PASS 4/4** | 保留键率 **0.3765**；fragments 340→352 | 符 |
| ⑦ | identity 自检两跑 | **PASS 23/23** | — | 符 |

**另加两道我自己的交叉锚**（记录里没有，用来把中间池链条钉在我亲手跑的代码上）：

- **⑧ 实施的最终池 `pool_B5_final` vs 我用当前工作树自己跑的池 → 23/23 逐字节相同。**
  ⇒ 中间池链条的末端与我实跑的代码同一。
- **⑨ HEAD → 最终码端到端（`--step 1a-ii`）→ PASS 4/4**，`world.meta` 逐字节相同、
  保留键率 0.3765、翻判 52/128。

### 假绿形排查

- **allowed-change 集互斥性**：见 F4——**世界/sidecar 侧确实互斥**（1a-i 允许四阶段五单元
  而要求 sidecar 逐字节同；1a-i′ 反之），但**判定侧 6 个 proj 单元两步都在 allowed 里**，
  故「互斥」字面不成立。要表达的意思（每步持对方的锚）成立。
- **空 PASS 形态**：存在一个（F5），当前未触发——我普查过 23 个单元在真实池里的形状，
  最小 (1,5)、最大 19,642 行，无 None、无空表。
- **判据打印自相矛盾**：一处（F6）。
- **未纳入比较的表**：两张（F5）。

---

## 四、必审项④：15 条性质测试的坍缩变异

### 变异器怎么造的（关键：不重置缓存会得到假红）

把 `rng_domains.sub_rng` 换成「键坍缩到 `(域串, world_id)`、同键共用**一条推进中的流**」，
**并在每个被测顶层函数调用开始时重置缓存**——不重置的话第二次对照调用会接着第一次的
状态跑，任何测试都会红，那种红证的不是隔离、只是「流被推进过」。
另设**无变异对照组**，确认变异器本身没把测试弄坏。

### 实跑结果

| 用例 | 无变异对照 | **坍缩变异** | 记录宣称 |
|---|---|---|---|
| T2 coverage_relations 前插 | 绿 | **红** | 红 ✅ |
| T2 coverage_sampling 前插 | 绿 | **红** | 红 ✅ |
| T2 technical_validation 前插 | 绿 | **红** | 红 ✅ |
| T2 structural_assessment 前插 | 绿 | **红** | 红 ✅ |
| T6 bool 槽插到最前 | 绿 | **红** | 红 ✅ |
| T6 轴积加组合 | 绿 | **红** | 红 ✅ |
| **T6 数值槽追加** | 绿 | **绿** | 红 ❌ **不符（F2）** |

⇒ **「T2 四条 ＋ T6 三条全红」实测是 T2 四条 ＋ T6 两条**。

### 我另做的第二种变异（比坍缩更贴近真实回归形态）——发现 F1

坍缩变异模拟的是 **1a 之前**的病。**1a 之后**真会犯的错是「键写漏一维」——
`sub_rng` 本来就每次新建流，写漏一维只会让若干消费点拿到**同一条新流**。
实测把 `SIDECAR_*` 四个域串各漏掉最后一维（`slot_id` / 规范化 combo）：

    绿 T2 / 绿 T4×3 / 绿 T5 / 绿 T6×3 / 绿 T3 / 绿 T1 / 绿 sub_rng 拒未登记域串
    —— 11 条全绿，一条都没红。

（同一变异施加在**四个阶段域串**上时 T4 会红 ⇒ T4 对它负责的那半边是有效的。）

---

## 五、发现清单（9 条）

### F1【中-高 · 须修】sidecar 侧的防坍缩护栏是空的

**现象**：把 `SIDECAR_NUMERIC` / `SIDECAR_BOOL_BUILDING` / `SIDECAR_BOOL_FRAGMENT` /
`SIDECAR_AXIS_COMBO` 的键各漏掉最后一维（`slot_id`、规范化 combo）——**这正是
`sidecar.py` docstring 里用红字写明「combo 这一维必须有」的那个错**——
15 条性质测试**一条都不红**。

**根因**：漏掉 `slot_id` 后同一 (world, fragment) 内所有槽拿到**同一条新流** ⇒
每个槽的值序列相同 ⇒ 「加一个槽不动既有槽」这条不变式**恒真**，T6 三条同时失效。
而专职防坍缩的 `test_t4_sub_rng_first_draw_differs_across_stage_world_fragment`
只枚举**四个阶段域串**、只跑 `(域串, world, fragment)` 三维，
**从不碰 sidecar 四个域串，也不碰 slot_id / combo 这两维**。

**后果**：1a-i′ 是本案唯一「当前就管着判定」的一步（核清 §0：66.3% 的
`threshold_evaluations` 行来自 sidecar 槽），它的回归探测器却是空的。

**修法**：把 T4 的首抽互异枚举表扩到 `SIDECAR_*` 四域，并把 `slot_id` 与 combo
加进枚举维（形如 `(域串, world, fragment, slot)` 与 `(域串, world, slot, combo)`）。
成本一条测试，不动生产码。

### F2【中 · 须修】`test_t6_numeric_slot_addition_is_a_pure_append` 在坍缩下是绿的

**现象**：该测试用 `records + [extra]` 把探针槽**追加到末尾**，而
`_sample_sidecar_facts_for_fragment`（`sidecar.py:212`）**按列表序**消费记录
⇒ 末尾追加不移动前面的槽 ⇒ 坍缩变异下值全同、测试绿。

**这正是实施记录自己在 §五 写过并已改掉的坑**（「更早一版用追加而非前插…
追加型对照在旧码上也绿、测不出病」）。T6-bool 用 `sampling_order = 1` 排到最前躲开了，
T6-axis 用前插躲开了，**只有 T6-numeric 漏了**（数值槽不按 `sampling_order` 排序，
只能靠改列表位置）。

**我实跑坐实修法**：把入参改成 `[extra] + records`，同一坍缩变异下**当场转红**
（断言消息「前插新槽后既有槽值变了」）。一行改动。

**连带**：实施记录 §五 与台账「T6 三条全红」须改成「T6 两条红、数值槽那条因用
追加型对照而未红，已改前插」。

### F3【中 · 数字口径】「33.2%」不是一个稳定量，是一次抽样

**现象**：惰性注册表变异（`RegistryBundle.version` 加后缀）对 HEAD 的冲击量
**随后缀而变**——同一变异手法换四个不同后缀在 HEAD 上实跑：

| 变异实例 | `sidecar.entries` 差异 | `expected_verdict` 翻判 |
|---|---|---|
| 记录报的那次 | 8,119 / 19,090 | 113 / 340 ＝ **33.2%** |
| 我的 `-RNGISO_AUDIT_MUTATION` | 8,259 / 19,090 | 94 / 340 ＝ **27.6%** |
| 我的 `-mutA` | 8,232 / 19,090 | 106 / 340 ＝ **31.2%** |
| 我的 `-mutB` | 8,153 / 19,090 | 107 / 340 ＝ **31.5%** |
| 我的 `-mutC` | 8,294 / 19,090 | 111 / 340 ＝ **32.6%** |

**该改的**：把「33.2%」写成「**~30% 量级（五次独立变异实测 27.6%–33.2%）**」。
**该撤的**：记录 §一与台账里「官方线 12 栋报 30.4%，**全池口径更高**」这句推断
**不成立**——30.4% 落在全池散布的中段，两者的差不是口径差。

**不受影响的**：定性结论我独立复现并坐实——HEAD 上任何惰性注册表字段变动都造成
~30% 量级背景翻判，**解绑后三项恰好全 0**（我自己跑的 1a-0 后池：21/21 PASS）。
「不解绑则后续每件改动的效应被淹没」这条论证完好。

### F4【低 · 措辞】「1a-i 与 1a-i′ 的 allowed-change 集互斥」字面不成立

两步的 allowed 集**都含全部 6 个 proj 单元**（`projections` / `threshold_evaluations` /
`basis_items` / `matched_families` / `coverage_control_metadata` / `cohort_manifest`），交集非空。
真正互斥的是**世界与 sidecar 侧**：1a-i 允许四阶段五单元变、要求 `sidecar.entries` 逐字节同；
1a-i′ 反之。要表达的意思（**每步持对方的锚**）成立且已被 ④⑤ 两道实测坐实。
**措辞应收窄成**「两步的世界侧 allowed 集互斥；判定侧两步都不设锚」。

### F5【低】配对器的空 PASS 形态 ＋ 两张表未纳入比较

- `compare_unit`（`:417-420`）在**两侧都读不到表**时判 `same`，并计入
  「N 个须相同单元逐字节一致」。改一个 parquet 文件名就会让该单元**静默变成空 PASS**。
  当前 23 个单元在真实池里全部非空（我普查过），**今天没被触发**；
  缺的是一个「两侧都缺 ⇒ FAIL」的分支。
- 池里 **`normative_projection_meta.parquet` 与 `sidecar_runtime_meta.parquet` 不在 23 个单元内**。
  前者**含 `registry_bundle_hash` 与 `deterministic_key`** ⇒ 投影侧的锚没被钉住。
  影响低（`world.meta` 钉住了同源的值），但「只解流不解锚」在投影侧目前无独立证据。

### F6【低】脚本打印的判据在 `registry-mutation` 这一步自相矛盾

`:547` **无条件**打印「其中 world.meta 任何步骤都不许变——只解流不解锚」，
而 `registry-mutation` 的 allowed 集里**恰好有** `world.meta`（实跑输出里它显示 `[允许]`）。
对一个以「判据全部当输出打印」立身的脚本，这一行须按 step 条件化。
另 `reference_metrics`（`:481`）在两侧 `threshold_evaluations` 行数不等时
**静默不打印** pass_bool 那行（1a-i 那道就缺这一行），应改成显式说明「行数不同故不比」。

### F7【低 · 观察，不属 1a】`proj.coverage_control_metadata` 疑似对世界内容不敏感

台账尾巴已记「未追根因」。我补一个数据点：**在 registry-mutation 那道里，它在
94 条 verdict 翻判、800 行 pass_bool 变动之下仍逐字节相同**；在 1a-ii 那道里，
片段从 340 变成 352、保留键率只有 0.3765，它仍逐字节相同。
该表是 50 行 × 7 列的真实内容（含 `raw_candidate_bucket_counts_json` 这种
理应随近阈值分布走的字段）。⇒ 它在 allowed 集里**既不构成锚也不构成信号**，
不像「碰巧没变」，更像根本不读投影结果。**建议单独立项**。

### F8【低】域串登记表不是全仓唯一入口——注释宣称过强

`rng_domains` 模块 docstring 称「域串集中登记在本模块，导入时即做唯一性自检」，
但仓内还有三条**未登记**域串在外面裸构造：

- `generator.py:746` `random.Random(f"ctcov|{building_template_id}|{ctype}")`
- `generator_sampling.py:341` `CHAIN_FACADE_PLAN_v1:`
- `generator_sampling.py:374` `DRAINAGE_AIRBALL_OBS_v1:`
  （另 `:362` 的 `DRAINAGE_UNDERGROUND_v1:` 是纯哈希分桶、不建流）

实际不撞名（前缀不同），但「撞名结构上不可能」这句**只对登记了的九条成立**。
顺带记一条：ctcov 子流的键**不含 `world_id`**（只有 `building_template_id|component_type`），
同楼型跨栋共用同一条流——属既有行为、不在 1a 范围，但与 `rng_domains` ⛔ 反面清单
第二条（「裸 fragment_id 不带 world_id」）**同形**。

### F9【低 · 作业事故披露】我覆盖了一个中间产物

Windows 路径大小写不敏感，我新建的 `pool_head_mut` 与实施留下的 `pool_HEAD_mut`
落到**同一个目录** ⇒ 后者被我的池覆盖。两者都是 scratchpad 临时池
（实施记录 §七 明写「随时可删」），可用 `genpool_head2.py` 任意重生，
**不影响任何已落账结论**。但因此记录报的 8,119 / 113 / 763 那一组数
**我已无法在原池上复算**——F3 的散布是我用四个新后缀独立测出来的。

---

## 六、审核过程中实跑的全部东西（可复算）

| 项 | 命令/做法 | 结果 |
|---|---|---|
| AST 全函数 rng 扫描 | 自写 `rngscan.py` / `s4struct.py` | 见 §一 |
| 50 栋池生成 × 8 | 直调 `run_worldgenerator_fullcoverage_framework_v2`（count=50 / seed=401 / ctcov=on） | 每个 **2.5 秒** |
| HEAD 侧代码 | `git worktree add … HEAD --detach`（收尾已 remove） | 主工作树零改动 |
| 配对 × 13 道 | `verify_rng_isolation_pairing.py` | §三那张表 |
| 坍缩变异 × 3 模式 | 自写 `mutate_probe.py` / `mutate_probe2.py`（补丁打在 `rng_domains.sub_rng`，**不改仓库**） | §四那张表 |
| 全量测试 | `pytest agent_v1/src/workflow_engine agent_v1/tests -q` | **1,454 passed / 2 xfailed / 0 failed**（与记录一致） |
| 比较单元普查 | 自写 `unit_census.py` | 23 单元全非空；2 张表未纳入 |

**未做**：没跑任何带大模型的批、没连 Neo4j、没改法规卡包、没提交任何东西。
池与脚本全部落 scratchpad（仓库外），随时可删。
