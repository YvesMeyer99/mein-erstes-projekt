from datetime import datetime

from app.adapters.base import TransactionAdapter
from app.adapters.bitcoin import fetch_all_pages_for_address, normalize_bitcoin_tx
from app.adapters.bitcoin_gap_scan import discover_used_addresses
from app.schemas import NormalizedTransaction


class BitcoinXpubAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "bitcoin"

    def __init__(self, account_label: str, extended_key: str):
        super().__init__(account_label)
        self.extended_key = extended_key

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        owned_addresses = discover_used_addresses(self.extended_key)

        raw_txs_by_txid: dict[str, dict] = {}
        for address in owned_addresses:
            for tx in fetch_all_pages_for_address(address):
                # Blockstream returns identical tx JSON regardless of which of the
                # tx's addresses you queried it from -- last-write-wins here is
                # safe, just deduplicating by txid, not merging different data.
                raw_txs_by_txid[tx["txid"]] = tx

        results: list[NormalizedTransaction] = []
        for tx in raw_txs_by_txid.values():
            ntx = normalize_bitcoin_tx(tx, owned_addresses, self.account_label, since)
            if ntx is not None:
                results.append(ntx)
        return results
