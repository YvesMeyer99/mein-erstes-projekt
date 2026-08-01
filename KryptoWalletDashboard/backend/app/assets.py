"""Canonical asset-symbol normalization.

Different data sources use different codes for the same underlying asset:
Kraken's Ledgers API reports Bitcoin as ``XBT`` and staked Ethereum rewards
as ``ETH2``, while the on-chain Bitcoin/Ethereum adapters use ``BTC``/``ETH``.
Left un-normalized, this causes the exact same asset to appear as two
separate portfolio lines depending on which source produced a given
transaction -- a real bug for a tool whose purpose is showing correct total
holdings per asset for a Swiss tax declaration.

This is the single source of truth for that mapping. `app.sync` applies
`normalize_asset()` when persisting a `Transaction`, so every other
consumer of `Transaction.asset`/`counter_asset`/`fee_asset` (portfolio
computation, CSV export, ...) can assume the value is already canonical.
"""

CANONICAL_ASSET_MAP = {"XBT": "BTC", "ETH2": "ETH"}

# Ticker symbols (BTC, XBT, ETH2, ZEUR, ...) are short and conventionally
# case-insensitive, so they're safe to uppercase for consistent portfolio
# grouping. Some adapters (e.g. Solana's SPL-token support) instead report
# an opaque, case-SENSITIVE identifier as the "asset" when no human-readable
# symbol is available (a base58 mint address, always well over this length) --
# uppercasing one of those would silently corrupt it into an unresolvable
# string. Anything longer than a real-world ticker is passed through
# untouched instead of being forced through the uppercase/canonical-map path.
_MAX_TICKER_LENGTH = 16


def normalize_asset(symbol: str) -> str:
    if len(symbol) > _MAX_TICKER_LENGTH:
        return symbol
    return CANONICAL_ASSET_MAP.get(symbol.upper(), symbol.upper())
