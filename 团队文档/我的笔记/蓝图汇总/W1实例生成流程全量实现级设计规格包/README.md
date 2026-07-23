# W1 实例生成流程层全量实现级设计规格包

状态：数据生成层封口版。

跨包权威源与负向不变量先读：`../_封口总则_字段权威源与负向不变量.md`。

如本包正文与该总则冲突，以总则和字段所属包的权威章节为准。

W1 使用 W0 静态资源生成具体 `WorldBundle` 与 `SidecarRuntimeBundle`。W1 的核心边界是 rule-blind：W1 不读取 rule_card v2，不读取 W2 family / threshold / regime / unknown reason，不为了下游法规标签反推世界生成参数。

W1 输出是 W2 的只读输入。W2 可以读取 W1 已采样的具体事实，但不得反写 W1 输出，不得读取 W1 内部 distribution / surrogate / recommended_mean / seed 策略。

阅读顺序：

1. 先读 `../_封口总则_字段权威源与负向不变量.md`。
2. 再读 `00_范围与过滤决策.md` / `01_设计原则与本体边界.md`。
3. 输入依赖以 `02_输入合约与W0依赖.md` 为准，其中 W0 registry 总数为 19。
4. 生成流程以 `03`-`09` 为准；禁止依赖以 `10_禁止依赖.md` 为准。

本包不记录实现状态、测试状态或工程推进状态。

## 3. 来源文件

本规格包从以下三方对照整理：

### 3.1 旧蓝图（pro-answer/，按相关性排）

| 文件 | 主要贡献 |
|---|---|
| `a8.md` (536 行) | **WorldGenerator 主设计原则**：fragment-driver-mechanism-damage-measurement 因果链 + observation/projection/gold 严格解耦 + 5 件物理一致性保障 |
| `a12.md` (2187 行) | full-coverage **完整规格**：字段合约 / Registry schema / Archetype / 枚举 / 参数 / 10 段函数 / 噪声 / 约束 / 派生 |
| `a10.md` (2336 行) | 三个 seed slice 字段级 / registry / surrogate **可编码规格** |
| `a11.md` (596 行) | a10 → full-coverage 扩展（universal substrate / unified defect / measurement taxonomy）|
| `a9.md` (939 行) | 法规从世界生成器降级为投影器；fragment world model + 独立 gold |

**警惕**（按 memory `feedback_legacy_blueprint_name_drift.md`）：
- a3-a7 早期 latent case / fragment hypergraph / claim-evidence graph 等设计已演进，**名字变了不要硬塞**
- a12 §1.3.4 HiddenGold / §7.10 hidden_gold 输出已删除（spec 09 §1.2 修订 2026-05-09 + 用户原则 09.md L20-L25）
- 巡检员模拟 / investigator simulation / QueryEpisode / AdjudicationState 等 a9 涉及的概念，新版砍掉

### 3.2 W0 包内待物理迁出章节（DEBT-019 trace）

| W0 包源 | 迁出对象 |
|---|---|
| `05_生成流程与依赖.md` 整文（除 §0 + §1 第 0 步保留 W0）| §1 第 1-5 步 + §2 1-9 段函数总表 + §3.1-§3.9 函数实现规格卡 + §4 依赖图 + §5 禁止依赖 |
| `06_surrogate公式噪声与unknown策略.md` | §13 / §14 测量噪声 / unknown 策略（实例生成阶段消费部分）|
| `07_约束与失败策略.md` | §1 P0/P1/P2/P3 优先级体系 + 实例生成阶段约束 |

W0 包对应章节**保留作"接口契约"级别引用 stub**，本包是 detailed 实现规格。

### 3.3 代码 cross-ref

W1 spec 只声明实例生成流程规格；具体模块 / 符号 / 行号 / 实施完成度不进入封口 spec。

## 4. 文件清单

见 `_拆分说明.md`。

## 5. 项目原则（继承 W0 包）

- **spec → code 单向**（按 memory `feedback_spec_to_code_one_way.md`）
- **rule-blind**：W1 输出不消费 rule_family_id / 阈值 / gold（按 a8 §6 三层接口定义）
- **不混 artifact / procedure 进 world truth**（W1 输出严格按字段合约 a12 §1.1，artifact/procedure 走 sidecar）
- **双向锚点对齐 + evo-agent blind**（按 memory `feedback_dual_anchor_alignment_evo_agent_blind.md`）
- **数据生成层内部自洽，最后才映射对齐**（按 memory `feedback_generation_layer_internal_self_consistent.md`）

## 6. 封口发布口径

本包是 W1 实例生成流程层封口版。W1 只生成 worldgen 事实与 sidecar runtime bundle，保持 rule-blind；不记录实现状态、测试状态、工程任务或后续迁移路径。

---

**状态**：2026-05-12 W1 封口版，详见 `_拆分说明.md`。
