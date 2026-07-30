from abc import ABC, abstractmethod
from datetime import datetime

from app.schemas import NormalizedTransaction


class TransactionAdapter(ABC):
    source_type: str
    source_name: str

    def __init__(self, account_label: str):
        self.account_label = account_label

    @abstractmethod
    def fetch_transactions(self, since: datetime | None) -> list[NormalizedTransaction]:
        """Return transactions newer than `since` (or all, if `since` is None)."""
