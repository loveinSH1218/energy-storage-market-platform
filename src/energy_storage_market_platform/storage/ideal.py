"""Minimal ideal storage backend for deterministic architecture tests."""

from dataclasses import dataclass
from datetime import datetime

from energy_storage_market_platform.core import (
    DispatchRequest,
    StorageAssetSpec,
    StorageState,
    StorageStepResult,
)


@dataclass
class IdealStorage:
    """Lossless storage model with SOC and power-limit clipping."""

    asset_spec: StorageAssetSpec
    initial_state: StorageState | None = None
    initial_timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.initial_state is None:
            if self.initial_timestamp is None:
                raise ValueError("initial_timestamp is required without initial_state")
            self._state = StorageState(
                timestamp=self.initial_timestamp,
                soc=self.asset_spec.initial_soc,
                soh=1.0,
                power_kw=0.0,
                energy_capacity_kwh=self.asset_spec.energy_capacity_kwh,
                temperature_c=self.asset_spec.initial_temperature_c,
            )
        else:
            if self.initial_state.energy_capacity_kwh != self.asset_spec.energy_capacity_kwh:
                raise ValueError("initial_state capacity must match asset_spec")
            if not self.asset_spec.min_soc <= self.initial_state.soc <= self.asset_spec.max_soc:
                raise ValueError("initial_state SOC must be within asset_spec bounds")
            self._state = self.initial_state

    def current_state(self) -> StorageState:
        """Return the latest state without exposing mutable implementation data."""
        return self._state.model_copy(deep=True)

    def step(self, request: DispatchRequest) -> StorageStepResult:
        """Apply a request, clipping power at rated power and SOC bounds."""
        duration_hours = request.duration_seconds / 3600
        current_energy_kwh = self._state.soc * self._state.energy_capacity_kwh
        requested_power_kw = request.power_kw
        power_kw = max(
            -self.asset_spec.max_charge_power_kw,
            min(self.asset_spec.max_discharge_power_kw, requested_power_kw),
        )

        if power_kw > 0:
            available_energy_kwh = (
                self._state.soc - self.asset_spec.min_soc
            ) * self._state.energy_capacity_kwh
            power_kw = min(power_kw, available_energy_kwh / duration_hours)
        elif power_kw < 0:
            available_capacity_kwh = (
                self.asset_spec.max_soc - self._state.soc
            )
            available_capacity_kwh *= self._state.energy_capacity_kwh
            power_kw = max(power_kw, -available_capacity_kwh / duration_hours)

        energy_to_grid_kwh = power_kw * duration_hours
        next_energy_kwh = current_energy_kwh - energy_to_grid_kwh
        min_energy_kwh = self.asset_spec.min_soc * self._state.energy_capacity_kwh
        max_energy_kwh = self.asset_spec.max_soc * self._state.energy_capacity_kwh
        next_energy_kwh = max(min_energy_kwh, min(max_energy_kwh, next_energy_kwh))
        next_state = StorageState(
            timestamp=request.timestamp,
            soc=next_energy_kwh / self._state.energy_capacity_kwh,
            soh=self._state.soh,
            power_kw=power_kw,
            energy_capacity_kwh=self._state.energy_capacity_kwh,
            temperature_c=self._state.temperature_c,
        )
        self._state = next_state
        return StorageStepResult(
            timestamp=request.timestamp,
            duration_seconds=request.duration_seconds,
            requested_power_kw=requested_power_kw,
            applied_power_kw=power_kw,
            energy_to_grid_kwh=energy_to_grid_kwh,
            state=next_state,
        )
