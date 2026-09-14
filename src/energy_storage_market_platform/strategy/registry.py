"""Small registry for replaceable platform trading strategies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from energy_storage_market_platform.core import StorageAssetSpec, TradingStrategy
from energy_storage_market_platform.strategy.dummy import SimpleTradingStrategy

StrategyFactory = Callable[..., TradingStrategy]
_STRATEGIES: dict[str, StrategyFactory] = {}


def register_strategy(name: str, factory: StrategyFactory, *, replace: bool = False) -> None:
    """Register a strategy factory under a configuration name."""

    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("strategy name must not be empty")
    if normalized in _STRATEGIES and not replace:
        raise ValueError(f"strategy backend already registered: {normalized}")
    _STRATEGIES[normalized] = factory


def create_strategy(name: str, asset_spec: StorageAssetSpec, **kwargs: Any) -> TradingStrategy:
    """Create a strategy and supply the shared static asset specification."""

    normalized = name.strip().lower()
    try:
        factory = _STRATEGIES[normalized]
    except KeyError as error:
        available = ", ".join(sorted(_STRATEGIES))
        raise ValueError(f"unknown strategy backend {name!r}; available: {available}") from error
    return factory(asset_spec=asset_spec, **kwargs)


def available_strategies() -> tuple[str, ...]:
    """Return registered strategy backend names."""

    return tuple(sorted(_STRATEGIES))


def _simple_factory(*, asset_spec: StorageAssetSpec, **kwargs: Any) -> TradingStrategy:
    return SimpleTradingStrategy(asset_spec=asset_spec, **kwargs)


def _assume_native_factory(*, asset_spec: StorageAssetSpec, **kwargs: Any) -> TradingStrategy:
    from energy_storage_market_platform.strategy.adapters.assume import (
        AssumeTradingStrategyAdapter,
    )

    return AssumeTradingStrategyAdapter(asset_spec=asset_spec, **kwargs)


register_strategy("simple", _simple_factory)
register_strategy("assume_native", _assume_native_factory)


__all__ = [
    "StrategyFactory",
    "available_strategies",
    "create_strategy",
    "register_strategy",
]
