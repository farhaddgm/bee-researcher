"""Bee CFO phase-one market analyst bounded context.

The package owns the product contract and persistence-facing orchestration.
Fetching and article extraction are consumed through an explicit adapter so
the context can be moved to its own service later without changing its data
contract.
"""

PRODUCT = "bee_cfo"
PHASE = "market_analyst"
CONTRACT_REVISION = "bee-cfo-1"

__all__ = ["CONTRACT_REVISION", "PHASE", "PRODUCT"]
