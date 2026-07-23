from __future__ import annotations

import argparse
from pathlib import Path

from workflow_engine.regulation_projection_contract import (
    DEFAULT_RULECARD_BUNDLE_DIR,
    write_projection_compile_artifacts,
)
from workflow_engine.regulation_projection_executor import (
    execute_projection_batch_v2,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPILED_SPEC_DIR = PROJECT_ROOT / "experiments" / "runs" / "20260422_regulation_projection_compiled_spec"


def _compile(args: argparse.Namespace) -> int:
    """编译 rule_card bundle → projection contract / compiled spec / manifest（无关 v2 化）."""
    bundle_dir = Path(args.bundle_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    paths = write_projection_compile_artifacts(output_dir=output_dir, bundle_dir=bundle_dir)
    print(paths["contract_path"])
    print(paths["spec_path"])
    print(paths["manifest_path"])
    return 0


def _execute_v2(args: argparse.Namespace) -> int:
    """V2 batch executor — 读 v2 building-centric inputs，输出 projection summary / results / samples.

    入口：`execute_projection_batch_v2`（W2 spec 03 / spec 04 phase 3-4 主调用）。
    输入：W0+W1 worldgen 三件 parquet（building_worlds / normative_projection / sidecar_runtime）；
    输出：projection_results.json + projection_summary.json + samples.json。
    """
    building_worlds_path = Path(args.building_worlds).resolve()
    normative_projection_path = Path(args.normative_projection).resolve()
    sidecar_runtime_path = Path(args.sidecar_runtime).resolve()
    output_dir = Path(args.output_dir).resolve()
    paths = execute_projection_batch_v2(
        building_worlds_path=building_worlds_path,
        normative_projection_path=normative_projection_path,
        sidecar_runtime_path=sidecar_runtime_path,
        output_dir=output_dir,
    )
    print(paths["results_path"])
    print(paths["summary_path"])
    print(paths["samples_path"])
    return 0


def _run_worldgen_batch_v2(args: argparse.Namespace) -> int:
    """从 v2 worldgen batch 输出目录跑 v2 batch executor.

    2026-05-10 全替换 parquet：
    `batch_dir` 应含 `WorldgenWorldBundles.v2.parquet/`（directory）+ 同模式 sidecar + projection。
    旧 `*.v2.json` 路径若仍存在（migration 期）也兼容；优先 parquet directory。
    """
    batch_dir = Path(args.batch_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    # 优先 parquet directory；fallback legacy JSON
    bw_path = batch_dir / "WorldgenWorldBundles.v2.parquet"
    if not bw_path.exists():
        bw_path = batch_dir / "WorldgenWorldBundles.v2.json"
    np_path = batch_dir / "WorldgenNormativeProjection.v2.parquet"
    if not np_path.exists():
        np_path = batch_dir / "WorldgenNormativeProjection.v2.json"
    sc_path = batch_dir / "WorldgenSidecarRuntimeBundle.v2.parquet"
    if not sc_path.exists():
        sc_path = batch_dir / "WorldgenSidecarRuntimeBundle.v2.json"
    execute_paths = execute_projection_batch_v2(
        building_worlds_path=bw_path,
        normative_projection_path=np_path,
        sidecar_runtime_path=sc_path,
        output_dir=output_dir,
    )
    print(execute_paths["results_path"])
    print(execute_paths["summary_path"])
    print(execute_paths["samples_path"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compile and execute repo-native Regulation Projection (v2).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("bundle_dir", nargs="?", default=str(DEFAULT_RULECARD_BUNDLE_DIR))
    compile_parser.add_argument("output_dir", nargs="?", default=str(DEFAULT_COMPILED_SPEC_DIR))
    compile_parser.set_defaults(func=_compile)

    execute_parser = subparsers.add_parser("execute", help="V2 batch executor — needs building_worlds + normative_projection + sidecar_runtime JSON")
    execute_parser.add_argument("building_worlds", help="Path to WorldgenWorldBundles.v2.json")
    execute_parser.add_argument("normative_projection", help="Path to WorldgenNormativeProjection.v2.json")
    execute_parser.add_argument("sidecar_runtime", help="Path to WorldgenSidecarRuntimeBundle.v2.json")
    execute_parser.add_argument("output_dir")
    execute_parser.set_defaults(func=_execute_v2)

    run_batch_parser = subparsers.add_parser("run-worldgen-batch", help="V2: 从 v2 worldgen batch 输出目录直接跑 batch executor")
    run_batch_parser.add_argument("batch_dir", help="run_worldgenerator_fullcoverage_framework_v2 的输出目录")
    run_batch_parser.add_argument("output_dir")
    run_batch_parser.set_defaults(func=_run_worldgen_batch_v2)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
