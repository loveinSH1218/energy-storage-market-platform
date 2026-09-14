# SimSES storage adapter

## Architecture

`SimSESStorageAdapter` is the first real implementation of the platform
`StorageBackend` protocol. It lives under
`energy_storage_market_platform.storage.adapters` and returns only platform
`StorageState` and `StorageStepResult` objects.

The adapter requires the immutable platform `StorageAssetSpec`. It is the
source of requested asset sizing and initial operating state; the SimSES
configuration contains only implementation choices.

The adapter owns a private SimSES object graph:

    Battery
      optionally wrapped by Converter
      optionally registered with AmbientThermalModel

No SimSES object is returned by `current_state()` or `step()`. The rest of the
platform imports only the adapter and core models; SimSES imports are confined
to the adapter module.

## Exact upstream API

The adapter uses the official SimSES repository at the revision recorded in
`simses_analysis.md` and the following public classes and methods:

- `simses.battery.Battery`
  - constructor with `cell`, `circuit`, `initial_states`, `soc_limits`,
    `degradation`, and `effective_cooling_area`;
  - `step(power_setpoint, dt)`;
  - `state.power`, `state.power_setpoint`, `state.loss`, `state.soc`,
    `state.T`, `state.soh_Q`, and `state.soh_R`;
  - `energy_capacity(state)`.
- `simses.model.cell.sony_lfp.SonyLFP` as the default cell factory.
- `simses.converter.Converter`
  - constructor with `loss_model`, `max_power`, and `storage`;
  - `step(power_setpoint, dt)`;
  - `state.power` and `state.loss`.
- `simses.model.converter.fix_efficiency.FixedEfficiency` for the optional
  converter configuration.
- `simses.thermal.AmbientThermalModel`
  - constructor with `T_ambient`;
  - `add_component(battery)`;
  - `step(dt)`.

The adapter calls the electrical object once per platform request. If a
thermal model is configured, it advances after the electrical step, matching
the documented SimSES sequencing.

## Initialization

`StorageAssetSpec` maps platform initialization to SimSES as follows:

| Platform configuration | SimSES input |
| --- | --- |
| `initial_soc` | `initial_states["start_soc"]` |
| `initial_temperature_c` | `initial_states["start_T"]` |
| `min_soc`, `max_soc` | `Battery(..., soc_limits=...)` |

`SimSESStorageConfig` maps implementation choices as follows:

| Implementation configuration | SimSES input |
| --- | --- |
| `initial_soh_Q`, `initial_soh_R` | SimSES initial state values |
| `circuit` | `Battery(..., circuit=...)` |
| `degradation` | `Battery(..., degradation=...)` |
| `cell_factory` | `Battery(..., cell=cell_factory())` |
| `effective_cooling_area` | Battery constructor option |

The default cell is `SonyLFP`, and the default circuit template is `(13, 10)`
(series, parallel). This circuit is not the platform asset definition. Its
realized size is reported explicitly below. Degradation is disabled unless explicitly set to `True` or a
SimSES degradation model is supplied through a future extension. Initial
temperature is required because SimSES requires `start_T`; it is not inferred
from market data.

An optional `SimSESConverterConfig` supplies converter efficiency. The
converter `max_power` is derived from the asset's maximum charge/discharge
capability and converted to W. Its efficiency is passed to SimSES `FixedEfficiency`; the
adapter does not apply a second efficiency calculation.

An optional `SimSESThermalConfig` constructs an `AmbientThermalModel` and
registers the battery as its thermal component. Without this option, the
SimSES battery temperature remains the value maintained by the battery model
itself.

## Unit and sign conversion

The platform uses kW, kWh, and seconds. SimSES uses W, Wh, and seconds. The
platform exports positive discharge power and negative charge power, while
SimSES uses positive charge power and negative discharge power.

For every request:

    simses_power_setpoint_w = -requested_power_kw * 1000
    simses_dt_seconds = request.duration_seconds

For the actual result:

    actual_power_kw = -simses_state.power / 1000
    energy_to_grid_kwh = actual_power_kw * dt_seconds / 3600

When a converter is configured, `state.power` is its AC-side actual power.
Without a converter, `state.power` is the battery-side actual power, which is
the explicitly documented abstraction exposed by this first adapter.

## Output mapping

| Platform output | SimSES source or treatment |
| --- | --- |
| `requested_power_kw` | Original `DispatchRequest.power_kw` |
| `applied_power_kw` / `actual_power_kw` | Selected SimSES object's `state.power`, sign- and unit-converted |
| `energy_to_grid_kwh` / `energy_delta_kwh` | Actual platform power multiplied by seconds / 3600 |
| `losses_kwh` | SimSES battery loss plus optional converter loss, converted from W over the step |
| `state.soc` | Battery `state.soc` |
| `state.soh` | Battery `state.soh_Q` |
| `state.soh_Q` | Battery `state.soh_Q` |
| `state.soh_R` | Battery `state.soh_R` |
| `state.temperature_c` | Battery `state.T` after optional thermal step |
| `state.energy_capacity_kwh` | `Battery.energy_capacity(state)` converted from Wh |

`soh_Q` is the capacity-health value and is normalized to [0, 1]; it is also
used for the generic platform `StorageState.soh`. SimSES `soh_R` is a
resistance multiplier and may exceed 1, so it is exposed separately and is not
used as the generic normalized SOH. SimSES `state.loss` is reported loss
power, which the adapter integrates over the requested seconds; no loss or SOC
equation is recreated in platform code.

## Static asset realization

`SimSESStorageAdapter.realization` returns a frozen
`SimSESAssetRealization` containing:

- `requested_rated_power_kw`;
- `requested_energy_capacity_kwh`;
- `realized_rated_power_kw` when a converter establishes a rated boundary;
- `realized_energy_capacity_kwh` from `Battery.nominal_energy_capacity`;
- relative power and energy sizing errors in percent.

The default SonyLFP `(13, 10)` circuit is an implementation template, not a
100 MW / 200 MWh platform asset. Its discrete capacity mismatch is reported;
the adapter does not optimize or silently substitute cell counts. Without a
converter, SimSES has no single static AC rated-power field, so power
realization and power error are explicitly unavailable.

## Timestep handling

The existing `StorageBackend.step()` contract represents one executed
interval. The adapter forwards its positive duration in seconds unchanged to
SimSES. A future coupling engine may subdivide a market interval into several
requests; each request will then produce one adapter result and the coupling
engine can aggregate actual energy and losses.

The adapter does not assume that a market interval equals a physical timestep.
It also does not internally substep or interpolate, because those are coupling
engine responsibilities.

## Limitations and risks

- The initial implementation supports the official `Battery` composition and
  optional `Converter`/`AmbientThermalModel`; arbitrary SimSES compositions
  require a deliberate adapter extension.
- Without a converter, reported actual power is battery-side rather than
  grid-side AC power.
- SimSES `state.loss` is the loss field exposed by the selected model. It is
  not silently expanded into unreported thermal or auxiliary losses.
- SOH availability and behavior depend on the selected degradation model.
  `soh_R` is a resistance factor and is not constrained to [0, 1].
- The adapter records the request timestamp as the result/state timestamp,
  matching the existing ideal storage implementation. End-time timeline
  management remains a coupling-layer responsibility.
- SimSES remains the sole physical state authority. ASSUME is intentionally
  not connected in this phase.
