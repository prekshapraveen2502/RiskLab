import pandas as pd
import yfinance as yf


class YFinanceProvider:
    def get_daily_prices(
        self,
        tickers: list[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        data = yf.download(
            tickers=tickers,
            start=start_date,
            end=end_date,
            interval="1d",
            auto_adjust=True,
            progress=False,
        )

        if data.empty:
            raise ValueError(
                f"No data returned for {tickers} between {start_date} and {end_date}"
            )

        prices = data["Close"].copy()
        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=tickers[0])

        prices.index = pd.to_datetime(prices.index)
        return prices.sort_index()
