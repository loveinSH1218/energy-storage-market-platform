"""Contract tests for the ASSUME platform-boundary adapters.

The records below are reduced, deterministic payloads copied from the official
ASSUME ``small_with_vre_and_storage`` result shape.  They are not a second
market model and do not import SimSES or ASSUME runtime objects.
"""

from datetime import UTC, datetime
from math import isfinite

import pytest

from energy_storage_market_platform.core import (
    MarketBackend,
    MarketObservation,
    StorageAssetSpec,
    StorageState,
    TradeResult,
    TradingStrategy,
)
from energy_storage_market_platform.market.adapters.assume import (
    AssumeMarketAdapter,
    AssumeTradingStrategyAdapter,
    assume_storage_config_from_asset,
)

START = datetime(2019, 1, 2, tzinfo=UTC)
END = datetime(2019, 1, 2, 1, tzinfo=UTC)
MARKET_META = [
    {
        "market_id": "EOM",
        "product_start": "2019-01-02T00:00:00+00:00",
        "product_end": "2019-01-02T01:00:00+00:00",
        "price": 14.010546666666666,
    },
    {
        "market_id": "EOM",
        "product_start": "2019-01-02T08:00:00+00:00",
        "product_end": "2019-01-02T09:00:00+00:00",
        "price": 24.098518518518514,
    },
]
ORDERS = [
    {
        "market_id": "EOM",
        "start_time": START,
        "end_time": END,
        "volume": -1000.0,
        "accepted_volume": -514.7440965749013,
        "price": 14.010546666666666,
        "accepted_price": 14.010546666666666,
    },
    {
        "market_id": "EOM",
        "start_time": datetime(2019, 1, 2, 8, tzinfo=UTC),
        "end_time": datetime(2019, 1, 2, 9, tzinfo=UTC),
        "volume": 992.0,
        "accepted_volume": 138.45431723618216,
        "price": 24.098518518518514,
        "accepted_price": 24.098518518518514,
    },
]


def _state() -> StorageState:
    return StorageState(
        timestamp=START,
        soc=0.5,
        soh=1.0,
        power_kw=0.0,
        energy_capacity_kwh=1_000_000.0,
    )


def _asset() -> StorageAssetSpec:
    return StorageAssetSpec(
        asset_id="bess-100mw-2h",
        technology="lfp",
        rated_power_kw=100_000.0,
        energy_capacity_kwh=200_000.0,
        duration_hours=2.0,
        max_charge_power_kw=100_000.0,
        max_discharge_power_kw=100_000.0,
        min_soc=0.1,
        max_soc=0.9,
        initial_soc=0.5,
        initial_temperature_c=25.0,
    )


def test_market_adapter_maps_official_market_meta() -> None:
    adapter = AssumeMarketAdapter(MARKET_META)

    assert isinstance(adapter, MarketBackend)
    observations = adapter.get_observations(START, datetime(2019, 1, 2, 9, tzinfo=UTC))

    assert len(observations) == 2
    assert all(isinstance(item, MarketObservation) for item in observations)
    assert observations[0].market_id == "EOM"
    assert observations[0].duration_seconds == pytest.approx(3600.0)
    assert observations[0].price_per_kwh == pytest.approx(0.014010546666666666)
    assert observations[0].timestamp == START


def test_strategy_adapter_maps_bid_acceptance_and_dispatch() -> None:
    observations = AssumeMarketAdapter(MARKET_META).get_observations(
        START, datetime(2019, 1, 2, 9, tzinfo=UTC)
    )
    strategy = AssumeTradingStrategyAdapter(
        ORDERS,
        market_id="EOM",
        asset_spec=_asset(),
    )

    assert isinstance(strategy, TradingStrategy)
    assert strategy.asset_spec == _asset()
    charge_request = strategy.decide(observations[0], _state())
    discharge_request = strategy.decide(observations[1], _state())
    charge_trade = strategy.trade_result_for(observations[0])

    assert charge_request.power_kw == pytest.approx(-514_744.0965749013)
    assert discharge_request.power_kw == pytest.approx(138_454.31723618216)
    assert charge_request.duration_seconds == 3600.0
    assert charge_request.market_id == "EOM"
    assert charge_request.product_id == observations[0].product_id
    assert isinstance(charge_trade, TradeResult)
    assert charge_trade is not None
    assert charge_trade.bid_quantity_kw == pytest.approx(-1_000_000.0)
    assert charge_trade.accepted_quantity_kw == pytest.approx(-514_744.0965749013)
    assert charge_trade.accepted_energy_kwh == pytest.approx(-514_744.0965749013)
    assert charge_trade.accepted_price_per_kwh == pytest.approx(0.014010546666666666)
    assert charge_trade.cash_flow < 0.0


def test_assume_receives_the_shared_static_asset_definition() -> None:
    asset = _asset()
    mapped = assume_storage_config_from_asset(asset, node="node0")
    strategy = AssumeTradingStrategyAdapter([], asset_spec=asset)

    assert mapped["rated_power"] == pytest.approx(100.0)
    assert mapped["capacity"] == pytest.approx(200.0)
    assert mapped["duration_hours"] == pytest.approx(2.0)
    assert mapped["max_power_charge"] == pytest.approx(-100.0)
    assert mapped["max_power_discharge"] == pytest.approx(100.0)
    assert mapped["initial_soc"] == pytest.approx(0.5)
    assert strategy.storage_asset_config(node="node0") == mapped


def test_clearing_message_accepted_orders_are_supported() -> None:
    observation = AssumeMarketAdapter(MARKET_META).get_observations(START, END)[0]
    strategy = AssumeTradingStrategyAdapter.from_clearing_message(
        {"market_id": "EOM", "accepted_orders": [ORDERS[0]]},
        asset_spec=_asset(),
    )

    request = strategy.decide(observation, _state())

    assert request.power_kw == pytest.approx(-514_744.0965749013)


def test_energy_semantics_are_explicit_and_convert_mwh_to_kwh() -> None:
    observation = MarketObservation(
        timestamp=START,
        duration_seconds=7200.0,
        price_per_kwh=0.02,
        currency="EUR",
        market_id="EOM",
    )
    strategy = AssumeTradingStrategyAdapter(
        [
            {
                "market_id": "EOM",
                "start_time": START,
                "end_time": END.replace(hour=2),
                "volume": -4.0,
                "accepted_volume": -2.0,
                "price": 20.0,
                "accepted_price": 20.0,
            }
        ],
        market_id="EOM",
        asset_spec=_asset(),
        volume_unit="MWh",
        volume_semantics="energy",
    )

    trade = strategy.trade_result_for(observation)

    assert trade is not None
    assert trade.bid_quantity_kw == pytest.approx(-2000.0)
    assert trade.accepted_quantity_kw == pytest.approx(-1000.0)
    assert trade.accepted_energy_kwh == pytest.approx(-2000.0)


def test_adapter_outputs_are_finite_and_do_not_leak_upstream_objects() -> None:
    observation = AssumeMarketAdapter(MARKET_META).get_observations(START, END)[0]
    trade = AssumeTradingStrategyAdapter(
        ORDERS,
        market_id="EOM",
        asset_spec=_asset(),
    ).trade_result_for(
        observation
    )

    assert trade is not None
    for value in trade.model_dump().values():
        if isinstance(value, (int, float)):
            assert isfinite(value)
        assert not type(value).__module__.startswith("assume")
