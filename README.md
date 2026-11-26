# Tiingo Rest Client For Stock Prices

A very simple python REST client for Tiingo's financial markets API. It can be used to retrieve historical and current prices only for stocks and ETFs, but not for crypto or forex so far.

I use this piece of code as a  tool to retrieve historical prices for my own research and analysis of investment strategies. This does not pretend to be a professional grade application, only an easy-to-use tool that can make the job if you just need to download stock prices for your own use.

## Usage

You will need a API Token which you can obtain for free if you register at [tiingo.com](https://tiingo.com).

Data is downloaded to a pandas DataFrame, as in the following example:

                                        open     high      low   close
    ticker date
    spy    2022-03-01 00:00:00+00:00  435.04  437.170  427.110  429.98
           2022-03-02 00:00:00+00:00  432.37  439.720  431.570  437.89
           2022-03-03 00:00:00+00:00  440.47  441.110  433.800  435.71
           2022-03-04 00:00:00+00:00  431.75  433.370  427.880  432.17
    tlt    2022-03-01 00:00:00+00:00  140.36  142.330  140.000  141.30
           2022-03-02 00:00:00+00:00  139.84  140.420  136.410  136.47
           2022-03-03 00:00:00+00:00  137.49  138.700  137.020  137.86
           2022-03-04 00:00:00+00:00  140.36  140.825  139.305  140.24

There are three main methods:  

        get_stock_metadata(...)
        get_stock_historical(...)
        get_stock_last(...)

The first one will retreive info about the stock instrument, like the start and end dates of available price data, instrument description, the Exchange it is listed on, etc.

The other two will retrieve, respectively, end of day historical data between two dates and last traded price.

## Example of usage

    from tiingo_data import TiingoRESTClient

    tii_client = TiingoRESTClient("YOUR_API_TOKEN")

    data = tii_client.get_stock_historical(
        tickers=["spy", "tlt"],
        frequency="daily",
        columns=["open", "high", "low", "close"],
        start="2022-03-01",
        end="2022-03-31",
    )

Historical results always use a `ticker`/`date` MultiIndex, including requests
for a single ticker or a single column. Empty results preserve the same index
and requested-column schema.

The client uses a persistent HTTP session, a 30-second timeout, and up to three
retries for rate limits and transient server errors. These values can be
configured when creating the client:

    tii_client = TiingoRESTClient(
        "YOUR_API_TOKEN",
        timeout=15,
        retries=2,
    )

The client can also be used as a context manager to close its HTTP session:

    with TiingoRESTClient("YOUR_API_TOKEN") as tii_client:
        data = tii_client.get_stock_historical("spy", frequency="daily")

By default, invalid column names are ignored with a warning. If a historical
download fails for a ticker, the client warns and continues with the others.

Use `TiingoRESTClient("YOUR_API_TOKEN", strict=True)` to raise `TiingoError`
on an invalid column before sending a data request, or on the first failed
historical download instead of returning partial results. A successful
response with no observations is valid in both modes.

The resample frequency is validated before requesting data.

Dates must be strings with this format: "YYYY-MM-DD".

## Aditional info

You can find more detailed information about the type of data you can retrieve in tiingo's [API documentation](https://api.tiingo.com/documentation/general/overview).

Additionally, you may want to consider one of their [pricing plans](https://api.tiingo.com/about/pricing) if you are thinking of making a more intensive use of data.
