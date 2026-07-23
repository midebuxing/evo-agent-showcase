"""回归：blind 红线异常 SecurityError 全局唯一类，跨层 except 不漏接。

历史 bug：agent.hooks 与 ingest.guard 各定义一个 SecurityError，而
run_orchestrator 的 `except SecurityError`(hooks 版) 接不住 retrieval/ingest 层
（pack_builder 等）抛的 guard 版，blind 违规会漏接、违背"blind 违规不抛给调用方、
转 status=blocked"的契约。本测试把二者钉死为同一个类。
"""

from evo_agent_baseline.errors import SecurityError as RootSecurityError
from evo_agent_baseline.agent.hooks import SecurityError as HooksSecurityError
from evo_agent_baseline.ingest.guard import SecurityError as GuardSecurityError


def test_security_error_is_single_class():
    assert HooksSecurityError is GuardSecurityError
    assert HooksSecurityError is RootSecurityError


def test_except_hooks_catches_guard_raised():
    """模拟检索/灌库层抛 guard 版、编排层用 hooks 版 except 捕获——必须接住。"""
    try:
        raise GuardSecurityError("forbidden property detected in retrieval layer")
    except HooksSecurityError as exc:
        assert "forbidden" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("guard.SecurityError 未被 hooks 版 except 捕获——跨层漏接回归")
