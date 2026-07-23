# W2 法规映射层全量实现级设计规格包

状态：数据生成层封口版。

跨包权威源与负向不变量先读：`../_封口总则_字段权威源与负向不变量.md`。

如本包正文与该总则冲突，以总则和字段所属包的权威章节为准。

W2 消费 W0 静态资源、W1 已生成的世界事实、SidecarRuntimeBundle、rule_card v2 bundle 与 projection runtime mapping，生成 per-fragment `NormativeProjection` 和 batch 级法规映射输出。

W2 的职责是生成训练 / 评测用 reference truth，不替代人类巡检员作最终决定。`expected_verdict` 是 W2 reference truth，不是 `final_decision`。

本包权威内容：

- 16 family baseline 与 projection binding：`06_canonical_slots与projection_binding.md`
- threshold regime 与 conflict fallback：`07_threshold_regime与冲突回退.md`
- unknown strategy：`08_unknown策略.md`
- `NormativeProjection` 输出契约：`09_输出契约_NormativeProjection.md`
- W2 禁止依赖：`10_禁止依赖.md`
- coverage-controlled rejection：`11_coverage_controlled_rejection.md`

本包不复写 rule_card v2 数据规格；rule_card v2 独立由 manifest + 13 sub-file + `projection_runtime_mapping_v1.json` 负责。

本包不记录实现状态、测试状态或工程推进状态。历史实现对照只可留在非正式工程跟踪区。

## 4. 文件清单

见 `_拆分说明.md`。

## 5. 项目原则（继承 W0/W1 包 + W2 端特化）

- **规格到代码单向**（按 memory `feedback_spec_to_code_one_way.md`）
- **rule-blind 红线只属 W0/W1，不延伸到 W2**（按 memory `feedback_rule_blind_only_w0_w1.md`）：W1 worldgen 受 rule-blind 红线约束不读 rule_card 反推世界；W2 法规映射层**合法消费** rule_card / projection_registry 是 W2 本职工作，**不是** rule-blind 红线的"消费方"或"反向延伸"
- **W2 自身红线**（跟 rule-blind 正交，详见 W2 规格 10 §2 10 条）：W2 不反向写回 W1 输出 / 不伪造世界事实补全 sidecar / 不生成 HiddenGold / 不消费 evo-agent 训练数据
- **不混 artifact / procedure 进 world truth**（W2 projection 可消费 sidecar 但不修改 W1 输出）
- **a9 投影器降级原则**：法规不再驱动世界生成，仅在世界生成完之后做投影（W2 在世界生成完后跑）
- **HiddenGold 全砍**（用户原则 09.md L20-L25）
- **AdjudicationState 全砍**（用户 D-2 决策 2026-05-13）

## 6. 封口发布口径

本包是 W2 法规映射层封口版。W2 只声明法规映射层输入、projection binding、threshold regime、unknown strategy、输出契约、禁止依赖与 coverage-controlled rejection；不记录实现状态、测试状态、工程任务或后续迁移路径。

---

**状态**：2026-05-13 W2 封口版，详见 `_拆分说明.md` 文件清单。
