import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

SATS_PER_BTC = Decimal(10**8)
API_BASE = "https://blockstream.info/api"


def fetch_all_pages_for_address(address: str) -> list[dict]:
    """Walk Blockstream's paginated txs endpoint for a single address.

    The base endpoint returns mempool txs plus only the most recent 25
    confirmed txs. Older confirmed txs must be fetched page-by-page via
    the /txs/chain/:last_seen_txid endpoint, keyed off the last
    confirmed txid seen so far, until a page comes back with fewer than
    25 confirmed txs (or none at all).
    """
    response = requests.get(f"{API_BASE}/address/{address}/txs", timeout=10)
    response.raise_for_status()
    page = response.json()

    all_txs: list[dict] = []
    while True:
        all_txs.extend(page)
        confirmed = [t for t in page if t.get("status", {}).get("confirmed")]
        if len(confirmed) < 25:
            break
        last_txid = confirmed[-1]["txid"]
        response = requests.get(
            f"{API_BASE}/address/{address}/txs/chain/{last_txid}", timeout=10
        )
        response.raise_for_status()
        page = response.json()

    return all_txs


def normalize_bitcoin_tx(
    tx: dict,
    owned_addresses: set[str],
    account_label: str,
    since: datetime | None,
) -> NormalizedTransaction | None:
    """Compute a single Bitcoin address (or HD wallet's) net BTC change for
    one transaction, and normalize it -- or return None if the tx should be
    skipped (unconfirmed, older than `since`, or nets to zero change for the
    owned addresses, e.g. a pure spend+change-back within the same wallet).

    `owned_addresses` is a set rather than a single address so this same
    function serves both the single-address BitcoinAdapter (a 1-element
    set) and the multi-address BitcoinXpubAdapter (every address discovered
    for an HD wallet) -- computing net vin/vout against the *whole* owned
    set, not per-address, is what makes internal wallet transfers (spend
    from one of our addresses, change back to another of our addresses)
    correctly net to zero instead of appearing as two separate taxable
    events.
    """
    block_time = tx.get("status", {}).get("block_time")
    if block_time is None:
        return None
    timestamp = datetime.fromtimestamp(block_time, tz=timezone.utc)
    if since is not None and timestamp <= since:
        return None

    vin_value = sum(
        vin.get("prevout", {}).get("value", 0)
        for vin in tx["vin"]
        if vin.get("prevout", {}).get("scriptpubkey_address") in owned_addresses
    )
    vout_value = sum(
        vout["value"]
        for vout in tx["vout"]
        if vout.get("scriptpubkey_address") in owned_addresses
    )
    net_sats = vout_value - vin_value
    if net_sats == 0:
        return None

    fee_amount = None
    fee_asset = None
    if net_sats < 0:
        total_vin = sum(vin.get("prevout", {}).get("value", 0) for vin in tx["vin"])
        total_vout = sum(vout["value"] for vout in tx["vout"])
        fee_sats = total_vin - total_vout
        fee_amount = Decimal(fee_sats) / SATS_PER_BTC
        fee_asset = "BTC"

    return NormalizedTransaction(
        timestamp=timestamp,
        source_type="chain",
        source_name="bitcoin",
        account_label=account_label,
        tx_type="transfer_in" if net_sats > 0 else "transfer_out",
        asset="BTC",
        amount=Decimal(abs(net_sats)) / SATS_PER_BTC,
        fee_amount=fee_amount,
        fee_asset=fee_asset,
        external_id=tx["txid"],
        raw_json=json.dumps(tx),
    )


class BitcoinAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "bitcoin"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for tx in fetch_all_pages_for_address(self.address):
            ntx = normalize_bitcoin_tx(tx, {self.address}, self.account_label, since)
            if ntx is not None:
                results.append(ntx)
        return results
