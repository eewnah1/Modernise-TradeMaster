# Modernise-TradeMaster Data Extensions

This directory contains a lightweight, pluggable scaffold for adding your own market data sources to the Modernise-TradeMaster platform.

## Quick Start

1. Subclass `data_extensions.sources.DataSource`.
2. Implement `fetch(symbol, start, end, interval)` returning a `pandas.DataFrame` with columns:
   `date`, `open`, `high`, `low`, `close`, `volume`.
3. Register your source in the experiment config or import it directly.

## Included Example

`data_extensions/sources/yahoo.py` provides `YahooFinanceSource`, a sample adapter around `yfinance`.
Install the optional dependency with:

```bash
pip install yfinance
```

## Design Notes

- The platform standardizes on OHLCV DataFrames indexed by `date`.
- All sources are expected to handle timezone conversion and missing-value imputation at the data-acquisition layer, or return raw data and let `data/CSDI` handle imputation.
- Keep each source in its own file under `sources/` so new backends (SQL, broker APIs, flat files, crypto exchanges) can be added without modifying core code.
