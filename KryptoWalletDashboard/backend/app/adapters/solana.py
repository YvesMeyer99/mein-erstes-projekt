import json
from datetime import datetime, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.schemas import NormalizedTransaction

API_URL = "https://api.mainnet-beta.solana.com"
LAMPORTS_PER_SOL = Decimal(10**9)
SIGNATURE_PAGE_LIMIT = 1000


class SolanaAdapter(TransactionAdapter):
    source_type = "chain"
    source_name = "solana"

    def __init__(self, account_label: str, address: str):
        super().__init__(account_label)
        self.address = address

    def _rpc_call(self, method: str, params: list) -> dict | list | None:
        response = requests.post(
            API_URL,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=10,
        )
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"Solana-Fehler beim Aufruf von {method}: {body['error']}")
        return body["result"]

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for entry in self._fetch_candidate_signatures(since):
            tx = self._rpc_call(
                "getTransaction",
                [entry["signature"], {"encoding": "json", "maxSupportedTransactionVersion": 0}],
            )
            if tx is None:
                continue
            timestamp = datetime.fromtimestamp(entry["blockTime"], tz=timezone.utc)
            results.extend(self._normalize_tx(tx, entry["signature"], timestamp))
        return results

    def _fetch_candidate_signatures(self, since: datetime | None) -> list[dict]:
        """Paginate getSignaturesForAddress, filtering out failed and
        too-old entries before the caller ever calls getTransaction."""
        candidates: list[dict] = []
        before = None
        while True:
            params_opts = {"limit": SIGNATURE_PAGE_LIMIT}
            if before is not None:
                params_opts["before"] = before
            page = self._rpc_call("getSignaturesForAddress", [self.address, params_opts])
            for entry in page:
                if entry.get("err") is not None:
                    continue
                if entry.get("blockTime") is None:
                    continue
                timestamp = datetime.fromtimestamp(entry["blockTime"], tz=timezone.utc)
                if since is not None and timestamp <= since:
                    continue
                candidates.append(entry)
            if len(page) < SIGNATURE_PAGE_LIMIT:
                break
            before = page[-1]["signature"]
        return candidates

    def _normalize_tx(
        self, tx: dict, signature: str, timestamp: datetime
    ) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []

        account_keys = tx["transaction"]["message"]["accountKeys"]
        if self.address in account_keys:
            idx = account_keys.index(self.address)
            net_lamports = tx["meta"]["postBalances"][idx] - tx["meta"]["preBalances"][idx]
            if net_lamports != 0:
                fee_amount = None
                fee_asset = None
                if idx == 0 and net_lamports < 0:
                    fee_amount = Decimal(tx["meta"]["fee"]) / LAMPORTS_PER_SOL
                    fee_asset = "SOL"
                results.append(
                    NormalizedTransaction(
                        timestamp=timestamp,
                        source_type=self.source_type,
                        source_name=self.source_name,
                        account_label=self.account_label,
                        tx_type="transfer_in" if net_lamports > 0 else "transfer_out",
                        asset="SOL",
                        amount=Decimal(abs(net_lamports)) / LAMPORTS_PER_SOL,
                        fee_amount=fee_amount,
                        fee_asset=fee_asset,
                        # `amount` above is the fee payer's total balance
                        # change (postBalance - preBalance), which already
                        # has the transaction fee baked in -- tells
                        # app.portfolio.compute_portfolio not to subtract
                        # fee_amount a second time.
                        fee_included_in_amount=fee_amount is not None,
                        external_id=f"{signature}-native",
                        raw_json=json.dumps(tx),
                    )
                )

        results.extend(self._normalize_token_legs(tx, signature, timestamp))
        return results

    def _normalize_token_legs(self, tx: dict, signature: str, timestamp) -> list[NormalizedTransaction]:
        pre_by_index = {b["accountIndex"]: b for b in tx["meta"].get("preTokenBalances", [])}
        post_by_index = {b["accountIndex"]: b for b in tx["meta"].get("postTokenBalances", [])}

        results: list[NormalizedTransaction] = []
        for idx in sorted(set(pre_by_index) | set(post_by_index)):
            pre_entry = pre_by_index.get(idx)
            post_entry = post_by_index.get(idx)
            reference = post_entry or pre_entry
            if reference.get("owner") != self.address:
                continue

            mint = reference["mint"]
            decimals = reference["uiTokenAmount"]["decimals"]
            pre_amount = Decimal(pre_entry["uiTokenAmount"]["amount"]) if pre_entry else Decimal(0)
            post_amount = Decimal(post_entry["uiTokenAmount"]["amount"]) if post_entry else Decimal(0)
            net = post_amount - pre_amount
            if net == 0:
                continue

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_in" if net > 0 else "transfer_out",
                    asset=mint,
                    amount=abs(net) / Decimal(10**decimals),
                    external_id=f"{signature}-{mint}",
                    raw_json=json.dumps(tx),
                )
            )
        return results
