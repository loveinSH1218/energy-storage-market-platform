"""End-to-end test for the initial reference implementations."""

from datetime import UTC, datetime, timedelta

from energy_storage_market_platform.core import (
    MarketObservation,
    StorageAssetSpec,
    StorageState,
)
from energy_storage_market_platform.coupling import run_simulation
from energy_storage_market_platform.market.dummy import DummyMarket
from energy_storage_market_platform.storage.ideal import IdealStorage
from energy_storage_market_platform.strategy.dummy import SimpleTradingStrategy


def test_dummy_market_strategy_coupling_and_ideal_storage() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observations = [
        MarketObservation(
            timestamp=start,
            duration_seconds=3600,
            price_per_kwh=0.10,
            currency="EUR",
        ),
        MarketObservation(
            timestamp=start + timedelta(hours=1),
            duration_seconds=3600,
            price_per_kwh=0.20,
            currency="EUR",
        ),
    ]
    storage_asset = StorageAssetSpec(
        asset_id="dummy-storage",
        technology="ideal",
        rated_power_kw=1.0,
        energy_capacity_kwh=10.0,
        duration_hours=10.0,
        min_soc=0.0,
        max_soc=1.0,
        initial_soc=0.5,
        initial_temperature_c=25.0,
    )
    storage = IdealStorage(
        asset_spec=storage_asset,
        initial_state=StorageState(
            timestamp=start,
            soc=0.5,
            soh=1.0,
            power_kw=0.0,
            energy_capacity_kwh=10.0,
        ),
    )

    results = run_simulation(
        market=DummyMarket(observations),
        strategy=SimpleTradingStrategy(
            price_threshold_per_kwh=0.15,
            power_kw=1.0,
            asset_spec=storage_asset,
        ),
        storage=storage,
        start=start,
        end=start + timedelta(hours=2),
    )

    assert [result.energy_kwh for result in results] == [-1.0, 1.0]
    assert [result.cash_flow for result in results] == [-0.1, 0.2]
    assert storage.current_state().soc == 0.5
