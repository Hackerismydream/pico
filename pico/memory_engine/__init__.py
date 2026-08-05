"""Memory contracts, host-owned context carriers, and Local Skill routing."""

from typing import TYPE_CHECKING

from pico.memory_engine.backend import Memory, MemoryBackend
from pico.memory_engine.base import AssembledContext, TokenBudget

if TYPE_CHECKING:
    from pico.memory_engine.contract_test import (
        LifecycleContractTests,
        MemoryBackendContractTests,
    )

__all__ = [
    "AssembledContext",
    "LifecycleContractTests",
    "Memory",
    "MemoryBackend",
    "MemoryBackendContractTests",
    "TokenBudget",
]


# The contract-test base classes live in ``contract_test``, which imports
# ``pytest`` (a dev-only dependency) at module top level. Importing them
# eagerly here would pull pytest into every ``import pico.memory_engine`` —
# breaking any production install without pytest (e.g. a packaged `pico`),
# with ``ModuleNotFoundError: No module named 'pytest'``. Expose them lazily
# (PEP 562) so they resolve only when actually accessed — which happens under
# pytest in the test suite, where the import succeeds.
def __getattr__(name: str):
    if name in ("LifecycleContractTests", "MemoryBackendContractTests"):
        from pico.memory_engine import contract_test

        return getattr(contract_test, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
