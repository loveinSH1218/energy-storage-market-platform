"""Thin adapters for result payloads produced by the ASSUME framework.

The adapters intentionally operate on plain mappings.  ASSUME's live boundary
is an asynchronous Mango message boundary; keeping that boundary serialized
means no ASSUME object can leak into the platform core and the upstream
repository remains an untouched, separately runnable dependency.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from math import isfinite
from typing import Any, Literal

from energy_storage_market_platform.core import (
    DispatchRequest,
    MarketObservation,
    StorageAssetSpec,
    StorageState,
    TradeResult,
)

VolumeSemantics = Literal["power", "energy"]


def assume_storage_config_from_asset(
    asset_spec: StorageAssetSpec,
    *,
    node: str | None = None,
) -> dict[str, float | str | None]:
    """Map the platform asset into ASSUME storage configuration units.

    ASSUME uses positive discharge power and negative charge power.  The
    returned mapping is intentionally plain data; ASSUME's ``Storage`` class
    remains responsible for interpreting and enforcing it.
    """

    return {
        "id": asset_spec.asset_id,
        "technology": asset_spec.technology,
        "rated_power": asset_spec.rated_power_kw / 1000.0,
        "capacity": asset_spec.energy_capacity_kwh / 1000.0,
        "duration_hours": asset_spec.duration_hours,
        "max_power_charge": -asset_spec.max_charge_power_kw / 1000.0,
        "max_power_discharge": asset_spec.max_discharge_power_kw / 1000.0,
        "min_soc": asset_spec.min_soc,
        "max_soc": asset_spec.max_soc,
        "initial_soc": asset_spec.initial_soc,
        "node": node,
    }


def _unwrap_records(payload: Any, key: str) -> tuple[Mapping[str, Any], ...]:
    """Extract mapping records from an ASSUME-shaped message or sequence."""

    if isinstance(payload, Mapping):
        if key in payload:
            payload = payload[key]
        elif "data" in payload and isinstance(payload["data"], (list, tuple)):
            payload = payload["data"]
        else:
            payload = [payload]
    if isinstance(payload, (str, bytes)):
        raise TypeError("ASSUME records must be mappings, not text")
    records = tuple(payload)
    if not all(isinstance(record, Mapping) for record in records):
        raise TypeError("ASSUME records must contain mapping values")
    return records


def _as_datetime(value: Any) -> datetime:
    """Convert ASSUME datetime values using ASSUME's UTC timestamp semantics."""

    if isinstance(value, datetime):
        return value
    if hasattr(value, "to_pydatetime"):
        converted = value.to_pydatetime()
        if isinstance(converted, datetime):
            return converted
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=UTC).replace(tzinfo=None)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    raise TypeError(f"Unsupported ASSUME timestamp value: {value!r}")


def _comparison_datetime(value: datetime) -> datetime:
    """Use a common UTC-naive basis only for filtering mixed input timestamps."""

    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _number(value: Any, *, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"ASSUME {field} must be numeric: {value!r}") from error
    if not isfinite(number):
        raise ValueError(f"ASSUME {field} must be finite: {value!r}")
    return number


def _interval_value(value: Any, start: datetime) -> Any:
    """Select a product value from ASSUME's scalar or datetime-keyed fields."""

    if not isinstance(value, Mapping):
        return value
    if start in value:
        return value[start]
    for key, item in value.items():
        try:
            if _as_datetime(key) == start:
                return item
        except (TypeError, ValueError):
            continue
    raise KeyError(f"No ASSUME interval value found for {start!r}")


def _product_times(record: Mapping[str, Any]) -> tuple[datetime, datetime]:
    start_value = record.get("product_start", record.get("start_time"))
    end_value = record.get("product_end", record.get("end_time"))
    if start_value is None or end_value is None:
        raise KeyError("ASSUME record requires start and end timestamps")
    start = _as_datetime(start_value)
    end = _as_datetime(end_value)
    if end <= start:
        raise ValueError(f"ASSUME interval must have positive duration: {start!r}, {end!r}")
    return start, end


def _product_id(record: Mapping[str, Any], start: datetime, end: datetime, market_id: str | None) -> str:
    explicit = record.get("product_id")
    if explicit is not None:
        return str(explicit)
    return f"{market_id or 'market'}:{start.isoformat()}:{end.isoformat()}"


def _price_to_kwh(value: Any, price_unit: str) -> float:
    price = _number(value, field="price")
    normalized = price_unit.replace("€", "EUR").replace(" ", "").upper()
    if normalized.endswith("/MWH"):
        return price / 1000.0
    if normalized.endswith("/KWH"):
        return price
    raise ValueError(
        "ASSUME price_unit must be an energy price in EUR/MWh-like or EUR/kWh-like form"
    )


def _quantity_to_platform(
    value: Any,
    *,
    volume_unit: str,
    volume_semantics: VolumeSemantics,
    duration_seconds: float,
) -> tuple[float, float]:
    """Return signed platform power kW and interval energy kWh."""

    quantity = _number(value, field="volume")
    unit = volume_unit.replace(" ", "").upper()
    duration_hours = duration_seconds / 3600.0
    if volume_semantics == "power":
        if unit == "MW":
            power_kw = quantity * 1000.0
        elif unit == "KW":
            power_kw = quantity
        else:
            raise ValueError("power-semantics ASSUME volume_unit must be MW or kW")
        return power_kw, power_kw * duration_hours
    if volume_semantics == "energy":
        if unit == "MWH":
            energy_kwh = quantity * 1000.0
        elif unit == "KWH":
            energy_kwh = quantity
        else:
            raise ValueError("energy-semantics ASSUME volume_unit must be MWh or kWh")
        return energy_kwh / duration_hours, energy_kwh
    raise ValueError(f"Unsupported ASSUME volume semantics: {volume_semantics!r}")


def _record_matches(
    record: Mapping[str, Any],
    observation: MarketObservation,
    *,
    market_id: str | None,
) -> bool:
    record_market = record.get("market_id", market_id)
    if market_id is not None and record_market is not None and str(record_market) != market_id:
        return False
    start, end = _product_times(record)
    if observation.product_id is not None:
        return observation.product_id == _product_id(record, start, end, record_market)
    return (
        _comparison_datetime(start) == _comparison_datetime(observation.timestamp)
        and _comparison_datetime(end)
        == _comparison_datetime(
            observation.timestamp
            + timedelta(seconds=observation.duration_seconds)
        )
    )


class AssumeMarketAdapter:
    """Expose ASSUME ``market_meta`` rows as :class:`MarketBackend` data."""

    def __init__(
        self,
        market_meta: Iterable[Mapping[str, Any]] | Mapping[str, Any],
        *,
        market_id: str | None = None,
        price_unit: str = "EUR/MWh",
        currency: str = "EUR",
    ) -> None:
        self._market_meta = _unwrap_records(market_meta, "market_meta")
        self._market_id = market_id
        self._price_unit = price_unit
        self._currency = currency

    def get_observations(self, start: datetime, end: datetime) -> Sequence[MarketObservation]:
        """Return normalized observations in the platform half-open interval."""

        start_cmp = _comparison_datetime(start)
        end_cmp = _comparison_datetime(end)
        observations: list[MarketObservation] = []
        for record in self._market_meta:
            product_start, product_end = _product_times(record)
            if not start_cmp <= _comparison_datetime(product_start) < end_cmp:
                continue
            market_id = record.get("market_id", self._market_id)
            market_text = str(market_id) if market_id is not None else None
            observations.append(
                MarketObservation(
                    timestamp=product_start,
                    duration_seconds=(product_end - product_start).total_seconds(),
                    price_per_kwh=_price_to_kwh(record.get("price"), self._price_unit),
                    currency=self._currency,
                    market_id=market_text,
                    product_id=_product_id(record, product_start, product_end, market_text),
                )
            )
        return tuple(observations)


class AssumeTradingStrategyAdapter:
    """Adapt ASSUME bid/clearing records into platform decisions and trades.

    The records are the plain payloads emitted by ASSUME's ``submit_bids`` and
    ``ClearingMessage.accepted_orders`` boundaries.  ASSUME continues to own
    bid construction and market clearing; this class only maps their results.
    """

    def __init__(
        self,
        orders: Iterable[Mapping[str, Any]] | Mapping[str, Any],
        *,
        accepted_orders: Iterable[Mapping[str, Any]] | Mapping[str, Any] | None = None,
        market_id: str | None = None,
        asset_spec: StorageAssetSpec,
        volume_unit: str = "MW",
        volume_semantics: VolumeSemantics = "power",
        price_unit: str = "EUR/MWh",
        currency: str = "EUR",
    ) -> None:
        self._orders = _unwrap_records(orders, "orderbook")
        self._accepted_orders = (
            _unwrap_records(accepted_orders, "accepted_orders")
            if accepted_orders is not None
            else self._orders
        )
        self._market_id = market_id
        self.asset_spec = asset_spec
        self._volume_unit = volume_unit
        self._volume_semantics = volume_semantics
        self._price_unit = price_unit
        self._currency = currency

    @classmethod
    def from_clearing_message(
        cls,
        message: Mapping[str, Any],
        **kwargs: Any,
    ) -> AssumeTradingStrategyAdapter:
        """Construct an adapter from an ASSUME ``ClearingMessage`` payload."""

        return cls(
            message.get("accepted_orders", ()),
            accepted_orders=message.get("accepted_orders", ()),
            market_id=message.get("market_id"),
            **kwargs,
        )

    def storage_asset_config(self, *, node: str | None = None) -> dict[str, float | str | None]:
        """Return the configured asset in ASSUME's MW/MWh storage units."""

        return assume_storage_config_from_asset(self.asset_spec, node=node)

    def _find_order(
        self,
        observation: MarketObservation,
        *,
        accepted: bool,
    ) -> Mapping[str, Any] | None:
        records = self._accepted_orders if accepted else self._orders
        for record in records:
            if _record_matches(record, observation, market_id=self._market_id):
                return record
        return None

    def trade_result_for(self, observation: MarketObservation) -> TradeResult | None:
        """Map one ASSUME order and its acceptance into a platform trade result."""

        order = self._find_order(observation, accepted=False)
        if order is None:
            return None
        accepted_order = self._find_order(observation, accepted=True)
        start = observation.timestamp
        duration_seconds = observation.duration_seconds
        bid_value = _interval_value(order.get("volume", 0.0), start)
        accepted_value = _interval_value(
            (accepted_order or order).get("accepted_volume", 0.0), start
        )
        bid_power, _ = _quantity_to_platform(
            bid_value,
            volume_unit=self._volume_unit,
            volume_semantics=self._volume_semantics,
            duration_seconds=duration_seconds,
        )
        accepted_power, accepted_energy = _quantity_to_platform(
            accepted_value,
            volume_unit=self._volume_unit,
            volume_semantics=self._volume_semantics,
            duration_seconds=duration_seconds,
        )
        bid_price = (
            _price_to_kwh(_interval_value(order.get("price", 0.0), start), self._price_unit)
            if order.get("price") is not None
            else None
        )
        accepted_price = (
            _price_to_kwh(
                _interval_value((accepted_order or order).get("accepted_price"), start),
                self._price_unit,
            )
            if (accepted_order or order).get("accepted_price") is not None
            else None
        )
        settlement_price = accepted_price if accepted_price is not None else (bid_price or 0.0)
        market_id = str(order.get("market_id", self._market_id)) if order.get("market_id", self._market_id) is not None else None
        product_id = _product_id(
            order,
            start,
            start + timedelta(seconds=duration_seconds),
            market_id,
        )
        return TradeResult(
            timestamp=start,
            duration_seconds=duration_seconds,
            energy_kwh=accepted_energy,
            price_per_kwh=settlement_price,
            currency=self._currency,
            cash_flow=accepted_energy * settlement_price,
            bid_price_per_kwh=bid_price,
            accepted_price_per_kwh=accepted_price,
            bid_quantity_kw=bid_power,
            accepted_quantity_kw=accepted_power,
            accepted_energy_kwh=accepted_energy,
            market_id=market_id,
            product_id=product_id,
        )

    def decide(
        self,
        market_observation: MarketObservation,
        storage_state: StorageState,
    ) -> DispatchRequest:
        """Return accepted ASSUME dispatch as a platform request."""

        del storage_state
        trade = self.trade_result_for(market_observation)
        return DispatchRequest(
            timestamp=market_observation.timestamp,
            duration_seconds=market_observation.duration_seconds,
            power_kw=(
                trade.accepted_quantity_kw
                if trade is not None and trade.accepted_quantity_kw is not None
                else 0.0
            ),
            market_id=market_observation.market_id,
            product_id=market_observation.product_id,
        )
