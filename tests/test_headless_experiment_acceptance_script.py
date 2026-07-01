import importlib.util
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_headless_experiment_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("run_headless_experiment_acceptance", _SCRIPT_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
_exit_code_for_summary = _MODULE._exit_code_for_summary


def test_live_acceptance_script_exit_code_rejects_benchmark_failures():
    assert _exit_code_for_summary(
        {
            "total_runs": 2,
            "passed": 1,
            "benchmark_failed": 1,
            "infrastructure_failed": 0,
            "skipped": 0,
        }
    ) == 3


def test_live_acceptance_script_exit_code_accepts_only_all_passed_runs():
    assert _exit_code_for_summary(
        {
            "total_runs": 2,
            "passed": 2,
            "benchmark_failed": 0,
            "infrastructure_failed": 0,
            "skipped": 0,
        }
    ) == 0
