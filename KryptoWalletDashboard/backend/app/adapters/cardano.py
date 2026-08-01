import json
from datetime import datetime, timezone
from decimal import Decimal

from app.schemas import NormalizedTransaction

LOVELACE_PER_ADA = Decimal(10**6)


def _extract_address(utxo: dict) -> str | None:
    """Koios's payment address field shape was not fully confirmed during
    design-time research -- this defensively supports both a nested
    {"bech32": "addr1..."} object and a plain "addr1..." string. Verify
    against Koios's actual live response in a later task and simplify this
    if only one shape is ever seen in practice."""
    addr = utxo.get("payment_addr")
    if isinstance(addr, dict):
        return addr.get("bech32")
    return addr


def normalize_cardano_tx(
    tx: dict,
    owned_addresses: set[str],
    account_label: str,
    since: datetime | None,
) -> list[NormalizedTransaction]:
    """Normalize one already-fetched Koios /tx_info transaction into zero
    or more NormalizedTransactions: one ADA leg if ADA moved, plus one leg
    per native token that moved.

    `owned_addresses` is a set rather than a single address so this same
    function serves both a single-address adapter and a future
    stake-address-resolved multi-address wallet scan -- computing net
    input/output against the *whole* owned set (not per-address) is what
    makes internal wallet transfers (spend from one owned address, change
    back to another owned address) correctly net to zero instead of
    appearing as two separate taxable events.
    """
    timestamp = datetime.fromtimestamp(tx["tx_timestamp"], tz=timezone.utc)
    if since is not None and timestamp <= since:
        return []

    input_addrs = {_extract_address(i) for i in tx["inputs"]}
    output_addrs = {_extract_address(o) for o in tx["outputs"]}
    if input_addrs <= owned_addresses and output_addrs <= owned_addresses:
        # Fully internal wallet reshuffle: no ADA left the wallet as a
        # whole, only the network fee did -- not treated as a taxable
        # transfer here. Same reasoning as app/adapters/bitcoin.py's
        # identical check.
        return []

    results: list[NormalizedTransaction] = []

    ada_in = sum(
        Decimal(o["value"]) for o in tx["outputs"] if _extract_address(o) in owned_addresses
    )
    ada_out = sum(
        Decimal(i["value"]) for i in tx["inputs"] if _extract_address(i) in owned_addresses
    )
    net_lovelace = ada_in - ada_out
    if net_lovelace != 0:
        fee_amount = None
        fee_asset = None
        if net_lovelace < 0:
            fee_amount = Decimal(tx["fee"]) / LOVELACE_PER_ADA
            fee_asset = "ADA"
        results.append(
            NormalizedTransaction(
                timestamp=timestamp,
                source_type="chain",
                source_name="cardano",
                account_label=account_label,
                tx_type="transfer_in" if net_lovelace > 0 else "transfer_out",
                asset="ADA",
                amount=abs(net_lovelace) / LOVELACE_PER_ADA,
                fee_amount=fee_amount,
                fee_asset=fee_asset,
                external_id=f"{tx['tx_hash']}-ADA",
                raw_json=json.dumps(tx),
            )
        )

    results.extend(_normalize_native_tokens(tx, owned_addresses, account_label, timestamp))
    return results


def _normalize_native_tokens(
    tx: dict, owned_addresses: set[str], account_label: str, timestamp: datetime
) -> list[NormalizedTransaction]:
    net_by_asset: dict[str, Decimal] = {}
    for output in tx["outputs"]:
        if _extract_address(output) not in owned_addresses:
            continue
        for asset in output.get("asset_list", []):
            key = f"{asset['policy_id']}{asset['asset_name']}"
            net_by_asset[key] = net_by_asset.get(key, Decimal(0)) + Decimal(asset["quantity"])
    for inp in tx["inputs"]:
        if _extract_address(inp) not in owned_addresses:
            continue
        for asset in inp.get("asset_list", []):
            key = f"{asset['policy_id']}{asset['asset_name']}"
            net_by_asset[key] = net_by_asset.get(key, Decimal(0)) - Decimal(asset["quantity"])

    results: list[NormalizedTransaction] = []
    for key, net in net_by_asset.items():
        if net == 0:
            continue
        results.append(
            NormalizedTransaction(
                timestamp=timestamp,
                source_type="chain",
                source_name="cardano",
                account_label=account_label,
                tx_type="transfer_in" if net > 0 else "transfer_out",
                asset=key,
                amount=abs(net),
                external_id=f"{tx['tx_hash']}-{key}",
                raw_json=json.dumps(tx),
            )
        )
    return results
