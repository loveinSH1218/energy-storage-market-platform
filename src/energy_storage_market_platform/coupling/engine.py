"""Interface-driven coupling engine for market, strategy, and storage."""

from datetime import datetime

from energy_storage_market_platform.core import (
    MarketBackend,
    StorageBackend,
    TradeResult,
    TradingStrategy,
)


def run_simulation(
    market: MarketBackend,
    strategy: TradingStrategy,
    storage: StorageBackend,
    start: datetime,
    end: datetime,
) -> tuple[TradeResult, ...]:
    """Run normalized market observations through strategy and storage layers."""
    results: list[TradeResult] = []
    for observation in market.get_observations(start, end):
        request = strategy.decide(observation, storage.current_state())
        step_result = storage.step(request)
        results.append(
            TradeResult(
                timestamp=observation.timestamp,
                duration_seconds=observation.duration_seconds,
                energy_kwh=step_result.energy_to_grid_kwh,
                price_per_kwh=observation.price_per_kwh,
                currency=observation.currency,
                cash_flow=step_result.energy_to_grid_kwh
                * observation.price_per_kwh,
            )
        )
    return tuple(results)