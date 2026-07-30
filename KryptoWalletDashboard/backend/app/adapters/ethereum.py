import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

WEI_PER_ETH = Decimal(10**18)


class EthereumAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "ethereum"
    API_URL = "https://api.etherscan.io/api"

    def __init__(self, account_label: str, address: str, api_key: str):
        super().__init__(account_label)
        self.address = address
        self.api_key = api_key

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        params = {
            "module": "account",
            "action": "txlist",
            "address": self.address,
            "startblock": 0,
            "endblock": 99999999,
            "sort": "asc",
            "apikey": self.api_key,
        }
        response = requests.get(self.API_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "1" and data.get("message") != "No transactions found":
            raise RuntimeError(f"Etherscan-Fehler: {data.get('message')}")

        address_lower = self.address.lower()
        results: list[NormalizedTransaction] = []
        for tx in data.get("result", []):
            if tx.get("isError") == "1":
                continue
            timestamp = datetime.fromtimestamp(int(tx["timeStamp"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            value_eth = Decimal(tx["value"]) / WEI_PER_ETH
            if value_eth == 0:
                continue

            is_outgoing = tx["from"].lower() == address_lower
            fee_amount = None
            fee_asset = None
            if is_outgoing:
                fee_amount = (Decimal(tx["gasUsed"]) * Decimal(tx["gasPrice"])) / WEI_PER_ETH
                fee_asset = "ETH"

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_out" if is_outgoing else "transfer_in",
                    asset="ETH",
                    amount=value_eth,
                    fee_amount=fee_amount,
                    fee_asset=fee_asset,
                    external_id=tx["hash"],
                    raw_json=json.dumps(tx),
                )
            )
        return results
