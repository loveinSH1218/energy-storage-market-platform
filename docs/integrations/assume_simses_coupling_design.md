# ASSUME–SimSES coupling design

## Status and design objective

This document is a design proposal only. No platform source code, interfaces,
configuration, or dependencies were modified in this audit.

The smallest safe architecture keeps the two upstream projects independent:

```text
ASSUME World / market roles
        │ opening, bids, clearing messages, market metadata
        ▼
ASSUME market adapter / settlement boundary
        │ normalized accepted schedule
        ▼
platform coupling engine
        │ DispatchRequest in kW and seconds
        ▼
SimSES storage adapter
        │ W and SimSES sign convention
        ▼
SimSES Battery + optional Converter + optional ThermalModel
```

ASSUME remains responsible for market products, bidding, clearing, and
settlement. SimSES remains responsible for battery electrical behavior,
converter behavior, temperature, and aging. The platform owns only the
translation and orchestration.

## Proposed adapter responsibilities

### 1. `AssumeMarketAdapter`

This adapter should wrap an ASSUME scenario/world boundary and expose only
platform-neutral records. It should:

- configure and start the ASSUME world using the upstream loader;
- translate an opening/product event into platform market observations;
- preserve submitted bid identifiers and product intervals;
- consume `ClearingMessage.accepted_orders` and rejected orders;
- read `market_meta` for clearing prices and aggregate volumes;
- normalize ASSUME units, prices, timestamps, product duration, and currency;
- expose accepted schedules to the coupling engine;
- keep ASSUME `World`, Mango messages, `Order`, `MarketConfig`, and
  `FastSeries` private to the adapter.

The adapter should not implement market clearing or reproduce ASSUME bidding
logic. If the platform strategy is the source of bids, it should translate a
platform bid into an ASSUME `Order`. If an ASSUME-native storage bidding
strategy is retained, the adapter should observe the resulting clearing
message and not duplicate its pricing algorithm.

### 2. `SimSESStorageAdapter`

This adapter should own a composed SimSES object graph:

```text
Battery(cell, circuit, initial_states, ...)
    optionally wrapped by Converter(...)
    optionally registered with ThermalModel
```

It should implement the platform storage contract by:

- accepting platform `DispatchRequest` in kW, seconds, and the platform sign;
- converting to SimSES W and reversing the sign;
- calling the SimSES object once per requested physical substep;
- snapshotting requested power, actual grid-side power, SOC, temperature, SoH,
  and losses;
- converting W/W·s/Wh back to kW/kWh and platform signs;
- reporting clipping when SimSES actual power differs from the request;
- keeping the mutable SimSES state private.

No SimSES equation or model implementation belongs in this adapter.

### 3. Coupling orchestration

The coupling engine should coordinate settlement intervals and physical
substeps. It should not contain `if simses` or `if assume` branches. A future
implementation can use dependency injection of the two adapters and a
registry/factory selected by experiment configuration.

## Exact data mapping

### Market to platform

| ASSUME source | Platform-side value | Required treatment |
|---|---|---|
| `Order.start_time`, `Order.end_time` | dispatch/observation timestamp and duration | Convert to timezone-aware `datetime` and seconds |
| `Order.volume` / `accepted_volume` | requested/applied grid power | Normalize to kW; verify whether the configured product value is power-like MW or energy-like MWh |
| `Order.price`, `accepted_price` | price per kWh | Convert `EUR/MWh` to `EUR/kWh` or retain an explicitly named original unit before settlement |
| `MarketConfig.price_unit`, `volume_unit` | metadata | Never discard these labels during normalization |
| `market_meta["price"]` | `MarketObservation.price_per_kwh` | Use only after confirming product interval and currency |
| accepted order presence | `MarketObservation.available` / trade eligibility | Rejected orders must not become physical dispatch |

ASSUME storage orders use positive discharge and negative charge. For the
platform convention, a normalized accepted order should therefore satisfy:

```text
platform_grid_power_kw = accepted_assume_power_mw * 1000
```

for a one-hour power product. For an energy-denominated product, first divide
accepted energy by product duration in hours to obtain MW. This distinction is
mandatory for products other than the reproduced one-hour example.

### Platform to SimSES

For a bare SimSES `Battery` or a grid-side SimSES `Converter`:

```text
simses_power_w = -platform_grid_power_kw * 1000
simses_dt_s = request.duration_seconds
```

Examples:

```text
platform +100 kW (discharge/export) -> SimSES -100,000 W (discharge)
platform -100 kW (charge/import)    -> SimSES +100,000 W (charge)
```

After stepping:

```text
platform_applied_power_kw = -simses_actual_power_w / 1000
energy_to_grid_kwh = platform_applied_power_kw * dt_s / 3600
```

When a `Converter` is used, `converter.state.power` is the preferred actual
grid-side power. When no converter is used, use `battery.state.power` and
document that the reported power is battery-side rather than AC grid-side.

## Initial state and configuration mapping

ASSUME storage metadata provides capacity, charge/discharge limits,
efficiencies, SOC limits, and sometimes `initial_soc`. SimSES requires at
least:

```python
initial_states={"start_soc": initial_soc, "start_T": initial_temperature_c}
```

Therefore:

- map ASSUME `initial_soc` directly to SimSES `start_soc`;
- choose `start_T` from explicit experiment configuration; ASSUME does not
  provide the required physical temperature in its storage metadata;
- map capacity only after choosing the SimSES circuit/cell model, because
  SimSES capacity is derived from cell parameters and series/parallel counts;
- map initial SoH only if the experiment has explicit SoH values;
- do not silently apply ASSUME charge/discharge efficiency on top of SimSES
  cell/converter losses.

The physically authoritative model should be SimSES. ASSUME's storage
efficiency and SOC series may still be useful to its bidding strategy, but
running both SOC models as authorities would create a duplicated and
potentially divergent state. The selected integration mode must explicitly
choose one owner.

## Recommended first integration mode

The lowest-risk first milestone is a settled-schedule co-simulation:

1. Run an ASSUME market scenario with a storage-capable participant.
2. Capture the accepted orderbook and clearing metadata at each settlement.
3. Convert each accepted order into a platform `DispatchRequest`.
4. Execute that request in SimSES, using smaller physical substeps when
   configured.
5. Record both ASSUME settlement data and SimSES actual physical outputs.
6. Compare scheduled versus actual power, SOC, and energy accounting.

This milestone should not claim that ASSUME's native storage model and SimSES
are equivalent. It characterizes the difference between the market schedule
and the selected physical model.

For a live bid/feedback integration, a second milestone is required: the
ASSUME-side market participant must obtain current SimSES SOC and feasible
power limits before calculating bids, and its clearing-feedback handler must
send accepted intervals to SimSES rather than advance an independent
algebraic SOC. That is an upstream-facing participant adapter, not a change to
ASSUME internals.

## Time resolution and sub-stepping

ASSUME schedules products on its scenario index, commonly one hour in the
baseline. SimSES accepts arbitrary positive `dt` per call in seconds. The
coupling engine should therefore:

- treat ASSUME product duration as the authoritative settlement interval;
- choose a physical step size from SimSES experiment configuration;
- require the settlement duration to be an integer multiple of the physical
  step, or make the remainder explicit;
- execute all physical substeps before emitting one interval-level platform
  result;
- use the final substep's actual power/state and accumulated loss energy for
  the interval result.

The thermal model, if present, must be stepped after electrical components have
written heat for each physical substep.

## Incompatibilities and risks

### 1. Opposite SimSES sign convention

ASSUME and the platform use positive discharge/export. SimSES uses positive
charge. The sign inversion must exist in exactly one storage adapter and must
be contract-tested in both directions.

### 2. Power/energy labels and interval semantics

ASSUME examples configure `volume_unit: MWh`, while the storage dispatch code
uses time-indexed power-like values in MW and multiplies by duration. The
one-hour example hides this issue. Multi-hour products require an explicit
normalization rule before SimSES is called.

### 3. Different capacity/efficiency ownership

ASSUME's native storage class advances an idealized SOC using scalar charge and
discharge efficiencies. SimSES derives behavior from cell, converter, limits,
thermal state, and optional aging. Both must not be treated as independent
physical authorities in one run.

### 4. ASSUME has no direct physical-storage command interface

The native command is an accepted market order and an output schedule. A live
bridge needs a participant/feedback integration point or an explicit
post-settlement observer. There is no upstream `step(power, dt)` hook to call
on a generic storage backend.

### 5. ASSUME is asynchronous and event-driven

Market openings and clearing results are Mango messages managed by a World
clock. SimSES is synchronous and caller-driven. The adapter must buffer or
await clearing events and must define what happens if a market event arrives
before a physical result or if a product is only partially accepted.

### 6. Initial temperature is missing in ASSUME metadata

SimSES requires `start_T`; ASSUME's storage input does not provide it. The
experiment configuration must supply it, and the choice must be recorded for
reproducibility.

### 7. Physical actual power can differ from an accepted bid

ASSUME clips against its own constraints before exporting `unit_dispatch`.
SimSES independently clips against electrical, voltage, SOC, temperature, and
derating limits. The platform must retain requested power, applied power, and
the source of curtailment rather than overwrite one with another.

### 8. Losses are reported at different levels

SimSES reports battery and converter losses as instantaneous power. ASSUME
reports market cashflow/cost series and does not provide SimSES-style
electrical/thermal loss fields. The coupling layer must integrate loss power
over seconds and keep monetary settlement separate from physical losses.

### 9. Current SimSES has no application-level result timeline

The caller must add timestamps, interval aggregation, serialization, and
logging. This is a good fit for the platform coupling layer but is not an API
provided by SimSES itself.

## Proposed contract tests before implementation

The first adapter implementation should add tests for:

1. +1 kW platform discharge becomes -1,000 W SimSES power.
2. -1 kW platform charge becomes +1,000 W SimSES power.
3. A one-hour accepted 1 MW ASSUME discharge becomes a 1,000 kW, 3,600 s
   platform request before the W conversion.
4. SimSES clipping is reported as requested versus applied power.
5. Initial SOC is preserved at construction and reflected in the first
   platform `StorageState`.
6. Loss power is integrated with `dt / 3600` into kWh without confusing it
   with cashflow.
7. SOC, temperature, `soh_Q`, and `soh_R` are serializable snapshots.
8. Physical substeps sum to exactly one ASSUME settlement interval.
9. Rejected ASSUME orders never generate storage requests.
10. A product with duration other than one hour follows the explicit
    power-versus-energy normalization rule.

## Final integration point summary

The exact recommended integration points are:

- ASSUME bid submission: `UnitsOperator.submit_bids()` and the
  `context == "submit_bids"` orderbook message.
- ASSUME accepted schedule: `UnitsOperator.handle_market_feedback()` receiving
  `ClearingMessage`, specifically `accepted_orders` and `rejected_orders`.
- ASSUME market prices/results: `MarketRole.clear_market()` result metadata and
  the `market_meta` output table.
- ASSUME dispatch export: `UnitsOperator.get_actual_dispatch()` and its
  `market_dispatch` / `unit_dispatch` records.
- SimSES input: `Battery.step(power_setpoint_w, dt_seconds)` or
  `Converter.step(power_setpoint_w, dt_seconds)`.
- SimSES output: `state.power_setpoint`, `state.power`, `state.loss`,
  `state.heat`, `state.soc`, `state.T`, `state.soh_Q`, and `state.soh_R`.

The adapter layer should stop at those boundaries. It should not copy upstream
classes or physics into `src/energy_storage_market_platform`.

