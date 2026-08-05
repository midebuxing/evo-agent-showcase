"""LLM 客户端封装（spec §7 LLM 接入 + §1.0 原则 1 backbone deterministic）。

baseline LLM-as-brain 的入口。用 `openai` SDK 接 OpenAI 兼容协议
（本机默认 Ollama `http://127.0.0.1:11434/v1`）；生产可换 Anthropic / 云端
任何 OpenAI 兼容 endpoint。

设计原则（与 spec §1.0 + §7.3 一致）：

1. LLM 只做**自然语言生成 + 工具编排**，不能覆盖确定性决策：
   `allow_stop` 由 `closure_verifier` 决定，LLM 不可改；
   `closure_status` / `satisfaction_status` 由 deterministic 派生，LLM 不可改。
2. 所有 LLM 输出必须过 `pre_output_language_guard`（spec §7.3.6）；
   所有 LLM 工具调用结果必须过 `post_retrieval_source_audit`
   （spec §7.3.4），防 W2 leakage。
3. 不依赖 LLM 进行任何 W2 reference truth 推理（spec §2.2.3 blind 红线）。
4. LLM 失败时编排器应有 deterministic fallback（不强求 LLM 必跑通）。

evo-agent blind：LLM 通过 system_prompt 被告知禁止 W2，prompt 内容由
`system_prompt.txt` 提供（同时被 hook 二次拦截 LLM 输出）。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # 可选依赖：单测 / deterministic mode 不需要 LLM
    from openai import OpenAI
    from openai.types.chat import ChatCompletion

    _OPENAI_OK = True
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment]
    ChatCompletion = Any  # type: ignore[misc,assignment]
    _OPENAI_OK = False


# ---------------------------------------------------------------------------
# 默认配置（本机 Ollama；env 可覆盖）
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "qwen3.5:latest"
DEFAULT_API_KEY_PLACEHOLDER = "ollama"  # Ollama 不校验 key，placeholder 即可

# spec §7.5 / §6.5：LLM 工具调用循环上限，防 LLM 失控无限调工具。
# 11 个 tool + agentic 深入查询（lookup_rule_card / lookup_clause /
# search_regulation）通常需要 8-15 轮；默认 16 给足空间，env 可覆盖。
# 2026-05-29：降为 8 减少 sixthsense LLM call 总数（防风控 + 加速跑批）.
DEFAULT_MAX_TOOL_ITERATIONS = 8


def _chat_timeout_seconds() -> int:
    """原生 `/api/chat` 的请求超时（秒），可用 `EVO_AGENT_LLM_TIMEOUT` 覆盖。

    缺省 600 与改动前一致。**首栋要叠「灌库 + 冷推理」，实测 600 秒会超**——
    2026-07-26 试跑两栋全部 `timed out` → `tool_call_missing` → 整批判废。
    非法值（非正整数）一律回落缺省并出声，不静默用一个坏值。
    """
    import os as _os
    raw = (_os.environ.get("EVO_AGENT_LLM_TIMEOUT") or "").strip()
    if not raw:
        return 600
    try:
        v = int(raw)
        if v <= 0:
            raise ValueError(raw)
        return v
    except ValueError:
        print(f"[llm_client] ⚠️ EVO_AGENT_LLM_TIMEOUT={raw!r} 非法，回落缺省 600 秒")
        return 600


def _num_gpu_layers() -> Optional[int]:
    """试验驱动可选的向下驻留层数；未设置时保持 Ollama 自动分配。"""
    raw = (os.environ.get("EVO_AGENT_LLM_NUM_GPU") or "").strip()
    if not raw:
        return None
    value = int(raw)
    if value < 0:
        raise ValueError("EVO_AGENT_LLM_NUM_GPU 必须为非负整数")
    return value


@dataclass
class LLMConfig:
    """LLM 接入配置（env 优先：EVO_AGENT_LLM_*）。"""

    base_url: str = field(
        default_factory=lambda: os.environ.get("EVO_AGENT_LLM_BASE_URL", DEFAULT_BASE_URL)
    )
    model: str = field(
        default_factory=lambda: os.environ.get("EVO_AGENT_LLM_MODEL", DEFAULT_MODEL)
    )
    api_key: str = field(
        default_factory=lambda: os.environ.get(
            "EVO_AGENT_LLM_API_KEY", DEFAULT_API_KEY_PLACEHOLDER
        )
    )
    temperature: float = 0.1
    # 满血档"查询次数不设限"经 env 放开（EXP-008 用高位兜底如 64 防失控）；
    # 默认 8 保持主线行为不变。此前注释承诺 env 可覆盖但未实现，此处兑现。
    max_tool_iterations: int = field(
        default_factory=lambda: int(os.environ.get(
            "EVO_AGENT_LLM_MAX_TOOL_ITERATIONS", DEFAULT_MAX_TOOL_ITERATIONS
        ))
    )
    # 单次 LLM 调用最大输出 token 数；qwen3.5 默认 32k context，留余地。
    max_response_tokens: int = 2048
    # 上下文窗口（Ollama `num_ctx`）。**必须显式设**：Ollama 默认只给 4096，
    # 不看模型本身支持多大——超出部分**静默截断对话前端**（系统提示词与 v3 提交
    # 契约正在那里），模型因此交不出合格提交。2026-07-20 实证：同一长提示词
    # 不设 num_ctx → prompt_eval_count 卡死 4096、开头信息丢失；设 16384 →
    # 6050 全量入模、答案正确。重锚批 30 栋中 9 栋"未提交可用分析"即此因
    # （末轮提示 token 全部恰为 4096）。env: EVO_AGENT_LLM_NUM_CTX
    num_ctx: int = field(
        default_factory=lambda: int(os.environ.get("EVO_AGENT_LLM_NUM_CTX", "16384"))
    )
    num_gpu: Optional[int] = field(default_factory=_num_gpu_layers)
    # 关思考模式（推理模型如 qwen3.5 输出进 reasoning、content 空 → agentic 循环里
    # forced_finalize 空响应早退；见记忆 reference_reasoning_model_empty_content_ollama）。
    # 置真 → 走 Ollama 原生 /api/chat + think:false（content 直出）。默认关（保 openai SDK
    # 主路不变，云端 OpenAI 端点不受影响）。env: EVO_AGENT_LLM_THINK_OFF=1
    think_off: bool = field(
        default_factory=lambda: os.environ.get(
            "EVO_AGENT_LLM_THINK_OFF", ""
        ).strip().lower() in ("1", "true", "yes", "on")
    )


@dataclass
class LLMTurn:
    """一轮 LLM 调用的输入输出记录（供 run_audit 落库 + 调试）。"""

    iteration: int
    response_text: str
    tool_calls: List[Dict[str, Any]]
    finish_reason: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    elapsed_seconds: Optional[float] = None


class LLMClient:
    """OpenAI 兼容协议 LLM 客户端（默认 Ollama 本机部署）。

    用法：
        client = LLMClient(LLMConfig())
        result = client.chat(
            messages=[{"role": "system", "content": SYSTEM_PROMPT}, ...],
            tools=[{...}, ...],
        )
        # result.tool_calls -> 处理 tool 调用，append tool_result，再 chat 一轮。
    """

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        if not _OPENAI_OK:
            raise RuntimeError(
                "openai SDK 未安装；`pip install openai` 后再用 LLM-as-brain 模式。"
            )
        self.config = config or LLMConfig()
        self._client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )

    # ------------------------------------------------------------------ #
    # 单轮 chat（含 tool calling）
    # ------------------------------------------------------------------ #
    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        iteration: int = 0,
    ) -> LLMTurn:
        """单轮 chat completion。返回 `LLMTurn` 含 LLM 文本 + tool_calls。

        tools 为 OpenAI function calling 格式列表；None 时不带工具。
        """
        if self.config.think_off:
            return self._native_chat_think_off(messages, tools, iteration)
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_response_tokens,
        }
        # Ollama 的 OpenAI 兼容端点同样默认 num_ctx=4096 并静默截断前端；
        # 经 extra_body 透传（云端 OpenAI 会忽略未知字段，故对云端无害）。
        options: Dict[str, Any] = {}
        if self.config.num_ctx:
            options["num_ctx"] = self.config.num_ctx
        if self.config.num_gpu is not None:
            options["num_gpu"] = self.config.num_gpu
        if options:
            kwargs["extra_body"] = {"options": options}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        started_at = time.perf_counter()
        resp = self._client.chat.completions.create(**kwargs)
        elapsed_seconds = round(time.perf_counter() - started_at, 6)
        choice = resp.choices[0]
        msg = choice.message

        tool_calls_out: List[Dict[str, Any]] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls_out.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments_json": tc.function.arguments,
                    }
                )

        usage = getattr(resp, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
        completion_tokens = (
            getattr(usage, "completion_tokens", None) if usage else None
        )

        return LLMTurn(
            iteration=iteration,
            response_text=msg.content or "",
            tool_calls=tool_calls_out,
            finish_reason=choice.finish_reason or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_seconds=elapsed_seconds,
        )

    # ------------------------------------------------------------------ #
    # think_off 路径：Ollama 原生 /api/chat + think:false（推理模型关思考）
    # ------------------------------------------------------------------ #
    def _native_chat_think_off(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        iteration: int,
    ) -> LLMTurn:
        """走 Ollama 原生 /api/chat 关思考。返回同一 LLMTurn 契约。

        为何：openai `/v1` 端点关不掉推理模型思考（think:false/no_think 均不认），
        content 常空 → agentic 循环 forced_finalize 空响应早退。原生 /api/chat 的
        think:false 让 content 直出。仅 Ollama 本机用；云端 OpenAI 端点勿开此旗标。
        适配：tool_calls.function.arguments 是 dict（转 JSON 串对齐下游）、done_reason
        代 finish_reason、eval_count/prompt_eval_count 代 usage。
        """
        import json as _json
        import urllib.error as _uerr
        import urllib.request as _url

        base = self.config.base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        # 云端护栏（codex 审核门）：原生 /api/chat 只对本机 Ollama 有意义（无
        # Authorization、路径不同）；误对云端 OpenAI 端点开 think_off 会打错端点。
        # 非本机且未显式放行则拒绝。
        _host = base.split("://")[-1].split("/")[0].split(":")[0].lower()
        if _host not in ("localhost", "127.0.0.1", "::1", "[::1]") and \
                os.environ.get("EVO_AGENT_LLM_ALLOW_NATIVE_OLLAMA", "").strip().lower() \
                not in ("1", "true", "yes", "on"):
            raise ValueError(
                f"think_off(原生 /api/chat)只支持本机 Ollama；base_url={self.config.base_url}"
                " 非本机。自托管 Ollama 请设 EVO_AGENT_LLM_ALLOW_NATIVE_OLLAMA=1 放行。"
            )
        endpoint = base + "/api/chat"
        # 归一化 messages 到 Ollama 原生格式（含 codex 审核门补丁）：
        # - assistant tool_calls.arguments: OpenAI 的 JSON 字符串 → 原生要 dict（否则
        #   400 "looks like object..."）；且剔除 OpenAI-only 的 id/type（原生不需要）。
        # - tool 结果消息：原生要 tool_name（不是 tool_call_id）→ 从 assistant tool_calls
        #   反查 id→name 补上、剔 tool_call_id（否则多轮里模型认不清哪个结果对应哪个工具）。
        # - content=null → ""。
        _id2name: Dict[str, str] = {}
        for _m in messages:
            if _m.get("role") == "assistant":
                for _tc in (_m.get("tool_calls") or []):
                    _tid = _tc.get("id")
                    _nm = (_tc.get("function") or {}).get("name")
                    if _tid and _nm:
                        _id2name[_tid] = _nm
        norm: List[Dict[str, Any]] = []
        for _m in messages:
            _m2 = dict(_m)
            if _m2.get("tool_calls"):
                _tcs = []
                for _tc in _m2["tool_calls"]:
                    _fn = dict((_tc.get("function") or {}))
                    _args = _fn.get("arguments")
                    if isinstance(_args, str):
                        try:
                            _fn["arguments"] = _json.loads(_args) if _args.strip() else {}
                        except Exception:
                            _fn["arguments"] = {}
                    _tcs.append({"function": _fn})  # 只留 function，剔 OpenAI-only id/type
                _m2["tool_calls"] = _tcs
            if _m2.get("role") == "tool":
                _tid = _m2.get("tool_call_id")
                if _tid and _id2name.get(_tid) and not _m2.get("tool_name"):
                    _m2["tool_name"] = _id2name[_tid]
                _m2.pop("tool_call_id", None)
            if _m2.get("content") is None:
                _m2["content"] = ""
            norm.append(_m2)
        body: Dict[str, Any] = {
            "model": self.config.model,
            "messages": norm,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_response_tokens,
                # 见 LLMConfig.num_ctx：不设则 Ollama 默认 4096 并静默截断前端。
                "num_ctx": self.config.num_ctx,
            },
        }
        if self.config.num_gpu is not None:
            body["options"]["num_gpu"] = self.config.num_gpu
        if tools:
            body["tools"] = tools
        req = _url.Request(
            endpoint, data=_json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        started_at = time.perf_counter()
        try:
            # 🔴 超时写死 600 秒曾整批判废(2026-07-26 试跑实证:两栋均
            # `native /api/chat 请求失败: timed out` → `tool_call_missing` → 批废)。
            # 首栋要叠灌库 + 冷推理，600 秒不够。改为可配，缺省仍 600 保持旧行为。
            with _url.urlopen(req, timeout=_chat_timeout_seconds()) as fh:
                data = _json.loads(fh.read().decode("utf-8"))
        except _uerr.HTTPError as e:  # Ollama 错误体带进异常，便于定位（如 schema/格式）
            try:
                _detail = e.read().decode("utf-8")[:500]
            except Exception:
                _detail = "(无法读取错误体)"
            raise RuntimeError(f"native /api/chat {e.code}: {_detail}") from e
        except (_uerr.URLError, OSError, ValueError) as e:  # 连接失败/超时/非JSON
            raise RuntimeError(f"native /api/chat 请求失败: {e}") from e
        if not isinstance(data, dict):
            raise RuntimeError(f"native /api/chat 响应非对象: {type(data).__name__}")
        elapsed_seconds = round(time.perf_counter() - started_at, 6)

        msg = data.get("message", {}) or {}
        tool_calls_out: List[Dict[str, Any]] = []
        for tc in (msg.get("tool_calls") or []):
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments")
            args_json = (
                _json.dumps(args, ensure_ascii=False)
                if isinstance(args, (dict, list)) else (args or "{}")
            )
            tool_calls_out.append({
                "id": tc.get("id") or f"call_{iteration}_{len(tool_calls_out)}",
                "name": fn.get("name"),
                "arguments_json": args_json,
            })
        return LLMTurn(
            iteration=iteration,
            response_text=msg.get("content") or "",
            tool_calls=tool_calls_out,
            finish_reason=data.get("done_reason") or "stop",
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
            elapsed_seconds=elapsed_seconds,
        )


def report_contract_mode() -> str:
    """当前报告契约模式：'v4' 当 EVO_REPORT_CONTRACT=v4，否则 'v3'（默认，不变）。"""
    return "v4" if os.environ.get("EVO_REPORT_CONTRACT", "").lower() == "v4" else "v3"


def load_system_prompt(contract_version: Optional[int] = None) -> str:
    """读系统提示词（spec §7.1）。契约版本 4 读 system_prompt_v4.txt，否则 system_prompt.txt。

    contract_version=None 时读进程环境（会话外场景）；编排会话内必须传
    state.contract_version 冻结值——防运行中环境翻转致提示词与提交校验错档
    （copilot 终审五轮致命#1）。
    """
    if contract_version is None:
        contract_version = 4 if report_contract_mode() == "v4" else 3
    fname = "system_prompt_v4.txt" if contract_version == 4 else "system_prompt.txt"
    path = Path(__file__).resolve().parent / fname
    return path.read_text(encoding="utf-8")


def is_llm_endpoint_available(config: Optional[LLMConfig] = None) -> bool:
    """探测 LLM endpoint 是否可达（单测 skip 判定用）。"""
    if not _OPENAI_OK:
        return False
    try:
        config = config or LLMConfig()
        client = OpenAI(base_url=config.base_url, api_key=config.api_key)
        # 不真调 chat，只调 models 列表（轻量），失败即不可用。
        list(client.models.list())  # noqa: SLF001
        return True
    except Exception:  # pragma: no cover
        return False


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_MAX_TOOL_ITERATIONS",
    "LLMConfig",
    "LLMTurn",
    "LLMClient",
    "load_system_prompt",
    "is_llm_endpoint_available",
]
