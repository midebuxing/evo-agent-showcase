# round 3 封口方案落地说明

## 1. 成功落地的 round 2 子节

### W0：round 2 §3

- ✅ §3.1 W0 registry 数量与文件名一次收敛：`02_资源域与19张注册表.md` 已创建；`02_资源域与17张注册表.md` 保留为旧路径 stub。
- ✅ §3.2 W0 README 第一屏替换：首屏已切换为封口版定位，并加入顶层总则 cross-ref。
- ✅ §3.3 W0 `00_术语表与名词解释.md` 局部替换：19 registry、`RegistryTable` 总数、`normative_projection_registry` 权威源、provenance 口径已收敛。
- ✅ §3.4 W0 `01_设计原则与本体边界.md` 局部替换：W0 定位、19 registry、当前工程估值 token 与非 pending 说明已落地。
- ✅ §3.5 W0 `03_registry_schema_matrix.md` 局部替换：开头 19 registry 口径与 W2 字段权威说明已落地。
- ✅ §3.6 W0 `04_生成实例与法规映射参考真值字段合约.md` 核心迁出：§§18-21 已 stub 化，字段权威迁至 W2 `09_输出契约_NormativeProjection.md`。
- ✅ §3.7 W0 `06_surrogate公式噪声与unknown策略.md` provenance 与 unknown 收口：authority token、sidecar fallback、W2 unknown cross-ref 已落地。
- ✅ §3.8 W0 `07_约束与失败策略.md` 局部替换：W2 输出约束迁出 stub 与 unknown fallback 路径已落地。
- ✅ §3.9 W0 `09_sidecar边界契约.md` sidecar 输出策略替换：三态 join 语义与 `sidecar_only_fact_pattern` 路径已落地。
- ✅ §3.10 W0 `10_批次QA版本与实现缺口.md` 退出正式封口正文：旧文件已 stub；新增 `10_规格版本与发布口径.md`。

### W1：round 2 §4

- ✅ §4.1 W1 README 替换：首屏已改为封口版，加入顶层总则 cross-ref 与 W1 rule-blind / W2 只读边界。
- ✅ §4.2 W1 `00_范围与过滤决策.md` 状态替换：W2 状态改为封口版，不再保留待建口径。
- ✅ §4.3 W1 `02_输入合约与W0依赖.md` registry 依赖替换：W0 registry 总数更新为 19，并补 W2 / rule_card 禁读边界。
- ✅ §4.4 W1 `06_测量噪声三层合约.md` authority token 替换：DEBT pending token 已替换为当前封口 authority token。
- ✅ §4.5 W1 `09_物理一致性+多样性并存机制.md` coverage control 边界替换：coverage control 迁至 W2 11，不回传 W1。
- ✅ §4.6 W1 `10_禁止依赖.md` 红线补丁：W2 法规侧信号、rule_card 与 evo-agent 训练反馈禁读表已补。
- ✅ §4.7 W1 保持不动章节与质量验证：主流程章节只接收 cross-ref 与局部旧口径清理，未做整章重写。

### W2：round 2 §5

- ✅ §5.1 W2 README 替换：首屏已改为封口版，加入顶层总则 cross-ref 与 W2 reference-truth 定位。
- ✅ §5.2 W2 `00_术语表与名词解释.md` enum 收口：`expected_verdict`、`pending`、`sidecar_derivation_failed`、`final_decision` 口径已收敛。
- ✅ §5.3 W2 `01_设计原则与本体边界.md` 增补 Closure Verifier / 副驾驶边界。
- ✅ §5.4 W2 `02_输入合约与W0_W1依赖.md` 补只读红线：W2 不读取 W1 内部派生、不回写 W1、不消费 evo-agent 训练数据。
- ✅ §5.5 W2 `06_canonical_slots与projection_binding.md` spec 权威收口：16 family baseline、records 权威、full evaluator 与 simplified route 边界已收敛。
- ✅ §5.6 W2 `07_threshold_regime与冲突回退.md` 收口：threshold regime 以 spec-side 表为准，历史实现侧口径不构成权威。
- ✅ §5.7 W2 `08_unknown策略.md` final 收口：13 reason code、三态 sidecar join、无第 14 条 reason code 已落地。
- ✅ §5.8 W2 `09_输出契约_NormativeProjection.md` 核心替换：整章替换为封口版字段合约。
- ✅ §5.9 W2 `10_禁止依赖.md` 撤回残留替换：sidecar join consistency 与禁止依赖表已收敛。
- ✅ §5.10 W2 `11_coverage_controlled_rejection.md` 核心替换：输入/输出、重采样路径、W1/evo-agent/Closure Verifier 边界已落地。
- ✅ §5.11 W2 `_rule_card_v2现状注解.md` 降级为备忘：首屏非权威备忘声明已加入。
- ✅ §5.12 W2 保持不动章节与质量验证：W2 03/04/05 与部分 06/07/08 主体保留，只按方案 patch 旧口径。

### cross-ref 与全包收敛：round 2 §6-§9

- ✅ §6.1 README 共同首屏 cross-ref：W0/W1/W2 README 第一屏均有顶层总则 cross-ref。
- ✅ §6.2 字段表重复删除规则：W0 04 的 W2 输出字段表已迁出；W2 09 为 `NormativeProjection` 等字段权威源。
- ✅ §6.3 撤回词全包搜索替换规则：全包 grep 后，残留只在已撤回 / 禁止 / 黑名单 / 旧路径 stub 说明语境中。
- ✅ §7 对旧蓝图的封口说明：顶层总则与 W2/W0/W1 局部口径已承接保留 / 偏离授权。
- ✅ §8 最终封口后的对外报告口径：已体现在三包 README、W0 `10_规格版本与发布口径.md`、W2 09 / 10 / 11 等权威章节中。
- ✅ §9 保持不动的总体验证：保持不动章节未整章重写，只接收 cross-ref 与明示 patch。

## 2. 边界模糊处的默认决定

- ⚠️ W0 `_拆分说明.md`：round 2 明示 W0 02 改名并保留旧文件 stub，但未单独说明 `_拆分说明.md` 文件清单；默认同步文件清单到 `02_资源域与19张注册表.md` / 旧 stub，以避免包内索引仍指向旧正式正文。
- ⚠️ W0 / W1 / W2 `99_来源索引.md`：round 2 §6.3 要求全包移出 “当前代码 / gap / 工单” 正文口径；默认将 source index 改为封口版来源索引，不再承载实现跟踪。
- ⚠️ W2 `08_unknown策略.md`：round 2 写“替换 §3.5”，现有文件结构中对应语义已在 §3.2；默认按语义落在现有 `sidecar_join_status` 小节，不强行重编号。
- ⚠️ W2 `_拆分说明.md`：round 2 §9 明示当前状态行改为封口版；默认同时把尾部历史闭环标题降级为历史拆分闭环记录，避免正式状态与工程进度混写。
- ⚠️ W0 旧路径 `10_批次QA版本与实现缺口.md`：文件名按方案保留为 stub，因此 sanity grep 会命中文件名中的“实现缺口”；该命中不属于正文权威内容。

## 3. sanity check 结果

1. ✅ 撤回词全包 grep：`sidecar_derivation_failed`、`sidecar_missing`、`pending verdict`、`DEBT021_pending`、`domain expert 复核`、`W2 待建 / 正在建立 / 框架建立中` 均已检查；残留仅在“已撤回 / 禁止 / 黑名单 / 旧概念 / 旧别名 / 状态措辞禁入”说明中。
2. ✅ registry 数字一致：全包未发现未标注旧口径的 “18 张 registry / 18 张表 / 18 张注册表”；正式口径为 19 张 registry。
3. ✅ 顶层封口总则文件存在：`spec包/_封口总则_字段权威源与负向不变量.md` 已创建；三包 README 第一屏均有 cross-ref。
4. ✅ W0 02 文件改名完成：`02_资源域与19张注册表.md` 存在；`02_资源域与17张注册表.md` 保留为 stub。
5. ✅ W0 04 §§18-21 已 stub 化迁出：W0 不再维护 `NormativeProjection` / `ProjectionFamilyEval` / `ThresholdEval` / `ReportBasisItem` 字段表；W2 `09_输出契约_NormativeProjection.md` 为字段权威源。
6. ⚠️ 实际 edit 文件列表 vs round 2 方案：48 个 spec 文件发生变更。变更均属于 round 2 明示处置、§6.3 全包搜索替换、或上述 metadata 默认决定；未对保持不动章节做方案外整章重写。

## 4. 修订后 spec 包统计

- 修订后 `spec包/` 文件总数：52
- 修订后 `spec包/` 总大小：858130 bytes（约 838.0 KiB）
- 新增正式文件：3 个（`_封口总则_字段权威源与负向不变量.md`、W0 `02_资源域与19张注册表.md`、W0 `10_规格版本与发布口径.md`）
- output zip 根目录新增说明文件：1 个（`_round3_落地说明.md`）
- 改名 / stub 化对象：W0 02 旧路径 stub + 新正式文件；W0 10 旧路径 stub + 新正式文件；W0 04 §§18-21 字段表 stub 化迁出。
- 实际 edited file 数：48

## 5. 其他说明

- 沙箱实际工作目录：`/mnt/data/round3_edit/`。
- 打包内容：修订后的 `spec包/` + 本说明文件。
- 本说明不作为 spec 权威正文；spec 权威以 output zip 内 `spec包/` 为准。
