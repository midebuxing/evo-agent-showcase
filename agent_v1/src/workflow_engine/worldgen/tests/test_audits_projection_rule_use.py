"""W1 audits / projection_rule_use 测试 (DEBT-030 audit 2)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from workflow_engine.worldgen.audits.projection_rule_use import (
    FORBIDDEN_IMPORT_PREFIXES,
    ImportViolation,
    ProjectionRuleUseReport,
    WHITELIST_IMPORTS,
    _scan_file_imports,
    projection_rule_use_audit,
)


# ---------------- Baseline pass --------------------------------------------


def test_baseline_pass() -> None:
    """master HEAD worldgen 子包扫一遍必 pass（whitelist 已 cover 已知 reach-back）."""
    report = projection_rule_use_audit()
    assert report.passed, (
        "W1 projection_rule_use violations (master HEAD): "
        + "; ".join(
            f"{v.file_path}:{v.line_no} import {v.imported_module} ({v.matched_prefix})"
            for v in report.violations
        )
    )
    assert report.n_files_scanned > 20  # 当前 33，留 buffer
    assert report.n_imports_scanned > 100  # 当前 474，留 buffer


def test_baseline_metadata() -> None:
    report = projection_rule_use_audit()
    assert report.forbidden_prefixes == list(FORBIDDEN_IMPORT_PREFIXES)


# ---------------- Forbidden import detection -------------------------------


_LEAK_IMPORT_FIXTURES = [
    # (source_code, expected_module_in_violation, expected_prefix)
    (
        "import regulations.rulecard_v2\n",
        "regulations.rulecard_v2",
        "regulations.",
    ),
    (
        "import agent_v1.regulations.rulecard_v2.loader\n",
        "agent_v1.regulations.rulecard_v2.loader",
        "agent_v1.regulations.",
    ),
    (
        "from workflow_engine.regulation_projection_executor import build_x\n",
        "workflow_engine.regulation_projection_executor",
        "workflow_engine.regulation_projection",
    ),
    (
        "from workflow_engine.regulation_thresholds import Threshold\n",
        "workflow_engine.regulation_thresholds",
        "workflow_engine.regulation_thresholds",
    ),
    (
        "from workflow_engine.regulation_coverage_control import x\n",
        "workflow_engine.regulation_coverage_control",
        "workflow_engine.regulation_coverage_control",
    ),
]


@pytest.mark.parametrize(
    "source,expected_module,expected_prefix", _LEAK_IMPORT_FIXTURES
)
def test_detect_forbidden_import(
    tmp_path: Path, source: str, expected_module: str, expected_prefix: str
) -> None:
    """每个伪 .py 必须被检出 violation."""
    py = tmp_path / "leak.py"
    py.write_text(source, encoding="utf-8")
    violations, n_imports = _scan_file_imports(
        py, FORBIDDEN_IMPORT_PREFIXES, WHITELIST_IMPORTS
    )
    assert n_imports >= 1
    assert len(violations) == 1
    v = violations[0]
    assert v.imported_module == expected_module
    assert v.matched_prefix == expected_prefix


def test_comment_mentioning_rule_card_not_flagged(tmp_path: Path) -> None:
    """注释 / docstring 中提及 rule_card 不被误伤（AST 只看 import）."""
    source = textwrap.dedent(
        '''\
        """Module docstring — 解释 rule_card threshold 跟 worldgen 的关系."""

        # rule_card 团队负责 threshold 维护
        # 这是 generator.py 风格的合法注释

        from workflow_engine.worldgen.models import WorldBundle

        RULE_CARD_DESCRIPTION = "rule_card_threshold dict key 不是真 import"
        '''
    )
    py = tmp_path / "safe.py"
    py.write_text(source, encoding="utf-8")
    violations, _ = _scan_file_imports(py, FORBIDDEN_IMPORT_PREFIXES, WHITELIST_IMPORTS)
    assert violations == []


def test_relative_safe_import_not_flagged(tmp_path: Path) -> None:
    """worldgen 子包内 module 互相 import 合法."""
    source = textwrap.dedent(
        """\
        from workflow_engine.worldgen.registry import RegistryBundle
        from workflow_engine.worldgen.models import WorldBundle
        from workflow_engine.worldgen.sidecar import build_sidecar
        """
    )
    py = tmp_path / "innerimport.py"
    py.write_text(source, encoding="utf-8")
    violations, n_imports = _scan_file_imports(
        py, FORBIDDEN_IMPORT_PREFIXES, WHITELIST_IMPORTS
    )
    assert violations == []
    assert n_imports == 3


# ---------------- Whitelist ------------------------------------------------


def test_whitelist_entries_cover_known_reachbacks() -> None:
    """master HEAD 三个已知合法 reach-back 必须在 whitelist 中."""
    entries = {(rel, mod) for rel, mod, _ in WHITELIST_IMPORTS}
    assert ("validation.py", "workflow_engine.regulation_projection_executor") in entries
    # DEBT-044 修根：批级楼级 coverage control 由外层编排（validation.py）执行
    # （spec 11 §3.1 / §3.3），路径专属白名单，其它 worldgen 文件 import 仍 fail.
    assert ("validation.py", "workflow_engine.regulation_coverage_control") in entries
    assert (
        "tests/test_parquet_io.py",
        "workflow_engine.regulation_projection_models",
    ) in entries


def test_whitelist_is_path_specific(tmp_path: Path) -> None:
    """同 module 在非 whitelist path 文件中 import 仍报 fail
    (whitelist 是 path-specific 不是 module-specific)."""
    nested = tmp_path / "unrelated.py"
    nested.write_text(
        "from workflow_engine.regulation_projection_executor import x\n",
        encoding="utf-8",
    )
    violations, _ = _scan_file_imports(
        nested, FORBIDDEN_IMPORT_PREFIXES, WHITELIST_IMPORTS
    )
    assert len(violations) == 1
    assert violations[0].imported_module == "workflow_engine.regulation_projection_executor"


def test_whitelist_path_suffix_match(tmp_path: Path) -> None:
    """whitelist path 用 endswith 后缀匹配；模拟 validation.py 在 tmp 里 OK."""
    fake_validation = tmp_path / "validation.py"
    fake_validation.write_text(
        "from workflow_engine.regulation_projection_executor import x\n",
        encoding="utf-8",
    )
    violations, _ = _scan_file_imports(
        fake_validation, FORBIDDEN_IMPORT_PREFIXES, WHITELIST_IMPORTS
    )
    assert violations == []


def test_whitelist_does_not_exempt_other_modules(tmp_path: Path) -> None:
    """whitelist 是 (path, module) tuple；同 path 但 import 别的禁止 module 还是 fail."""
    fake_validation = tmp_path / "validation.py"
    fake_validation.write_text(
        "from workflow_engine.regulation_thresholds import Threshold\n",
        encoding="utf-8",
    )
    violations, _ = _scan_file_imports(
        fake_validation, FORBIDDEN_IMPORT_PREFIXES, WHITELIST_IMPORTS
    )
    assert len(violations) == 1
    assert violations[0].imported_module == "workflow_engine.regulation_thresholds"


# ---------------- Scan root override ---------------------------------------


def test_audit_with_custom_scan_root(tmp_path: Path) -> None:
    """用 scan_root 参数指 tmp 目录 + 故意带 violation 文件，audit 必 fail."""
    leak = tmp_path / "leak.py"
    leak.write_text("import regulations.rulecard_v2\n", encoding="utf-8")
    safe = tmp_path / "safe.py"
    safe.write_text(
        "from workflow_engine.worldgen.models import WorldBundle\n", encoding="utf-8"
    )
    report = projection_rule_use_audit(scan_root=tmp_path)
    assert not report.passed
    assert report.n_files_scanned == 2
    assert len(report.violations) == 1
    assert report.violations[0].file_path.endswith("leak.py")


def test_audit_exclude_paths(tmp_path: Path) -> None:
    """exclude_paths 显式跳过指定文件不计."""
    leak = tmp_path / "leak.py"
    leak.write_text("import regulations.rulecard_v2\n", encoding="utf-8")
    report = projection_rule_use_audit(scan_root=tmp_path, exclude_paths=[leak])
    assert report.passed
    assert report.n_files_scanned == 0


# ---------------- Syntax error tolerance -----------------------------------


def test_syntax_error_file_skipped(tmp_path: Path) -> None:
    """AST parse 失败的文件计 0 imports 不抛 exc."""
    bad = tmp_path / "broken.py"
    bad.write_text("def foo(\n", encoding="utf-8")  # 未闭合
    violations, n_imports = _scan_file_imports(
        bad, FORBIDDEN_IMPORT_PREFIXES, WHITELIST_IMPORTS
    )
    assert violations == []
    assert n_imports == 0


# ---------------- API shape -----------------------------------------------


def test_report_dataclass() -> None:
    report = projection_rule_use_audit()
    assert isinstance(report, ProjectionRuleUseReport)
    assert isinstance(report.passed, bool)
    assert isinstance(report.violations, list)


def test_violation_dataclass(tmp_path: Path) -> None:
    leak = tmp_path / "leak.py"
    leak.write_text("import regulations.rulecard_v2\n", encoding="utf-8")
    report = projection_rule_use_audit(scan_root=tmp_path)
    v = report.violations[0]
    assert isinstance(v, ImportViolation)
    assert v.file_path.endswith("leak.py")
    assert v.line_no == 1
