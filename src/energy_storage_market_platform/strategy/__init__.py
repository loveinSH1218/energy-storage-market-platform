"""Trading strategies that turn market and storage state into dispatch requests.

Strategies remain independent of concrete storage backends. Optimization,
rule-based, model-predictive, and learning strategies can be added here later.
"""

from .registry import (
    available_strategies,
    create_strategy,
    register_strategy,
)

__all__ = ["available_strategies", "create_strategy", "register_strategy"]
