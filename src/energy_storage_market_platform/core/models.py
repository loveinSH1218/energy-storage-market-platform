"""Serializable, implementation-independent platform data models."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlatformModel(BaseModel):
    """Base configuration shared by all core data models."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


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
    state: StorageState = Field(description="Storage state after execution.")


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