"""evo-agent 公共异常类型。

放在包根、零业务依赖，供 agent.hooks / ingest.guard 等各层共享，避免同名异常
在不同模块各定义一份导致**跨层 except 漏接**：blind 违规从检索/灌库层冒到编排层时，
必须是同一个 SecurityError 类，run_orchestrator 的 `except SecurityError` 才能捕获并
转成 status=blocked（否则漏接、违背"blind 违规不抛给调用方"的契约）。
"""

from __future__ import annotations


class SecurityError(Exception):
    """blind 红线违规异常。

    任一层（hooks 输入/输出守卫、ingest/retrieval 的 DTO blind 校验）检出 W2 参考真值 /
    evaluator-only 内容 / 禁止属性·标签时抛出；上层编排归一为
    stop_reason=forbidden_reference_truth_detected、run status=blocked。

    **唯一定义点**：agent.hooks 与 ingest.guard 均从这里 import 复用同一个类，
    确保跨层 ``except SecurityError`` 能捕获任意一层抛出的实例。
    """
