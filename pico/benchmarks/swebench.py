"""Generate SWE-bench predictions with Pico."""

from __future__ import annotations

import argparse
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ..cli import _build_model_client
from ..config import resolve_provider_config
from .swebench_agent import SWEBenchAgent, Trajectory
from .swebench_docker import resolve_image, run_shell, start_container, stop_container

DATASETS = {
    "lite": "SWE-bench/SWE-bench_Lite",
    "verified": "SWE-bench/SWE-bench_Verified",
    "full": "SWE-bench/SWE-bench",
}


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        instances = load_instances(args)
    except ImportError:
        print("pico-swebench requires optional dependency: uv sync --extra swebench")
        return 2

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    predictions = load_predictions(output / "preds.json")
    selected_ids = [str(instance["instance_id"]) for instance in instances]
    selected_count = len(selected_ids)
    if args.redo_existing:
        for instance_id in selected_ids:
            predictions.pop(instance_id, None)
    selected = filter_rerun_instances(
        instances,
        predictions,
        redo_existing=args.redo_existing,
        skip_existing_empty_predictions=args.skip_existing_empty_predictions,
    )
    skipped = selected_count - len(selected)

    trajectories: list[Trajectory] = []
    with ThreadPoolExecutor(max_workers=max(int(args.workers), 1)) as executor:
        futures = {executor.submit(run_instance, dict(instance), args): str(instance["instance_id"]) for instance in selected}
        for future in as_completed(futures):
            instance_id = futures[future]
            try:
                trajectory = future.result()
            except Exception as exc:
                trajectory = Trajectory(
                    instance_id=instance_id,
                    model=args.model or args.provider,
                    image="",
                    model_error=str(exc),
                    exit_status="model_error",
                    model_patch_chars=0,
                    model_patch="",
                    steps=[{"model_error": str(exc)}],
                )
            trajectories.append(trajectory)
            write_trajectory(output, trajectory)
            if trajectory.model_patch or args.include_empty_predictions:
                predictions[instance_id] = {
                    "model_name_or_path": f"pico-v3/{trajectory.model}",
                    "instance_id": instance_id,
                    "model_patch": trajectory.model_patch,
                }
                write_predictions(output / "preds.json", predictions)

    write_predictions(output / "preds.json", predictions)
    summary = build_summary(args, output, selected_ids, len(selected), skipped, predictions, trajectories)
    write_json(output / "summary.json", summary)
    return exit_code(summary)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", default="lite")
    parser.add_argument("--split", default="test", choices=("test", "dev"))
    parser.add_argument("--slice", default=None)
    parser.add_argument("--filter", default=None)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--redo-existing", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output", required=True)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--model", default=None)
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--max-steps", type=int, default=80)
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--command-timeout", type=int, default=120)
    parser.add_argument("--openai-timeout", type=int, default=300)
    parser.add_argument("--ollama-timeout", type=int, default=300)
    parser.add_argument("--include-empty-predictions", action="store_true")
    parser.add_argument("--skip-existing-empty-predictions", action="store_true")
    return parser


def load_instances(args) -> list[dict[str, Any]]:
    from datasets import load_dataset

    dataset_name = DATASETS.get(str(args.subset).lower(), args.subset)
    dataset = load_dataset(dataset_name, split=args.split)
    instances = [dict(item) for item in dataset]
    if args.filter:
        pattern = re.compile(args.filter)
        instances = [item for item in instances if pattern.search(str(item.get("instance_id", "")))]
    if args.shuffle:
        random.Random(0).shuffle(instances)
    if args.slice:
        instances = _apply_slice(instances, args.slice)
    return instances


def filter_rerun_instances(
    instances: list[dict[str, Any]],
    predictions: dict[str, dict[str, Any]],
    *,
    redo_existing: bool,
    skip_existing_empty_predictions: bool = False,
) -> list[dict[str, Any]]:
    if redo_existing:
        return instances
    selected = []
    for instance in instances:
        instance_id = str(instance["instance_id"])
        existing = predictions.get(instance_id)
        if existing is not None and skip_existing_empty_predictions:
            continue
        existing = existing or {}
        if str(existing.get("model_patch") or ""):
            continue
        selected.append(instance)
    return selected


def run_instance(instance: dict[str, Any], args) -> Trajectory:
    instance_id = str(instance.get("instance_id", ""))
    model_name = args.model or args.provider
    image = resolve_image_best_effort(instance)
    try:
        provider_config = resolve_provider_config(
            args.provider,
            start=".",
            config_path=args.config,
            model=args.model,
            base_url=args.base_url or args.host,
            api_key=args.api_key,
        )
        client = _build_model_client(
            SimpleNamespace(
                cwd=".",
                config=args.config,
                provider=args.provider,
                model=args.model,
                base_url=args.base_url or args.host,
                api_key=args.api_key,
                temperature=args.temperature,
                openai_timeout=args.openai_timeout,
            )
        )
        actual_model = (
            getattr(client, "model", None)
            or provider_config.model
            or args.model
            or args.provider
        )
    except Exception as exc:
        return Trajectory(
            instance_id=instance_id,
            model=model_name,
            image=image,
            model_error=str(exc),
            exit_status="model_error",
            model_patch_chars=0,
            model_patch="",
            steps=[{"model_error": str(exc)}],
        )

    agent = SWEBenchAgent(
        client,
        model=actual_model,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
    )
    output = Path(args.output)
    container = None
    try:
        container = start_container(image, timeout=args.command_timeout)
        return agent.run(
            instance,
            lambda command: run_shell(container, command, timeout=args.command_timeout),
            image=image,
            on_step=lambda trajectory: write_trajectory(output, trajectory),
        )
    except RuntimeError as exc:
        return Trajectory(
            instance_id=instance_id,
            model=actual_model,
            image=image,
            setup_error=str(exc),
            exit_status="setup_error",
            model_patch_chars=0,
            model_patch="",
        )
    except Exception as exc:
        return Trajectory(
            instance_id=instance_id,
            model=actual_model,
            image=image,
            model_error=str(exc),
            exit_status="model_error",
            model_patch_chars=0,
            model_patch="",
            steps=[{"model_error": str(exc)}],
        )
    finally:
        if container is not None:
            stop_container(container)


def resolve_image_best_effort(instance: dict[str, Any]) -> str:
    try:
        return resolve_image(instance)
    except Exception:
        return ""


def build_summary(
    args,
    output: Path,
    selected_ids: list[str],
    attempted_count: int,
    skipped_count: int,
    predictions: dict[str, dict[str, Any]],
    trajectories: list[Trajectory],
) -> dict[str, Any]:
    selected_id_set = set(selected_ids)
    attempted_ids = {item.instance_id for item in trajectories}
    skipped_ids = sorted(selected_id_set - attempted_ids)
    non_empty = sum(
        1
        for instance_id in selected_ids
        if str((predictions.get(instance_id) or {}).get("model_patch") or "")
    )
    empty_patch_count = sum(1 for item in trajectories if not item.model_patch)
    setup_error_count = sum(1 for item in trajectories if item.exit_status == "setup_error")
    model_error_count = sum(1 for item in trajectories if item.exit_status == "model_error")
    timeout_count = sum(
        1
        for item in trajectories
        for step in item.steps
        if (step.get("tool_result") or {}).get("timed_out") is True
    )
    failed_ids = [
        item.instance_id
        for item in trajectories
        if item.exit_status in {"setup_error", "model_error"} or not item.model_patch
    ]
    return {
        "subset": args.subset,
        "split": args.split,
        "selected_instances": len(selected_ids),
        "attempted_instances": attempted_count,
        "skipped_instances": skipped_count,
        "non_empty_predictions": non_empty,
        "total_predictions_in_file": len(predictions),
        "empty_patch_count": empty_patch_count,
        "setup_error_count": setup_error_count,
        "model_error_count": model_error_count,
        "timeout_count": timeout_count,
        "predictions_path": str(output / "preds.json"),
        "trajectory_root": str(output),
        "failed_instance_ids": failed_ids,
        "skipped_instance_ids": skipped_ids,
    }


def exit_code(summary: dict[str, Any]) -> int:
    if summary["selected_instances"] == 0:
        return 0
    if summary["attempted_instances"] > 0 and summary["non_empty_predictions"] == 0:
        return 1
    return 0


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def write_predictions(path: Path, predictions: dict[str, dict[str, Any]]) -> None:
    write_json(path, predictions)


def write_trajectory(output: Path, trajectory: Trajectory) -> None:
    path = output / trajectory.instance_id / f"{trajectory.instance_id}.traj.json"
    write_json(path, trajectory.to_dict())


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _apply_slice(items: list[dict[str, Any]], value: str) -> list[dict[str, Any]]:
    parts = value.split(":")
    if len(parts) > 3:
        raise SystemExit(f"invalid --slice value: {value}")
    indexes = [int(part) if part else None for part in parts]
    return items[slice(*indexes)]


if __name__ == "__main__":
    raise SystemExit(main())
