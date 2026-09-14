"""Small, configuration-driven constructors for platform experiments."""

from __future__ import annotations

from collections.abc import Mapping
from math import isclose
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from energy_storage_market_platform.core import StorageAssetSpec


def _scaled_dimension(
    values: Mapping[str, Any],
    *,
    platform_key: str,
    human_key: str,
    factor: float,
) -> float | None:
    platform_value = values.get(platform_key)
    human_value = values.get(human_key)
    if platform_value is not None and human_value is not None and not isclose(
        float(platform_value), float(human_value) * factor
    ):
        raise ValueError(
            f"conflicting {platform_key} and {human_key} values in asset config"
        )
    if platform_value is not None:
        return float(platform_value)
    if human_value is not None:
        return float(human_value) * factor
    return None


def storage_asset_spec_from_mapping(payload: Mapping[str, Any]) -> StorageAssetSpec:
    """Convert one human-facing asset mapping into platform units."""

    raw_asset = payload.get("asset", payload)
    if not isinstance(raw_asset, Mapping):
        raise TypeError("asset configuration must be a mapping")
    values = dict(raw_asset)
    values["asset_id"] = values.pop("asset_id", values.pop("id", None))
    values["rated_power_kw"] = _scaled_dimension(
        values,
        platform_key="rated_power_kw",
        human_key="rated_power_mw",
        factor=1000.0,
    )
    values["energy_capacity_kwh"] = _scaled_dimension(
        values,
        platform_key="energy_capacity_kwh",
        human_key="energy_capacity_mwh",
        factor=1000.0,
    )
    for field in ("max_charge_power", "max_discharge_power"):
        scaled_value = _scaled_dimension(
            values,
            platform_key=f"{field}_kw",
            human_key=f"{field}_mw",
            factor=1000.0,
        )
        if scaled_value is None:
            values.pop(f"{field}_kw", None)
        else:
            values[f"{field}_kw"] = scaled_value
    for key in (
        "rated_power_mw",
        "energy_capacity_mwh",
        "max_charge_power_mw",
        "max_discharge_power_mw",
    ):
        values.pop(key, None)
    return StorageAssetSpec(**values)


def load_storage_asset_spec(path: str | Path) -> StorageAssetSpec:
    """Load a YAML asset file and convert MW/MWh at the config boundary."""

    config_path = Path(path)
    with config_path.open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream)
    if not isinstance(payload, Mapping):
        raise TypeError("asset YAML must contain a mapping")
    return storage_asset_spec_from_mapping(payload)


class ExperimentConfig(BaseModel):
    """Minimal future-facing experiment selection configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_config: str = Field(min_length=1)
    market_backend: str = Field(min_length=1)
    strategy_backend: str = Field(min_length=1)
    storage_backend: str = Field(min_length=1)
    physical_substep_seconds: float = Field(gt=0)

    @classmethod
    def from_yaml(cls, path: str | Path) -> ExperimentConfig:
        config_path = Path(path)
        with config_path.open(encoding="utf-8") as stream:
            payload = yaml.safe_load(stream)
        if not isinstance(payload, Mapping):
            raise TypeError("experiment YAML must contain a mapping")
        asset = payload.get("asset")
        market = payload.get("market")
        strategy = payload.get("strategy")
        storage = payload.get("storage")
        simulation = payload.get("simulation")
        sections = (asset, market, strategy, storage, simulation)
        if not all(isinstance(section, Mapping) for section in sections):
            raise ValueError(
                "experiment YAML requires asset, market, strategy, storage, and simulation mappings"
            )
        asset_values = cast(Mapping[str, Any], asset)
        market_values = cast(Mapping[str, Any], market)
        strategy_values = cast(Mapping[str, Any], strategy)
        storage_values = cast(Mapping[str, Any], storage)
        simulation_values = cast(Mapping[str, Any], simulation)
        asset_config = Path(str(asset_values["config"]))
        if not asset_config.is_absolute():
            asset_config = config_path.parent / asset_config
        return cls(
            asset_config=str(asset_config),
            market_backend=str(market_values["backend"]),
            strategy_backend=str(strategy_values["backend"]),
            storage_backend=str(storage_values["backend"]),
            physical_substep_seconds=float(simulation_values["physical_substep_seconds"]),
        )

    def load_asset(self) -> StorageAssetSpec:
        """Load the single asset specification selected by this experiment."""

        return load_storage_asset_spec(self.asset_config)


__all__ = [
    "ExperimentConfig",
    "load_storage_asset_spec",
    "storage_asset_spec_from_mapping",
]
