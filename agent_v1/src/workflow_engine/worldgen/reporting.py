from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from workflow_engine.worldgen.constants import (
    BATCH_CONTRACT_TARGETS,
    DEFAULT_BATCH_RANDOM_SEED,
    PROJECT_ROOT,
)
from workflow_engine.worldgen.validation import run_worldgenerator_fullcoverage_framework

DEFAULT_RUNS_ROOT = PROJECT_ROOT / "experiments" / "runs"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "团队文档" / "技术团队文档"
SUMMARY_FILENAME = "WorldgenFullCoverageSummary.json"
VALIDATION_FILENAME = "WorldgenFullCoverageValidation.v1.json"
WORLD_BUNDLE_FILENAME = "WorldgenFullCoverageBundle.v1.json"
TIER_ORDER = ["smoke_batch", "dev_batch", "benchmark_batch", "release_batch"]
TIER_LABELS = {
    "smoke_batch": "120 (smoke)",
    "dev_batch": "600 (dev)",
    "benchmark_batch": "1200 (benchmark)",
    "release_batch": "3000 (release)",
}
SEVERITY_ORDER = [
    "minor",
    "moderate",
    "major",
    "severe",
    "critical",
]
TEMPLATE_LABELS = {
    "FT_EXT_WALL_CRACK_COVERED_V1": "被遮挡外墙裂缝切片",
    "FT_DRAINAGE_MISCONNECTION_V1": "排水错接切片",
    "FT_UBW_FIRE_SAFETY_V1": "僭建与消防缺陷切片",
    "FT_RC_BEAM_SPALL_REPAIR_V1": "钢筋混凝土梁剥落修复切片",
    "FT_FACADE_MOISTURE_DETACHMENT_V1": "立面潮湿渗漏与脱落切片",
    "FT_TRANSFER_BEAM_HOLLOWING_V1": "转换梁空鼓切片",
    "FT_DRAINAGE_NETWORK_BLOCKAGE_V1": "排水网络堵塞切片",
    "FT_ESCAPE_STAIR_FIRE_DEFICIENCY_V1": "逃生楼梯消防缺陷切片",
    "FT_REPAIR_PATCH_VALIDATION_V1": "修补区验证切片",
}


@dataclass(frozen=True)
class BatchRunArtifact:
    batch_profile: str
    requested_count: int
    run_dir: Path
    summary_path: Path
    validation_path: Path
    world_bundle_path: Path


@dataclass(frozen=True)
class BatchDistributionSnapshot:
    batch_profile: str
    requested_count: int
    world_count: int
    run_dir: Path
    summary_path: Path
    validation_path: Path
    world_bundle_path: Path
    validation_passed: bool
    severity_ratios: Dict[str, float]
    template_ratios: Dict[str, float]
    fragment_family_ratios: Dict[str, float]
    domain_tag_ratios: Dict[str, float]
    measurement_branch_ratios: Dict[str, float]
    summary_payload: Dict[str, Any]
    validation_payload: Dict[str, Any]


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _ratio(value: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return value / total


def _format_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_pp(value: float) -> str:
    return f"{value * 100:.1f} pp"


def _humanize_token(token: str) -> str:
    cleaned = token
    for prefix in ("FT_", "BT_", "DC_", "NP_", "RULE_", "marker."):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    cleaned = cleaned.replace("_V1", "").replace("_V2", "")
    cleaned = cleaned.replace(".", " ")
    cleaned = cleaned.replace("_", " ")
    return " ".join(cleaned.split()).lower()


def _template_label(template_id: str) -> str:
    return TEMPLATE_LABELS.get(template_id, _humanize_token(template_id))


def _batch_run_dir_name(run_date: str, batch_profile: str) -> str:
    return f"{run_date}_worldgenerator_{batch_profile}"


def expected_run_dir(runs_root: Path, run_date: str, batch_profile: str) -> Path:
    return runs_root / _batch_run_dir_name(run_date, batch_profile)


def run_batch_suite(
    runs_root: Path = DEFAULT_RUNS_ROOT,
    run_date: Optional[str] = None,
    seed: int = DEFAULT_BATCH_RANDOM_SEED,
    include_smoke: bool = True,
) -> List[BatchRunArtifact]:
    resolved_date = run_date or date.today().strftime("%Y%m%d")
    batch_profiles = TIER_ORDER if include_smoke else TIER_ORDER[1:]
    artifacts: List[BatchRunArtifact] = []
    for batch_profile in batch_profiles:
        requested_count = BATCH_CONTRACT_TARGETS[batch_profile]
        run_dir = expected_run_dir(runs_root, resolved_date, batch_profile)
        bundle = run_worldgenerator_fullcoverage_framework(
            output_dir=run_dir,
            count=requested_count,
            seed=seed,
        )
        artifacts.append(
            BatchRunArtifact(
                batch_profile=batch_profile,
                requested_count=requested_count,
                run_dir=Path(bundle.output_dir),
                summary_path=Path(bundle.summary_path),
                validation_path=Path(bundle.validation_report_path),
                world_bundle_path=Path(bundle.world_bundle_path),
            )
        )
    return artifacts


def load_batch_snapshot(run_dir: Path) -> BatchDistributionSnapshot:
    summary_path = run_dir / SUMMARY_FILENAME
    validation_path = run_dir / VALIDATION_FILENAME
    world_bundle_path = run_dir / WORLD_BUNDLE_FILENAME
    summary_payload = _load_json(summary_path)
    validation_payload = _load_json(validation_path)
    world_count = int(summary_payload["world_count"])
    severity_ratios = {
        severity: _ratio(int(summary_payload.get("severity_distribution", {}).get(severity, 0)), world_count)
        for severity in SEVERITY_ORDER
    }
    template_ratios = {
        template_id: _ratio(int(count), world_count)
        for template_id, count in summary_payload.get("template_distribution", {}).items()
    }
    fragment_family_ratios = {
        key: _ratio(int(count), world_count)
        for key, count in summary_payload.get("fragment_family_distribution", {}).items()
    }
    domain_tag_ratios = {
        key: _ratio(int(count), world_count)
        for key, count in summary_payload.get("domain_tag_distribution", {}).items()
    }
    measurement_branch_ratios = {
        key: _ratio(int(count), world_count)
        for key, count in summary_payload.get("measurement_branch_distribution", {}).items()
    }
    validation_passed = all(bool(check.get("passed")) for check in validation_payload.get("checks", []))
    return BatchDistributionSnapshot(
        batch_profile=str(summary_payload["batch_profile"]),
        requested_count=int(summary_payload["requested_count"]),
        world_count=world_count,
        run_dir=run_dir,
        summary_path=summary_path,
        validation_path=validation_path,
        world_bundle_path=world_bundle_path,
        validation_passed=validation_passed,
        severity_ratios=severity_ratios,
        template_ratios=template_ratios,
        fragment_family_ratios=fragment_family_ratios,
        domain_tag_ratios=domain_tag_ratios,
        measurement_branch_ratios=measurement_branch_ratios,
        summary_payload=summary_payload,
        validation_payload=validation_payload,
    )


def load_snapshots_for_date(
    runs_root: Path = DEFAULT_RUNS_ROOT,
    run_date: Optional[str] = None,
    include_smoke: bool = True,
) -> List[BatchDistributionSnapshot]:
    resolved_date = run_date or date.today().strftime("%Y%m%d")
    batch_profiles = TIER_ORDER if include_smoke else TIER_ORDER[1:]
    return [
        load_batch_snapshot(expected_run_dir(runs_root, resolved_date, batch_profile))
        for batch_profile in batch_profiles
    ]


def _ordered_snapshots(snapshots: Sequence[BatchDistributionSnapshot]) -> List[BatchDistributionSnapshot]:
    ordering = {batch_profile: index for index, batch_profile in enumerate(TIER_ORDER)}
    return sorted(snapshots, key=lambda snapshot: ordering.get(snapshot.batch_profile, 999))


def _metric_drift(values: Iterable[float]) -> float:
    series = list(values)
    if not series:
        return 0.0
    return max(series) - min(series)


def _drift_assessment(drift: float) -> str:
    if drift <= 0.02:
        return "没有明显漂移"
    if drift <= 0.05:
        return "轻微漂移"
    return "明显漂移"


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join("---" for _ in headers) + " |"
    body_lines = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header_line, separator_line, *body_lines])


def _load_worlds(run_dir: Path) -> List[Dict[str, Any]]:
    payload = _load_json(run_dir / WORLD_BUNDLE_FILENAME)
    return list(payload.get("worlds", []))


def _release_template_projection_support(release_snapshot: BatchDistributionSnapshot) -> Dict[str, int]:
    support_map: Dict[str, set[str]] = {}
    for world in _load_worlds(release_snapshot.run_dir):
        template_id = world["fragment_context"]["fragment_template_id"]
        projection_family = world["normative_projection"]["projection_family"]
        support_map.setdefault(template_id, set()).add(projection_family)
    return {template_id: len(families) for template_id, families in support_map.items()}


def _build_stability_observations(snapshots: Sequence[BatchDistributionSnapshot]) -> List[str]:
    ordered = _ordered_snapshots(snapshots)
    severity_drifts = {
        severity: _metric_drift(snapshot.severity_ratios.get(severity, 0.0) for snapshot in ordered)
        for severity in SEVERITY_ORDER
    }
    all_templates = sorted({template_id for snapshot in ordered for template_id in snapshot.template_ratios})
    template_drifts = {
        template_id: _metric_drift(snapshot.template_ratios.get(template_id, 0.0) for snapshot in ordered)
        for template_id in all_templates
    }
    all_branches = sorted({branch for snapshot in ordered for branch in snapshot.measurement_branch_ratios})
    branch_drifts = {
        branch: _metric_drift(snapshot.measurement_branch_ratios.get(branch, 0.0) for snapshot in ordered)
        for branch in all_branches
    }
    max_template_id = max(template_drifts, key=template_drifts.get) if template_drifts else ""
    max_severity = max(severity_drifts, key=severity_drifts.get) if severity_drifts else ""
    max_branch = max(branch_drifts, key=branch_drifts.get) if branch_drifts else ""
    return [
        (
            "measurement branch 占比漂移峰值："
            f"{max_branch or 'n/a'} 为 {_format_pp(branch_drifts.get(max_branch, 0.0))}。"
            f"{_drift_assessment(branch_drifts.get(max_branch, 0.0))}。"
        ),
        (
            "严重程度漂移峰值："
            f"{max_severity} 为 {_format_pp(severity_drifts.get(max_severity, 0.0))}。"
            f"{_drift_assessment(severity_drifts.get(max_severity, 0.0))}。"
        ),
        (
            "模板占比漂移峰值："
            f"{max_template_id or 'n/a'} 为 {_format_pp(template_drifts.get(max_template_id, 0.0))}。"
            f"{_drift_assessment(template_drifts.get(max_template_id, 0.0))}。"
        ),
    ]


def _build_anomaly_notes(snapshots: Sequence[BatchDistributionSnapshot]) -> List[str]:
    ordered = _ordered_snapshots(snapshots)
    release_snapshot = ordered[-1]
    template_ratios = release_snapshot.template_ratios
    if not template_ratios:
        return ["release_batch summary 中没有发现模板分布数据。"]
    average_ratio = 1.0 / max(1, len(template_ratios))
    projection_support = _release_template_projection_support(release_snapshot)
    notes: List[str] = []
    high_templates = sorted(
        (
            (template_id, ratio)
            for template_id, ratio in template_ratios.items()
            if ratio >= average_ratio * 1.35
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    low_templates = sorted(
        (
            (template_id, ratio)
            for template_id, ratio in template_ratios.items()
            if 0.0 < ratio <= average_ratio * 0.65
        ),
        key=lambda item: item[1],
    )
    for template_id, ratio in high_templates[:3]:
        support_count = projection_support.get(template_id, 1)
        notes.append(
            f"{template_id} / {_template_label(template_id)} 在 release_batch 中占比达到 {_format_pct(ratio)}；"
            f"该模板承载 {support_count} 个 projection family，这更像结构性集中，不像运行时偏斜。"
        )
    for template_id, ratio in low_templates[:3]:
        support_count = projection_support.get(template_id, 1)
        notes.append(
            f"{template_id} / {_template_label(template_id)} 在 release_batch 中仅占 {_format_pct(ratio)}；"
            f"它只承载 {support_count} 个 projection family，属于尾部切片。"
        )
    if not notes:
        notes.append("没有切片触发异常集中启发式；release_batch 整体分布较均匀。")
    return notes


def build_distribution_report_markdown(snapshots: Sequence[BatchDistributionSnapshot]) -> str:
    ordered = _ordered_snapshots(snapshots)
    if not ordered:
        raise ValueError("At least one batch snapshot is required.")

    observation_rows = []
    for snapshot in ordered:
        observation_rows.append(
            [
                TIER_LABELS.get(snapshot.batch_profile, snapshot.batch_profile),
                str(snapshot.world_count),
                "passed" if snapshot.validation_passed else "failed",
                _format_pct(snapshot.measurement_branch_ratios.get("defect_geometry_measurement", 0.0)),
                _format_pct(snapshot.measurement_branch_ratios.get("coverage_sampling_measurement", 0.0)),
                _format_pct(snapshot.measurement_branch_ratios.get("structural_assessment_measurement", 0.0)),
            ]
        )

    severity_rows = []
    for snapshot in ordered:
        severity_rows.append(
            [
                TIER_LABELS.get(snapshot.batch_profile, snapshot.batch_profile),
                *[_format_pct(snapshot.severity_ratios.get(severity, 0.0)) for severity in SEVERITY_ORDER],
            ]
        )

    template_ids = sorted(
        {template_id for snapshot in ordered for template_id in snapshot.template_ratios},
        key=lambda template_id: (
            -ordered[-1].template_ratios.get(template_id, 0.0),
            template_id,
        ),
    )
    template_rows = []
    for template_id in template_ids:
        template_rows.append(
            [
                template_id,
                _template_label(template_id),
                *[_format_pct(snapshot.template_ratios.get(template_id, 0.0)) for snapshot in ordered],
            ]
        )

    stability_lines = _build_stability_observations(ordered)
    anomaly_lines = _build_anomaly_notes(ordered)
    report_date = date.today().isoformat()
    batch_seed = ordered[0].summary_payload.get("seed", DEFAULT_BATCH_RANDOM_SEED)
    report_lines = [
        "# WorldGenerator 大批次分布分析",
        "",
        f"- 报告日期：`{report_date}`",
        f"- 批次随机种子：`{batch_seed}`",
        f"- 产物根目录：`{ordered[0].run_dir.parent}`",
        f"- 对比批次：`{', '.join(TIER_LABELS.get(snapshot.batch_profile, snapshot.batch_profile) for snapshot in ordered)}`",
        "",
        "## 1. Worldgen 观测分布",
        "",
        _markdown_table(
            ["批次", "样本数", "Validation", "缺陷几何", "覆盖观察", "结构评估"],
            observation_rows,
        ),
        "",
        "## 2. 严重程度分布",
        "",
        _markdown_table(
            ["批次", "Minor", "Moderate", "Major", "Severe", "Critical"],
            severity_rows,
        ),
        "",
        "## 3. 模板覆盖比例",
        "",
        _markdown_table(
            ["模板 ID", "模板切片", *[TIER_LABELS.get(snapshot.batch_profile, snapshot.batch_profile) for snapshot in ordered]],
            template_rows,
        ),
        "",
        "## 4. 跨批次稳定性观察",
        "",
        *[f"- {line}" for line in stability_lines],
        "",
        "## 5. 异常集中点",
        "",
        *[f"- {line}" for line in anomaly_lines],
        "",
        "## 6. 产物路径",
        "",
        *[
            f"- `{snapshot.batch_profile}`：`{snapshot.summary_path}` 和 `{snapshot.validation_path}`"
            for snapshot in ordered
        ],
        "",
    ]
    return "\n".join(report_lines)


def write_distribution_report(
    snapshots: Sequence[BatchDistributionSnapshot],
    report_path: Path,
) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_distribution_report_markdown(snapshots), encoding="utf-8")
    return report_path


def _format_observed_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _primary_location(world: Dict[str, Any]) -> Dict[str, Any]:
    locations = world.get("locations", [])
    if locations:
        return locations[0]
    location_nodes = world.get("fragment_context", {}).get("location_graph_nodes", [])
    if location_nodes:
        qualifiers = location_nodes[0].get("qualifiers", [])
        return {
            "location_class": qualifiers[0] if qualifiers else "unknown",
            "exposure_zone": world.get("fragment_context", {}).get("exposure_zone", "unknown"),
            "storey_band": "unknown",
        }
    return {"location_class": "unknown", "exposure_zone": "unknown", "storey_band": "unknown"}


def _find_world(world_bundle_path: Path, world_id: str) -> Dict[str, Any]:
    payload = _load_json(world_bundle_path)
    for world in payload.get("worlds", []):
        if world.get("world_id") == world_id:
            return world
    raise KeyError(f"world_id not found: {world_id}")


def format_world_readable(world_bundle_path: Path, world_id: str) -> str:
    world = _find_world(world_bundle_path, world_id)
    building = world.get("building", {})
    fragment = world.get("fragment_context", {})
    location = _primary_location(world)
    condition = world.get("conditions", [{}])[0] if world.get("conditions") else {}
    projection = world.get("normative_projection", {})
    defect_ids = condition.get("condition_classes", [])
    defect_list = ", ".join(_humanize_token(defect_id) for defect_id in defect_ids) if defect_ids else "none"
    basis_items = projection.get("basis_items", [])
    primary_basis = basis_items[0] if basis_items else None
    verdict_reason = "worldgen does not produce verdict; run projection executor for compliance result."
    compliance_gap = "N/A in worldgen output."
    if primary_basis is not None:
        verdict_reason = (
            f"{primary_basis['reason_code']} 使用 `{primary_basis['slot_id']}` = "
            f"{_format_observed_value(primary_basis['observed_value'])}。"
        )
    lines = [
        f"World ID: {world['world_id']}",
        "",
        "楼栋基本情况",
        f"- 楼栋：{building.get('building_name', fragment.get('building_metadata', {}).get('building_name', 'unknown'))}",
        f"- 楼龄 / 楼层：{building.get('age_years', 0.0):.1f} 年 / {building.get('storey_count', fragment.get('building_metadata', {}).get('floor_count', 'unknown'))} 层",
        f"- 类型：{building.get('building_use', 'unknown')} / {building.get('structure_type', 'unknown')}",
        f"- 位置：{location.get('location_class', 'unknown')} / exposure={location.get('exposure_zone', 'unknown')} / storey_band={location.get('storey_band', 'unknown')}",
        "",
        "主要缺陷",
        f"- 主缺陷：{_humanize_token(str(condition.get('condition_class', condition.get('dominant_condition_type', 'unknown'))))}",
        f"- 缺陷条件：{defect_list}",
        f"- 严重程度：{condition.get('severity_band', 'unknown')}",
        "",
        "检测结论",
        "- Verdict：worldgen does not produce verdict",
        f"- 原因：{verdict_reason}",
        "",
        "未满足要求",
        f"- {compliance_gap}",
    ]
    return "\n".join(lines)


def format_world_readable_from_run(run_dir: Path, world_id: str) -> str:
    return format_world_readable(run_dir / WORLD_BUNDLE_FILENAME, world_id)


def _discover_run_dirs(runs_root: Path) -> List[Path]:
    return sorted(
        [
            path
            for path in runs_root.iterdir()
            if path.is_dir() and (path / WORLD_BUNDLE_FILENAME).exists()
        ]
    )


def show_world_from_runs(runs_root: Path, world_id: str, run_dir: Optional[Path] = None) -> str:
    candidate_dirs = [run_dir] if run_dir is not None else _discover_run_dirs(runs_root)
    for candidate_dir in candidate_dirs:
        if candidate_dir is None:
            continue
        try:
            return format_world_readable_from_run(candidate_dir, world_id)
        except KeyError:
            continue
    raise KeyError(f"world_id not found in candidate runs: {world_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Worldgenerator batch reporting utilities.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_suite_parser = subparsers.add_parser("run-suite", help="Run smoke/dev/benchmark/release batch tiers.")
    run_suite_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    run_suite_parser.add_argument("--run-date", default=date.today().strftime("%Y%m%d"))
    run_suite_parser.add_argument("--seed", type=int, default=DEFAULT_BATCH_RANDOM_SEED)
    run_suite_parser.add_argument("--skip-smoke", action="store_true")

    report_parser = subparsers.add_parser("write-report", help="Write a markdown batch distribution report.")
    report_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    report_parser.add_argument("--run-date", default=date.today().strftime("%Y%m%d"))
    report_parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_DIR / f"REPORT_{date.today().strftime('%Y%m%d')}_worldgenerator_batch_distribution_analysis.md",
    )

    show_parser = subparsers.add_parser("show-world", help="Print a human-readable world sample.")
    show_parser.add_argument("--world-id", required=True)
    show_parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    show_parser.add_argument("--run-dir", type=Path)

    args = parser.parse_args()
    if args.command == "run-suite":
        artifacts = run_batch_suite(
            runs_root=args.runs_root,
            run_date=args.run_date,
            seed=args.seed,
            include_smoke=not args.skip_smoke,
        )
        print(
            json.dumps(
                [
                    {
                        "batch_profile": artifact.batch_profile,
                        "requested_count": artifact.requested_count,
                        "run_dir": str(artifact.run_dir),
                        "summary_path": str(artifact.summary_path),
                        "validation_path": str(artifact.validation_path),
                    }
                    for artifact in artifacts
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "write-report":
        snapshots = load_snapshots_for_date(runs_root=args.runs_root, run_date=args.run_date, include_smoke=True)
        report_path = write_distribution_report(snapshots=snapshots, report_path=args.report_path)
        print(str(report_path))
        return 0
    if args.command == "show-world":
        print(show_world_from_runs(runs_root=args.runs_root, world_id=args.world_id, run_dir=args.run_dir))
        return 0
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
