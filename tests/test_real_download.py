import os

from tiingo_data import TiingoRESTClient

with TiingoRESTClient(
    os.environ["tiingo_api_key"], validate_token=True
) as client:
    prices = client.get_stock_historical(
        tickers=["SPY", "TLT"],
        frequency="daily",
        start="2002-07-18",
        end="2002-07-30",
        columns=["open", "high", "low", "close", "adjClose"],
    )

print(prices.head())
print(prices["adjClose"].unstack("ticker"))
