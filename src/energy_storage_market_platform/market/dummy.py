"""Minimal deterministic market backend for architecture tests."""

from collections.abc import Sequence
from datetime import datetime

from energy_storage_market_platform.core import MarketObservation


class DummyMarket:
    """Return a fixed sequence of normalized market observations."""

    def __init__(self, observations: Sequence[MarketObservation]) -> None:
        self._observations = tuple(observations)

    def get_observations(
        self,
        start: datetime,
        end: datetime,
    ) -> Sequence[MarketObservation]:
        """Return configured observations whose starts fall in ``[start, end)``."""
        return tuple(
            observation
            for observation in self._observations
            if start <= observation.timestamp < end
        )