"""LocalLLMConfig — Phase D baseline 本地模型配置.

环境变量:
  LOCAL_LLM_BASE_URL — 必须是本地 endpoint (http://127.0.0.1:... 或 http://localhost:...)
  LOCAL_LLM_API_KEY  — 本地模型 API key（部分本地服务不需要，可设为 "no-key"）
  LOCAL_LLM_MODEL    — 本地模型名称（如 qwen3.5:latest, qwen2.5:7b 等）

向后兼容: 如果 LOCAL_LLM_* 不存在，回退读取 OPENAI_BASE_URL / OPENAI_API_KEY / LLM_MODEL，
但仍会校验 base_url 必须指向本地地址。
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv


_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


def _load_env() -> None:
    env_path = _PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _require_env(name: str, fallback_name: Optional[str] = None) -> str:
    value = os.getenv(name)
    if not value and fallback_name:
        value = os.getenv(fallback_name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _validate_local_url(url: str) -> None:
    """Raise if *url* does not point to a local address."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in _LOCAL_HOSTS:
        raise RuntimeError(
            f"base_url 必须指向本地地址 (127.0.0.1 / localhost)，"
            f"当前值 '{url}' 指向 '{host}'，不符合 Phase D 本地模型要求。"
            f"请启动本地推理服务（如 Ollama / LM Studio / vLLM）。"
        )


class LocalLLMConfig:
    """Phase D 最小本地模型配置.

    强制要求 base_url 指向本机地址，拒绝远端代理。
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 180,
        max_retries: int = 3,
    ) -> None:
        _load_env()
        self.base_url = base_url or _require_env(
            "LOCAL_LLM_BASE_URL", fallback_name="OPENAI_BASE_URL"
        )
        _validate_local_url(self.base_url)
        self.api_key = api_key or _require_env(
            "LOCAL_LLM_API_KEY", fallback_name="OPENAI_API_KEY"
        )
        self.model = model or os.getenv(
            "LOCAL_LLM_MODEL", os.getenv("LLM_MODEL", "qwen3.5:latest")
        )
        env_timeout = os.getenv("LLM_TIMEOUT")
        if env_timeout:
            self.timeout = int(env_timeout)
        elif self.model.startswith("qwen3.5"):
            self.timeout = 360
        else:
            self.timeout = int(timeout)
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", str(max_retries)))

    def summary(self) -> dict:
        return {
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "is_local": True,
        }
