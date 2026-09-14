# Energy Storage Market Platform

An extensible research platform for coupling electricity markets, trading
strategies, and energy-storage models. The project is structured so that a
market backend, strategy, or storage backend can be replaced independently.

## Architecture

The intended dependency direction is:

```text
Market Backend
	|
MarketObservation
	|
TradingStrategy
	|
DispatchRequest
	|
Coupling Engine
	|
StorageBackend
	|
StorageStepResult
```

The Python package lives under `src/energy_storage_market_platform/`:

- `core/` contains stable interfaces and shared data models. It must not import
  concrete implementations.
- `market/` contains electricity-market concepts and backend adapters.
- `strategy/` contains trading decisions that return standard dispatch requests.
- `storage/` contains storage backends and adapters.
- `coupling/` coordinates market steps, strategy decisions, storage execution,
  sub-stepping, and accounting.
- `experiments/` contains reproducible, configuration-driven experiments.
- `io/` contains data loading, serialization, and output boundaries.

Concrete market and storage implementations must not depend directly on each
other. External repositories will be integrated later through adapters and
must remain outside the platform's core architecture.

## Core contracts

The core package currently defines typed, JSON-serializable models for
`MarketObservation`, `StorageState`, `DispatchRequest`, `StorageStepResult`,
and `TradeResult`. The implementation-independent protocols are
`MarketBackend`, `TradingStrategy`, and `StorageBackend`.

The reference implementations are intentionally small and deterministic:
`DummyMarket`, `SimpleTradingStrategy`, and `IdealStorage`. They are used to
validate the architecture before any external repository is integrated.

## Internal conventions

Platform interfaces use kW for power, kWh for energy, seconds for durations,
normalized values in `[0, 1]` for SOC and SOH, and degrees Celsius for
temperature. Positive power means discharging to the grid; negative power means
charging from the grid.

Market and storage time steps may differ. Sub-stepping belongs in the coupling
layer and must be explicit.

## Development

Run the test suite and static checks with:

```powershell
uv run pytest
uv run ruff check .
uv run mypy src
```

The current reference implementations are not production market or battery
models. Advanced market behavior, optimization strategies, physical storage
models, external integrations, and additional validation will be added
incrementally with unit, contract, integration, and regression tests.
