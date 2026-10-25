import pytest

from fxbot.mt5_client import resolve_symbol_in


def test_resolve_symbol_raises_clear_error_when_absent():
    with pytest.raises(ValueError, match="XAUUSD"):
        resolve_symbol_in(["EURUSD", "GBPUSD"], "XAUUSD")


def test_error_lists_available_candidates():
    with pytest.raises(ValueError, match="GBPUSD"):
        resolve_symbol_in(["EURUSD", "GBPUSD"], "XAUUSD")


def test_resolve_symbol_matches_broker_suffix():
    assert resolve_symbol_in(["XAUUSD.m", "EURUSD"], "XAUUSD") == "XAUUSD.m"


def test_exact_match_is_case_insensitive_and_preferred():
    assert resolve_symbol_in(["XAUUSD.m", "xauusd"], "XAUUSD") == "xauusd"


def test_prefix_match_picks_first_sorted():
    assert resolve_symbol_in(["XAUUSD.z", "XAUUSD.a"], "XAUUSD") == "XAUUSD.a"
