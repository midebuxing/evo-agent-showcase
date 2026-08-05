"""已停用的阈值旁路守卫（DEBT-072）。

`rulecard_threshold_sidecar_v1.json` 现为逐条裁定记录，`status=deferred` 且
`runtime_effect=none`。运行时增广接线已从 `rulecard_loader.py` 删除；本模块只保留
旧环境开关的明确拒绝，防止外部脚本误以为设置开关仍可启用该实验。

严格签名对账结果是 4/5 精确重复；剩余一条 `== 1.0` 对权威索引 `>= 1.0`，
算子不一致，不能再声称“重复 5/5、真新增 0”。旁路仍须停用，因为它还存在
角色混路由、限定符不足、数据传输对象形状不合法与双读径身份闸等结构性问题。
"""
from __future__ import annotations

import os

ENV_FLAG = "EVO_THRESHOLD_SIDECAR"


class ThresholdSidecarError(RuntimeError):
    """旧开关尝试启用已停用实验。"""


def enabled() -> bool:
    """缺省返回假；旧开关为真时明确拒绝，不提供任何增广能力。"""
    if os.environ.get(ENV_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}:
        raise ThresholdSidecarError(
            f"{ENV_FLAG} 已停用（unsupported_experiment）：严格签名仅 4/5 重复，"
            "另 1 条算子不一致且尚未裁定；运行时增广接线已删除。"
            "裁定记录仅供纵切片逐条复核，不产生运行时效果。"
        )
    return False


__all__ = ["ENV_FLAG", "ThresholdSidecarError", "enabled"]