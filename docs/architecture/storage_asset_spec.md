# StorageAssetSpec

## Decision

`StorageAssetSpec` is the single platform source of truth for the static
storage asset used by an experiment. It describes what the asset is, not its
current physical state:

```text
StorageAssetSpec -> static requested asset definition
StorageState    -> current SOC, power, temperature, SOH, and capacity state
```

The specification is a frozen Pydantic model in
`energy_storage_market_platform.core`. It contains only platform units:

| Field | Unit / meaning |
| --- | --- |
| `asset_id` | stable asset identifier |
| `technology` | technology label |
| `rated_power_kw` | nominal power |
| `energy_capacity_kwh` | nominal energy capacity |
| `duration_hours` | energy-to-power duration |
| `max_charge_power_kw` | positive charging capability magnitude |
| `max_discharge_power_kw` | positive discharging capability magnitude |
| `min_soc`, `max_soc`, `initial_soc` | normalized [0, 1] |
| `initial_temperature_c` | degrees Celsius |

Static power-limit magnitudes are positive. Dispatch sign is applied only to
requests: positive means discharge/export and negative means charge/import.
No physical efficiency is stored here; SimSES remains the physical efficiency
authority. Planning-only efficiency assumptions may be added later as clearly
named fields.

## Dimension validation

`rated_power_kw` is required. At least one of `energy_capacity_kwh` and
`duration_hours` must be supplied. The missing dimension is derived:

```text
energy_capacity_kwh = rated_power_kw * duration_hours
duration_hours = energy_capacity_kwh / rated_power_kw
```

If all three are supplied, the capacity must equal power multiplied by
duration within a strict numerical tolerance. Contradictory values fail
explicitly. SOC bounds require `0 <= min_soc < max_soc <= 1`, and initial SOC
must lie inside that range. Charge/discharge power limits must be positive and
cannot exceed rated power.

## Configuration boundary

Human-facing YAML may use MW/MWh. `load_storage_asset_spec()` in
`energy_storage_market_platform.experiments` converts MW->kW and MWh->kWh once,
at the configuration boundary. Downstream platform models receive only kW,
kWh, seconds, and normalized SOC values.

Example: `configs/assets/bess_100mw_2h.yaml` defines 100 MW and two hours;
the loaded specification contains 100,000 kW and 200,000 kWh. The future
experiment selection in `configs/experiments/phase4_assume_simses.yaml` points
market, strategy, and storage selection at this same asset file.

## Backend ownership

- The ASSUME adapter maps this specification into ASSUME's MW/MWh storage
  configuration. It does not create another nominal size.
- The SimSES adapter receives this specification, passes its initial SOC,
  temperature, and SOC limits into SimSES, and uses it to size an optional
  converter boundary.
- SimSES's selected cell circuit may realize a different discrete capacity.
  `SimSESAssetRealization` reports requested versus realized power/capacity and
  sizing errors; it never silently overwrites the specification.
- Strategies receive the same immutable specification through their
  `asset_spec` boundary and must use it for capability-aware decisions.

The specification is not a replacement for `StorageState`. SimSES remains the
source of truth for dynamic SOC, actual power, losses, thermal state, limits,
and aging once it is executed. ASSUME remains the source of truth for market
clearing and settlement.
