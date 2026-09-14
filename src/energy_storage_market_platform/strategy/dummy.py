"""Minimal deterministic trading strategy for architecture tests."""

from pydantic import BaseModel, ConfigDict, Field

from energy_storage_market_platform.core import (
    DispatchRequest,
    MarketObservation,
    StorageState,
)


class SimpleTradingStrategy(BaseModel):
    """Charge below a threshold and discharge at or above it."""

    model_config = ConfigDict(extra="forbid")

    price_threshold_per_kwh: float = Field(
        description="Price threshold in the same currency per kWh as observations."
    )
    power_kw: float = Field(
        gt=0,
        description="Absolute requested power in kW.",
    )

    def decide(
        self,
        market_observation: MarketObservation,
        storage_state: StorageState,
    ) -> DispatchRequest:
        """Create a signed request without directly accessing storage internals."""
        del storage_state
        if not market_observation.available:
            requested_power_kw = 0.0
        elif market_observation.price_per_kwh < self.price_threshold_per_kwh:
            requested_power_kw = -self.power_kw
        else:
            requested_power_kw = self.power_kw
        return DispatchRequest(
            timestamp=market_observation.timestamp,
            duration_seconds=market_observation.duration_seconds,
            power_kw=requested_power_kw,
        )