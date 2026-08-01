import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

API_URL = "https://sync-mainnet.vechain.org"
WEI_PER_VET = Decimal(10**18)
PAGE_LIMIT = 256
TRANSFER_EVENT_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class VeChainAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "vechain"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def fetch_transactions(self, since) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        results.extend(self._fetch_vet_transfers(since))
        results.extend(self._fetch_vip180_transfers(since))
        return results

    def _fetch_vet_transfers(self, since) -> list[NormalizedTransaction]:
        entries = self._fetch_transfer_logs()
        occurrence_counts: dict[tuple[str, int], int] = {}
        results: list[NormalizedTransaction] = []
        for entry in entries:
            # A single tx+clause can contain multiple transfer log entries.
            # Track an occurrence index per (txID, clauseIndex) pair, over
            # every row the API returns (before since/self-transfer/zero-
            # amount filtering), so external_id stays unique per entry and -
            # critically - stable across repeated syncs regardless of which
            # `since` value filtered which entries out. Indexing only over
            # survivors would let the index a given entry gets shift between
            # calls, causing a new entry to silently collide (and get
            # deduped away by sync.py) with an already-persisted external_id.
            key = (entry["meta"]["txID"], entry["meta"]["clauseIndex"])
            occurrence = occurrence_counts.get(key, 0)
            occurrence_counts[key] = occurrence + 1

            ntx = self._normalize_vet_entry(entry, since, occurrence)
            if ntx is not None:
                results.append(ntx)
        return results

    def _fetch_transfer_logs(self) -> list[dict]:
        # NOTE: pagination is offset-based over a live, desc-ordered feed.
        # If a new transfer confirms between two page fetches, entries can
        # shift and a page boundary could skip or duplicate a row. This
        # mirrors the established "always re-fetch fully, rely on sync.py's
        # external_id dedup" convention used by other adapters (Binance,
        # MEXC) rather than cursor-based incremental fetching; only matters
        # once an address has >256 transfers, so accepted as YAGNI for now.
        all_entries: list[dict] = []
        offset = 0
        while True:
            body = {
                "criteriaSet": [{"sender": self.address}, {"recipient": self.address}],
                "order": "desc",
                "options": {"offset": offset, "limit": PAGE_LIMIT},
            }
            response = requests.post(f"{API_URL}/logs/transfer", json=body, timeout=15)
            response.raise_for_status()
            page = response.json()
            all_entries.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return all_entries

    def _normalize_vet_entry(self, entry: dict, since, index: int) -> NormalizedTransaction | None:
        timestamp = datetime.fromtimestamp(entry["meta"]["blockTimestamp"], tz=timezone.utc)
        if since is not None and timestamp <= since:
            return None

        sender = entry["sender"]
        recipient = entry["recipient"]
        if sender.lower() == recipient.lower():
            return None

        amount_wei = int(entry["amount"], 16)
        if amount_wei == 0:
            return None

        if recipient.lower() == self.address.lower():
            tx_type = "transfer_in"
        elif sender.lower() == self.address.lower():
            tx_type = "transfer_out"
        else:
            return None

        return NormalizedTransaction(
            timestamp=timestamp,
            source_type=self.source_type,
            source_name=self.source_name,
            account_label=self.account_label,
            tx_type=tx_type,
            asset="VET",
            amount=Decimal(amount_wei) / WEI_PER_VET,
            external_id=f"{entry['meta']['txID']}-{entry['meta']['clauseIndex']}-VET-{index}",
            raw_json=json.dumps(entry),
        )

    def _fetch_vip180_transfers(self, since) -> list[NormalizedTransaction]:
        entries = self._fetch_event_logs()
        occurrence_counts: dict[tuple[str, int], int] = {}
        results: list[NormalizedTransaction] = []
        for entry in entries:
            # Same stable-external_id pattern as _fetch_vet_transfers above:
            # the occurrence index per (txID, clauseIndex) must be computed
            # over the full unfiltered entries list, before since/self-
            # transfer/zero-amount filtering, so a survivor's external_id
            # never shifts across syncs depending on what an earlier `since`
            # value happened to filter out. See the comment in
            # _fetch_vet_transfers for the full rationale (this exact bug
            # was found and fixed in Task 1's review for VET transfers, and
            # would reappear here with a naive running-index-over-survivors
            # loop if not applied).
            key = (entry["meta"]["txID"], entry["meta"]["clauseIndex"])
            occurrence = occurrence_counts.get(key, 0)
            occurrence_counts[key] = occurrence + 1

            ntx = self._normalize_vip180_entry(entry, since, occurrence)
            if ntx is not None:
                results.append(ntx)
        return results

    def _fetch_event_logs(self) -> list[dict]:
        # See the pagination caveat on _fetch_transfer_logs above; the same
        # offset-based-over-a-live-feed tradeoff applies here.
        padded_address = "0x" + "0" * 24 + self.address[2:].lower()
        all_entries: list[dict] = []
        offset = 0
        while True:
            body = {
                "criteriaSet": [
                    {"topic0": TRANSFER_EVENT_TOPIC0, "topic1": padded_address},
                    {"topic0": TRANSFER_EVENT_TOPIC0, "topic2": padded_address},
                ],
                "order": "desc",
                "options": {"offset": offset, "limit": PAGE_LIMIT},
            }
            response = requests.post(f"{API_URL}/logs/event", json=body, timeout=15)
            response.raise_for_status()
            page = response.json()
            all_entries.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return all_entries

    def _normalize_vip180_entry(self, entry: dict, since, index: int) -> NormalizedTransaction | None:
        timestamp = datetime.fromtimestamp(entry["meta"]["blockTimestamp"], tz=timezone.utc)
        if since is not None and timestamp <= since:
            return None

        topics = entry["topics"]
        sender = "0x" + topics[1][-40:]
        recipient = "0x" + topics[2][-40:]
        if sender.lower() == recipient.lower():
            return None

        amount_raw = int(entry["data"], 16)
        if amount_raw == 0:
            return None

        if recipient.lower() == self.address.lower():
            tx_type = "transfer_in"
        elif sender.lower() == self.address.lower():
            tx_type = "transfer_out"
        else:
            return None

        contract = entry["address"]
        return NormalizedTransaction(
            timestamp=timestamp,
            source_type=self.source_type,
            source_name=self.source_name,
            account_label=self.account_label,
            tx_type=tx_type,
            asset=contract,
            # Simplifying assumption: all VIP-180 tokens use 18 decimals
            # (matches VET/VTHO and the overwhelming ERC-20/VIP-180
            # convention). Documented trade-off, see design doc.
            amount=Decimal(amount_raw) / WEI_PER_VET,
            external_id=f"{entry['meta']['txID']}-{entry['meta']['clauseIndex']}-{contract}-{index}",
            raw_json=json.dumps(entry),
        )
