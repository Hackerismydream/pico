from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable


def materialize(workspace: Path, fixture: dict[str, Any]) -> tuple[str, ...]:
    kind = fixture["kind"]
    starter = {
        "config_precedence": "def resolve(cli, env, project, default):\n    raise NotImplementedError\n",
        "retry_after": ("def retry_delay(header, *, now, attempt, minimum, maximum):\n    raise NotImplementedError\n"),
        "atomic_json": "def write_json(path, value):\n    raise NotImplementedError\n",
        "jsonl_dedup": ("def aggregate(paths, *, identity_fields, keep='first'):\n    raise NotImplementedError\n"),
        "path_containment": (
            "def safe_path(workspace, candidate, *, allow_root=False):\n    raise NotImplementedError\n"
        ),
        "async_cleanup": "async def run_managed(factories, body):\n    raise NotImplementedError\n",
        "verification_receipts": "def verification_name(command):\n    raise NotImplementedError\n",
        "derived_skill_admission": (
            "def select_skills(candidates, selected_ids=None, *, gate_failed=False, max_select=2, legacy_top_k=5):\n"
            "    raise NotImplementedError\n"
        ),
        "checkpoint_policy": "def checkpoint_active(policy, *, interactive):\n    raise NotImplementedError\n",
        "source_failure_isolation": "def isolate_sources(sources):\n    raise NotImplementedError\n",
        "delivery_accounting": (
            "def delivery_outcome(*, runner_state, outlet_matches, emitted, outlet_accepted):\n"
            "    raise NotImplementedError\n"
        ),
        "activation_governance": (
            "def activation_state(candidate_kind, *, train_promoted, sealed_credited, human_approved):\n"
            "    raise NotImplementedError\n"
        ),
    }.get(kind)
    if starter is None:
        raise ValueError(f"unknown skill transfer fixture: {kind}")
    (workspace / "solution.py").write_text(starter, encoding="utf-8")
    (workspace / "smoke.py").write_text(_smoke(kind), encoding="utf-8")
    return ("solution.py", "smoke.py")


def verify(workspace: Path, fixture: dict[str, Any]) -> dict[str, Any]:
    try:
        module = _load(workspace / "solution.py")
        checks = _CHECKS[fixture["kind"]](module, fixture["variant"])
        passed = all(checks.values())
        error = None
    except Exception as exc:
        checks = {}
        passed = False
        error = {"type": type(exc).__name__, "message": str(exc)}
    return {
        "schema": "pico.picobench.skill-transfer.verification.v1",
        "fixture": fixture,
        "passed": passed,
        "checks": checks,
        "error": error,
    }


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("skill_transfer_solution", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("solution module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _smoke(kind: str) -> str:
    examples = {
        "config_precedence": "assert resolve(None, 0, 3, 4) == 0",
        "retry_after": "assert retry_delay('2', now=0, attempt=0, minimum=1, maximum=10) == 2",
        "atomic_json": (
            "from pathlib import Path\nimport tempfile\n"
            "with tempfile.TemporaryDirectory() as d:\n"
            "    p = Path(d) / 'state.json'\n"
            "    write_json(p, {'b': 2, 'a': 1})\n"
            "    assert p.exists()"
        ),
        "jsonl_dedup": (
            "from pathlib import Path\nimport tempfile\n"
            "with tempfile.TemporaryDirectory() as d:\n"
            "    p = Path(d) / 'x.jsonl'\n"
            '    p.write_text(\'{"id":1}\n{"id":1}\n\')\n'
            "    assert len(aggregate([p], identity_fields=['id'])['records']) == 1"
        ),
        "path_containment": (
            "from pathlib import Path\nimport tempfile\n"
            "with tempfile.TemporaryDirectory() as d:\n"
            "    root = Path(d)\n"
            "    assert safe_path(root, 'x.txt') == (root / 'x.txt').resolve()"
        ),
        "async_cleanup": (
            "import asyncio\n"
            "class R:\n"
            "    async def close(self): pass\n"
            "async def factory(): return R()\n"
            "async def body(resources): return len(resources)\n"
            "assert asyncio.run(run_managed([factory], body)) == 1"
        ),
        "verification_receipts": "assert verification_name('uv run pytest -q') == 'pytest'",
        "derived_skill_admission": (
            "candidates = [{'id':'local/a','gate_required':False},{'id':'myna/b','gate_required':True}]\n"
            "assert select_skills(candidates, gate_failed=True) == ['local/a']"
        ),
        "checkpoint_policy": "assert checkpoint_active('interactive', interactive=True) is True",
        "source_failure_isolation": (
            "result = isolate_sources([{'name':'local','hits':['a']},{'name':'memory','error_type':'TimeoutError'}])\n"
            "assert result['hits'] == ['a']"
        ),
        "delivery_accounting": (
            "assert delivery_outcome(runner_state='completed', outlet_matches=True, emitted=True, "
            "outlet_accepted=True) == 'delivered'"
        ),
        "activation_governance": (
            "assert activation_state('runtime', train_promoted=True, sealed_credited=True, "
            "human_approved=False) == 'pending_human'"
        ),
    }
    return f"from solution import *\n{examples[kind]}\n"


def _config(module: Any, variant: str) -> dict[str, bool]:
    cases = {
        "integer_zero": ((0, 2, 3, 4, 0), (None, 2, 3, 4, 2)),
        "boolean_false": ((False, True, True, True, False), (None, False, True, True, False)),
        "empty_string": (("", "env", "project", "default", ""), (None, "env", "project", "default", "env")),
        "four_layers": ((None, None, 8, 4, 8), (None, None, None, 4, 4)),
    }[variant]
    return {f"case_{index}": module.resolve(*values[:4]) == values[4] for index, values in enumerate(cases, 1)}


def _retry(module: Any, variant: str) -> dict[str, bool]:
    import datetime as dt
    from email.utils import format_datetime

    now = 1_800_000_000
    date = format_datetime(dt.datetime.fromtimestamp(now + 7, tz=dt.timezone.utc), usegmt=True)
    cases = {
        "delta_seconds": (("3", now, 0, 1, 10, 3), ("0", now, 2, 1, 10, 1)),
        "http_date": ((date, now, 0, 1, 10, 7),),
        "malformed": (("later", now, 2, 1, 10, 4), (None, now, 4, 1, 10, 10)),
        "clamping": (("99", now, 0, 2, 9, 9), ("-3", now, 0, 2, 9, 2)),
    }[variant]
    return {
        f"case_{index}": module.retry_delay(
            values[0], now=values[1], attempt=values[2], minimum=values[3], maximum=values[4]
        )
        == values[5]
        for index, values in enumerate(cases, 1)
    }


def _atomic(module: Any, variant: str) -> dict[str, bool]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / "state.json"
        path.write_text('{"old":true}\n', encoding="utf-8")
        if variant == "serialization_failure":
            try:
                module.write_json(path, {"bad": object()})
            except (TypeError, ValueError):
                pass
            return {
                "old_preserved": path.read_text(encoding="utf-8") == '{"old":true}\n',
                "temporary_cleaned": list(root.iterdir()) == [path],
            }
        module.write_json(path, {"b": 2, "a": 1})
        payload = path.read_text(encoding="utf-8")
        decoded = json.loads(payload)
        checks = {
            "valid_json": decoded == {"a": 1, "b": 2},
            "stable_order": payload.index('"a"') < payload.index('"b"'),
            "temporary_cleaned": list(root.iterdir()) == [path],
        }
        if variant == "replace_failure":
            checks["same_directory_strategy"] = not any(item.name.startswith("tmp") for item in root.iterdir())
        return checks


def _jsonl(module: Any, variant: str) -> dict[str, bool]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        left, right = root / "left.jsonl", root / "right.jsonl"
        left.write_text('{"id":1,"scope":"a","value":"first"}\ninvalid\n{"id":2,"scope":"a"}\n', encoding="utf-8")
        right.write_text('{"id":1,"scope":"a","value":"last"}\n{"id":1,"scope":"b"}\n', encoding="utf-8")
        fields = ["id", "scope"] if variant == "compound" else ["id"]
        keep = "last" if variant == "last_seen" else "first"
        result = module.aggregate([left, right], identity_fields=fields, keep=keep)
        records = result["records"]
        checks = {
            "invalid_count": result["invalid_lines"] == 1,
            "stable_count": len(records) == (3 if variant == "compound" else 2),
        }
        if variant == "last_seen":
            checks["last_wins"] = records[0].get("scope") == "b"
        if variant == "conflict":
            checks["conflict_reported"] = bool(result["conflicts"])
        return checks


def _path(module: Any, variant: str) -> dict[str, bool]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "workspace"
        root.mkdir()
        inside = module.safe_path(root, "a/../b.txt") == (root / "b.txt").resolve()
        checks = {"normalized_inside": inside}
        if variant == "root_equality":
            try:
                module.safe_path(root, ".")
                rejected = False
            except ValueError:
                rejected = True
            checks["root_policy"] = rejected and module.safe_path(root, ".", allow_root=True) == root.resolve()
        else:
            candidate = "../escape.txt"
            if variant == "symlink_escape":
                outside = Path(directory) / "outside"
                outside.mkdir()
                os.symlink(outside, root / "link")
                candidate = "link/escape.txt"
            try:
                module.safe_path(root, candidate)
                rejected = False
            except ValueError:
                rejected = True
            checks["escape_rejected"] = rejected
        return checks


def _async(module: Any, variant: str) -> dict[str, bool]:
    events: list[str] = []

    class Resource:
        def __init__(self, name: str, *, close_fails: bool = False) -> None:
            self.name = name
            self.close_fails = close_fails

        async def close(self) -> None:
            events.append(f"close:{self.name}")
            if self.close_fails:
                raise RuntimeError("close failed")

    async def factory(name: str, *, fails: bool = False, close_fails: bool = False):
        if fails:
            raise RuntimeError("open failed")
        events.append(f"open:{name}")
        return Resource(name, close_fails=close_fails)

    async def scenario() -> dict[str, bool]:
        if variant == "partial_open":
            try:
                await module.run_managed([lambda: factory("a"), lambda: factory("b", fails=True)], lambda _: None)
            except RuntimeError:
                pass
            return {"partial_cleanup": events == ["open:a", "close:a"]}

        async def body(resources):
            if variant in {"cancellation", "dual_failure"}:
                raise asyncio.CancelledError() if variant == "cancellation" else ValueError("body failed")
            return len(resources)

        factories = [lambda: factory("a", close_fails=variant == "dual_failure")]
        try:
            result = await module.run_managed(factories, body)
        except BaseException as exc:
            result = exc
        checks = {"closed": events[-1:] == ["close:a"]}
        if variant == "context_manager":
            checks["result"] = result == 1
        elif variant == "cancellation":
            checks["cancellation_preserved"] = isinstance(result, asyncio.CancelledError)
        else:
            checks["body_exception_preserved"] = isinstance(result, ValueError)
        return checks

    return asyncio.run(scenario())


def _verification_receipts(module: Any, variant: str) -> dict[str, bool]:
    cases = {
        "python_checks": {
            "pytest": ("pytest -q", "pytest"),
            "uv_pytest": ("uv run pytest tests -q", "pytest"),
            "mypy": ("mypy src", "mypy"),
            "ruff": ("ruff check src", "ruff"),
            "unsupported_ruff": ("ruff analyze src", None),
        },
        "masked_commands": {
            "or_mask": ("pytest || true", None),
            "and_mask": ("make check && echo ok", None),
            "pipe_mask": ("pytest | tee test.log", None),
            "sequence_mask": ("cargo test; echo done", None),
            "background_mask": ("go test ./... &", None),
            "newline_mask": ("pytest\necho ok", None),
        },
        "package_commands": {
            "npm_test": ("npm test", "npm"),
            "npm_build": ("npm run build", "npm"),
            "pnpm_test": ("pnpm run test", "pnpm"),
            "cargo_check": ("cargo check", "cargo"),
            "go_vet": ("go vet ./...", "go"),
            "maven": ("./mvnw test", "mvnw"),
        },
        "non_checks": {
            "prose": ("echo tests passed", None),
            "python_wrapper": ("python -m pytest", None),
            "make_deploy": ("make deploy", None),
            "npm_lint": ("npm run lint", None),
            "empty": ("", None),
            "broken_quote": ("pytest '", None),
        },
    }[variant]
    return {name: module.verification_name(command) == expected for name, (command, expected) in cases.items()}


def _derived_skill_admission(module: Any, variant: str) -> dict[str, bool]:
    local_a = {"id": "local/a", "gate_required": False}
    local_b = {"id": "local/b", "gate_required": False}
    myna_a = {"id": "myna/a", "gate_required": True}
    myna_b = {"id": "myna/b", "gate_required": True}
    myna_c = {"id": "myna/c", "gate_required": True}
    if variant == "provider_failure":
        return {
            "derived_abstains": module.select_skills([myna_a, local_a, myna_b, local_b], gate_failed=True)
            == ["local/a", "local/b"],
            "legacy_limit": module.select_skills(
                [local_a, local_b, {"id": "local/c", "gate_required": False}],
                gate_failed=True,
                legacy_top_k=2,
            )
            == ["local/a", "local/b"],
        }
    if variant == "unknown_id":
        return {
            "unknown_invalidates": module.select_skills([myna_a, local_a], ["myna/a", "ghost/missing"]) == ["local/a"]
        }
    if variant == "explicit_empty":
        return {"empty_rejects_derived": module.select_skills([myna_a, local_a, myna_b], []) == ["local/a"]}
    return {
        "bounded_exact_selection": module.select_skills(
            [myna_a, local_a, myna_b, myna_c],
            ["myna/c", "myna/b", "myna/a"],
            max_select=2,
        )
        == ["local/a", "myna/b", "myna/c"]
    }


def _checkpoint_policy(module: Any, variant: str) -> dict[str, bool]:
    if variant in {"never", "always", "interactive"}:
        expected = {
            "never": (False, False),
            "always": (True, True),
            "interactive": (True, False),
        }[variant]
        return {
            "interactive_call": module.checkpoint_active(variant, interactive=True) is expected[0],
            "one_shot_call": module.checkpoint_active(variant, interactive=False) is expected[1],
        }
    try:
        module.checkpoint_active("sometimes", interactive=True)
        rejected = False
    except ValueError:
        rejected = True
    return {"invalid_rejected": rejected}


def _source_failure_isolation(module: Any, variant: str) -> dict[str, bool]:
    local = {"name": "local", "hits": ["local/a", "local/b"]}
    memory_failure = {"name": "memory", "error_type": "TimeoutError"}
    hub_failure = {"name": "hub", "error_type": "ConnectionError"}
    if variant == "one_failure":
        result = module.isolate_sources([local, memory_failure])
        return {
            "healthy_hits_preserved": result["hits"] == ["local/a", "local/b"],
            "failure_recorded": result["failed_sources"] == ["memory"],
        }
    if variant == "ordered_diagnostics":
        result = module.isolate_sources([hub_failure, local, memory_failure])
        return {
            "failure_order": result["failed_sources"] == ["hub", "memory"],
            "failure_types": result["failure_types"] == {"hub": "ConnectionError", "memory": "TimeoutError"},
        }
    if variant == "all_fail":
        result = module.isolate_sources([memory_failure, hub_failure])
        return {
            "empty_hits": result["hits"] == [],
            "all_failures_visible": result["failed_sources"] == ["memory", "hub"],
        }
    result = module.isolate_sources(
        [
            {"name": "first", "hits": ["a", "b"]},
            {"name": "empty", "hits": []},
            {"name": "last", "hits": ["c"]},
        ]
    )
    return {
        "hit_order": result["hits"] == ["a", "b", "c"],
        "no_false_failures": result["failed_sources"] == [] and result["failure_types"] == {},
    }


def _delivery_accounting(module: Any, variant: str) -> dict[str, bool]:
    def classify(runner_state: str, outlet_matches: bool, emitted: bool, outlet_accepted: bool) -> str:
        return module.delivery_outcome(
            runner_state=runner_state,
            outlet_matches=outlet_matches,
            emitted=emitted,
            outlet_accepted=outlet_accepted,
        )

    if variant == "delivered":
        return {"delivered": classify("completed", True, True, True) == "delivered"}
    if variant == "dropped":
        return {
            "silent_dropped": classify("completed", True, False, True) == "dropped",
            "rejected_dropped": classify("completed", True, True, False) == "dropped",
        }
    if variant == "no_outlet":
        return {
            "unmatched": classify("completed", False, True, True) == "no_outlet",
            "unmatched_silent": classify("completed", False, False, False) == "no_outlet",
        }
    return {
        "provider_failure_dropped": classify("provider_failed", True, False, True) == "dropped",
        "runtime_error_dropped": classify("error", True, True, True) == "dropped",
    }


def _activation_governance(module: Any, variant: str) -> dict[str, bool]:
    def state(kind: str, train: bool, sealed: bool, human: bool) -> str:
        return module.activation_state(
            kind,
            train_promoted=train,
            sealed_credited=sealed,
            human_approved=human,
        )

    if variant == "pending_human":
        return {"awaits_authority": state("runtime", True, True, False) == "pending_human"}
    if variant == "unsupported_kind":
        return {
            "skill_ineligible": state("skill", True, True, True) == "ineligible",
            "prompt_ineligible": state("prompt", True, True, True) == "ineligible",
            "route_ineligible": state("route", True, True, True) == "ineligible",
        }
    if variant == "sealed_not_credited":
        return {
            "sealed_gate": state("runtime", True, False, True) == "ineligible",
            "train_gate": state("runtime", False, True, True) == "ineligible",
        }
    return {
        "human_makes_ready": state("runtime", True, True, True) == "ready",
        "not_auto_activated": state("runtime", True, True, True) != "activated",
    }


_CHECKS: dict[str, Callable[[Any, str], dict[str, bool]]] = {
    "config_precedence": _config,
    "retry_after": _retry,
    "atomic_json": _atomic,
    "jsonl_dedup": _jsonl,
    "path_containment": _path,
    "async_cleanup": _async,
    "verification_receipts": _verification_receipts,
    "derived_skill_admission": _derived_skill_admission,
    "checkpoint_policy": _checkpoint_policy,
    "source_failure_isolation": _source_failure_isolation,
    "delivery_accounting": _delivery_accounting,
    "activation_governance": _activation_governance,
}


__all__ = ["materialize", "verify"]
