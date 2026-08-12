"""Sample Yahoo Finance data source for the data-extension scaffold."""

from datetime import datetime
from typing import Optional

import pandas as pd

try:
    import yfinance as yf
except ImportError as _exc:  # pragma: no cover
    yf = None  # type: ignore

from data_extensions.sources.base import DataSource


class YahooFinanceSource(DataSource):
    """Fetch OHLCV data from Yahoo Finance using the ``yfinance`` package."""

    name = "yahoo_finance"

    def fetch(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if yf is None:
            raise ImportError(
                "YahooFinanceSource requires yfinance. Install with: pip install yfinance"
            )

        ticker = yf.Ticker(symbol)
        df = ticker.history(
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval=interval,
            auto_adjust=False,
        )
        if df is None or df.empty:
            raise ValueError(f"No data returned for {symbol}")

        df = df.reset_index()
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]
        # Rename common Yahoo columns to the platform standard.
        if "adj_close" in df.columns:
            df = df.rename(columns={"adj_close": "adj_close"})
        if "date" not in df.columns and "datetime" in df.columns:
            df = df.rename(columns={"datetime": "date"})
        return self._standardize(df, symbol)


class YahooTickerListSource(DataSource):
    """Fetch a list of tickers from a Yahoo-style CSV or watchlist file."""

    name = "yahoo_ticker_list"

    def fetch(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
    ) -> pd.DataFrame:
        # This is a stub for batch / universe loading; implement as needed.
        raise NotImplementedError("Use YahooFinanceSource for per-ticker downloads.")
