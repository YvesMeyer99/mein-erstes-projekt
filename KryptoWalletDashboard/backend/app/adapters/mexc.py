import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.adapters.mexc_auth import build_signed_params
from app.config import TradingPairConfig
from app.schemas import NormalizedTransaction

logger = logging.getLogger(__name__)

API_URL = "https://api.mexc.com"
PAGE_LIMIT = 1000

MAX_RETRIES = 3

# MEXC's myTrades endpoint silently ignores `startTime` beyond this window
# and only ever returns the last 30 days of trades, regardless of what's
# requested. If more than 30 days have passed since the last sync, any
# trades older than 30 days ago but newer than the previous watermark are
# permanently unfetchable via the API -- not something SYNC_LOOKBACK above
# can fix, since that's a client concern and this is a hard server-side
# limit. We can't recover the data, but we can at least warn.
TRADE_HISTORY_WINDOW = timedelta(days=30)

# MEXC's two documented "deposit completed" status codes: 5 = SUCCESS, 12 = COMPLETED.
DEPOSIT_SUCCESS_STATUSES = {"5", "12"}
WITHDRAWAL_SUCCESS_STATUS = "7"

# fetch_transactions() combines three independent MEXC data streams --
# deposits, withdrawals, and trades across every configured pair -- in one
# call, but sync.py tracks a single shared last_synced_at watermark per
# account_label across all of them (the max timestamp seen across every
# stream). A deposit awaiting confirmations (status not in
# DEPOSIT_SUCCESS_STATUSES) or a withdrawal still processing (status !=
# WITHDRAWAL_SUCCESS_STATUS) is filtered out and never persisted. If it
# later completes, it keeps its original insertTime/applyTime, which can be
# well before the shared watermark (advanced by a *different*, faster
# stream) -- so a naive `timestamp <= since` filter would silently and
# permanently drop it, since there's nothing persisted yet for
# _already_persisted() dedup to catch. Unlike Coinbase, MEXC's API also
# supports server-side filtering via `startTime`, so the raw `since` must
# never reach the API directly either -- the server would already exclude
# the late-completing record before it's even seen client-side. To close
# this gap we always widen the query window (both server-side startTime and
# client-side filtering) by a trailing safety margin subtracted from
# `since`, rather than trusting the watermark to be precise per stream.
# Re-seeing an already-persisted transaction is a harmless no-op in sync.py
# (dedup by external_id).
SYNC_LOOKBACK = timedelta(days=7)


class MexcAdapter(TransactionAdapter):
    source_type = "exchange"
    source_name = "mexc"

    def __init__(
        self,
        account_label: str,
        api_key: str,
        api_secret: str,
        trading_pairs: list[TradingPairConfig],
    ):
        super().__init__(account_label)
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_pairs = trading_pairs

    def _get(self, path: str, params: dict) -> list:
        response = None
        for attempt in range(MAX_RETRIES):
            signed_params = build_signed_params(params, self.api_secret)
            response = requests.get(
                f"{API_URL}{path}",
                params=signed_params,
                headers={"X-MEXC-APIKEY": self.api_key},
                timeout=10,
            )
            if response.status_code != 429:
                break
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)

        response.raise_for_status()
        return response.json()

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        # Widen the effective query window by SYNC_LOOKBACK (see comment above)
        # -- this is what actually gets sent as `startTime` to the API and
        # used for client-side filtering across all three streams.
        effective_since = since - SYNC_LOOKBACK if since is not None else None
        results.extend(self._fetch_deposits(effective_since))
        results.extend(self._fetch_withdrawals(effective_since))
        # Trades additionally need the original, un-widened `since` to detect
        # a >30-day sync gap against MEXC's hard trade-history limit (see
        # TRADE_HISTORY_WINDOW above) -- SYNC_LOOKBACK would mask exactly the
        # gap size we're trying to detect here.
        results.extend(self._fetch_trades(effective_since, since))
        return results

    def _fetch_all_records(
        self,
        path: str,
        since: datetime | None,
        time_field: str,
        extra_params: dict | None = None,
    ) -> list[dict]:
        all_records: list[dict] = []
        start_time_ms = int(since.timestamp() * 1000) if since is not None else None
        while True:
            params: dict = {"limit": PAGE_LIMIT}
            if extra_params:
                params.update(extra_params)
            if start_time_ms is not None:
                params["startTime"] = start_time_ms
            batch = self._get(path, params)
            all_records.extend(batch)
            if len(batch) < PAGE_LIMIT:
                break
            # Advance past the latest timestamp seen so far to avoid re-fetching the
            # same page forever. Tradeoff: if a full PAGE_LIMIT page shares one exact
            # millisecond timestamp, records beyond it at that same timestamp would be
            # skipped -- accepted as deposit/withdrawal volume never reaches that
            # density in practice.
            start_time_ms = max(int(r[time_field]) for r in batch) + 1
        return all_records

    def _fetch_deposits(self, since: datetime | None) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for record in self._fetch_all_records("/api/v3/capital/deposit/hisrec", since, "insertTime"):
            if str(record.get("status")) not in DEPOSIT_SUCCESS_STATUSES:
                continue
            tx_id = record.get("txId")
            if not tx_id:
                continue
            timestamp = datetime.fromtimestamp(int(record["insertTime"]) / 1000, tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_in",
                    asset=record["coin"],
                    amount=Decimal(str(record["amount"])),
                    external_id=f"deposit-{tx_id}",
                    raw_json=json.dumps(record),
                )
            )
        return results

    def _fetch_withdrawals(self, since: datetime | None) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for record in self._fetch_all_records("/api/v3/capital/withdraw/history", since, "applyTime"):
            if str(record.get("status")) != WITHDRAWAL_SUCCESS_STATUS:
                continue
            timestamp = datetime.fromtimestamp(int(record["applyTime"]) / 1000, tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue
            fee_raw = record.get("transactionFee")
            parsed_fee = Decimal(str(fee_raw)) if fee_raw else None
            fee_amount = parsed_fee if parsed_fee else None
            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="transfer_out",
                    asset=record["coin"],
                    amount=Decimal(str(record["amount"])),
                    fee_amount=fee_amount,
                    fee_asset=record["coin"] if fee_amount is not None else None,
                    external_id=f"withdrawal-{record['id']}",
                    raw_json=json.dumps(record),
                )
            )
        return results

    def _fetch_trades(
        self, since: datetime | None, original_since: datetime | None = None
    ) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for pair in self.trading_pairs:
            results.extend(self._fetch_trades_for_pair(pair, since, original_since))
        return results

    def _fetch_trades_for_pair(
        self,
        pair: TradingPairConfig,
        since: datetime | None,
        original_since: datetime | None = None,
    ) -> list[NormalizedTransaction]:
        if original_since is not None and datetime.now(timezone.utc) - original_since > TRADE_HISTORY_WINDOW:
            logger.warning(
                "MEXC-Trades für %s: seit letztem Sync sind mehr als 30 Tage vergangen, "
                "ältere Trades sind über die API nicht mehr abrufbar",
                pair.symbol,
            )

        records = self._fetch_all_records(
            "/api/v3/myTrades", since, "time", extra_params={"symbol": pair.symbol}
        )

        results = []
        for record in records:
            timestamp = datetime.fromtimestamp(int(record["time"]) / 1000, tz=timezone.utc)
            if since is not None and timestamp <= since:
                continue

            qty = Decimal(str(record["qty"]))
            quote_qty = Decimal(str(record["quoteQty"]))
            commission_raw = record.get("commission")
            commission = (
                Decimal(str(commission_raw))
                if commission_raw and Decimal(str(commission_raw)) != 0
                else None
            )
            commission_asset = record.get("commissionAsset") if commission is not None else None

            if record["isBuyer"]:
                asset, amount = pair.base_asset, qty
                counter_asset, counter_amount = pair.quote_asset, quote_qty
            else:
                asset, amount = pair.quote_asset, quote_qty
                counter_asset, counter_amount = pair.base_asset, qty

            results.append(
                NormalizedTransaction(
                    timestamp=timestamp,
                    source_type=self.source_type,
                    source_name=self.source_name,
                    account_label=self.account_label,
                    tx_type="swap",
                    asset=asset,
                    amount=amount,
                    counter_asset=counter_asset,
                    counter_amount=counter_amount,
                    fee_amount=commission,
                    fee_asset=commission_asset,
                    external_id=f"trade-{pair.symbol}-{record['id']}",
                    raw_json=json.dumps(record),
                )
            )
        return results
