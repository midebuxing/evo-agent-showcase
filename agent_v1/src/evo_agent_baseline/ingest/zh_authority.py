"""中文权威源读取（DEBT-071 丙′ 消费面改指，**默认关闭**）。

## 为什么是开关而不是直接改

改「报告引什么文本」「大模型看什么文本」是**运行时行为变更**——改完消费者看到的报告变、
模型输入也变。两位商议者都要求「消费面切换 + 对账审计**必须同批验收**」，而验收要跑批。

**在没有批次验证的情况下改运行时路径，正是本项目反复栽过的形状**：
2026-07-26 早上，bundle 世界目录格式写成绝对路径（应为目录名）→ 组件结构早退**全关** →
**2,588 个测试与 12 项发布门禁全绿**，跑了 8 栋才被「新批 vs 旧批逐栋对账」抓出来。

故本模块**默认关闭**：不设 `EVO_ZH_AUTHORITY=1` 时行为与改动前**逐字节相同**。
验证批只需翻开关，对照同池同库的旧批即可确认改指是否只动了叙述面。

## fail-closed

开关**打开**但附件缺失/过期 → **抛错拒跑**，绝不静默回退到英文。
静默回退正是「关键配置静默退化」那一族的成员（见 CLAUDE.md 红线）：
配置没生效、行为退回旧路径、而没有任何东西报错。

## 权威关系

中文正文是**权威**；卡的 `source_quote` / `normalized_rule_text` 是**译文**
（卡自身 `provenance` 写明 `source_quote_policy=translated_load_bearing_quotes`，
且仓库里没有英文版守则）。实测 386/397 张卡的译文里 **140 张（36.3%）不忠实**。
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import pathlib
from typing import Optional

_ENV_FLAG = "EVO_ZH_AUTHORITY"
_SIDECAR_REL = ("agent_v1/regulations/rulecard_v2/mbis_cop_2023/"
                "rulecard_zh_sidecar_v1.json")
_REGULATION_REL = "agent_v1/regulations/markdown/MBIS_CoP_2023.md"


def enabled() -> bool:
    """中文权威源是否启用。**默认关闭**——不设环境变量时行为与改动前完全一致。"""
    return os.environ.get(_ENV_FLAG, "").strip() in {"1", "true", "True", "yes"}


def _repo_root() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[4]


@functools.lru_cache(maxsize=1)
def _load() -> dict:
    """加载附件并校验它与当前法规原文对得上。**fail-closed，不静默回退。**"""
    root = _repo_root()
    path = root / _SIDECAR_REL
    if not path.is_file():
        raise RuntimeError(
            f"{_ENV_FLAG} 已启用但中文权威源附件不存在：{path}\n"
            f"请先跑 `agent_v1/scripts/build_rulecard_zh_sidecar.py --out <该路径>`。"
            f"**不静默回退到英文**——静默退化正是本项目反复栽过的那一族。")
    doc = json.loads(path.read_text(encoding="utf-8"))
    reg = root / _REGULATION_REL
    actual = hashlib.sha256(reg.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    if doc.get("regulation_sha256") != actual:
        raise RuntimeError(
            f"{_ENV_FLAG} 已启用但附件与当前法规原文不符（附件已过期）：\n"
            f"  附件记 {str(doc.get('regulation_sha256'))[:16]}… / "
            f"实际 {actual[:16]}…\n请重建附件。**不静默回退。**")
    return doc


def zh_text_for_card(rule_card_id: str) -> Optional[str]:
    """取该卡对应的中文正文；开关未开、或该卡显式缺席时返回 None。

    ⚠️ 返回 None 有两种含义，调用方按同一种处理（回退到英文）即可：
      ① 开关未开（默认）——行为与改动前一致；
      ② 开关已开但**该卡显式缺席**（`cn_text: null`，11/397 张，附录表格类等）。
    但**附件缺失或过期**不属于这里——那会在 `_load()` 抛错，绝不返回 None。
    """
    if not enabled():
        return None
    entry = (_load().get("cards") or {}).get(rule_card_id) or {}
    text = entry.get("cn_text")
    # 空串伪装防线:构建器已禁，这里再挡一次——`""` 绝不能被当成"有正文"
    return text if isinstance(text, str) and text.strip() else None


def reset_cache() -> None:
    """测试用:清掉附件缓存（改环境变量或改附件后需调用）。"""
    _load.cache_clear()
