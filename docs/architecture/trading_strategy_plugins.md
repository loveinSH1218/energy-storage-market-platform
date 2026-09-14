# Trading strategy plug-ins

## Stable boundary

The platform keeps one replaceable `TradingStrategy` protocol:

```python
decide(MarketObservation, StorageState) -> DispatchRequest
```

Each strategy also exposes the immutable platform `StorageAssetSpec` it was
constructed with. The asset is capability information, not mutable storage
state. A strategy never imports SimSES and never manipulates an ASSUME storage
object. Forecast information, when available, is carried as an optional
platform price forecast on `MarketObservation`.

The current reference strategy remains usable with an explicit `power_kw` for
backward compatibility. Registry-created strategies receive the shared asset
and default their request magnitude from its rated power.

## Registry

`energy_storage_market_platform.strategy.registry` provides a deliberately
small registry:

- `register_strategy(name, factory)` adds a backend;
- `create_strategy(name, asset_spec, **kwargs)` constructs it with the shared
  asset;
- `available_strategies()` lists configured names.

The built-in names are `simple` and `assume_native`. The latter constructs the
thin ASSUME cleared-order adapter and still requires ASSUME order payloads;
it does not reimplement ASSUME bidding. MILP, MPC, and RL implementations can
register factories under their own names without changing `CouplingEngine`.

Configuration can therefore select a backend by name:

```yaml
strategy:
  backend: assume_native
```

## Bid versus dispatch

`BidRequest` is intentionally not introduced in this hardening phase. The
existing `TradingStrategy -> DispatchRequest` boundary is stable and avoids a
speculative rewrite of `CouplingEngine`. The Phase 3 ASSUME adapter consumes
already-cleared orders and maps them to `TradeResult` and `DispatchRequest`.

The planned migration for live market participation is:

```text
MarketObservation
    -> TradingStrategy
    -> BidRequest
    -> MarketBackend / clearing
    -> TradeResult
    -> DispatchRequest
    -> CouplingEngine
```

That distinction should be added when a platform-owned bidding flow is
implemented. It must remain an additive market/settlement boundary and must
not change the storage interface or make strategies backend-specific.
