"""Thin adapter around the official SimSES storage API.

The adapter is the only platform module that imports SimSES. SimSES remains
the authority for physical state transitions, limits, efficiency, losses,
temperature, and degradation.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any

from simses.battery import Battery
from simses.converter import Converter
from simses.model.cell.sony_lfp import SonyLFP
from simses.model.converter.fix_efficiency import FixedEfficiency
from simses.thermal import AmbientThermalModel

from energy_storage_market_platform.core import (
    DispatchRequest,
    StorageState,
    StorageStepResult,
)

WATTS_PER_KW = 1_000.0
SECONDS_PER_HOUR = 3_600.0


@dataclass(frozen=True, slots=True)
class SimSESStorageConfig:
    """Configuration passed to the SimSES Battery constructor.

    cell_factory permits selecting another upstream cell model without copying
    that model into the platform. The default is the official Sony LFP model
    used by the reproduced SimSES example.
    """

    initial_soc: float
    initial_temperature_c: float
    circuit: tuple[int, int] = (13, 10)
    soc_limits: tuple[float, float] = (0.0, 1.0)
    degradation: bool | None = None
    initial_soh_Q: float = 1.0
    initial_soh_R: float = 1.0
    effective_cooling_area: float = 1.0
    cell_factory: Callable[[], Any] = SonyLFP

    def __post_init__(self) -> None:
        if not 0.0 <= self.initial_soc <= 1.0:
            raise ValueError("initial_soc must be between 0 and 1")
        if not isfinite(self.initial_temperature_c):
            raise ValueError("initial_temperature_c must be finite")
        if len(self.circuit) != 2 or min(self.circuit) <= 0:
            raise ValueError("circuit must contain positive (series, parallel) counts")
        soc_min, soc_max = self.soc_limits
        if not 0.0 <= soc_min < soc_max <= 1.0:
            raise ValueError("soc_limits must satisfy 0 <= min < max <= 1")
        if not 0.0 < self.initial_soh_Q <= 1.0:
            raise ValueError("initial_soh_Q must be in (0, 1]")
        if not 0.0 < self.initial_soh_R:
            raise ValueError("initial_soh_R must be positive")
        if self.effective_cooling_area <= 0.0:
            raise ValueError("effective_cooling_area must be positive")


@dataclass(frozen=True, slots=True)
class SimSESConverterConfig:
    """Optional SimSES converter configuration in platform-facing units."""

    max_power_kw: float
    efficiency: float | tuple[float, float] = 1.0

    def __post_init__(self) -> None:
        if not isfinite(self.max_power_kw) or self.max_power_kw <= 0.0:
            raise ValueError("max_power_kw must be positive and finite")
        efficiencies = (
            self.efficiency
            if isinstance(self.efficiency, tuple)
            else (self.efficiency,)
        )
        if any(not isfinite(value) or not 0.0 < value <= 1.0 for value in efficiencies):
            raise ValueError("converter efficiency must be in (0, 1]")
        if isinstance(self.efficiency, tuple) and len(self.efficiency) != 2:
            raise ValueError("directional efficiency must be (charge, discharge)")


@dataclass(frozen=True, slots=True)
class SimSESThermalConfig:
    """Optional constant-ambient SimSES thermal model configuration."""

    ambient_temperature_c: float

    def __post_init__(self) -> None:
        if not isfinite(self.ambient_temperature_c):
            raise ValueError("ambient_temperature_c must be finite")


class SimSESStorageAdapter:
    """Implement StorageBackend using a private SimSES object graph.

    The public surface contains only platform models. The internal SimSES
    Battery, optional Converter, and optional thermal model never leave this
    adapter.
    """

    def __init__(
        self,
        config: SimSESStorageConfig,
        initial_timestamp: datetime,
        converter: SimSESConverterConfig | None = None,
        thermal: SimSESThermalConfig | None = None,
    ) -> None:
        self._config = config
        self._battery = Battery(
            cell=config.cell_factory(),
            circuit=config.circuit,
            initial_states={
                "start_soc": config.initial_soc,
                "start_T": config.initial_temperature_c,
                "start_soh_Q": config.initial_soh_Q,
                "start_soh_R": config.initial_soh_R,
            },
            soc_limits=config.soc_limits,
            degradation=config.degradation,
            effective_cooling_area=config.effective_cooling_area,
        )
        if converter is None:
            self._simses_storage: Any = self._battery
        else:
            self._simses_storage = Converter(
                loss_model=FixedEfficiency(converter.efficiency),
                max_power=converter.max_power_kw * WATTS_PER_KW,
                storage=self._battery,
            )

        self._thermal_model: AmbientThermalModel | None = None
        if thermal is not None:
            self._thermal_model = AmbientThermalModel(
                T_ambient=thermal.ambient_temperature_c,
            )
            self._thermal_model.add_component(self._battery)

        self._state_timestamp = initial_timestamp

    def current_state(self) -> StorageState:
        """Return a platform-only snapshot of the latest SimSES state."""
        return self._state_from_simses(self._state_timestamp)

    def step(self, request: DispatchRequest) -> StorageStepResult:
        """Execute one platform request through SimSES."""
        simses_power_w = -request.power_kw * WATTS_PER_KW
        dt_seconds = request.duration_seconds

        self._simses_storage.step(simses_power_w, dt_seconds)
        if self._thermal_model is not None:
            self._thermal_model.step(dt_seconds)

        self._state_timestamp = request.timestamp
        actual_power_kw = -self._actual_power_w() / WATTS_PER_KW
        losses_kwh = self._loss_power_w() * dt_seconds / (
            WATTS_PER_KW * SECONDS_PER_HOUR
        )
        state = self._state_from_simses(request.timestamp)
        return StorageStepResult(
            timestamp=request.timestamp,
            duration_seconds=dt_seconds,
            requested_power_kw=request.power_kw,
            applied_power_kw=actual_power_kw,
            energy_to_grid_kwh=actual_power_kw * dt_seconds / SECONDS_PER_HOUR,
            losses_kwh=losses_kwh,
            state=state,
        )

    def _actual_power_w(self) -> float:
        """Read the actual power at the selected SimSES boundary."""
        return float(self._simses_storage.state.power)

    def _loss_power_w(self) -> float:
        """Read SimSES-reported battery and converter loss power."""
        battery_loss_w = float(getattr(self._battery.state, "loss", 0.0))
        converter_loss_w = (
            float(getattr(self._simses_storage.state, "loss", 0.0))
            if self._simses_storage is not self._battery
            else 0.0
        )
        return max(0.0, battery_loss_w + converter_loss_w)

    def _state_from_simses(self, timestamp: datetime) -> StorageState:
        simses_state = self._battery.state
        soh_q = float(simses_state.soh_Q)
        soh_r = float(simses_state.soh_R)
        return StorageState(
            timestamp=timestamp,
            soc=float(simses_state.soc),
            soh=soh_q,
            soh_Q=soh_q,
            soh_R=soh_r,
            power_kw=-self._actual_power_w() / WATTS_PER_KW,
            energy_capacity_kwh=self._battery.energy_capacity(simses_state)
            / WATTS_PER_KW,
            temperature_c=float(simses_state.T),
        )


__all__ = [
    "SimSESConverterConfig",
    "SimSESStorageAdapter",
    "SimSESStorageConfig",
    "SimSESThermalConfig",
]
