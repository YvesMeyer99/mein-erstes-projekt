import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

LOVELACE_PER_ADA = Decimal(10**6)
API_URL = "https://api.koios.rest/api/v1"
PAGE_LIMIT = 1000


def _extract_address(utxo: dict) -> str | None:
    """Confirmed against the live Koios API and its OpenAPI schema
    (koiosapi.yaml): `payment_addr` is always a nested
    {"cred": "...", "bech32": "addr1..."} object, never a plain string.
    The plain-string branch below is kept as a harmless defensive fallback
    (it was never observed in practice) rather than removed, since it
    costs nothing and Koios does not formally guarantee the shape won't
    ever change."""
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


def _koios_post(path: str, body: dict, params: dict | None = None) -> list:
    """POST to a Koios (PostgREST-based) RPC endpoint.

    Pagination is via `limit`/`offset` HTTP query-string parameters, NOT
    JSON body fields -- Koios's PostgREST backend validates the POST body
    against a strict per-endpoint schema and rejects (404, "Query not
    found!") any body containing keys it doesn't recognize (e.g. `limit`
    inside the body for /address_txs), so `limit`/`offset` must be passed
    via `params`, confirmed against the live API.
    """
    response = requests.post(f"{API_URL}{path}", json=body, params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def _fetch_tx_infos(tx_hashes: list[str]) -> list[dict]:
    if not tx_hashes:
        return []
    all_tx_infos: list[dict] = []
    for i in range(0, len(tx_hashes), PAGE_LIMIT):
        chunk = tx_hashes[i : i + PAGE_LIMIT]
        all_tx_infos.extend(
            _koios_post(
                "/tx_info",
                # _inputs and _assets default to false on Koios's side (confirmed
                # against the live API): without them, /tx_info silently returns
                # "inputs": [] and every "asset_list": [] with a 200 OK, which
                # would make normalize_cardano_tx's netting logic look like every
                # transaction is incoming-only and has no native tokens.
                {"_tx_hashes": chunk, "_inputs": True, "_assets": True},
            )
        )
    return all_tx_infos


class CardanoAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "cardano"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        candidates = self._fetch_candidate_signatures(since)
        if not candidates:
            return []
        tx_infos = _fetch_tx_infos([c["tx_hash"] for c in candidates])
        results: list[NormalizedTransaction] = []
        for tx in tx_infos:
            results.extend(normalize_cardano_tx(tx, {self.address}, self.account_label, since))
        return results

    def _fetch_candidate_signatures(self, since: datetime | None) -> list[dict]:
        all_entries: list[dict] = []
        offset = 0
        while True:
            page = _koios_post(
                "/address_txs",
                {"_addresses": [self.address]},
                params={"limit": PAGE_LIMIT, "offset": offset},
            )
            all_entries.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT

        if since is None:
            return all_entries
        return [
            e for e in all_entries if datetime.fromtimestamp(e["block_time"], tz=timezone.utc) > since
        ]
