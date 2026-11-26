# tiingo-data

`tiingo-data` is a Python library for downloading stock and ETF market data
from the Tiingo REST API. Use it to look up instrument metadata, retrieve
end-of-day or intraday price history, and fetch the latest available IEX
quotes. Price and quote data are returned as pandas DataFrames.

The library uses Tiingo's End-of-Day and IEX endpoints. Access and data
availability depend on your Tiingo account.


## Quick start

Get a token from your [Tiingo account](https://www.tiingo.com/documentation/general/connecting)
and set the `TIINGO_API_TOKEN` environment variable before running the examples.
Keep the token out of source code and version control. The examples read it from
the environment and pass it to the client explicitly.

```python
import os

from tiingo_data import TiingoRESTClient

with TiingoRESTClient(os.environ["TIINGO_API_TOKEN"]) as client:
    prices = client.get_stock_historical(
        tickers=["SPY", "TLT"],
        frequency="daily",
        start="2024-01-02",
        end="2024-01-05",
        columns=["open", "high", "low", "close", "adjClose"],
    )

print(prices.head())
print(prices["adjClose"].unstack("ticker"))
```

The historical DataFrame has a two-level index named `ticker` and `date`,
even when you request one ticker or one price column. Dates are parsed as
UTC timestamps. The last line reshapes adjusted closing prices into one
column per returned ticker and one row per date.

## API overview

All methods are available on `TiingoRESTClient`, imported from `tiingo_data`.

| Method | Returns |
| --- | --- |
| `get_stock_metadata(ticker)` | A dictionary of Tiingo metadata for one ticker. |
| `get_stock_historical(tickers, frequency, start="", end="", columns=None)` | A DataFrame indexed by `(ticker, date)`. |
| `get_stock_last(tickers, columns=None)` | A DataFrame of the latest available IEX data, indexed by `ticker`. |

### Historical prices

- Pass a ticker string or a sequence of ticker strings.
- Choose `daily`, `weekly`, `monthly`, or `annually` for end-of-day data.
  For IEX intraday data, use an interval such as `5min` or `1hour`.
- Specify `start` and `end` as `YYYY-MM-DD` strings. Omit either bound to
  use Tiingo's default for that bound. When both are supplied, `start` must
  be on or before `end`.
- Pass a sequence of field names to select columns, or omit `columns` to
  use Tiingo's default fields. For end-of-day data, `close` is the raw
  close and `adjClose` is the adjusted close. Intraday history supports
  `open`, `high`, `low`, `close`, and `volume`.

Prices for multiple tickers are retrieved one ticker at a time. A successful
response with no observations is valid. An empty historical result still has
the named two-level index.

### Metadata and latest quotes

Metadata can include the instrument name, exchange code, and dates for which
historical data is available. Use `get_stock_last()` with a single ticker or
a sequence to retrieve the latest available values from IEX.

```python
import os

from tiingo_data import TiingoRESTClient

with TiingoRESTClient(os.environ["TIINGO_API_TOKEN"]) as client:
    metadata = client.get_stock_metadata("SPY")
    quotes = client.get_stock_last(["SPY", "TLT"])

print(metadata.get("name"))
print(quotes.head())
```

## Error handling

| Situation | Default behavior | With `strict=True` |
| --- | --- | --- |
| An invalid column name is supplied | Emit a `UserWarning` and ignore that name. If no valid columns remain, use Tiingo's default fields. | Raise `TiingoError` before sending the data request. |
| A ticker's historical request fails or its response cannot be parsed | Emit a `RuntimeWarning` and continue with the remaining tickers. The result may be partial or empty. | Raise `TiingoError` for the first failure without returning partial results. |
| A valid historical response contains no observations | Accept the response as empty. | Accept the response as empty. |

Failures during the initial token check, invalid date ranges, and failed
metadata or latest quote requests raise `TiingoError` in either mode.
Import it from `tiingo_data` to handle these failures in your application.

## Client configuration

```python
import os

from tiingo_data import TiingoRESTClient

with TiingoRESTClient(
    os.environ["TIINGO_API_TOKEN"],
    timeout=(5, 30),
    retries=2,
    strict=True,
) as client:
    prices = client.get_stock_historical("SPY", frequency="daily")
```

- **`timeout`** is 30 seconds by default. Pass a number or a
  `(connect_timeout, read_timeout)` tuple in seconds.
- **`retries`** defaults to three for the built-in HTTP session. It applies
  to retryable GET failures, including HTTP 429 and selected 5xx responses.
  The retry policy respects `Retry-After` when applicable.
- **`validate_token`** defaults to `True` and checks the token when the
  client is created. Set it to `False` to skip that initial request.
- **`session`** accepts a caller-managed `requests.Session`. The client
  adds its authentication and accept headers to the session. The caller
  manages its retry policy and closes it.

The built-in session reuses HTTP connections. Use the client as a context
manager to close that session automatically, or call `client.close()` when
you're done.

## Development

From the repository root, run the unit tests with uv:

```bash
uv run --locked python -m unittest discover -s tests
```

The tests use simulated HTTP responses and run without a Tiingo token.

## References

- [Tiingo End-of-Day API documentation](https://www.tiingo.com/documentation/end-of-day)
- [Tiingo API overview and data usage terms](https://www.tiingo.com/documentation/general/overview)

## License
The source code is released under the [MIT License](LICENSE.md). Market
data obtained through the API is subject to Tiingo's terms.
