"""Contract tests for the real SimSES storage adapter."""

from datetime import UTC, datetime, timedelta
from math import isfinite

import pytest

from energy_storage_market_platform.core import (
    DispatchRequest,
    StorageBackend,
    StorageState,
)
from energy_storage_market_platform.storage.adapters import (
    SimSESConverterConfig,
    SimSESStorageAdapter,
    SimSESStorageConfig,
    SimSESThermalConfig,
)

START = datetime(2026, 1, 1, tzinfo=UTC)
DT_SECONDS = 60.0


def make_adapter(
    *,
    initial_soc: float = 0.5,
    converter: SimSESConverterConfig | None = None,
) -> SimSESStorageAdapter:
    return SimSESStorageAdapter(
        config=SimSESStorageConfig(
            initial_soc=initial_soc,
            initial_temperature_c=25.0,
            circuit=(13, 10),
            degradation=True,
        ),
        initial_timestamp=START,
        converter=converter,
        thermal=SimSESThermalConfig(ambient_temperature_c=25.0),
    )


def request(index: int, power_kw: float, dt_seconds: float = DT_SECONDS) -> DispatchRequest:
    return DispatchRequest(
        timestamp=START + timedelta(seconds=index * DT_SECONDS),
        duration_seconds=dt_seconds,
        power_kw=power_kw,
    )


def test_simses_adapter_satisfies_storage_backend_and_maps_sequence() -> None:
    storage = make_adapter(
        converter=SimSESConverterConfig(max_power_kw=2.0, efficiency=0.95),
    )
    assert isinstance(storage, StorageBackend)

    initial_state = storage.current_state()
    assert isinstance(initial_state, StorageState)
    assert initial_state.soc == pytest.approx(0.5)

    results = [
        storage.step(request(0, 0.0)),
        storage.step(request(1, -1.0)),
        storage.step(request(2, -1.0)),
        storage.step(request(3, 0.0)),
        storage.step(request(4, 1.0)),
        storage.step(request(5, 1.0)),
        storage.step(request(6, 0.0)),
    ]

    assert results[0].applied_power_kw == pytest.approx(0.0)
    assert results[1].applied_power_kw < 0.0
    assert results[2].applied_power_kw < 0.0
    assert results[4].applied_power_kw > 0.0
    assert results[5].applied_power_kw > 0.0
    assert results[1].state.soc > results[0].state.soc
    assert results[2].state.soc > results[1].state.soc
    assert results[4].state.soc < results[3].state.soc
    assert results[5].state.soc < results[4].state.soc

    for result in results:
        assert result.requested_power_kw == result.model_dump()["requested_power_kw"]
        assert result.actual_power_kw == result.applied_power_kw
        assert result.energy_delta_kwh == result.energy_to_grid_kwh
        assert 0.0 <= result.state.soc <= 1.0
        assert 0.0 <= result.state.soh <= 1.0
        assert result.state.soh_Q is not None
        assert 0.0 <= result.state.soh_Q <= 1.0
        assert result.state.soh_R is not None
        assert result.state.soh_R > 0.0
        assert result.losses_kwh >= 0.0
        assert result.state.temperature_c is not None
        assert isfinite(result.state.temperature_c)
        assert all(
            isfinite(value)
            for value in (
                result.requested_power_kw,
                result.applied_power_kw,
                result.energy_to_grid_kwh,
                result.losses_kwh,
                result.state.soc,
                result.state.soh,
                result.state.energy_capacity_kwh,
            )
        )

    assert results[1].energy_to_grid_kwh < 0.0
    assert results[4].energy_to_grid_kwh > 0.0


def test_charge_at_high_soc_is_clipped_and_recorded() -> None:
    storage = make_adapter(initial_soc=0.99)

    result = storage.step(request(0, -1.0, dt_seconds=3600.0))

    assert result.requested_power_kw == -1.0
    assert result.applied_power_kw <= 0.0
    assert abs(result.applied_power_kw) < abs(result.requested_power_kw)
    assert 0.0 <= result.state.soc <= 1.0


def test_discharge_at_low_soc_is_clipped_and_recorded() -> None:
    storage = make_adapter(initial_soc=0.01)

    result = storage.step(request(0, 1.0, dt_seconds=3600.0))

    assert result.requested_power_kw == 1.0
    assert result.applied_power_kw >= 0.0
    assert result.applied_power_kw < result.requested_power_kw
    assert 0.0 <= result.state.soc <= 1.0


def test_request_above_physical_power_capability_is_clipped() -> None:
    storage = make_adapter()

    result = storage.step(request(0, -10.0))

    assert result.requested_power_kw == -10.0
    assert result.applied_power_kw <= 0.0
    assert abs(result.applied_power_kw) < abs(result.requested_power_kw)
    assert 0.0 <= result.state.soc <= 1.0
