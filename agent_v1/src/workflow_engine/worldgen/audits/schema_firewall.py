"""W1 schema firewall audit — 输出对象字段名禁止 token 静态扫.

W1 spec 01 §6 表第 1 行红线：
> Schema firewall: W1 输出对象 schema 不含任何 rule_family_id / threshold /
> gold / observation 字段.

设计
====
W1 输出契约由 ``WorldBundle`` + ``SidecarRuntimeBundle`` 两个顶层 dataclass 树
覆盖。本 audit 从两棵树递归收集所有嵌套 BaseModel 类的字段名，按禁止 token
正则集合扫一遍，任何匹配即 fail。

禁止 token 设计避免误伤合法字段：
- ``rule_family`` 覆盖 ``rule_family_id`` 不伤 ``mechanism_family``.
- ``\\brule_card`` / ``\\brule_id`` 用 word boundary 不伤 ``mechanism_rule``（无此字段）.
- ``threshold_value`` / ``threshold_id`` 精确匹配不伤 sidecar threshold 描述符.
- ``\\bgold`` 不伤 ``goldenrod`` 类无关词.
- ``observation`` / ``verdict`` / ``expected_outcome`` / ``reference_verdict``
  / ``w2_truth`` / ``raw_w2`` / ``eval_truth`` 全是 W2 / evaluator 概念词.

WHITELIST_FIELDS 登记现役合法跨层外键（SidecarRuntimeRecord.projection_id 是
sidecar runtime 按 W2 projection 注入的外键，spec 09 §1.2 sidecar 边界设计
明示）；扫到字段在 whitelist 视作合法不报 fail.

跨进程 / 跑批 CI 用法
=====================
本 audit 是静态分析（不依赖 batch 数据），跑一次任何时点都能验。release_batch
CI hook 在 worldgen 启动前调一次：

    from workflow_engine.worldgen.audits import schema_firewall_audit
    report = schema_firewall_audit()
    assert report.passed, report.violations
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, List, Set, Tuple, Type

from pydantic import BaseModel

from workflow_engine.worldgen.models import SidecarRuntimeBundle, WorldBundle


FORBIDDEN_FIELD_TOKENS: Tuple[str, ...] = (
    r"rule_family",
    r"\brule_card",
    r"\brule_id\b",
    r"threshold_value",
    r"threshold_id",
    r"\bgold",
    r"observation",
    r"verdict",
    r"expected_outcome",
    r"reference_verdict",
    r"w2_truth",
    r"raw_w2",
    r"eval_truth",
)


WHITELIST_FIELDS: Tuple[Tuple[str, str, str], ...] = (
    (
        "SidecarRuntimeRecord",
        "projection_id",
        "W1 sidecar runtime 按 W2 projection 注入的外键引用 (spec 09 §1.2)",
    ),
)


@dataclass
class FieldViolation:
    class_name: str
    field_name: str
    matched_pattern: str


@dataclass
class SchemaFirewallReport:
    passed: bool
    violations: List[FieldViolation] = field(default_factory=list)
    n_classes_scanned: int = 0
    n_fields_scanned: int = 0
    forbidden_tokens: List[str] = field(default_factory=list)
    whitelist_entries: List[Tuple[str, str, str]] = field(default_factory=list)


def _collect_basemodel_classes(
    root_classes: Iterable[Type[BaseModel]],
) -> List[Type[BaseModel]]:
    """从 root_classes 出发递归收集嵌套引用到的所有 BaseModel 子类.

    通过遍历 ``model_fields`` 的 annotation，剥 ``List[X]`` / ``Optional[X]`` /
    ``Dict[K, V]`` 后看是否是 BaseModel 子类，是则递归收集.
    """
    seen: Set[Type[BaseModel]] = set()
    order: List[Type[BaseModel]] = []

    def _is_basemodel(tp: object) -> bool:
        return isinstance(tp, type) and issubclass(tp, BaseModel)

    def _walk_annotation(ann: object) -> Iterable[Type[BaseModel]]:
        # 直接是 BaseModel 子类
        if _is_basemodel(ann):
            yield ann  # type: ignore[misc]
            return
        # 含 __args__ 的 generic（List/Dict/Optional/Union）
        args = getattr(ann, "__args__", None)
        if not args:
            return
        for sub in args:
            yield from _walk_annotation(sub)

    def _visit(cls: Type[BaseModel]) -> None:
        if cls in seen:
            return
        seen.add(cls)
        order.append(cls)
        for finfo in cls.model_fields.values():
            for sub in _walk_annotation(finfo.annotation):
                _visit(sub)

    for root in root_classes:
        _visit(root)

    return order


def schema_firewall_audit(
    forbidden_tokens: Iterable[str] = FORBIDDEN_FIELD_TOKENS,
    whitelist: Iterable[Tuple[str, str, str]] = WHITELIST_FIELDS,
    root_classes: Iterable[Type[BaseModel]] = (WorldBundle, SidecarRuntimeBundle),
) -> SchemaFirewallReport:
    """W1 schema firewall audit.

    参数
    ----
    forbidden_tokens:
        regex 模式串集合（默认 ``FORBIDDEN_FIELD_TOKENS``）.
    whitelist:
        ``(class_name, field_name, reason)`` 三元组集合，命中视作合法.
    root_classes:
        扫描入口（默认 W1 双顶层契约 ``WorldBundle`` + ``SidecarRuntimeBundle``）.

    返回 ``SchemaFirewallReport``。``passed`` = no violations.
    """
    patterns = [(p, re.compile(p)) for p in forbidden_tokens]
    whitelist_set: Set[Tuple[str, str]] = {(c, f) for c, f, _ in whitelist}

    classes = _collect_basemodel_classes(root_classes)
    violations: List[FieldViolation] = []
    n_fields = 0

    for cls in classes:
        for field_name in cls.model_fields.keys():
            n_fields += 1
            if (cls.__name__, field_name) in whitelist_set:
                continue
            for raw, compiled in patterns:
                if compiled.search(field_name):
                    violations.append(
                        FieldViolation(
                            class_name=cls.__name__,
                            field_name=field_name,
                            matched_pattern=raw,
                        )
                    )
                    break

    return SchemaFirewallReport(
        passed=len(violations) == 0,
        violations=violations,
        n_classes_scanned=len(classes),
        n_fields_scanned=n_fields,
        forbidden_tokens=list(forbidden_tokens),
        whitelist_entries=list(whitelist),
    )


__all__ = [
    "FORBIDDEN_FIELD_TOKENS",
    "WHITELIST_FIELDS",
    "FieldViolation",
    "SchemaFirewallReport",
    "schema_firewall_audit",
]
