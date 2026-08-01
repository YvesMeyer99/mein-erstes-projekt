from app.assets import normalize_asset


def test_kraken_bitcoin_code_normalizes_to_btc():
    assert normalize_asset("XBT") == "BTC"


def test_kraken_staked_eth_code_normalizes_to_eth():
    assert normalize_asset("ETH2") == "ETH"


def test_already_canonical_symbol_passes_through_unchanged():
    assert normalize_asset("BTC") == "BTC"
    assert normalize_asset("ZEUR") == "ZEUR"


def test_normalization_is_case_insensitive():
    # Kraken's own ledger entries are uppercase (see app/adapters/kraken.py
    # and tests/test_kraken_adapter.py, which use "XBT"/"ETH2"/"ZEUR"), so
    # this isn't needed to fix the reported bug. It's kept as a defensive
    # safety net against any future adapter or manual data entry using a
    # different case, so normalization can't silently be defeated by casing.
    assert normalize_asset("xbt") == "BTC"
    assert normalize_asset("eth2") == "ETH"
    assert normalize_asset("btc") == "BTC"


def test_long_case_sensitive_identifiers_pass_through_unchanged():
    # Solana SPL-token transfers report a base58 mint address as the asset
    # when no human-readable symbol is available (see
    # app/adapters/solana.py). Base58 is case-sensitive -- uppercasing one
    # of these would silently produce an unresolvable string, unlike short
    # tickers (BTC, ETH2, ...) where uppercasing is safe and desired.
    mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    assert normalize_asset(mint) == mint
