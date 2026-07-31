import json
import time
from datetime import datetime
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.adapters.coinbase_auth import build_coinbase_jwt
from app.schemas import NormalizedTransaction

HOST = "api.coinbase.com"

DIRECT_TYPE_MAP = {"buy": "buy", "sell": "sell"}
TRANSFER_TYPES = {"send", "receive", "transfer"}

MAX_RETRIES = 3


class CoinbaseAdapter(TransactionAdapter):
    source_type = "exchange"
    source_name = "coinbase"
    PAGE_LIMIT = 25

    def __init__(self, account_label: str, api_key_name: str, private_key_pem: str):
        super().__init__(account_label)
        self.api_key_name = api_key_name
        self.private_key_pem = private_key_pem

    def _get(self, path: str, params: dict) -> dict:
        response = None
        for attempt in range(MAX_RETRIES):
            token = build_coinbase_jwt(self.api_key_name, self.private_key_pem, "GET", HOST, path)
            response = requests.get(
                f"https://{HOST}{path}",
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if response.status_code != 429:
                break
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)

        response.raise_for_status()
        return response.json()

    def _paginated(self, path: str) -> list[dict]:
        items: list[dict] = []
        starting_after = None
        while True:
            params: dict = {"limit": self.PAGE_LIMIT}
            if starting_after is not None:
                params["starting_after"] = starting_after
            data = self._get(path, params)
            batch = data.get("data", [])
            items.extend(batch)
            if len(batch) < self.PAGE_LIMIT:
                break
            starting_after = batch[-1]["id"]
        return items

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for account in self._paginated("/v2/accounts"):
            for tx in self._paginated(f"/v2/accounts/{account['id']}/transactions"):
                normalized = self._normalize(tx, since)
                if normalized is not None:
                    results.append(normalized)
        return results

    def _normalize(self, tx: dict, since: datetime | None) -> NormalizedTransaction | None:
        if tx.get("status") != "completed":
            return None

        timestamp = datetime.fromisoformat(tx["created_at"].replace("Z", "+00:00"))
        if since is not None and timestamp <= since:
            return None

        amount_obj = tx["amount"]
        signed_amount = Decimal(amount_obj["amount"])
        if signed_amount == 0:
            return None
        asset = amount_obj["currency"]

        tx_type = DIRECT_TYPE_MAP.get(tx["type"])
        if tx_type is None:
            if tx["type"] not in TRANSFER_TYPES:
                return None
            tx_type = "transfer_in" if signed_amount > 0 else "transfer_out"

        fee_amount = None
        fee_asset = None
        fee = tx.get("fee")
        if fee is not None:
            fee_amount = Decimal(fee["amount"])
            fee_asset = fee["currency"]

        return NormalizedTransaction(
            timestamp=timestamp,
            source_type=self.source_type,
            source_name=self.source_name,
            account_label=self.account_label,
            tx_type=tx_type,
            asset=asset,
            amount=abs(signed_amount),
            fee_amount=fee_amount,
            fee_asset=fee_asset,
            external_id=tx["id"],
            raw_json=json.dumps(tx),
        )
