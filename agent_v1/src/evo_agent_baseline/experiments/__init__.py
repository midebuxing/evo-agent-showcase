"""evo-agent v1 实验子包（spec v1 §11）。

模块清单：

- ``scaling_law``：spec v1 §11.1-§11.4 运行时 Scaling Law 指标。
  包含 effective trace 计数、E_runtime 综合经验量、三类指标
  （合规质量 / 闭包质量 / Evo 特有）、Error(E)=A·E^-α+β 曲线拟合。
- ``paired_runner``：spec v1 §11.5 + §11.6 数据集分层切分 + paired
  held-out 同 budget/同 model/同 KG 对比 runner（baseline vs evo）。
- ``ablations``：spec v1 §11.7 五个必跑 ablation 配置
  （baseline_static / trace_only / policy_only / skill_only / full_evo）。
- ``run_registry``：实验归档工厂——统一实验目录约定 + 强制 run_meta.json 元数据
  + 机器可读 jsonl / 人类可读 INDEX.md 索引。纯工程基础设施，不读 W2、不介入
  allow_stop、不消费法规真值。

spec→code 单向（项目原则 1）：本子包所有公式 / 阈值 / 配置均锚定 spec v1
§11；不私自加权重 / 不私自改阈值。代码若发现 spec 缺口，应先修 spec，再补码。

evo-agent blind 红线（项目原则 2 + spec v1 §2.2.3）：本子包计算指标 **不**
直接访问 W2 字段；合规质量指标输入是 evaluator 私域产物的 aggregate（已脱
sensitive 字段），closure 质量指标输入是 agent-owned closure artifacts，
Evo 特有指标输入是 traces + skills + policy versions + validation records。

allow_stop 边界（项目原则 3）：本子包 **不** 介入 allow_stop 判定；只读
ClosureValidationResult.allow_stop 做事后统计，绝不回写 verifier。
"""

from __future__ import annotations

__all__ = [
    "scaling_law",
    "paired_runner",
    "ablations",
    "run_registry",
]
