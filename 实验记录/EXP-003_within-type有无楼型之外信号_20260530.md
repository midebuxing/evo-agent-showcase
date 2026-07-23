# 实验报告 EXP-003：within-type 有没有"楼型之外"的信号（type-level 是不是天花板）

- **日期**：2026-05-30（夜）
- **状态**：✓ 完成（确定性，不烧 token）

## 由来
EXP-001 得 type-only 天花板 0.571。问：同楼型内不同楼 fail 落在不同家族（如 UBW-PRONE 有的 fire、有的 ubw），**这栋楼的 salient_facts 能不能区分它 fail 在哪个家族**？能 → 0.571 之上有空间、值得上"数值→语义翻译"；不能 → type-level 就是天花板。

## 方法
每测试型 ~30 栋（UBW 38/TONG 34/LEGACY 29）。salient_facts 向量化 → fail 家族，sklearn LOO 交叉验证，对比模态基线。**含旗标 vs 纯测量量两版**（见下方泄漏发现）。脚本 `杂物箱/exp003_withintype_probe.py` + `exp003_diag_leakage.py`。

## 结果

| 楼型 | fail 家族分布 | 模态基线(LOO) | 含旗标 facts | 纯测量量 facts | 主判据差 |
|---|---|---|---|---|---|
| UBW-PRONE | ubw×22/fire×16 | 0.579 | 1.000 | 0.605 | **+0.026**（噪声）|
| TONG-LAU | 7 类(剔罕见后 5 类) | 0.333 | 0.233 | 0.300 | **−0.033**（输模态）|
| LEGACY | fire×16/ubw×13 | 0.552 | 0.724 | 0.724(DT)/0.586(LR) | **+0.172**（仅 DT, n=29 孤证）|

## 结论
**within-type 基本无真信号，type-level（0.571）≈ 天花板。** 纯测量量 3 型里 2 型 ≤ 模态、1 型仅弱 DT 信号（单型 n=29、非线性、不足以拍板）。**"数值→语义翻译"收益太小、证据不足以支撑做。** 闭合了 EXP-001 最后一个开放问题：分诊技能本质是 **type-level**。

## ★ 关键方法论发现（泄漏陷阱，必须记住）
原始 salient_facts 看着很能分（含旗标版 UBW 冲 1.000，+0.421），但这是**结构泄漏**：驱动特征是 `defect.<family>.present` / `deficiency_present` / `verification_failed` / `severity_index` 这类**缺陷/验证状态旗标——直接复述 W2 verdict**（等价偷看答案）。剔掉、只留真几何/物理测量量（crack_width/spall_area/thickness/age/carbonation/moisture…）后就塌回模态水平。

**→ 任何 facts→fail-family 实验（含将来真上 LLM 翻译）必须先剔这类状态旗标**，否则 0.571 天花板会被泄漏假象击穿。**EXP-001/002 未受影响**（它们喂的是楼型名+O+审计实例，不是 salient_facts）。
