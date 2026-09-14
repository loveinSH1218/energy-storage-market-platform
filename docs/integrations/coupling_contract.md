# ASSUME-SimSES Coupling Contract

## Scope

This document defines the platform-level boundary between the ASSUME market
integration, the SimSES storage integration, and the coupling engine. It is a
data and ownership contract, not a reimplementation of either upstream
project.

The integrations must preserve the upstream projects as separate, replaceable
backends. Upstream-specific objects must not leak into the platform core.

## Platform units and sign convention

| Quantity | Platform unit |
| --- | --- |
| Power | kW |
| Energy | kWh |
| Timestep duration | seconds |
| State of charge (SOC) | normalized [0, 1] |
| State of health (SOH) | normalized [0, 1], when available |
| Temperature | deg C |

The platform power convention is:

- Positive power means discharge: the storage exports power to the grid.
- Negative power means charge: the storage imports power from the grid.

Any conversion from an upstream unit or sign convention happens in the
corresponding adapter or coupling boundary. The conversion must not be spread
through market, strategy, or storage code.

## Ownership

### ASSUME

ASSUME is authoritative for:

- market timeline;
- market products;
- bids;
- market clearing;
- accepted orders;
- market prices; and
- financial settlement.

ASSUME produces market outcomes and accepted orders. It does not own the
physical battery state or battery physics.

### SimSES

SimSES is authoritative for:

- physical SOC;
- actual battery power;
- charge and discharge efficiency;
- conversion losses;
- thermal state;
- battery limits; and
- SOH and aging, when provided by the selected SimSES model.

SimSES is the source of truth for the physical result after a power request is
executed. A requested power is not assumed to be the actual power delivered.

### Coupling engine

The coupling engine is authoritative for the coordination between the two
backends. It owns:

- unit conversion;
- sign conversion;
- timestep conversion;
- synchronization;
- requested-versus-actual dispatch tracking.

The engine passes market-cleared dispatch requests to the storage adapter,
handles storage substeps where required, and returns actual storage results to
the platform accounting and observation layers.

## Dispatch flow

The intended flow is:

    ASSUME market outcome
            ->
    platform dispatch request
            ->
    coupling engine converts units, sign, and time
            ->
    SimSES executes the requested power
            ->
    SimSES storage step result
            ->
    coupling engine records requested and actual dispatch
            ->
    platform observation/accounting

At minimum, a platform dispatch request must identify the interval, requested
power, and timestep duration. A storage step result must expose the actual
power and updated SOC, and should expose losses, temperature, and SOH/aging
metrics whenever the selected SimSES model provides them.

Market acceptance and physical execution are separate events. An accepted
ASSUME order records the market-side obligation; SimSES determines how much
power can physically be delivered under its SOC, power, thermal, efficiency,
and other limits. The coupling layer must retain both requested and actual
values so deviations are observable.

## Time synchronization

ASSUME market intervals and SimSES simulation steps may have different
durations. The coupling engine converts all durations to seconds at the
platform boundary and explicitly maps each market interval to one or more
storage steps. It must not assume that a market timestep equals a SimSES
timestep.

For a market interval with substeps, the engine aggregates the SimSES results
using explicit energy accounting. It must preserve the distinction between:

- requested dispatch for the market interval;
- each storage substep request;
- actual power returned by SimSES; and
- cumulative actual energy, losses, and state changes.

## No double integration

SOC and efficiency must not be independently integrated by both ASSUME and
SimSES.

Specifically:

- SimSES alone advances physical SOC and applies its efficiency and loss
  calculations.
- ASSUME may use market-side schedules, bids, and settlement quantities, but it
  must not independently update the physical SOC or apply a second efficiency
  calculation.
- The coupling engine must pass the authoritative SimSES state onward rather
  than reconstructing SOC from requested power.

If a market strategy needs storage state, it consumes the latest platform
storage state derived from SimSES. It does not access or mutate a concrete
SimSES battery object directly.

## Compatibility and validation requirements

The adapters must document and test:

1. ASSUME power, energy, price, and time representations at the market
   boundary.
2. SimSES requested-power, timestep, initial-SOC, and configuration inputs.
3. SimSES actual-power, SOC, loss, temperature, and SOH/aging outputs that are
   available for the selected model.
4. Positive/negative power conversion in both directions.
5. Market-interval to storage-substep synchronization.
6. Clipping or rejection when SimSES cannot satisfy a request.
7. Preservation of requested and actual dispatch in the resulting records.

Missing upstream outputs must be represented explicitly as unavailable; they
must not be fabricated or silently inferred.
