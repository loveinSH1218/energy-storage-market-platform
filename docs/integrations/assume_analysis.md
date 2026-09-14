# ASSUME integration analysis

## Scope and upstream revision

This audit covers the official ASSUME repository:

- Repository: <https://github.com/assume-framework/assume>
- Local audit copy: `external/assume`
- Revision: tag `v0.6.0`, commit `e9f8376d3a9fd8334408ea267d66559b87549e17`
- Upstream release commit date: 2026-03-18
- License: AGPL-3.0-or-later (`external/assume/LICENSES/AGPL-3.0-or-later.txt`)
- Declared Python range: `>=3.10`; this audit used CPython 3.12.11

The external checkout was not edited. The generated SQLite database is a
baseline artifact from the unchanged example and is not part of the platform
implementation.

## Unchanged upstream baseline

The repository example `external/assume/examples/examples.py` was executed
unchanged with:

```powershell
uv run --extra test python examples/examples.py
```

The shipped selection is `small_with_vre_and_storage`, which loads
`examples/inputs/example_01c` and the `eom_only` study case. It completed with
exit code 0 and wrote a local SQLite result database at
`external/assume/examples/local_db/assume_db.db`.

Observed baseline facts:

- Simulation period: 2019-01-01 through 2019-02-01, one-hour simulation step.
- Market result rows: 743 in `market_meta`.
- Bid/order rows: 10,708 in `market_orders`.
- Planned market dispatch rows: 7,726 in `market_dispatch`.
- Actual unit dispatch rows: 8,184 in `unit_dispatch`.
- Storage unit: `Storage 1`, 6,076 MWh capacity, initial SOC defaults to 0.0
  for this input, charge limit -1,000 MW, discharge limit 992 MW.
- The storage orderbook contained 741 rows, of which 331 had non-zero
  accepted volume.

The run logged that learning strategies were unavailable because PyTorch was
not installed. That did not affect this non-learning storage example.

## Runtime architecture and integration-relevant path

The useful execution path is:

```text
CSV/YAML scenario
    -> World and MarketConfig
    -> market opening message with products
    -> UnitOperator / unit bidding strategy
    -> submit_bids orderbook
    -> MarketRole clearing
    -> ClearingMessage with accepted/rejected orders
    -> unit dispatch plan and unit outputs
    -> market_dispatch / unit_dispatch persistence
```

Relevant source anchors in the audited revision:

- `assume/scenario/loader_csv.py`: scenario, market, and unit construction.
- `assume/common/market_objects.py`: `Order`, `MarketProduct`, `MarketConfig`,
  `OpeningMessage`, and `ClearingMessage`.
- `assume/common/units_operator.py`: bid submission, clearing feedback, dispatch
  setting, and actual-dispatch export.
- `assume/markets/base_market.py`: order validation, clearing, result messages,
  and persistence.
- `assume/common/base.py`: common unit bidding, accepted-order dispatch-plan
  handling, and output series.
- `assume/units/storage.py`: ASSUME's algebraic storage unit and SOC handling.

## Market state and prices

ASSUME does not expose one platform-style `MarketObservation` object. Its
market state is distributed across these objects and messages:

| Concept | ASSUME representation | Integration interpretation |
|---|---|---|
| Market identity | `MarketConfig.market_id` | Stable market identifier |
| Market product | `MarketProduct` and concrete product tuples `(start, end, only_hours)` | Settlement interval and product eligibility |
| Market opening | `OpeningMessage` with `market_id`, `start_time`, `end_time`, and `products` | Event that starts bidding |
| Market constraints | `MarketConfig`: product type, opening frequency/duration, volume and price limits, units, mechanism, additional fields | Adapter configuration and validation metadata |
| Clearing price | `market_meta["price"]`, plus `max_price` and `min_price` | Normalized price observation after clearing |
| Cleared volumes | `market_meta["supply_volume"]`, `demand_volume`, and energy variants | Market-level settlement result |
| Per-order outcome | `accepted_price` and `accepted_volume` on each order | Unit-level settlement and dispatch source |

During clearing, the market role appends result metadata with `product_start`
and adds `market_id` and `time`. The result can be requested through the
market's `data_request` mechanism or read from the `market_meta` output table.
The clearing price is therefore a post-clearing result, not a synchronous price
returned from bid calculation.

Forecast prices used by bidding strategies are separate from clearing results.
For example, `StorageEnergyHeuristicFlexableStrategy` reads
`unit.forecaster.price[market_config.market_id]` when calculating a bid. A
platform adapter must not confuse this forecast series with the settled
`market_meta` price.

## Bids

The canonical order is the typed dictionary `Order` in
`assume/common/market_objects.py`. Its important fields are:

```text
bid_id, start_time, end_time, volume, price,
agent_addr, node, only_hours,
accepted_volume, accepted_price
```

`volume > 0` means supply/generation and `volume < 0` means demand/consumption.
The storage implementation uses the same grid-facing convention: positive
power discharges and negative power charges.

The call chain is:

1. `BaseUnit.calculate_bids()` delegates to the selected strategy's
   `calculate_bids(unit, market_config, product_tuples)`.
2. `UnitsOperator.submit_bids()` sends an orderbook in a message with
   `context == "submit_bids"`.
3. `MarketRole.handle_orderbook()` validates products, price bounds, required
   fields, and market membership before adding orders to the market orderbook.

For the shipped storage strategy, the strategy calculates charge/discharge
limits from the ASSUME storage unit's output series and creates one order per
product with `start_time`, `end_time`, `price`, `volume`, and `node`.

## Accepted bids and settlement

`MarketRole.clear_market()` calls the selected clearing algorithm. The clearing
algorithm returns accepted orders, rejected orders, market metadata, and
optionally grid flows. Every accepted order receives `accepted_volume` and
`accepted_price`; rejected orders receive zero accepted volume and a clearing
price where the mechanism supplies one.

The market sends each registered agent a `ClearingMessage`:

```text
{
    "context": "clearing",
    "market_id": ...,
    "accepted_orders": [...],
    "rejected_orders": [...]
}
```

The message is the most direct integration point for an external physical
storage model. It contains product intervals and the accepted schedule, rather
than a battery command object.

## Dispatch schedules and storage-related commands

ASSUME has no generic `request_power(power, timestep)` storage API. Its native
storage command is an accepted market order that is copied into time-indexed
output series.

`BaseUnit.set_dispatch_plan()` adds accepted volumes to the output series named
for the product type and records accepted price. For storage units,
`SupportsMinMaxCharge.set_dispatch_plan()` also advances a theoretical SOC
using:

- positive power: discharge, SOC decreases by power / discharge efficiency;
- negative power: charge, SOC increases by `abs(power) * charge efficiency`;
- time: ASSUME index frequency expressed in hours;
- energy capacity: MWh.

`Storage.execute_current_dispatch()` then applies unit constraints and updates
the scheduled `energy` and `soc` series. It clips power to charge/discharge
limits, enforces minimum-power behavior, and clips against SOC limits. The
actual dispatch is exported by `UnitsOperator.get_actual_dispatch()` and
`write_actual_dispatch()`:

- `market_dispatch`: aggregated tuples `(datetime, power, market_id, unit_id)`;
- `unit_dispatch`: per-unit time series containing `power`, `soc`, cashflow,
  generation costs, total costs, and `heat` when available.

The SQLite output writer also exposes:

- `market_orders`: submitted and accepted bid fields;
- `market_meta`: clearing price and market aggregate results;
- `market_dispatch`: accepted-volume-derived planned/market dispatch;
- `unit_dispatch`: clipped actual unit dispatch and unit output series;
- `storage_meta`: static storage limits, capacity, efficiencies, and SOC limits.

ASSUME's storage `heat` field is not a physical temperature or battery thermal
state. It is an output slot available to units and is `None` in the reproduced
example's `unit_dispatch` rows.

## Units and sign/scale conventions

The example storage input is configured with MW/MWh values. The storage class
documents charge power as negative and discharge power as positive. SOC is a
fraction in `[0, 1]`. The one-hour example makes a power-versus-energy product
ambiguity invisible; for products longer than one hour the adapter must use
the product interval explicitly and must not assume every `volume_unit` label
has already been normalized to platform kW.

ASSUME's settlement cashflow uses accepted price times accepted volume and
multiplies across the elapsed product intervals. Currency and price units are
market-configured strings such as `EUR/MWh`; the adapter must retain those
units explicitly.

## Baseline test status

The upstream test command was also run:

```powershell
uv run --extra test pytest
```

Result: `284 passed, 24 failed, 11 errors, 4 skipped`.

The failures/errors were concentrated in optional learning paths without
PyTorch, network/redispatch and nodal-clearing paths without the corresponding
optional installation/imports, and related tests. The non-learning storage
strategy tests, storage tests, market tests, output tests, and the unchanged
storage example completed successfully. This is an upstream baseline result;
no upstream source was patched.

## Integration conclusion

The reliable ASSUME boundary is the market event/order boundary:

```text
market opening -> orderbook -> clearing message -> accepted product schedule
```

An adapter should consume accepted orders and market metadata, normalize their
time, unit, currency, and sign conventions, and pass only normalized platform
records downstream. It should not import SimSES or expose ASSUME `Order`,
`FastSeries`, `World`, or Mango message objects through the platform core.

