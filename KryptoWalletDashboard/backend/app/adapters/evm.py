import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

WEI_PER_NATIVE_UNIT = Decimal(10**18)


class EvmAdapter(TransactionAdapter):
    """Fetches native-coin transfers for one EVM-compatible chain via
    Etherscan's V2 multi-chain API. One instance = one (wallet, chain) pair;
    the same `api_key` works across every chain Etherscan V2 supports, only
    `chain_id` changes."""

    source_type = "chain"
    API_URL = "https://api.etherscan.io/v2/api"
    PAGE_SIZE = 1000

    def __init__(
        self,
        account_label: str,
        address: str,
        api_key: str,
        chain_id: int,
        chain_name: str,
        native_asset: str,
    ):
        super().__init__(account_label)
        self.address = address
        self.api_key = api_key
        self.chain_id = chain_id
        self.source_name = chain_name
        self.native_asset = native_asset

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        return self._native_transactions(since)

    def _native_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        address_lower = self.address.lower()
        results: list[NormalizedTransaction] = []
        for tx in self._fetch_all_pages("txlist"):
            if tx.get("isError") == "1":
                continue
            timestamp = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            value = Decimal(tx["value"]) / WEI_PER_NATIVE_UNIT
            if value == 0:
                continue

            is_outgoing = tx["from"].lower() == address_lower
            fee_amount = None
            fee_asset = None
            if is_outgoing:
                fee_amount = (Decimal(tx["gasUsed"]) * Decimal(tx["gasPrice"])) / WEI_PER_NATIVE_UNIT
                fee_asset = self.native_asset

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_out" if is_outgoing else "transfer_in",
                    asset=self.native_asset,
                    amount=value,
                    fee_amount=fee_amount,
                    fee_asset=fee_asset,
                    external_id=tx["hash"],
                    raw_json=json.dumps(tx),
                )
            )
        return results

    def _fetch_all_pages(self, action: str) -> list[dict]:
        """Walk Etherscan's page/offset-paginated endpoint for the given action.

        Same termination rule as Phase 1's Bitcoin/Ethereum adapters: keep
        requesting subsequent pages, incrementing `page`, until a page comes
        back with fewer than PAGE_SIZE records - that short page signals
        there is nothing left to fetch. Etherscan also caps total records
        reachable via a single startblock/endblock window at 10'000 per
        chain; walking further would require chunking the block range,
        which is out of scope here.
        """
        all_items: list[dict] = []
        page = 1
        while True:
            params = {
                "chainid": self.chain_id,
                "module": "account",
                "action": action,
                "address": self.address,
                "startblock": 0,
                "endblock": 99999999,
                "page": page,
                "offset": self.PAGE_SIZE,
                "sort": "asc",
                "apikey": self.api_key,
            }
            response = requests.get(self.API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get("status") != "1" and data.get("message") != "No transactions found":
                raise RuntimeError(f"Etherscan-Fehler ({self.source_name}): {data.get('message')}")

            batch = data.get("result", [])
            all_items.extend(batch)
            if len(batch) < self.PAGE_SIZE:
                break
            page += 1

        return all_items
