# SimSES integration analysis

## Scope and upstream revision

This audit targets the current official SimSES repository:

- Repository: <https://github.com/tum-ees/simses>
- Local audit copy: `external/simses`
- Revision: `main`, commit `d8bb7906ed58bb47be531f09e031ad6f4bf5ee39`
- Upstream head commit date: 2026-09-03
- License: BSD-3-Clause (`external/simses/LICENSE`)
- Declared Python requirement: `>=3.12`; this audit used CPython 3.12.11

The older repository at <https://gitlab.lrz.de/open-ees-ses/simses> was also
inspected. Its `master` README marks it deprecated and points to the TUM
GitHub repository. It is retained as `external/simses-legacy` only for
historical compatibility context and is not the target adapter API.

The current repository is a ground-up rewrite and is deliberately a component
library. Application-level scheduling, timestamps, market settlement, and
result logging belong to the caller.

## Unchanged upstream baseline

The shipped example `external/simses/examples/state_logging.py` was executed
unchanged with:

```powershell
uv run python examples/state_logging.py
```

It completed with exit code 0. The example constructs a `Battery` with
`SonyLFP`, circuit `(13, 1)`, initial SOC 0.5, and initial temperature 25 °C;
then applies 120 one-minute steps: 60 steps at +50 W followed by 60 steps at
-50 W. It logs `soc`, `v`, `i`, `power`, `loss`, and `T` into a pandas
DataFrame. The optional plot was skipped because matplotlib was not installed.

Observed baseline values from the unchanged function:

- First logged state: SOC `0.506341848868591`, actual power
  `50.000000000000014` W, loss `1.036033245293397` W, temperature `25.0` °C.
- Last logged state: SOC `0.48771233293290667`, actual power
  `-50.00000000000002` W, loss `0.5819131795823055` W, temperature `25.0` °C.
- Logged SOC range: `0.48771233293290667` to `0.8782645519159571`.
- Sum of logged battery losses multiplied by 60 seconds:
  `5729.794355285909` W·s.

The example intentionally logs state externally because each `step()` mutates
one in-place state object rather than returning a time-series result.

The upstream test command was run as:

```powershell
uv run --group dev pytest
```

Result: `366 passed, 4 skipped` in 11.82 seconds.

## Battery construction and configuration

The principal battery API is `simses.battery.Battery` in
`src/simses/battery/battery.py`:

```python
Battery(
    cell=SonyLFP(),
    circuit=(serial_cells, parallel_strings),
    initial_states={"start_soc": 0.5, "start_T": 25.0},
    soc_limits=(0.0, 1.0),
    degradation=True,
    derating=None,
)
```

Accepted configuration inputs are Python constructor arguments and composed
model objects, not a market-style YAML scenario. Important inputs include:

- `cell`: a cell model such as `SonyLFP()`;
- `circuit`: serial/parallel cell count;
- `initial_states`: required `start_soc` and `start_T`, with optional
  `start_soh_Q` and `start_soh_R`;
- `soc_limits`: normalized operating limits;
- `degradation`: `True` for the cell default, a concrete degradation model, or
  `False`/`None` to disable it;
- `derating`: optional current derating strategy;
- `effective_cooling_area`: used by the battery thermal properties.

There is no timestamp parameter in `Battery.step()`. The caller owns the
simulation clock and must provide the duration on each call.

## Requested power and timestep

`Battery.step(power_setpoint, dt)` accepts:

- `power_setpoint`: watts;
- `dt`: seconds;
- return value: `None`; state is mutated in place.

SimSES battery sign convention is the inverse of the platform convention:

- positive power/current: charging/importing into the battery;
- negative power/current: discharging/exporting from the battery.

The battery solves its equivalent-circuit response, applies current, voltage,
SOC, and optional thermal derating limits, updates SOC, then writes the actual
result to `battery.state.power`. The requested value remains available as
`battery.state.power_setpoint`; therefore a wrapper can detect curtailment by
comparing those two fields.

## Returned state and results

`Battery.state` is the mutable `BatteryState` dataclass. Relevant fields are:

| Required platform observation | SimSES field | Unit / meaning |
|---|---|---|
| Requested power | `state.power_setpoint` | W, positive charge |
| Actual battery power | `state.power` | W, positive charge |
| SOC | `state.soc` | normalized p.u. |
| Battery loss | `state.loss` | W, irreversible loss recorded by the battery |
| Heat generation | `state.heat` | W, irreversible plus reversible heat |
| Temperature | `state.T` | °C |
| Capacity SoH | `state.soh_Q` | normalized p.u. |
| Resistance SoH | `state.soh_R` | normalized resistance-health factor |
| Voltage/current | `state.v`, `state.i` | V and A |

The battery's current `state.loss` is a power quantity, not an energy total.
The adapter must multiply by the executed duration to obtain a loss energy
quantity when required by a platform result model. The distinction between
`loss` and `heat` should be preserved.

If aging is enabled, `Battery.step()` calls the configured degradation model.
`soh_Q` and `soh_R` are updated in the state. The model also owns an accessible
`DegradationState` containing accumulated calendar/cyclic capacity loss and
resistance increase (`qloss_cal`, `qloss_cyc`, `rinc_cal`, `rinc_cyc`).

## Converter and AC-side integration

For grid-facing power, the optional `simses.converter.Converter` is normally
the better boundary than a bare battery. It wraps a downstream battery,
accepts `step(power_setpoint, dt)`, clamps to rated `max_power` in W, applies a
loss model, and exposes:

- `converter.state.power_setpoint`: requested AC power in W;
- `converter.state.power`: actual AC power in W;
- `converter.state.loss`: converter loss in W;
- `converter.storage.state`: downstream battery state.

The converter uses the same SimSES sign convention: positive AC power charges,
negative AC power discharges. Its two-pass logic re-computes actual AC power
when the downstream storage cannot fulfill the DC request. This allows the
adapter to report grid-side applied power while separately retaining battery
losses and converter losses.

## Thermal behavior

Battery temperature is a state field, but the battery alone does not advance an
ambient or container thermal environment. `AmbientThermalModel` and
`ContainerThermalModel` are separate components. The documented sequencing is:

```text
battery/converter.step(power, dt)
thermal_model.step(dt)
```

The electrical component writes `state.heat`; the thermal model reads heat and
writes the next `state.T`. If no thermal model is configured, the battery's
temperature can remain at its initialized value, as it did in the reproduced
example.

## Capacity, units, and limits

SimSES uses SI-scale electrical units internally:

- power: W;
- energy capacity: Wh (`battery.energy_capacity(state)` returns Wh);
- nominal capacity: Ah;
- voltage: V;
- current: A;
- time: seconds;
- SOC and SoH: normalized p.u.;
- temperature: °C.

The platform therefore needs explicit conversions to kW and kWh. The wrapper
must also decide whether the requested power is battery-side DC power or
grid-side AC power. That decision determines whether a `Converter` is part of
the composed SimSES object.

SimSES clips requests internally. It does not return a separate structured
`StorageStepResult`; the adapter must snapshot the pre-step request and the
post-step state and create the platform result.

## Integration conclusion

The smallest stable SimSES boundary is:

```text
construct Battery (optionally behind Converter and thermal model)
    -> step(power_W, duration_seconds)
    -> snapshot mutable state
```

The adapter must own timestamps, kW/kWh conversion, the platform power sign,
loss-energy calculation, and serialization. It must not copy SimSES battery,
converter, thermal, or degradation equations into platform code.

