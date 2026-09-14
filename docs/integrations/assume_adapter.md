# ASSUME adapter

## Scope

Phase 3 integrates ASSUME's market results and cleared order schedules into
the platform contracts. It does not connect ASSUME to SimSES and does not
replace ASSUME bidding, clearing, or storage calculations.

The adapter accepts plain mapping payloads at the upstream message boundary.
This is intentional: ASSUME uses asynchronous Mango messages and this keeps
ASSUME-specific objects out of the platform core. The official checkout is
`external/assume`, tag `v0.6.0`, commit
`e9f8376d3a9fd8334408ea267d66559b87549e17`.

## Exact upstream APIs and classes

The audit and adapter boundary use these ASSUME APIs:

- `assume.common.units_operator.UnitsOperator.submit_bids()` calls a unit's
  `calculate_bids(...)` and sends a `context == "submit_bids"` orderbook.
- `assume.common.units_operator.UnitsOperator.handle_market_feedback()`
  receives a `ClearingMessage` and reads `accepted_orders` and
  `rejected_orders`.
- `assume.markets.base_market.MarketRole.clear_market()` invokes the market
  mechanism, adds `market_id` and `time` to each market metadata row, and
  publishes `market_meta`.
- `assume.common.units_operator.UnitsOperator.get_actual_dispatch()` emits
  `market_dispatch` and `unit_dispatch` records.

`AssumeMarketAdapter` maps `market_meta` rows to `MarketObservation`.
`AssumeTradingStrategyAdapter` maps the bid/clearing order records to
`TradeResult` and `DispatchRequest`. The latter is a result adapter: ASSUME
continues to execute its own bidding strategy and market clearing upstream.

Both ASSUME storage mapping and strategy capability information use the
platform `StorageAssetSpec`; ASSUME does not define an independent experiment
asset size. `assume_storage_config_from_asset()` converts the common asset to
ASSUME's MW/MWh storage configuration, including its negative charge-power
convention.

ASSUME's native storage strategy is not a platform `TradingStrategy`. Its
`StorageEnergyHeuristicFlexableStrategy.calculate_bids()` requires an ASSUME
storage unit, forecast, `MarketConfig`, and product tuples. Therefore it is
not called with a platform `StorageState` in this phase. A future live
participant bridge may invoke it behind the `submit_bids` message boundary.

## Mapping and semantics

ASSUME `market_meta` fields map as follows:

| ASSUME field | Platform field |
| --- | --- |
| `product_start` (or `time`) | `MarketObservation.timestamp` |
| `product_end - product_start` | `duration_seconds` |
| `price` | `price_per_kwh` |
| `market_id` | `market_id` |
| generated stable start/end key | `product_id` |

ASSUME `Order` fields map as follows:

| ASSUME field | Platform field |
| --- | --- |
| `volume` | `TradeResult.bid_quantity_kw` |
| `accepted_volume` | `TradeResult.accepted_quantity_kw` and `accepted_energy_kwh` |
| `price` | `bid_price_per_kwh` |
| `accepted_price` | `accepted_price_per_kwh` and settlement `price_per_kwh` |
| accepted quantity | `DispatchRequest.power_kw` |

The official storage path confirms that positive volume is supply/generation
(discharge/export) and negative volume is demand/consumption
(charge/import). This is the same as the platform convention, so the sign
conversion is identity; no hidden negation is performed.

ASSUME's storage and market code uses numeric order volume as a power-like
schedule for storage dispatch. `calculate_meta()` derives interval energy by
multiplying accepted volume by interval hours. The adapter therefore requires
explicit `volume_semantics`; its official-scenario default is `"power"`.
When semantics are `"power"`, MW is converted to kW by `* 1000` and energy is
`power_kw * duration_seconds / 3600`. When semantics are `"energy"`, MWh is
converted to kWh by `* 1000` and average power is derived by dividing by the
interval duration. The adapter never decides this from the `volume_unit`
label alone.

ASSUME prices in the energy-market example are EUR/MWh. They become platform
EUR/kWh by `/ 1000`. EUR/kWh input is accepted without scaling. Cash flow is
accepted energy times accepted price and remains separate from physical loss.

ASSUME's `datetime2timestamp()` uses UTC calendar seconds and
`timestamp2datetime()` returns a UTC-naive `datetime`. The adapter preserves
datetime inputs, parses ISO timestamps, and applies the same UTC-naive result
for numeric Unix timestamps. Product duration is always calculated from the
upstream start/end timestamps and exposed in seconds.

## Storage ownership in ASSUME

Storage state remains entirely upstream in this phase:

- initialization: `assume.units.storage.Storage.__init__`, including
  `initial_soc`, capacity, SOC bounds, power bounds, and efficiencies;
- bid-time limits: `calculate_min_max_charge()` and
  `calculate_min_max_discharge()`, used by
  `StorageEnergyHeuristicFlexableStrategy.calculate_bids()`;
- dispatch plan: `SupportsMinMaxCharge.set_dispatch_plan()` writes accepted
  volume and price into time-indexed output series;
- physical-ish update: `Storage.execute_current_dispatch()` clips charge and
  discharge power, applies SOC and capacity limits, and updates `outputs["soc"]`;
- charge efficiency: the charging branch multiplies imported power by
  `efficiency_charge` for SOC change;
- discharge efficiency: the discharging branch divides exported power by
  `efficiency_discharge` for SOC change;
- storage capacity and SOC limits: the same execution and min/max helper
  methods enforce `capacity`, `min_soc`, `max_soc`, and configured power limits.

ASSUME `storage_meta` exposes configured capacity, efficiency, power, and SOC
limits. `unit_dispatch` exposes ASSUME's `soc`, power, cashflow, and related
series. ASSUME's `heat` output is not a guaranteed physical temperature.
SOH/aging and SimSES thermal/loss outputs are not supplied by this adapter.

One upstream caveat is recorded rather than corrected here: in the audited
revision, `Storage.as_dict()` assigns `efficiency_charge` from
`self.efficiency_discharge` and vice versa. The adapter does not use that
metadata path to calculate dispatch; any future configuration import should
either consume the constructor/configuration values or add an upstream
regression issue without changing ASSUME in this repository.

## Limitations and Phase 4 boundary

- No live Mango agent is wrapped yet; callers provide the serialized payloads
  emitted by the upstream boundaries.
- Rejected orders are not dispatch requests. A missing accepted order maps to
  a zero request when `decide()` is called for an observation.
- Complex datetime-keyed order quantities are supported only when the product
  key can be matched to the observation start.
- Product volume semantics must be configured explicitly for non-power
  products.
- ASSUME's native storage SOC/efficiency/limits are characterization data only
  for this phase. They must not run as a second physical authority once SimSES
  is coupled.

The next boundary is:

```text
ASSUME market_meta + accepted_orders
    -> Assume adapters
    -> DispatchRequest
    -> CouplingEngine
    -> SimSESStorageAdapter
```

At that point ASSUME accepted power is a request, while SimSES owns actual
power, SOC, efficiency, losses, temperature, and aging. ASSUME must not also
advance SOC or independently apply efficiency for the same physical interval.
