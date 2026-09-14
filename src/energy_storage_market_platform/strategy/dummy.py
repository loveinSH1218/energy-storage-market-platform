"""Minimal deterministic trading strategy for architecture tests."""

from pydantic import BaseModel, ConfigDict, Field

from energy_storage_market_platform.core import (
    DispatchRequest,
    MarketObservation,
    StorageAssetSpec,
    StorageState,
)


class SimpleTradingStrategy(BaseModel):
    """Charge below a threshold and discharge at or above it."""

    model_config = ConfigDict(extra="forbid")

    price_threshold_per_kwh: float = Field(
        description="Price threshold in the same currency per kWh as observations."
    )
    power_kw: float | None = Field(
        default=None,
        gt=0,
        description="Optional absolute requested power in kW; defaults to asset rating.",
    )
    asset_spec: StorageAssetSpec = Field(
        description="Static asset capability supplied by the experiment.",
    )

    def decide(
        self,
        market_observation: MarketObservation,
        storage_state: StorageState,
    ) -> DispatchRequest:
        """Create a signed request without directly accessing storage internals."""
        del storage_state
        power_kw = self.power_kw
        if power_kw is None:
            power_kw = self.asset_spec.rated_power_kw
        if not market_observation.available:
            requested_power_kw = 0.0
        elif market_observation.price_per_kwh < self.price_threshold_per_kwh:
            requested_power_kw = -power_kw
        else:
            requested_power_kw = power_kw
        return DispatchRequest(
            timestamp=market_observation.timestamp,
            duration_seconds=market_observation.duration_seconds,
            power_kw=requested_power_kw,
        )
