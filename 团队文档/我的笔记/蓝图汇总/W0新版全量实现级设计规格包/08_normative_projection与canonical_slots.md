# Normative Projection 与 Canonical Slots

> 跨包权威源与负向不变量见：`../_封口总则_字段权威源与负向不变量.md`。如本章与总则冲突，以总则和字段所属包权威章节为准。


## 0. 本文档层级归属（2026-05-13 stub 化）

本文档原描述：

1. **W0 静态资源层**：canonical slot universe（原 §1-§5）、`normative_projection_registry` schema 与填表依据（原 §6）、`sidecar_ownership_registry` 引用
2. **法规映射层动作**：projection compile logic（原 §7）、projection fallback 策略（原 §8）、不生成 HiddenGold（原 §9）

**2026-05-13 物理迁出**：按 D-3 决策 + _拆分说明.md 步骤 4，本文档全文物理迁出到 [`W2法规映射层全量实现级设计规格包/`](../W2法规映射层全量实现级设计规格包/)（DEBT-018 落地交付物）。本规格包仅保留路牌 stub。

`NormativeProjection` 本身是法规映射层的参考真值输出，不是 W0 资源层的输出终点；canonical slot universe 是法规映射层的 baseline 框架，跨 W0 (类型分类) + W2 (family coverage + projection binding) 两层。新版 W2 规格包正式承担 canonical slot universe + family coverage + projection binding + compile logic + fallback 全套描述。

## 1. 物理迁出对照表

| 本文件原章节 | W2 规格包对应章节 |
|---|---|
| §1 Canonical slot universe 5 类 slot_class | W2 规格 [`06_canonical_slots与projection_binding.md`](../W2法规映射层全量实现级设计规格包/06_canonical_slots与projection_binding.md) §1 |
| §2 W0 core canonical slots（building / scope / defect / risk / repair / verification + coverage.insufficient world-quality guard） | W2 规格 [`06_canonical_slots与projection_binding.md`](../W2法规映射层全量实现级设计规格包/06_canonical_slots与projection_binding.md) §1（按 5 类 slot_class 归类描述）|
| §3 Measurement canonical slots（coverage / sampling / assessment / repair / verification） | W2 规格 [`06_canonical_slots与projection_binding.md`](../W2法规映射层全量实现级设计规格包/06_canonical_slots与projection_binding.md) §1 |
| §4 Sidecar-only canonical slots（procedure / supervision / artifact / sidecar qualifier） | W2 规格 [`06_canonical_slots与projection_binding.md`](../W2法规映射层全量实现级设计规格包/06_canonical_slots与projection_binding.md) §1 |
| §5 Regulation family coverage（16 family × 5 列大表） | W2 规格 [`06_canonical_slots与projection_binding.md`](../W2法规映射层全量实现级设计规格包/06_canonical_slots与projection_binding.md) §2 |
| §6 `normative_projection_registry` 填表依据（11 字段） | W2 规格 [`06_canonical_slots与projection_binding.md`](../W2法规映射层全量实现级设计规格包/06_canonical_slots与projection_binding.md) §3 + §4 |
| §7 Projection compile logic（伪代码） | W2 规格 [`04_函数实现规格卡.md`](../W2法规映射层全量实现级设计规格包/04_函数实现规格卡.md) §3-§4（主入口 `build_normative_projections_for_world` + `evaluate_fragment_projection_candidates`）+ W2 规格 [`07_threshold_regime与冲突回退.md`](../W2法规映射层全量实现级设计规格包/07_threshold_regime与冲突回退.md) §4（family 冲突解析）+ W2 规格 [`08_unknown策略.md`](../W2法规映射层全量实现级设计规格包/08_unknown策略.md) §2（unknown_reason_code 派生）|
| §8 Projection fallback 策略（`unknown` / `not_applicable` / `covered` / `conflict`；`sidecar_missing` 为旧概念黑名单） | W2 规格 [`08_unknown策略.md`](../W2法规映射层全量实现级设计规格包/08_unknown策略.md) §1（三态语义对照）+ §3（sidecar 派生异常沿用现有 13 条之一兜底，2026-05-13 重审拍板撤回 `sidecar_derivation_failed` 单独 reason_code）+ §4（不在 W2 范围的 fallback）|
| §9 明确不生成 HiddenGold | W2 规格 [`00_范围与过滤决策.md`](../W2法规映射层全量实现级设计规格包/00_范围与过滤决策.md) §3 砍除清单 + W2 规格 [`10_禁止依赖.md`](../W2法规映射层全量实现级设计规格包/10_禁止依赖.md) §2 禁止依赖 10 条（禁 3 / 禁 4） |

## 2. 闭环 trace

- DEBT-018（W0 规格包内含法规映射层内容待迁移）：2026-05-13 闭环（本文件 stub 化是 DEBT-018 落地步骤 4，整个 W2 规格包完成后跟踪表 DEBT-018 ⏳ → ✅ 同步）
- 实现跟踪信息不属于本封口正文；字段与 enum 权威以顶层总则和 W2 06 / 07 / 08 / 09 为准。
- 用户 2026-05-13 决策记录：D-1（coverage_control 归 W2）+ D-2（AdjudicationState 全砍）+ D-3（W0 规格 08 留 stub）+ D-4（rule_card v2 不复写规格 / 备忘留 trace）+ family 数量选甲（维持 16）+ sidecar 派生异常 fallback 沿用现有 13 条之一（2026-05-13 重审拍板撤回原先 sidecar_derivation_failed 选项 B 增订路径）

## 3. 来源

- W2 规格包：[`W2法规映射层全量实现级设计规格包/`](../W2法规映射层全量实现级设计规格包/)（16 文件齐套，2026-05-13 落地）
- _拆分说明.md DEBT-018 关闭路径步骤 4：[`W2法规映射层全量实现级设计规格包/_拆分说明.md`](../W2法规映射层全量实现级设计规格包/_拆分说明.md) §"DEBT-018 关闭路径"
- 跟踪表 + 技术与研究债.md DEBT-018 / DEBT-030 / DEBT-031 全条目

---
