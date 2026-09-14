"""Serializable, implementation-independent platform data models."""

from collections.abc import Mapping
from datetime import datetime
from math import isclose, isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PlatformModel(BaseModel):
    """Base configuration shared by all core data models."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class StorageAssetSpec(PlatformModel):
    """Immutable static description of the storage asset in an experiment.

    This is the platform source of truth for requested asset sizing.  Backend
    adapters may realize it differently, but may not silently replace it.
    Power limits are positive magnitudes; the platform sign convention is
    applied to dispatch values, not to these static capabilities.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        frozen=True,
    )

    asset_id: str = Field(min_length=1)
    technology: str = Field(min_length=1)
    rated_power_kw: float = Field(gt=0)
    energy_capacity_kwh: float = Field(gt=0)
    duration_hours: float = Field(gt=0)
    max_charge_power_kw: float = Field(gt=0)
    max_discharge_power_kw: float = Field(gt=0)
    min_soc: float = Field(ge=0, le=1)
    max_soc: float = Field(ge=0, le=1)
    initial_soc: float = Field(ge=0, le=1)
    initial_temperature_c: float

    @model_validator(mode="before")
    @classmethod
    def _derive_dimensions(cls, values: Any) -> Any:
        if not isinstance(values, Mapping):
            return values
        data = dict(values)
        rated_power = data.get("rated_power_kw")
        energy_capacity = data.get("energy_capacity_kwh")
        duration_hours = data.get("duration_hours")
        if rated_power is None:
            raise ValueError("rated_power_kw is required")
        rated_power = float(rated_power)
        if not isfinite(rated_power) or rated_power <= 0:
            raise ValueError("rated_power_kw must be positive and finite")

        if energy_capacity is None and duration_hours is None:
            raise ValueError(
                "provide energy_capacity_kwh or duration_hours to define asset size"
            )
        if energy_capacity is None:
            assert duration_hours is not None
            duration_hours = float(duration_hours)
            if not isfinite(duration_hours) or duration_hours <= 0:
                raise ValueError("duration_hours must be positive and finite")
            energy_capacity = rated_power * duration_hours
            data["energy_capacity_kwh"] = energy_capacity
        elif duration_hours is None:
            energy_capacity = float(energy_capacity)
            if not isfinite(energy_capacity) or energy_capacity <= 0:
                raise ValueError("energy_capacity_kwh must be positive and finite")
            data["duration_hours"] = energy_capacity / rated_power
        else:
            energy_capacity = float(energy_capacity)
            duration_hours = float(duration_hours)
            if not isfinite(energy_capacity) or energy_capacity <= 0:
                raise ValueError("energy_capacity_kwh must be positive and finite")
            if not isfinite(duration_hours) or duration_hours <= 0:
                raise ValueError("duration_hours must be positive and finite")
            expected_capacity = rated_power * duration_hours
            if not isclose(energy_capacity, expected_capacity, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(
                    "inconsistent storage dimensions: energy_capacity_kwh must equal "
                    "rated_power_kw * duration_hours"
                )
        data.setdefault("max_charge_power_kw", rated_power)
        data.setdefault("max_discharge_power_kw", rated_power)
        return data

    @model_validator(mode="after")
    def _validate_asset(self) -> "StorageAssetSpec":
        if self.min_soc >= self.max_soc:
            raise ValueError("min_soc must be less than max_soc")
        if not self.min_soc <= self.initial_soc <= self.max_soc:
            raise ValueError("initial_soc must be within [min_soc, max_soc]")
        if self.max_charge_power_kw > self.rated_power_kw:
            raise ValueError("max_charge_power_kw cannot exceed rated_power_kw")
        if self.max_discharge_power_kw > self.rated_power_kw:
            raise ValueError("max_discharge_power_kw cannot exceed rated_power_kw")
        if not isfinite(self.initial_temperature_c):
            raise ValueError("initial_temperature_c must be finite")
        return self

    @property
    def duration_seconds(self) -> float:
        """Return the static asset duration in platform seconds."""

        return self.duration_hours * 3600.0


class MarketObservation(PlatformModel):
    """A market observation for one settlement interval."""

    timestamp: datetime = Field(description="Start of the observation interval.")
    duration_seconds: float = Field(
        gt=0,
        description="Length of the observation interval in seconds.",
    )
    price_per_kwh: float = Field(
        description="Market price per kWh in the explicitly named currency.",
    )
    currency: str = Field(
        min_length=1,
        description="ISO 4217 currency code or other explicitly documented code.",
    )
    available: bool = Field(
        default=True,
        description="Whether trading is available for this interval.",
    )
    forecast: dict[str, float] | None = Field(
        default=None,
        description=(
            "Optional price forecast keyed by serialized interval timestamp, "
            "using platform currency per kWh."
        ),
    )
    market_id: str | None = Field(
        default=None,
        description="External or platform market identifier, when available.",
    )
    product_id: str | None = Field(
        default=None,
        description="External or platform product identifier, when available.",
    )


class StorageState(PlatformModel):
    """Observable storage state using platform units and sign conventions."""

    timestamp: datetime = Field(description="Timestamp at which this state applies.")
    soc: float = Field(
        ge=0,
        le=1,
        description="State of charge normalized to the inclusive range [0, 1].",
    )
    soh: float = Field(
        ge=0,
        le=1,
        description="State of health normalized to the inclusive range [0, 1].",
    )
    soh_Q: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Capacity state of health from a backend, when available.",
    )
    soh_R: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Resistance state-of-health factor from a backend, when available. "
            "SimSES defines this as a resistance multiplier and it may exceed 1."
        ),
    )
    power_kw: float = Field(
        description=(
            "Current storage power in kW; positive discharges to the grid and "
            "negative charges from the grid."
        ),
    )
    energy_capacity_kwh: float = Field(
        gt=0,
        description="Usable storage energy capacity in kWh.",
    )
    temperature_c: float | None = Field(
        default=None,
        description="Storage temperature in degrees Celsius, when available.",
    )


class DispatchRequest(PlatformModel):
    """A strategy request for storage power during one interval."""

    timestamp: datetime = Field(description="Start of the requested interval.")
    duration_seconds: float = Field(
        gt=0,
        description="Requested interval duration in seconds.",
    )
    power_kw: float = Field(
        description=(
            "Requested storage power in kW; positive means discharge and "
            "negative means charge."
        ),
    )
    market_id: str | None = Field(
        default=None,
        description="Market identifier associated with the request, when available.",
    )
    product_id: str | None = Field(
        default=None,
        description="Product identifier associated with the request, when available.",
    )


class StorageStepResult(PlatformModel):
    """Result of applying one dispatch request to a storage backend."""

    timestamp: datetime = Field(description="Start of the executed interval.")
    duration_seconds: float = Field(
        gt=0,
        description="Executed interval duration in seconds.",
    )
    requested_power_kw: float = Field(
        description="Power requested by the strategy in kW.",
    )
    applied_power_kw: float = Field(
        description="Power accepted by storage constraints in kW.",
    )
    energy_to_grid_kwh: float = Field(
        description=(
            "Net energy delivered to the grid in kWh; positive is export and "
            "negative is import."
        ),
    )
    losses_kwh: float = Field(
        default=0.0,
        ge=0,
        description="Physical losses reported by the storage backend in kWh.",
    )
    state: StorageState = Field(description="Storage state after execution.")

    @property
    def actual_power_kw(self) -> float:
        """Alias for the applied power using the platform terminology."""
        return self.applied_power_kw

    @property
    def energy_delta_kwh(self) -> float:
        """Alias for net energy exchanged with the grid."""
        return self.energy_to_grid_kwh


class TradeResult(PlatformModel):
    """Settlement result for energy exchanged during one market interval."""

    timestamp: datetime = Field(description="Start of the settled interval.")
    duration_seconds: float = Field(
        gt=0,
        description="Settled interval duration in seconds.",
    )
    energy_kwh: float = Field(
        description="Energy exchanged with the grid in kWh; positive is export.",
    )
    price_per_kwh: float = Field(
        description="Applied market price per kWh.",
    )
    currency: str = Field(
        min_length=1,
        description="Currency code for the settlement value.",
    )
    cash_flow: float = Field(
        description="Settlement cash flow in the named currency; positive is revenue.",
    )
    bid_price_per_kwh: float | None = Field(
        default=None,
        description="Submitted bid price per kWh, when available.",
    )
    accepted_price_per_kwh: float | None = Field(
        default=None,
        description="Accepted market price per kWh, when available.",
    )
    bid_quantity_kw: float | None = Field(
        default=None,
        description="Submitted bid quantity in platform kW, when available.",
    )
    accepted_quantity_kw: float | None = Field(
        default=None,
        description="Accepted quantity in platform kW, when available.",
    )
    accepted_energy_kwh: float | None = Field(
        default=None,
        description="Accepted interval energy in platform kWh, when available.",
    )
    market_id: str | None = Field(
        default=None,
        description="External or platform market identifier, when available.",
    )
    product_id: str | None = Field(
        default=None,
        description="External or platform product identifier, when available.",
    )
