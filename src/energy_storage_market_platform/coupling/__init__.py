"""Simulation orchestration between markets, strategies, and storage.

The coupling layer will coordinate market steps, strategy decisions, storage
execution, sub-stepping, accounting, and state transitions through interfaces.
"""

from .engine import run_simulation

__all__ = ["run_simulation"]