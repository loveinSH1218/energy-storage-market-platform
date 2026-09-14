# AGENTS.md

## 1. Project Mission

This repository is a modular research platform for coupling:

- electricity-market models,
- electricity-trading strategies,
- battery and energy-storage models,
- optimization algorithms,
- and physical storage simulation.

The primary goals of this project are:

1. modularity,
2. replaceability,
3. reproducibility,
4. physical correctness,
5. testability,
6. extensibility,
7. research transparency.

The platform must allow different electricity-market models, trading strategies,
and storage models to be exchanged independently without requiring major changes
to the rest of the codebase.

The long-term architecture should support combinations such as:

- Market A + MILP strategy + ideal battery,
- Market A + MILP strategy + SimSES,
- Market B + rule-based strategy + SimSES,
- Market B + reinforcement-learning strategy + PyBaMM,
- historical market data + real battery hardware adapter.

Do not design the repository around one specific external open-source project.

External repositories are integrations, not the architecture of this project.


## 2. Core Architectural Principle

The project must maintain strict separation between:

1. Market layer
2. Trading-strategy layer
3. Storage layer
4. Coupling/simulation layer
5. Core interfaces and shared data types
6. Data IO
7. Experiment configuration
8. Analysis and visualization

The intended dependency direction is:

Market Backend
    ↓
MarketObservation
    ↓
TradingStrategy
    ↓
DispatchRequest
    ↓
Coupling Engine
    ↓
StorageBackend
    ↓
StorageStepResult

Concrete market implementations and concrete storage implementations must never
depend directly on each other.


## 3. Required Package Structure

The preferred project structure is:

```text
src/
└── energy_platform/
    ├── core/
    ├── market/
    ├── strategy/
    ├── storage/
    ├── coupling/
    ├── experiments/
    └── io/

configs/
├── markets/
├── strategies/
├── storage/
└── experiments/

tests/
├── unit/
├── contract/
├── integration/
└── regression/

docs/
├── architecture/
├── integrations/
└── validation/

external/
scripts/
results/
```

Do not create new top-level folders unless there is a clear architectural reason.


## 4. Core Interfaces

All concrete implementations must communicate through stable interfaces defined
inside:

```text
src/energy_platform/core/
```

The core layer must not import any concrete implementation.

The minimum long-term interfaces are:

- `MarketBackend`
- `TradingStrategy`
- `StorageBackend`

The minimum shared data models should include:

- `MarketObservation`
- `StorageState`
- `DispatchRequest`
- `StorageStepResult`
- `TradeResult`

Additional shared structures may be introduced when justified, but upstream
repository-specific objects must never leak into the core interfaces.


## 5. Market Layer Rules

Market code belongs under:

```text
src/energy_platform/market/
```

The market layer is responsible for concepts such as:

- electricity prices,
- market products,
- market timelines,
- bidding windows,
- settlement periods,
- market availability,
- historical market data,
- market-specific constraints.

Market implementations must not contain battery physics.

Market implementations must not import:

- SimSES,
- PyBaMM,
- concrete battery implementations,
- concrete storage adapters.

Every external market repository must be integrated through an adapter.

Example:

```text
External Market Repository
        ↓
MarketAAdapter
        ↓
MarketBackend
```

Do not modify the platform architecture to match one external market repository.


## 6. Trading Strategy Rules

Trading strategies belong under:

```text
src/energy_platform/strategy/
```

Trading strategies may include:

- rule-based strategies,
- arbitrage algorithms,
- linear programming,
- mixed-integer linear programming,
- model predictive control,
- reinforcement learning,
- heuristic optimization.

A trading strategy should consume standard platform data such as:

- `MarketObservation`
- `StorageState`

and return a standard command such as:

- `DispatchRequest`

Trading strategies must not directly control concrete battery objects.

Forbidden pattern:

```python
strategy.sim_ses_battery.charge(...)
```

Preferred pattern:

```python
request = strategy.decide(market_observation, storage_state)
```

The coupling engine is responsible for executing that request.


## 7. Storage Layer Rules

Storage code belongs under:

```text
src/energy_platform/storage/
```

Every storage implementation must implement the common storage interface.

Possible storage backends include:

- ideal battery model,
- simple equivalent battery model,
- legacy battery model,
- SimSES,
- PyBaMM,
- future proprietary battery model,
- real laboratory battery hardware.

The market layer must not know which storage backend is being used.

Example:

```text
StorageBackend
├── IdealStorageAdapter
├── LegacyBatteryAdapter
├── SimSESAdapter
├── PyBaMMAdapter
└── RealBatteryAdapter
```


## 8. Coupling Layer Rules

The coupling layer belongs under:

```text
src/energy_platform/coupling/
```

This layer is responsible for connecting:

- market time steps,
- trading decisions,
- storage power requests,
- storage physical constraints,
- internal simulation time steps,
- accounting,
- simulation state transitions.

The coupling engine must depend on interfaces, not concrete implementations.

Preferred:

```python
def run_simulation(
    market: MarketBackend,
    strategy: TradingStrategy,
    storage: StorageBackend,
):
    ...
```

Avoid:

```python
if storage_type == "simses":
    ...
elif storage_type == "pybamm":
    ...
```

Prefer polymorphism and adapters.


## 9. Standard Internal Units

All platform-level interfaces must use one consistent internal unit system.

Unless explicitly changed in the future, use:

- Power: `kW`
- Energy: `kWh`
- Time duration: `seconds`
- SOC: normalized `[0, 1]`
- SOH: normalized `[0, 1]`
- Temperature: `°C`
- Efficiency: normalized `[0, 1]`
- Monetary values: explicitly specify currency

Default power sign convention:

```text
Positive power = storage discharging / exporting power to the grid

Negative power = storage charging / importing power from the grid
```

This convention must be documented and tested.

If an external project uses another sign convention, unit system, or definition,
the conversion must occur inside that project's adapter.

Do not spread external unit conversions across the platform.


## 10. Time Resolution and Sub-Stepping

Market models and physical storage models may use different time resolutions.

Examples:

```text
Market:
15 min
30 min
60 min

Storage model:
1 s
10 s
60 s
```

The coupling layer must support sub-stepping when required.

Do not assume that:

```text
market timestep == battery timestep
```

Time conversion logic must be explicit and tested.


## 11. External Repository Policy

Third-party repositories should normally live under:

```text
external/
```

Treat third-party repositories as read-only unless explicitly instructed
otherwise.

Do not casually copy source files from external repositories into the platform.

For every external repository integration, record:

- repository name,
- repository URL,
- exact release/tag/commit,
- license,
- Python version,
- installation procedure,
- required dependencies,
- original execution entry point,
- original test status,
- baseline example used,
- known limitations.

Documentation should be placed under:

```text
docs/integrations/
```

Before publishing code derived from an external repository, verify its license
and attribution requirements.


## 12. External Environment Compatibility

Do not assume all external repositories can run in the same Python environment.

For example:

```text
Repository A → Python 3.9
Repository B → Python 3.11
SimSES       → Python 3.12
```

The architecture should allow future integrations through:

- in-process Python adapters,
- subprocess workers,
- JSON serialization,
- separate virtual environments,
- Docker containers,
- APIs.

Core data structures should therefore remain simple and serializable whenever
reasonable.


## 13. Baseline-First Rule

Never begin major refactoring of an external or legacy repository before its
original behavior has been reproduced.

Required workflow:

1. Read the original documentation.
2. Identify the intended entry point.
3. Install dependencies.
4. Run the original example.
5. Run original tests.
6. Record failures.
7. Save baseline outputs.
8. Create regression or characterization tests.
9. Only then begin refactoring or integration.

The baseline should include relevant numerical outputs such as:

- market revenue,
- power trajectory,
- SOC trajectory,
- energy throughput,
- losses,
- temperature,
- SOH,
- degradation,
- constraint violations.

Never mix baseline reproduction and architecture refactoring into one large
unverified change.


## 14. Refactoring Rules

During structural refactoring:

- preserve numerical behavior unless explicitly instructed otherwise,
- avoid changing physics and architecture simultaneously,
- prefer small isolated changes,
- introduce tests before changing legacy behavior,
- document intentional numerical changes.

Before changing legacy behavior, determine whether the change is:

1. architecture-only,
2. bug fix,
3. physical-model change,
4. numerical-method change,
5. feature addition.

Do not silently combine these categories.


## 15. Adapter Integration Workflow

Every new external backend should follow this sequence:

### Phase 1 — Repository Audit

Understand:

- project structure,
- entry points,
- dependencies,
- configuration system,
- test system,
- architecture,
- input/output formats.

### Phase 2 — Baseline Reproduction

Run the upstream implementation unchanged.

Record reproducible results.

### Phase 3 — Interface Mapping

Map external concepts to platform concepts.

For example:

```text
External battery SOC
        ↓
StorageState.soc
```

### Phase 4 — Adapter Implementation

Create the smallest adapter necessary.

Do not rewrite upstream code unless required.

### Phase 5 — Contract Tests

Verify that the adapter satisfies the platform interface.

### Phase 6 — Integration Tests

Run the adapter through the full coupling engine.

### Phase 7 — Regression Tests

Compare results against the upstream baseline.

### Phase 8 — Documentation

Document assumptions, unit conversions, limitations, and configuration.


## 16. Dummy Reference Implementations

The platform should maintain simple reference implementations.

At minimum:

- DummyMarket
- SimpleTradingStrategy
- IdealStorage

These reference implementations should have analytically understandable behavior.

They are used to verify the coupling architecture independently from complex
external repositories.

Do not remove them after real backends are integrated.


## 17. Testing Philosophy

A program running without an exception does not mean the implementation is
correct.

Testing should cover four levels.

### Unit Tests

Test isolated functions and classes.

Location:

```text
tests/unit/
```

### Contract Tests

Verify that all adapters satisfy common interfaces.

Location:

```text
tests/contract/
```

### Integration Tests

Verify combinations such as:

```text
Market
+
Strategy
+
Storage
+
Coupling Engine
```

Location:

```text
tests/integration/
```

### Regression Tests

Compare refactored/integrated results against known baseline outputs.

Location:

```text
tests/regression/
```


## 18. Required Physical Validation Cases

Storage integrations should eventually include deterministic validation cases.

Examples:

### Case 1 — Constant charging

Known initial SOC, constant charging power, known duration.

Verify final SOC.

### Case 2 — Constant discharging

Known initial SOC, constant discharge power, known duration.

Verify final SOC.

### Case 3 — SOC upper limit

Request charging beyond maximum SOC.

Verify power clipping and constraint handling.

### Case 4 — SOC lower limit

Request discharging beyond minimum SOC.

Verify power clipping and constraint handling.

### Case 5 — Power limit

Request power greater than rated power.

Verify clipping.

### Case 6 — Round-trip efficiency

Charge and discharge known energy.

Verify energy losses.

### Case 7 — Market arbitrage

Use a simple known price profile and verify expected trading behavior.


## 19. Configuration-Driven Experiments

Experiments should eventually be configurable without editing source code.

Preferred example:

```yaml
market:
  backend: market_a

strategy:
  backend: arbitrage_milp

storage:
  backend: simses

simulation:
  start: 2026-01-01
  duration_days: 7
```

Changing market or storage implementations should generally require changing
configuration, not rewriting source code.


## 20. Data and Results

Raw input data should not be silently modified.

Generated results should normally go under:

```text
results/
```

Large generated result files should not be committed to Git unless explicitly
required.

Every important experiment should record enough information to reproduce it,
including:

- configuration,
- software version,
- external repository version,
- random seed when relevant,
- data version,
- timestamp,
- model parameters.


## 21. Numerical Reproducibility

When using stochastic algorithms:

- expose random seeds,
- record random seeds,
- avoid hidden randomness where possible.

When changing optimization or simulation behavior, compare before/after results.

Do not describe results as equivalent without quantitative evidence.


## 22. Coding Standards

Prefer:

- clear type annotations,
- small focused modules,
- explicit interfaces,
- dataclasses or validated data models where appropriate,
- descriptive variable names,
- limited hidden global state.

Avoid:

- very large scripts,
- duplicated business logic,
- duplicated unit conversions,
- hard-coded paths,
- hidden constants,
- mutable global state,
- circular imports.

Research code should still follow maintainable software-engineering practices.


## 23. Dependency Rules

Before introducing a new dependency:

1. determine whether the functionality already exists in the repository,
2. determine whether the dependency is actively maintained,
3. consider its license,
4. avoid unnecessary heavy dependencies.

Do not add packages merely for convenience if a simple implementation is
sufficient.


## 24. Testing Commands

When available, use:

```powershell
uv run pytest
uv run pytest --cov
uv run ruff check .
uv run mypy src
```

If the project configuration changes, update this section accordingly.

Before claiming a substantial task is complete, run the relevant available
tests.


## 25. Git Workflow

Do not directly perform substantial experimental development on `main`.

Prefer branches such as:

```text
feat/...
refactor/...
fix/...
integration/...
docs/...
```

Examples:

```text
integration/simses
integration/market-a
refactor/storage-interface
feat/milp-strategy
```

Prefer small, meaningful commits.

Example commit messages:

```text
feat: add storage backend interface
test: add ideal battery contract tests
refactor: separate market and storage logic
integration: add SimSES adapter
docs: document market A integration
fix: correct storage power sign conversion
```


## 26. Git Safety Rules

Never:

- commit API keys,
- commit passwords,
- commit access tokens,
- commit private credentials,
- commit large generated output unintentionally,
- force-push without explicit instruction,
- rewrite shared Git history without explicit instruction.

Before commits, inspect the changed files.


## 27. Documentation Requirements

Architecture decisions must be documented.

Important documentation should include:

```text
docs/architecture/
docs/integrations/
docs/validation/
```

For every backend integration explain:

- what the external project does,
- why it is integrated,
- how it maps to platform interfaces,
- unit/sign conversions,
- limitations,
- test results,
- upstream version.


## 28. Research Integrity

Never fabricate:

- simulation results,
- test results,
- external repository behavior,
- benchmark results,
- performance improvements.

If an experiment has not been run, state that clearly.

If a test fails, report it.

Do not hide warnings or unresolved numerical discrepancies.


## 29. Codex Working Procedure

Before making significant changes:

1. Read this `AGENTS.md`.
2. Inspect relevant files.
3. Understand the current architecture.
4. Identify the smallest reasonable change.
5. Check existing tests.
6. Modify code.
7. Add or update tests.
8. Run relevant tests.
9. Inspect the diff.
10. Report results.

Do not begin with large-scale rewriting unless explicitly requested.


## 30. Codex Completion Report

At the end of every substantial task, report:

### Files changed

List important created, modified, and deleted files.

### Architecture impact

Explain whether interfaces or dependencies changed.

### Tests executed

List the exact relevant commands executed.

### Test results

State which tests passed or failed.

### Numerical impact

State whether numerical behavior changed.

If numerical behavior changed, quantify it where possible.

### Remaining risks

List unresolved issues, assumptions, or technical debt.

### Recommended next step

Suggest the next logical development action.


## 31. Current Project Priority

Until the platform core is stable, prioritize work in this order:

1. repository skeleton,
2. stable core interfaces,
3. dummy/reference implementations,
4. coupling engine,
5. unit and contract tests,
6. first market integration,
7. first storage integration,
8. cross-backend validation,
9. experiment configuration,
10. advanced optimization and research models.

Do not prematurely optimize the architecture for a specific external repository.


## 32. Final Architectural Principle

The long-term success criterion is:

```text
New market model
        ↓
implement MarketBackend
        ↓
works with existing strategies and storage models
```

and:

```text
New storage model
        ↓
implement StorageBackend
        ↓
works with existing market models and strategies
```

and:

```text
New trading strategy
        ↓
implement TradingStrategy
        ↓
works with existing markets and storage models
```

If adding one backend requires extensive modifications to unrelated parts of the
platform, treat that as an architectural problem and investigate before
continuing.