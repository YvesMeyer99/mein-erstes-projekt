import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

NON_TRADE_TYPE_MAP = {
    "deposit": "transfer_in",
    "withdrawal": "transfer_out",
    "staking": "staking_reward",
}


class KrakenAdapter(TransactionAdapter):
    source_type = "exchange"
    source_name = "kraken"
    API_URL = "https://api.kraken.com"
    LEDGERS_PATH = "/0/private/Ledgers"
    PAGE_SIZE = 50

    def __init__(self, account_label: str, api_key: str, api_secret: str):
        super().__init__(account_label)
        self.api_key = api_key
        self.api_secret = api_secret
        self._last_nonce = 0

    def _sign(self, urlpath: str, data: dict) -> str:
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        signature = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)
        return base64.b64encode(signature.digest()).decode()

    def _next_nonce(self) -> str:
        # Kraken requires a strictly increasing nonce per request. Wall-clock
        # milliseconds can repeat across back-to-back paginated calls, so
        # fall back to incrementing the previous value when that happens.
        nonce = int(time.time() * 1000)
        if nonce <= self._last_nonce:
            nonce = self._last_nonce + 1
        self._last_nonce = nonce
        return str(nonce)

    def _fetch_ledger_page(self, since: datetime | None, ofs: int) -> dict:
        data = {"nonce": self._next_nonce(), "ofs": str(ofs)}
        if since is not None:
            data["start"] = str(int(since.timestamp()))
        headers = {"API-Key": self.api_key, "API-Sign": self._sign(self.LEDGERS_PATH, data)}
        response = requests.post(self.API_URL + self.LEDGERS_PATH, data=data, headers=headers, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(f"Kraken-Fehler: {', '.join(payload['error'])}")
        return payload["result"]

    def _fetch_ledger(self, since: datetime | None) -> dict:
        ledger: dict = {}
        ofs = 0
        while True:
            result = self._fetch_ledger_page(since, ofs)
            page_ledger = result.get("ledger", {})
            if not page_ledger:
                break
            ledger.update(page_ledger)
            total_count = result.get("count", len(ledger))
            if len(ledger) >= total_count:
                break
            ofs += self.PAGE_SIZE
        return ledger

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        ledger = self._fetch_ledger(since)

        trade_legs_by_refid: dict[str, list[tuple[str, dict]]] = {}
        other_entries: list[tuple[str, dict]] = []
        for entry_id, entry in ledger.items():
            if entry["type"] == "trade":
                trade_legs_by_refid.setdefault(entry["refid"], []).append((entry_id, entry))
            else:
                other_entries.append((entry_id, entry))

        results: list[NormalizedTransaction] = []
        results.extend(self._build_non_trade_transactions(other_entries, since))
        results.extend(self._build_swap_transactions(trade_legs_by_refid, since))
        return results

    def _build_non_trade_transactions(self, entries, since):
        results = []
        for entry_id, entry in entries:
            tx_type = NON_TRADE_TYPE_MAP.get(entry["type"])
            if tx_type is None:
                continue
            timestamp = datetime.fromtimestamp(float(entry["time"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            fee = Decimal(entry.get("fee", "0"))
            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type=tx_type,
                    asset=entry["asset"],
                    amount=abs(Decimal(entry["amount"])),
                    fee_amount=fee if fee != 0 else None,
                    fee_asset=entry["asset"] if fee != 0 else None,
                    external_id=entry_id,
                    raw_json=json.dumps(entry),
                )
            )
        return results

    def _build_swap_transactions(self, trade_legs_by_refid, since):
        results = []
        for refid, legs in trade_legs_by_refid.items():
            if len(legs) != 2:
                continue
            (_, entry_a), (_, entry_b) = legs
            sold, bought = (
                (entry_a, entry_b) if Decimal(entry_a["amount"]) < 0 else (entry_b, entry_a)
            )
            timestamp = datetime.fromtimestamp(float(bought["time"]), tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            bought_fee = Decimal(bought.get("fee", "0"))
            sold_fee = Decimal(sold.get("fee", "0"))
            fee_amount = None
            fee_asset = None
            if bought_fee != 0 and sold_fee != 0:
                if bought["asset"] == sold["asset"]:
                    # Same currency on both legs: safe to combine.
                    fee_amount = bought_fee + sold_fee
                    fee_asset = bought["asset"]
                else:
                    # Different currencies: our schema has only one fee
                    # slot, so summing would mix currencies into a
                    # meaningless number. Prefer the sold (counter/quote)
                    # leg's fee and drop the bought leg's.
                    fee_amount = sold_fee
                    fee_asset = sold["asset"]
            elif bought_fee != 0:
                fee_amount = bought_fee
                fee_asset = bought["asset"]
            elif sold_fee != 0:
                fee_amount = sold_fee
                fee_asset = sold["asset"]
            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="swap",
                    asset=bought["asset"],
                    amount=Decimal(bought["amount"]),
                    counter_asset=sold["asset"],
                    counter_amount=abs(Decimal(sold["amount"])),
                    fee_amount=fee_amount,
                    fee_asset=fee_asset,
                    external_id=refid,
                    raw_json=json.dumps({"sold": sold, "bought": bought}),
                )
            )
        return results
