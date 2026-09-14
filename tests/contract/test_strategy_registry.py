"""Contract tests for replaceable strategy construction."""

from datetime import UTC, datetime

import pytest

from energy_storage_market_platform.core import (
    MarketObservation,
    StorageAssetSpec,
    StorageState,
    TradingStrategy,
)
from energy_storage_market_platform.strategy import (
    available_strategies,
    create_strategy,
)


def _asset() -> StorageAssetSpec:
    return StorageAssetSpec(
        asset_id="registry-asset",
        technology="lfp",
        rated_power_kw=100.0,
        energy_capacity_kwh=200.0,
        duration_hours=2.0,
        max_charge_power_kw=100.0,
        max_discharge_power_kw=100.0,
        min_soc=0.1,
        max_soc=0.9,
        initial_soc=0.5,
        initial_temperature_c=25.0,
    )


def test_strategy_registry_supplies_shared_asset_without_coupling_changes() -> None:
    strategy = create_strategy(
        "simple",
        _asset(),
        price_threshold_per_kwh=0.10,
    )
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    observation = MarketObservation(
        timestamp=timestamp,
        duration_seconds=3600.0,
        price_per_kwh=0.20,
        currency="EUR",
    )
    state = StorageState(
        timestamp=timestamp,
        soc=0.5,
        soh=1.0,
        power_kw=0.0,
        energy_capacity_kwh=200.0,
    )

    assert isinstance(strategy, TradingStrategy)
    assert strategy.asset_spec is not None
    assert strategy.asset_spec.rated_power_kw == pytest.approx(100.0)
    assert strategy.decide(observation, state).power_kw == pytest.approx(100.0)


def test_assume_native_backend_is_selectable_and_receives_asset() -> None:
    strategy = create_strategy("assume_native", _asset(), orders=[])

    assert isinstance(strategy, TradingStrategy)
    assert strategy.asset_spec is not None
    assert strategy.asset_spec.energy_capacity_kwh == pytest.approx(200.0)


def test_unknown_strategy_backend_fails_explicitly() -> None:
    with pytest.raises(ValueError, match="unknown strategy backend"):
        create_strategy("not_registered", _asset())


def test_expected_plugin_names_are_available_for_extension() -> None:
    assert "simple" in available_strategies()
    assert "assume_native" in available_strategies()
