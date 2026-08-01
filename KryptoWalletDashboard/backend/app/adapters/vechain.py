import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

API_URL = "https://sync-mainnet.vechain.org"
WEI_PER_VET = Decimal(10**18)
PAGE_LIMIT = 256


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
        results: list[NormalizedTransaction] = []
        index = 0
        for entry in entries:
            ntx = self._normalize_vet_entry(entry, since, index)
            if ntx is not None:
                results.append(ntx)
                index += 1
        return results

    def _fetch_transfer_logs(self) -> list[dict]:
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
        # A later task fills this in.
        return []
