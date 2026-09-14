"""Tests for the single platform storage asset definition."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from energy_storage_market_platform.core import StorageAssetSpec
from energy_storage_market_platform.experiments import (
    ExperimentConfig,
    load_storage_asset_spec,
)


def _base_asset(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "asset_id": "asset-1",
        "technology": "lfp",
        "rated_power_kw": 100_000.0,
        "duration_hours": 2.0,
        "min_soc": 0.1,
        "max_soc": 0.9,
        "initial_soc": 0.5,
        "initial_temperature_c": 25.0,
    }
    values.update(overrides)
    return values


def test_power_and_duration_derive_energy() -> None:
    asset = StorageAssetSpec(**_base_asset())

    assert asset.energy_capacity_kwh == pytest.approx(200_000.0)
    assert asset.duration_seconds == pytest.approx(7200.0)
    assert asset.max_charge_power_kw == asset.rated_power_kw
    assert asset.max_discharge_power_kw == asset.rated_power_kw


def test_power_and_energy_derive_duration() -> None:
    values = _base_asset(energy_capacity_kwh=200_000.0)
    values.pop("duration_hours")
    asset = StorageAssetSpec(**values)

    assert asset.duration_hours == pytest.approx(2.0)


def test_inconsistent_dimensions_are_rejected() -> None:
    with pytest.raises(ValueError, match="inconsistent storage dimensions"):
        StorageAssetSpec(
            **_base_asset(energy_capacity_kwh=200_000.0, duration_hours=4.0),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"min_soc": 0.9, "max_soc": 0.1},
        {"initial_soc": 0.95},
        {"max_charge_power_kw": 0.0},
        {"max_discharge_power_kw": -1.0},
        {"max_charge_power_kw": 100_001.0},
        {"max_discharge_power_kw": 100_001.0},
    ],
)
def test_asset_operating_bounds_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        StorageAssetSpec(**_base_asset(**overrides))


def test_asset_is_immutable() -> None:
    asset = StorageAssetSpec(**_base_asset())

    with pytest.raises(ValidationError):
        asset.rated_power_kw = 1.0  # type: ignore[misc]


def test_yaml_configuration_converts_human_units_at_boundary() -> None:
    asset_path = Path("configs/assets/bess_100mw_2h.yaml")
    asset = load_storage_asset_spec(asset_path)

    assert asset.asset_id == "bess_100mw_2h"
    assert asset.rated_power_kw == pytest.approx(100_000.0)
    assert asset.energy_capacity_kwh == pytest.approx(200_000.0)
    assert asset.duration_hours == pytest.approx(2.0)


def test_experiment_configuration_selects_the_same_asset_file() -> None:
    config = ExperimentConfig.from_yaml("configs/experiments/phase4_assume_simses.yaml")

    assert config.market_backend == "assume"
    assert config.strategy_backend == "assume_native"
    assert config.storage_backend == "simses"
    assert config.load_asset().asset_id == "bess_100mw_2h"
