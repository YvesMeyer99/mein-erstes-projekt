import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

SATS_PER_BTC = Decimal(10**8)


class BitcoinAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "bitcoin"
    API_BASE = "https://blockstream.info/api"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        response = requests.get(f"{self.API_BASE}/address/{self.address}/txs", timeout=10)
        response.raise_for_status()
        results: list[NormalizedTransaction] = []
        for tx in response.json():
            block_time = tx.get("status", {}).get("block_time")
            if block_time is None:
                continue
            timestamp = datetime.fromtimestamp(block_time, tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue

            vin_value = sum(
                vin["prevout"]["value"]
                for vin in tx["vin"]
                if vin.get("prevout", {}).get("scriptpubkey_address") == self.address
            )
            vout_value = sum(
                vout["value"]
                for vout in tx["vout"]
                if vout.get("scriptpubkey_address") == self.address
            )
            net_sats = vout_value - vin_value
            if net_sats == 0:
                continue

            fee_amount = None
            fee_asset = None
            if net_sats < 0:
                total_vin = sum(vin["prevout"]["value"] for vin in tx["vin"])
                total_vout = sum(vout["value"] for vout in tx["vout"])
                fee_sats = total_vin - total_vout
                fee_amount = Decimal(fee_sats) / SATS_PER_BTC
                fee_asset = "BTC"

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_in" if net_sats > 0 else "transfer_out",
                    asset="BTC",
                    amount=Decimal(abs(net_sats)) / SATS_PER_BTC,
                    fee_amount=fee_amount,
                    fee_asset=fee_asset,
                    external_id=tx["txid"],
                    raw_json=json.dumps(tx),
                )
            )
        return results
