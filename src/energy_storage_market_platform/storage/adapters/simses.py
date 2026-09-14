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
    StorageAssetSpec,
    StorageState,
    StorageStepResult,
)

WATTS_PER_KW = 1_000.0
SECONDS_PER_HOUR = 3_600.0


@dataclass(frozen=True, slots=True)
class SimSESStorageConfig:
    """Implementation-specific configuration for the SimSES object graph.

    cell_factory permits selecting another upstream cell model without copying
    that model into the platform. The default circuit is an implementation
    template, not the platform asset definition.
    """

    circuit: tuple[int, int] = (13, 10)
    degradation: bool | None = None
    initial_soh_Q: float = 1.0
    initial_soh_R: float = 1.0
    effective_cooling_area: float = 1.0
    cell_factory: Callable[[], Any] = SonyLFP

    def __post_init__(self) -> None:
        if len(self.circuit) != 2 or min(self.circuit) <= 0:
            raise ValueError("circuit must contain positive (series, parallel) counts")
        if not 0.0 < self.initial_soh_Q <= 1.0:
            raise ValueError("initial_soh_Q must be in (0, 1]")
        if not 0.0 < self.initial_soh_R:
            raise ValueError("initial_soh_R must be positive")
        if self.effective_cooling_area <= 0.0:
            raise ValueError("effective_cooling_area must be positive")


@dataclass(frozen=True, slots=True)
class SimSESConverterConfig:
    """Optional SimSES converter configuration in platform-facing units."""

    efficiency: float | tuple[float, float] = 1.0

    def __post_init__(self) -> None:
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
class SimSESAssetRealization:
    """Requested platform asset versus the selected SimSES realization."""

    requested_rated_power_kw: float
    requested_energy_capacity_kwh: float
    realized_rated_power_kw: float | None
    realized_energy_capacity_kwh: float
    power_sizing_error_percent: float | None
    energy_sizing_error_percent: float


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
        asset_spec: StorageAssetSpec,
        initial_timestamp: datetime,
        config: SimSESStorageConfig | None = None,
        converter: SimSESConverterConfig | None = None,
        thermal: SimSESThermalConfig | None = None,
    ) -> None:
        implementation = config or SimSESStorageConfig()
        self._asset_spec = asset_spec
        self._config = implementation
        self._battery = Battery(
            cell=implementation.cell_factory(),
            circuit=implementation.circuit,
            initial_states={
                "start_soc": asset_spec.initial_soc,
                "start_T": asset_spec.initial_temperature_c,
                "start_soh_Q": implementation.initial_soh_Q,
                "start_soh_R": implementation.initial_soh_R,
            },
            soc_limits=(asset_spec.min_soc, asset_spec.max_soc),
            degradation=implementation.degradation,
            effective_cooling_area=implementation.effective_cooling_area,
        )
        if converter is None:
            self._simses_storage: Any = self._battery
        else:
            self._simses_storage = Converter(
                loss_model=FixedEfficiency(converter.efficiency),
                max_power=max(
                    asset_spec.max_charge_power_kw,
                    asset_spec.max_discharge_power_kw,
                )
                * WATTS_PER_KW,
                storage=self._battery,
            )

        self._thermal_model: AmbientThermalModel | None = None
        if thermal is not None:
            self._thermal_model = AmbientThermalModel(
                T_ambient=thermal.ambient_temperature_c,
            )
            self._thermal_model.add_component(self._battery)

        self._state_timestamp = initial_timestamp
        realized_energy = self._battery.nominal_energy_capacity / WATTS_PER_KW
        realized_power = (
            max(asset_spec.max_charge_power_kw, asset_spec.max_discharge_power_kw)
            if converter is not None
            else None
        )
        self._realization = SimSESAssetRealization(
            requested_rated_power_kw=asset_spec.rated_power_kw,
            requested_energy_capacity_kwh=asset_spec.energy_capacity_kwh,
            realized_rated_power_kw=realized_power,
            realized_energy_capacity_kwh=realized_energy,
            power_sizing_error_percent=(
                None
                if realized_power is None
                else (realized_power / asset_spec.rated_power_kw - 1.0) * 100.0
            ),
            energy_sizing_error_percent=(
                realized_energy / asset_spec.energy_capacity_kwh - 1.0
            )
            * 100.0,
        )

    @property
    def asset_spec(self) -> StorageAssetSpec:
        """Return the immutable requested platform asset specification."""

        return self._asset_spec

    @property
    def realization(self) -> SimSESAssetRealization:
        """Return transparent requested-versus-realized sizing metadata."""

        return self._realization

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
    "SimSESAssetRealization",
    "SimSESConverterConfig",
    "SimSESStorageAdapter",
    "SimSESStorageConfig",
    "SimSESThermalConfig",
]
