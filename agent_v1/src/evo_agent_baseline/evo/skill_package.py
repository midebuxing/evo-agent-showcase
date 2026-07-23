"""EvoSkillPackage 目录读写 + sha256 完整性验证（spec v1 §4.2 + §10）。

本模块负责把 SkillPackage 4 件目录形态解析为 `EvoSkillPackage` DTO：

- `skill.json`：机器权威源，pydantic `SkillJson` 校验（extra=forbid）；
- `SKILL.md`：LLM-readable view，必须含 non-authority statement（spec v1 §10.3 / §9.4.1）；
- `plan.yaml`：可选，`micro_routing` / `retrieval_macro` kind 必需（spec v1 §4.2.1）；
- `validation_records.jsonl`：jsonl 一行一个 `SkillValidationRecord`。

并提供 Gate 0 静态安全检查（spec v1 §9.4.1）：
1. forbidden_actions 含 5 hard 项；
2. scope 不含 building / world / run literal；
3. name / description / non_authority_statement / SKILL.md / plan.yaml 不含 verdict-like phrase；
4. forbidden W2 label / property scan；
5. SKILL.md 含 non-authority statement。

spec→code 单向：DTO 形态以 `evo_agent_baseline.contracts` 为权威；本模块只做解析 + 校验，
不引入新规格字段。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from evo_agent_baseline.contracts import (
    EvoSkillPackage,
    SkillJson,
    SkillValidationRecord,
)
from evo_agent_baseline.ingest._common import canonical_json
from evo_agent_baseline.ingest.guard import (
    FORBIDDEN_AGENT_LABELS,
    FORBIDDEN_AGENT_PROPERTIES,
    SecurityError,
)


# ===========================================================================
# 常量：5 hard forbidden_actions / verdict 词典 / 禁止 literal
# spec v1 §9.4.1 Gate 0 / §10.2 forbidden_actions / Appendix A.4 禁止 phrases
# ===========================================================================

HARD_FORBIDDEN_ACTIONS: List[str] = [
    "override_verifier",
    "force_allow_stop",
    "emit_final_verdict",
    "read_evaluator_truth",
    "suppress_rule_candidate",
]

# Appendix A.4 禁止 phrase（spec v1）：verdict-like / authority override。
# 用小写匹配；命中即 Gate 0 fail。
FORBIDDEN_PHRASES: List[str] = [
    "最终裁决",
    "最终合规",
    "最终不合规",
    "结案",
    "本建筑已合规",
    "本建筑不合规",
    "according to expected_verdict",
    "based on normativeprojection",
    "force allow_stop",
    "override verifier",
    "expected verdict says",
    "w2 says",
]

# spec v1 §10.7 / §9.4.1 禁止 literal：scope / name / description 不得出现
# 具体 building/world/run 实例 id。检测 token 前缀，不针对 spec keywords。
# 设计：FORBIDDEN_SCOPE_PREFIXES 与 name/desc 合并扫描。
FORBIDDEN_SCOPE_LITERAL_TOKENS: List[str] = [
    "building_",
    "bldg_",
    "world_seed_",
    "run_id_",
    "car-",
    "ert-",
]


# ===========================================================================
# sha256 + jsonl 工具
# ===========================================================================


def sha256_bytes(payload: bytes) -> str:
    """对字节计算 SHA-256，返回 `sha256:<hex>`（spec v1 §3.8）。"""
    digest = hashlib.sha256(payload).hexdigest()
    return f"sha256:{digest}"


def sha256_file(path: Path) -> str:
    """对文件全量计算 SHA-256。"""
    return sha256_bytes(path.read_bytes())


def sha256_text(text: str) -> str:
    """对字符串以 utf-8 编码后计算 SHA-256。"""
    return sha256_bytes(text.encode("utf-8"))


def _read_jsonl_lines(path: Path) -> List[Dict[str, Any]]:
    """逐行读 jsonl，忽略空行 / 注释（`#` 起始）。"""
    rows: List[Dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


# ===========================================================================
# 单文件 parse
# ===========================================================================


def parse_skill_json(path: Path) -> SkillJson:
    """解析 `skill.json` → `SkillJson`（pydantic extra=forbid 校验）。

    Args:
        path: skill.json 文件路径。

    Returns:
        SkillJson 实例。

    Raises:
        ValueError: schema 校验失败 / 缺 hard forbidden_actions。
        FileNotFoundError: 文件不存在。
    """
    if not path.is_file():
        raise FileNotFoundError(f"skill.json not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        skill = SkillJson(**raw)
    except ValidationError as exc:
        raise ValueError(f"skill.json schema violation: {exc}") from exc

    # spec v1 §9.4.1 Gate 0 / §10.2：必须含 5 hard forbidden_actions。
    missing = [a for a in HARD_FORBIDDEN_ACTIONS if a not in skill.forbidden_actions]
    if missing:
        raise ValueError(
            f"skill.json forbidden_actions missing hard items: {missing}; "
            f"required={HARD_FORBIDDEN_ACTIONS}"
        )

    # spec v1 §10.2 description ≤1024 chars（Gate 1 / quality）。
    if len(skill.description) > 1024:
        raise ValueError(
            f"skill.json description > 1024 chars: {len(skill.description)}"
        )

    # spec v1 §10.7 Naming：skill_id 不得含 verdict/result 词。
    forbidden_in_id = [
        "expected_verdict",
        "force_allow_stop",
        "fail_case",
        "pass_case",
    ]
    for tok in forbidden_in_id:
        if tok in skill.skill_id:
            raise ValueError(f"skill_id contains forbidden token {tok!r}: {skill.skill_id}")

    return skill


def parse_skill_md_view(path: Path) -> str:
    """读 `SKILL.md` 正文 + 验证含 non-authority statement（spec v1 §10.3 + §9.4.1）。

    Args:
        path: SKILL.md 文件路径。

    Returns:
        SKILL.md 原文 string。

    Raises:
        ValueError: 缺 non-authority statement。
        FileNotFoundError: 文件不存在。
    """
    if not path.is_file():
        raise FileNotFoundError(f"SKILL.md not found: {path}")
    text = path.read_text(encoding="utf-8")

    # spec v1 §9.4.1 Gate 0 第 6 条：SKILL.md 必须含 non-authority statement。
    # 接受多种表达：authority / decide / verifier / allow_stop 上下文的否定式。
    lowered = text.lower()
    statement_patterns = [
        r"non[-_ ]?authoritative",
        r"does not\s+(decide|determine|set|modify|override|affect)\s+(compliance|allow_stop|closure_status|satisfaction_status|verifier)",
        r"only\s+(changes|expands|reorders|affects)\s+.*?(retrieval|routing|report|ordering)",
        r"never\s+(decides|sets|determines|overrides)",
        r"not\s+(decide|determine|set|modify|override).*?(verifier|allow_stop|closure)",
    ]
    if not any(re.search(p, lowered) for p in statement_patterns):
        raise ValueError(
            f"SKILL.md missing non-authority statement (spec v1 §10.3 / §9.4.1). "
            f"Path={path}"
        )
    return text


def parse_plan_yaml(path: Path) -> Dict[str, Any]:
    """解析 `plan.yaml` → dict（spec v1 §10.4 DSL）。

    Args:
        path: plan.yaml 文件路径。

    Returns:
        plan dict（顶层）。

    Raises:
        ValueError: yaml 解析失败 / 缺关键字段。
        FileNotFoundError: 文件不存在。
    """
    if not path.is_file():
        raise FileNotFoundError(f"plan.yaml not found: {path}")
    raw = path.read_text(encoding="utf-8")
    try:
        plan = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"plan.yaml yaml parse failed: {exc}") from exc
    if not isinstance(plan, dict):
        raise ValueError(f"plan.yaml top level must be mapping, got {type(plan).__name__}")
    # spec v1 §10.4 plan DSL：必填 plan_id / steps。
    if "plan_id" not in plan or "steps" not in plan:
        raise ValueError(f"plan.yaml missing plan_id/steps: keys={list(plan.keys())}")
    # spec v1 §10.4 forbidden actions in plan.yaml steps。
    forbidden_step_actions = {
        "remove_candidate",
        "set_allow_stop",
        "set_closure_status",
        "set_satisfaction_status",
        "read_evaluator_truth",
        "write_fact_kg",
        "write_rule_card_kg",
        "emit_final_verdict",
    }
    for step in plan.get("steps", []) or []:
        action = step.get("action")
        if action in forbidden_step_actions:
            raise ValueError(
                f"plan.yaml step uses forbidden action {action!r} (spec v1 §10.4)"
            )
    return plan


def parse_validation_records(path: Path) -> List[SkillValidationRecord]:
    """解析 `validation_records.jsonl` → list[SkillValidationRecord]。

    Args:
        path: jsonl 文件路径。

    Returns:
        验证记录列表。

    Raises:
        ValueError: 任一行 schema 校验失败。
        FileNotFoundError: 文件不存在。
    """
    if not path.is_file():
        raise FileNotFoundError(f"validation_records.jsonl not found: {path}")
    rows = _read_jsonl_lines(path)
    records: List[SkillValidationRecord] = []
    for idx, row in enumerate(rows):
        try:
            records.append(SkillValidationRecord(**row))
        except ValidationError as exc:
            raise ValueError(
                f"validation_records.jsonl line {idx+1} schema violation: {exc}"
            ) from exc
    return records


# ===========================================================================
# 包级 load
# ===========================================================================


def _compute_manifest_sha256(
    package_sha256: str,
    skill_json_sha256: str,
    skill_md_sha256: str,
    validation_records_sha256: str,
    plan_yaml_sha256: Optional[str],
) -> str:
    """spec v1 §10.1 + §3.8：manifest_sha256 = canonical hash of 文件 hash 字典。"""
    manifest_dict: Dict[str, Any] = {
        "package_sha256": package_sha256,
        "files": {
            "skill.json": skill_json_sha256,
            "SKILL.md": skill_md_sha256,
            "validation_records.jsonl": validation_records_sha256,
        },
    }
    if plan_yaml_sha256 is not None:
        manifest_dict["files"]["plan.yaml"] = plan_yaml_sha256
    return sha256_text(canonical_json(manifest_dict))


def _compute_package_sha256(file_hashes: Dict[str, str]) -> str:
    """对 file→hash 字典做 canonical JSON hash，作为 package_sha256。"""
    return sha256_text(canonical_json(file_hashes))


def load_skill_package(
    package_dir: Path,
    package_uri: Optional[str] = None,
) -> EvoSkillPackage:
    """读取 SkillPackage 目录 → 组装 `EvoSkillPackage`（spec v1 §10.1 + §4.2）。

    必需文件：skill.json / SKILL.md / validation_records.jsonl。
    可选文件：plan.yaml（`micro_routing` / `retrieval_macro` kind 必需）。

    Args:
        package_dir: SkillPackage 目录路径。
        package_uri: 可选，覆盖 package_uri 字段；默认用 `package_dir.as_posix()`。

    Returns:
        EvoSkillPackage 实例（已计算 4 个 sha256 + manifest_sha256）。

    Raises:
        FileNotFoundError: 必需文件缺失。
        ValueError: schema 校验失败 / kind 要求 plan.yaml 但缺失。
    """
    if not package_dir.is_dir():
        raise FileNotFoundError(f"package dir not found: {package_dir}")

    skill_json_path = package_dir / "skill.json"
    skill_md_path = package_dir / "SKILL.md"
    plan_yaml_path = package_dir / "plan.yaml"
    val_records_path = package_dir / "validation_records.jsonl"

    skill = parse_skill_json(skill_json_path)
    _ = parse_skill_md_view(skill_md_path)  # 仅做校验，view 文本不入 DTO
    _ = parse_validation_records(val_records_path)  # 仅做 schema 校验

    # spec v1 §4.2.1：micro_routing / retrieval_macro 必须 plan.yaml。
    plan_required = skill.kind in {"micro_routing", "retrieval_macro"}
    plan_yaml_sha256: Optional[str] = None
    if plan_yaml_path.is_file():
        _ = parse_plan_yaml(plan_yaml_path)
        plan_yaml_sha256 = sha256_file(plan_yaml_path)
    elif plan_required:
        raise ValueError(
            f"skill.kind={skill.kind!r} requires plan.yaml but missing in {package_dir}"
        )

    skill_json_sha256 = sha256_file(skill_json_path)
    skill_md_sha256 = sha256_file(skill_md_path)
    val_records_sha256 = sha256_file(val_records_path)

    file_hashes: Dict[str, str] = {
        "skill.json": skill_json_sha256,
        "SKILL.md": skill_md_sha256,
        "validation_records.jsonl": val_records_sha256,
    }
    if plan_yaml_sha256 is not None:
        file_hashes["plan.yaml"] = plan_yaml_sha256

    package_sha256 = _compute_package_sha256(file_hashes)
    manifest_sha256 = _compute_manifest_sha256(
        package_sha256=package_sha256,
        skill_json_sha256=skill_json_sha256,
        skill_md_sha256=skill_md_sha256,
        validation_records_sha256=val_records_sha256,
        plan_yaml_sha256=plan_yaml_sha256,
    )

    return EvoSkillPackage(
        package_schema_version="1.0.0",
        package_uri=package_uri or package_dir.as_posix(),
        package_sha256=package_sha256,
        skill=skill,
        skill_md_sha256=skill_md_sha256,
        plan_yaml_sha256=plan_yaml_sha256,
        validation_records_sha256=val_records_sha256,
        manifest_sha256=manifest_sha256,
    )


# ===========================================================================
# Gate 0 静态安全（spec v1 §9.4.1）
# ===========================================================================


def _scan_for_forbidden_phrases(text: str, where: str) -> List[str]:
    """对文本扫描 verdict-like / authority-override phrase，返回命中条目。"""
    hits: List[str] = []
    lowered = text.lower()
    for phrase in FORBIDDEN_PHRASES:
        if phrase.lower() in lowered:
            hits.append(f"{where}: {phrase}")
    return hits


def _scan_for_forbidden_labels(text: str, where: str) -> List[str]:
    """对文本扫描禁止 W2 label 字符串（spec v1 Appendix A.1）。"""
    hits: List[str] = []
    for label in FORBIDDEN_AGENT_LABELS:
        # 全词匹配（label 是 PascalCase 单词，简单子串扫描足够 Gate 0 防御深度）。
        if label in text:
            hits.append(f"{where}: label={label}")
    return hits


def _scan_for_forbidden_properties(payload: Any, where: str) -> List[str]:
    """递归扫描 dict key / list element 是否命中禁止 property 名（spec v1 Appendix A.2）。"""
    hits: List[str] = []
    if isinstance(payload, dict):
        for key, val in payload.items():
            if key in FORBIDDEN_AGENT_PROPERTIES:
                hits.append(f"{where}.{key}: forbidden W2 property")
            hits.extend(_scan_for_forbidden_properties(val, f"{where}.{key}"))
    elif isinstance(payload, list):
        for idx, item in enumerate(payload):
            hits.extend(_scan_for_forbidden_properties(item, f"{where}[{idx}]"))
    elif isinstance(payload, str):
        for prop in FORBIDDEN_AGENT_PROPERTIES:
            if prop in payload:
                hits.append(f"{where}: property literal {prop!r} in string")
    return hits


def _scan_scope_for_instance_literal(skill: SkillJson) -> List[str]:
    """spec v1 §10.7 / §9.4.1：scope 不得含 building/world/run literal id。"""
    hits: List[str] = []
    scope = skill.scope
    fields = {
        "rule_families": scope.rule_families,
        "rule_cards": scope.rule_cards,
        "semantic_slots": scope.semantic_slots,
        "measure_keys": scope.measure_keys,
        "artifact_keys": scope.artifact_keys,
        "obligation_kinds": scope.obligation_kinds,
    }
    for field_name, values in fields.items():
        for v in values:
            lowered = v.lower()
            for tok in FORBIDDEN_SCOPE_LITERAL_TOKENS:
                if tok in lowered:
                    hits.append(f"scope.{field_name}: literal {v!r} contains {tok!r}")
    # name 也扫一遍（spec §10.7 命名规范）
    name_lower = skill.name.lower()
    for tok in FORBIDDEN_SCOPE_LITERAL_TOKENS:
        if tok in name_lower:
            hits.append(f"name: contains forbidden literal token {tok!r}")
    return hits


def assert_skill_package_safe(pkg: EvoSkillPackage, skill_md_text: Optional[str] = None,
                              plan_yaml_text: Optional[str] = None) -> None:
    """Gate 0 静态安全检查（spec v1 §9.4.1）。

    检查（spec v1 §9.4.1 编号）：
    1. forbidden field scan（property / label）；
    2. W2 path / label scan；
    3. verdict-like phrase scan；
    4. verifier override phrase scan；
    5. building/world/run/projection literal scan；
    6. SKILL.md non-authority statement（在 `parse_skill_md_view` 已校验，这里冗余 once more 仅当传入文本）；
    7. `skill.json.kind` 在允许枚举（pydantic 已校验）；
    8. `allowed_tools` 子集（loader 负责，这里不强约束 tool allowlist 注册表）；
    9. `forbidden_actions` 含 5 hard（`parse_skill_json` 已校验）。

    Args:
        pkg: 已 load 的 EvoSkillPackage。
        skill_md_text: 可选 SKILL.md 文本（外部传入避免重新读盘）。
        plan_yaml_text: 可选 plan.yaml 文本。

    Raises:
        SecurityError: 任一 hit。
    """
    all_hits: List[str] = []

    # 5 hard forbidden_actions（冗余检查）
    missing = [a for a in HARD_FORBIDDEN_ACTIONS if a not in pkg.skill.forbidden_actions]
    if missing:
        all_hits.append(f"skill.json.forbidden_actions missing hard items: {missing}")

    # scope literal
    all_hits.extend(_scan_scope_for_instance_literal(pkg.skill))

    # SkillJson 全字段 dict serialize 后做 forbidden property / label / phrase 扫
    skill_dict = pkg.skill.model_dump(mode="json")
    serialized = canonical_json(skill_dict)
    all_hits.extend(_scan_for_forbidden_properties(skill_dict, "skill.json"))
    all_hits.extend(_scan_for_forbidden_labels(serialized, "skill.json"))
    all_hits.extend(_scan_for_forbidden_phrases(serialized, "skill.json"))

    # 显式 description / name 单独扫一遍（重要字段双保险）
    all_hits.extend(_scan_for_forbidden_phrases(pkg.skill.description, "skill.json.description"))
    all_hits.extend(_scan_for_forbidden_phrases(pkg.skill.non_authority_statement,
                                                 "skill.json.non_authority_statement"))

    # SKILL.md
    if skill_md_text is not None:
        all_hits.extend(_scan_for_forbidden_phrases(skill_md_text, "SKILL.md"))
        all_hits.extend(_scan_for_forbidden_labels(skill_md_text, "SKILL.md"))

    # plan.yaml
    if plan_yaml_text is not None:
        all_hits.extend(_scan_for_forbidden_phrases(plan_yaml_text, "plan.yaml"))
        all_hits.extend(_scan_for_forbidden_labels(plan_yaml_text, "plan.yaml"))

    if all_hits:
        raise SecurityError(
            "Gate 0 static safety failed: " + "; ".join(all_hits)
        )


def load_skill_package_texts(
    package: EvoSkillPackage,
) -> Dict[str, Optional[str]]:
    """从 `EvoSkillPackage.package_uri` 指向的目录读 `SKILL.md` / `plan.yaml`
    原文，供 audit 模块消费（spec v1 §11.9 features 清单含两份文本）。

    设计：
    - audit 模块本身（`evo/audits.py`）是 pure 函数，不做 IO；caller 用本
      helper 拿到文本后通过 `text_provider` 喂给
      `adversarial_reconstruction_audit_artifact` 等。
    - 工程产物（SKILL.md / plan.yaml 文本）按设计不进 DTO，否则 hash 跟踪
      会捆死文本 + sha 字段（详见模块顶部 `load_skill_package` 注释 "view
      文本不入 DTO"）。本 helper 是 caller 侧的桥接，不修 DTO 形态。

    Args:
        package: 已 `load_skill_package(...)` 解析过的 EvoSkillPackage。

    Returns:
        dict 含 `skill_md_text` / `plan_yaml_text` 两 key；plan.yaml 不存在
        时 `plan_yaml_text` 为 None（spec v1 §4.2.1：仅 micro_routing /
        retrieval_macro 必需 plan.yaml）。

    Raises:
        FileNotFoundError: `package.package_uri` 指向目录不存在 / SKILL.md
            缺失（plan.yaml 缺失允许，对应可选场景）。
        ValueError: SKILL.md 缺 non-authority statement（沿用
            `parse_skill_md_view` 校验）。
    """
    package_dir = Path(package.package_uri)
    if not package_dir.is_dir():
        raise FileNotFoundError(
            f"package_uri does not point to a directory: {package.package_uri}"
        )
    skill_md_path = package_dir / "SKILL.md"
    plan_yaml_path = package_dir / "plan.yaml"
    skill_md_text = parse_skill_md_view(skill_md_path)
    plan_yaml_text: Optional[str] = None
    if plan_yaml_path.is_file():
        # 文本本身按原样返；plan.yaml schema 校验已在 load_skill_package 完成。
        plan_yaml_text = plan_yaml_path.read_text(encoding="utf-8")
    return {
        "skill_md_text": skill_md_text,
        "plan_yaml_text": plan_yaml_text,
    }


__all__ = [
    "HARD_FORBIDDEN_ACTIONS",
    "FORBIDDEN_PHRASES",
    "FORBIDDEN_SCOPE_LITERAL_TOKENS",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "parse_skill_json",
    "parse_skill_md_view",
    "parse_plan_yaml",
    "parse_validation_records",
    "load_skill_package",
    "load_skill_package_texts",
    "assert_skill_package_safe",
]
