"""Electricity-market backends and market-domain concepts.

This layer owns prices, products, timelines, bidding windows, settlement, and
market availability. It must communicate with storage through core contracts,
not through concrete battery implementations.
"""