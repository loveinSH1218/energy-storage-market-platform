"""Minimal ideal storage backend for deterministic architecture tests."""

from dataclasses import dataclass

from energy_storage_market_platform.core import (
    DispatchRequest,
    StorageState,
    StorageStepResult,
)


@dataclass
class IdealStorage:
    """Lossless storage model with SOC and power-limit clipping."""

    initial_state: StorageState
    max_power_kw: float

    def __post_init__(self) -> None:
        if self.max_power_kw <= 0:
            raise ValueError("max_power_kw must be positive")
        self._state = self.initial_state

    def current_state(self) -> StorageState:
        """Return the latest state without exposing mutable implementation data."""
        return self._state.model_copy(deep=True)

    def step(self, request: DispatchRequest) -> StorageStepResult:
        """Apply a request, clipping power at rated power and SOC bounds."""
        duration_hours = request.duration_seconds / 3600
        current_energy_kwh = self._state.soc * self._state.energy_capacity_kwh
        requested_power_kw = request.power_kw
        power_kw = max(-self.max_power_kw, min(self.max_power_kw, requested_power_kw))

        if power_kw > 0:
            power_kw = min(power_kw, current_energy_kwh / duration_hours)
        elif power_kw < 0:
            available_capacity_kwh = (
                self._state.energy_capacity_kwh - current_energy_kwh
            )
            power_kw = max(power_kw, -available_capacity_kwh / duration_hours)

        energy_to_grid_kwh = power_kw * duration_hours
        next_energy_kwh = current_energy_kwh - energy_to_grid_kwh
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