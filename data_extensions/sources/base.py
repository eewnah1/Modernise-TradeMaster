"""Base class for adding new data sources to Modernise-TradeMaster."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import pandas as pd


@dataclass
class OHLCV:
    """A single OHLCV observation."""

    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    adj_close: Optional[float] = None
    symbol: Optional[str] = None


class DataSource(ABC):
    """Abstract data source that returns a standardized OHLCV DataFrame.

    Implementations must return a pandas DataFrame with at least the columns:
    ``date``, ``open``, ``high``, ``low``, ``close``, ``volume``.
    """

    name: str = "abstract"

    @abstractmethod
    def fetch(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Fetch market data for *symbol* and return a standardized DataFrame."""
        ...

    def _standardize(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Ensure the output matches the platform's expected format."""
        df = df.copy()
        df.columns = [c.lower().strip() for c in df.columns]
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataSource {self.name} missing columns: {missing}")
        df["symbol"] = symbol
        return df[required | {"symbol"}]
