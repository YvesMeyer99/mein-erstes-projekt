import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import requests

from app.adapters.base import TransactionAdapter
from app.adapters.binance_auth import build_signed_params
from app.config import TradingPairConfig
from app.schemas import NormalizedTransaction

API_URL = "https://api.binance.com"
PAGE_LIMIT = 1000
MAX_RETRIES = 3

DEPOSIT_SUCCESS_STATUS = "1"
WITHDRAWAL_SUCCESS_STATUS = "6"

# Binance caps every deposit/withdrawal history query to a 90-day window
# between startTime and endTime - unlike MEXC, which allows an arbitrarily
# long range in a single call. To cover a longer gap, the adapter walks
# consecutive 90-day windows from a start point up to "now".
WINDOW = timedelta(days=90)

# Binance has no "give me everything" mode for deposits/withdrawals: without
# startTime it silently defaults to the last 90 days. For the very first
# sync (since is None) we need a concrete start point. BINANCE_SYNC_START
# (wired in Task 4) lets the user provide their account creation date; if
# they don't, this fallback covers 5 years, a generous upper bound for
# realistic account ages rather than silently missing history.
DEFAULT_SYNC_START_LOOKBACK = timedelta(days=365 * 5)

# Same watermark-safety pattern already proven necessary in Coinbase's and
# MEXC's *final* reviews (see app/adapters/mexc.py's SYNC_LOOKBACK comment):
# fetch_transactions() combines two independent Binance data streams -
# deposits and withdrawals - under one shared sync watermark. A deposit
# still pending (status != DEPOSIT_SUCCESS_STATUS) or a withdrawal still
# processing (status != WITHDRAWAL_SUCCESS_STATUS) is filtered out and never
# persisted; if it completes later, its original insertTime/applyTime can
# already be before a watermark advanced by the *other*, faster stream. We
# widen the effective window start by a trailing safety margin on every
# incremental sync so a late-completing record is re-fetched and picked up.
# Re-seeing an already-persisted transaction is a harmless no-op in sync.py
# (dedup by external_id).
SYNC_LOOKBACK = timedelta(days=7)


class BinanceAdapter(TransactionAdapter):
    source_type = "exchange"
    source_name = "binance"

    def __init__(
        self,
        account_label: str,
        api_key: str,
        api_secret: str,
        trading_pairs: list[TradingPairConfig],
        sync_start: datetime | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        super().__init__(account_label)
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_pairs = trading_pairs
        self.sync_start = sync_start
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _get(self, path: str, params: dict) -> list:
        response = None
        for attempt in range(MAX_RETRIES):
            signed_params = build_signed_params(params, self.api_secret)
            response = requests.get(
                f"{API_URL}{path}",
                params=signed_params,
                headers={"X-MBX-APIKEY": self.api_key},
                timeout=10,
            )
            if response.status_code != 429:
                break
            if attempt < MAX_RETRIES - 1:
                time.sleep(2**attempt)

        response.raise_for_status()
        return response.json()

    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        now = self._clock()
        if since is not None:
            effective_since = since - SYNC_LOOKBACK
        else:
            # Unlike MEXC (which has no forced start point and so skips
            # since-filtering entirely on the first sync), Binance always
            # needs a concrete effective_since here (sync_start or the
            # 5-year fallback) to bound the very first windowed query. That
            # concrete value is then used as an *exclusive* lower bound
            # below (timestamp <= effective_since is skipped), so a record
            # dated exactly at sync_start is deliberately excluded rather
            # than an oversight - callers who need that exact instant
            # included should configure sync_start one moment earlier.
            effective_since = self.sync_start or (now - DEFAULT_SYNC_START_LOOKBACK)

        results: list[NormalizedTransaction] = []
        results.extend(self._fetch_deposits(effective_since, now))
        results.extend(self._fetch_withdrawals(effective_since, now))
        results.extend(self._fetch_trades())
        return results

    def _fetch_windowed_records(self, path: str, window_start: datetime, now: datetime) -> list[dict]:
        all_records: list[dict] = []
        cursor = window_start
        while cursor < now:
            window_end = min(cursor + WINDOW, now)
            all_records.extend(self._fetch_window_page(path, cursor, window_end))
            cursor = window_end + timedelta(milliseconds=1)
        return all_records

    def _fetch_window_page(self, path: str, window_start: datetime, window_end: datetime) -> list[dict]:
        records: list[dict] = []
        offset = 0
        start_ms = int(window_start.timestamp() * 1000)
        end_ms = int(window_end.timestamp() * 1000)
        while True:
            batch = self._get(path, {"startTime": start_ms, "endTime": end_ms, "offset": offset, "limit": PAGE_LIMIT})
            records.extend(batch)
            if len(batch) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT
        return records

    def _fetch_deposits(self, effective_since: datetime, now: datetime) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for record in self._fetch_windowed_records("/sapi/v1/capital/deposit/hisrec", effective_since, now):
            if str(record.get("status")) != DEPOSIT_SUCCESS_STATUS:
                continue
            timestamp = datetime.fromtimestamp(int(record["insertTime"]) / 1000, tz=timezone.utc)
            if timestamp <= effective_since:
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
                    external_id=f"deposit-{record['id']}",
                    raw_json=json.dumps(record),
                )
            )
        return results

    def _fetch_withdrawals(self, effective_since: datetime, now: datetime) -> list[NormalizedTransaction]:
        results: list[NormalizedTransaction] = []
        for record in self._fetch_windowed_records("/sapi/v1/capital/withdraw/history", effective_since, now):
            if str(record.get("status")) != WITHDRAWAL_SUCCESS_STATUS:
                continue
            timestamp = datetime.fromtimestamp(int(record["applyTime"]) / 1000, tz=timezone.utc)
            if timestamp <= effective_since:
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

    def _fetch_trades(self) -> list[NormalizedTransaction]:
        return []
