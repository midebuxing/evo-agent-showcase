"""W1 projection-only rule use audit — worldgen 主代码不读 rule_card 静态扫.

W1 spec 01 §6 表第 2 行红线：
> Projection-only rule use: rule_card 只在 法规映射层消费 W1 输出，
> 绝不在 W1 路径中读取.

设计
====
扫 ``src/workflow_engine/worldgen/`` 下所有 .py 文件的 import 语句，禁止任何
``rule_card`` / ``rulecard_v2`` / 法规映射层（W2）模块的 import。注释 / docstring
中提及 ``rule_card`` 作为业务上下文说明是允许的——本 audit 用 AST 精确分析
``ast.Import`` / ``ast.ImportFrom``，不扫注释 / docstring / 字符串字面量.

禁止 module path 前缀（``startswith`` 匹配）：
- ``regulations.``                            — agent_v1.regulations.* (rule_card 数据)
- ``agent_v1.regulations``                    — 全路径变体
- ``workflow_engine.regulation_projection``   — W2 法规映射层主模块
- ``workflow_engine.regulation_thresholds``   — W2 真阈值 loader (本身读 rule_card)
- ``workflow_engine.regulation_coverage_control`` — W2 coverage-controlled rejection

白名单：worldgen 子包内 module 互相 import 不限.

跨进程 / 跑批 CI 用法
=====================
本 audit 也是静态分析，跟 schema_firewall 同语境。release_batch CI hook 一并跑：

    from workflow_engine.worldgen.audits import projection_rule_use_audit
    report = projection_rule_use_audit()
    assert report.passed, report.violations
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


FORBIDDEN_IMPORT_PREFIXES: Tuple[str, ...] = (
    "regulations.",
    "agent_v1.regulations.",
    "workflow_engine.regulation_projection",
    "workflow_engine.regulation_thresholds",
    "workflow_engine.regulation_coverage_control",
)


WHITELIST_IMPORTS: Tuple[Tuple[str, str, str], ...] = (
    (
        "validation.py",
        "workflow_engine.regulation_projection_executor",
        "spec framework 7-step orchestrator step 7 主入口调 W2 phase 3 投影 "
        "(详见 validation.py docstring + W2 规格 04 §3，DEBT-031 gap 5 用户拍板合法 reach-back)",
    ),
    (
        "validation.py",
        "workflow_engine.regulation_coverage_control",
        "DEBT-044 修根 (2026-06-11)：spec 11 §3.1 批级楼级 coverage-controlled "
        "rejection 在 phase 3 输出后、phase 4 聚合前由外层编排执行（spec 11 §3.3 "
        "'外层编排' = validation.py 7-step orchestrator）；与上一条同类合法 "
        "reach-back——编排层只消费 world_id 取舍结果，bucket / ratio 不回流 W1 "
        "生成（spec 11 §3.3 禁止项不触碰，W1 rule-blind 红线不破）",
    ),
    (
        "tests/test_parquet_io.py",
        "workflow_engine.regulation_projection_models",
        "测试 fixture 验证 W2 parquet round-trip schema 兼容性",
    ),
)


def _default_scan_root() -> Path:
    """``src/workflow_engine/worldgen/`` (本模块所在子包的父目录)."""
    return Path(__file__).resolve().parent.parent


@dataclass
class ImportViolation:
    file_path: str
    line_no: int
    imported_module: str
    matched_prefix: str


@dataclass
class ProjectionRuleUseReport:
    passed: bool
    violations: List[ImportViolation] = field(default_factory=list)
    n_files_scanned: int = 0
    n_imports_scanned: int = 0
    forbidden_prefixes: List[str] = field(default_factory=list)


def _iter_python_files(scan_root: Path) -> Iterable[Path]:
    yield from sorted(scan_root.rglob("*.py"))


def _matched_prefix(module_name: str, prefixes: Iterable[str]) -> Optional[str]:
    for p in prefixes:
        if module_name == p.rstrip(".") or module_name.startswith(p):
            return p
    return None


def _is_whitelisted(
    py_path: Path,
    imported_module: str,
    whitelist: Iterable[Tuple[str, str, str]],
) -> bool:
    """py_path 的 posix 路径 endswith whitelist[i][0] 且 imported_module 匹配 [i][1]."""
    path_str = py_path.as_posix()
    for rel_suffix, allowed_module, _reason in whitelist:
        if path_str.endswith(rel_suffix) and imported_module == allowed_module:
            return True
    return False


def _scan_file_imports(
    py_path: Path,
    prefixes: Iterable[str],
    whitelist: Iterable[Tuple[str, str, str]],
) -> Tuple[List[ImportViolation], int]:
    """返回 ``(violations, n_imports)``。解析失败的文件计 0 imports 不抛 exc."""
    source = py_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(py_path))
    except SyntaxError:
        return [], 0

    violations: List[ImportViolation] = []
    n_imports = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                n_imports += 1
                m = _matched_prefix(alias.name, prefixes)
                if m and not _is_whitelisted(py_path, alias.name, whitelist):
                    violations.append(
                        ImportViolation(
                            file_path=str(py_path),
                            line_no=node.lineno,
                            imported_module=alias.name,
                            matched_prefix=m,
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            n_imports += 1
            module = node.module or ""
            m = _matched_prefix(module, prefixes)
            if m and not _is_whitelisted(py_path, module, whitelist):
                violations.append(
                    ImportViolation(
                        file_path=str(py_path),
                        line_no=node.lineno,
                        imported_module=module,
                        matched_prefix=m,
                    )
                )
    return violations, n_imports


def projection_rule_use_audit(
    scan_root: Optional[Path] = None,
    forbidden_prefixes: Iterable[str] = FORBIDDEN_IMPORT_PREFIXES,
    whitelist: Iterable[Tuple[str, str, str]] = WHITELIST_IMPORTS,
    exclude_paths: Iterable[Path] = (),
) -> ProjectionRuleUseReport:
    """W1 projection-only rule use audit.

    参数
    ----
    scan_root:
        默认 ``src/workflow_engine/worldgen/``（本子包父目录）.
    forbidden_prefixes:
        禁止的 module path 前缀集合.
    whitelist:
        ``(relative_path_suffix, allowed_module, reason)`` 三元组集合.
        path 用 posix style 后缀匹配 (跨 worktree / OS 稳定).
    exclude_paths:
        显式跳过的文件 path（如本 audit 自己的测试 fixture）.

    返回 ``ProjectionRuleUseReport``。``passed`` = no violations.
    """
    root = scan_root or _default_scan_root()
    exclude_set = {p.resolve() for p in exclude_paths}
    prefixes = list(forbidden_prefixes)
    whitelist_list = list(whitelist)

    all_violations: List[ImportViolation] = []
    n_files = 0
    n_imports = 0

    for py_path in _iter_python_files(root):
        if py_path.resolve() in exclude_set:
            continue
        n_files += 1
        vs, imp_count = _scan_file_imports(py_path, prefixes, whitelist_list)
        all_violations.extend(vs)
        n_imports += imp_count

    return ProjectionRuleUseReport(
        passed=len(all_violations) == 0,
        violations=all_violations,
        n_files_scanned=n_files,
        n_imports_scanned=n_imports,
        forbidden_prefixes=prefixes,
    )


__all__ = [
    "FORBIDDEN_IMPORT_PREFIXES",
    "WHITELIST_IMPORTS",
    "ImportViolation",
    "ProjectionRuleUseReport",
    "projection_rule_use_audit",
]
