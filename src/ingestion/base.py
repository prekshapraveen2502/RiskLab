from typing import Protocol

import pandas as pd


class MarketDataProvider(Protocol):
    def get_daily_prices(
        self,
        tickers: list[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Return daily prices indexed by date with one column per ticker."""
        ...
