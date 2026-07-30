from app.config import parse_wallets


def test_parse_wallets_returns_empty_list_for_none():
    assert parse_wallets(None) == []


def test_parse_wallets_returns_empty_list_for_empty_string():
    assert parse_wallets("") == []


def test_parse_wallets_parses_single_entry():
    result = parse_wallets("main:bc1qexample")
    assert len(result) == 1
    assert result[0].label == "main"
    assert result[0].address == "bc1qexample"


def test_parse_wallets_parses_multiple_entries_and_trims_whitespace():
    result = parse_wallets(" main : bc1qexample , savings:bc1qother ")
    assert result == [
        __import__("app.config", fromlist=["WalletConfig"]).WalletConfig(label="main", address="bc1qexample"),
        __import__("app.config", fromlist=["WalletConfig"]).WalletConfig(label="savings", address="bc1qother"),
    ]
