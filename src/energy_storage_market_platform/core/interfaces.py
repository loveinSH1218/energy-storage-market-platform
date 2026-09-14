"""Implementation-independent contracts between platform layers."""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from .models import (
    DispatchRequest,
    MarketObservation,
    StorageState,
    StorageStepResult,
)


@runtime_checkable
class MarketBackend(Protocol):
    """Provider of normalized market observations."""

    def get_observations(
        self,
        start: datetime,
        end: datetime,
    ) -> Sequence[MarketObservation]:
        """Return observations in the half-open interval ``[start, end)``."""


@runtime_checkable
class TradingStrategy(Protocol):
    """Decision maker that never controls a concrete storage implementation."""

    def decide(
        self,
        market_observation: MarketObservation,
        storage_state: StorageState,
    ) -> DispatchRequest:
        """Create a normalized dispatch request for one market observation."""


@runtime_checkable
class StorageBackend(Protocol):
    """Executor of normalized dispatch requests."""

    def current_state(self) -> StorageState:
        """Return the latest observable storage state."""

    def step(self, request: DispatchRequest) -> StorageStepResult:
        """Apply one request and return the resulting state transition."""