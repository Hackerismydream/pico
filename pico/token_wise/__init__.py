"""TokenWise — token and cost efficiency strategies.

Public API:
    - ``StrategyRegistry``       — chains TokenStrategy hooks around LLM calls.
    - ``UsageTracker``           — strategy 1: records tokens + cost per call.
    - ``CacheOptimizer``         — strategy 2: Anthropic cache_control placement.
    - ``estimate_cost_usd``      — single source of truth for cost estimation.

The ``install_from_config`` assembly helper lives in ``pico.cli._token_wise_stack``
— it's CLI-layer composition, not part of TokenWise's strategy API.
The token_wise package has no dependency on the CLI layer.
"""

from pico.token_wise.cache_optimizer import CacheOptimizer
from pico.token_wise.pricing import estimate_cost_usd
from pico.token_wise.registry import StrategyRegistry
from pico.token_wise.usage_tracker import UsageTracker

__all__ = [
    "CacheOptimizer",
    "StrategyRegistry",
    "UsageTracker",
    "estimate_cost_usd",
]
