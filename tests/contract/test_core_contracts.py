"""Contract checks for the core protocols and serializable models."""

from datetime import UTC, datetime

from energy_storage_market_platform.core import (
    DispatchRequest,
    MarketBackend,
    MarketObservation,
    StorageAssetSpec,
    StorageBackend,
    StorageState,
    StorageStepResult,
    TradeResult,
    TradingStrategy,
)
from energy_storage_market_platform.market.dummy import DummyMarket
from energy_storage_market_platform.storage.ideal import IdealStorage
from energy_storage_market_platform.strategy.dummy import SimpleTradingStrategy


def test_reference_implementations_satisfy_core_protocols() -> None:
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    observation = MarketObservation(
        timestamp=timestamp,
        duration_seconds=3600,
        price_per_kwh=0.10,
        currency="EUR",
    )
    state = StorageState(
        timestamp=timestamp,
        soc=0.5,
        soh=1.0,
        power_kw=0.0,
        energy_capacity_kwh=10.0,
    )
    market = DummyMarket([observation])
    strategy = SimpleTradingStrategy(
        price_threshold_per_kwh=0.15,
        power_kw=1.0,
        asset_spec=StorageAssetSpec(
            asset_id="core-test",
            technology="ideal",
            rated_power_kw=1.0,
            energy_capacity_kwh=10.0,
            duration_hours=10.0,
            min_soc=0.0,
            max_soc=1.0,
            initial_soc=0.5,
            initial_temperature_c=25.0,
        ),
    )
    storage = IdealStorage(
        asset_spec=StorageAssetSpec(
            asset_id="core-storage",
            technology="ideal",
            rated_power_kw=1.0,
            energy_capacity_kwh=10.0,
            duration_hours=10.0,
            min_soc=0.0,
            max_soc=1.0,
            initial_soc=0.5,
            initial_temperature_c=25.0,
        ),
        initial_state=state,
    )

    assert isinstance(market, MarketBackend)
    assert isinstance(strategy, TradingStrategy)
    assert isinstance(storage, StorageBackend)

    request = strategy.decide(observation, state)
    step_result = storage.step(request)
    assert isinstance(request, DispatchRequest)
    assert isinstance(step_result, StorageStepResult)

    serialized_result = TradeResult(
        timestamp=timestamp,
        duration_seconds=3600,
        energy_kwh=-1.0,
        price_per_kwh=0.10,
        currency="EUR",
        cash_flow=-0.10,
    ).model_dump_json()
    assert isinstance(TradeResult.model_validate_json(serialized_result), TradeResult)
