"""Public strategy-layer import for the ASSUME orderbook adapter.

The implementation lives beside the market payload adapter because ASSUME's
bid and clearing records cross one upstream message boundary.  This re-export
keeps the platform's strategy import path stable without introducing a second
conversion implementation.
"""

from energy_storage_market_platform.market.adapters.assume import (
    AssumeTradingStrategyAdapter,
)

__all__ = ["AssumeTradingStrategyAdapter"]
