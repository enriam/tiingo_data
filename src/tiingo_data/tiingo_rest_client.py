"""REST client for Tiingo market data."""

import re
import warnings
from collections.abc import Mapping, Sequence
from datetime import date
from io import StringIO
from types import TracebackType
from typing import Self
from urllib.parse import quote

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

type JSONValue = str | int | float | bool | None | JSONObject | JSONArray
type JSONObject = dict[str, JSONValue]
type JSONArray = list[JSONValue]
type JSON = JSONObject | JSONArray


class TiingoError(Exception):
    """Raised when a Tiingo request or response cannot be processed."""


class TiingoRESTClient:
    """REST client used to connect to and retrieve data from Tiingo.

    With strict=True, invalid column names and failed historical downloads
    raise TiingoError instead of emitting warnings and continuing.
    """

    _AUTH_TEST_URL = "https://api.tiingo.com/api/test/"
    _EOD_BASE_URL = "https://api.tiingo.com/tiingo/daily/"
    _IEX_BASE_URL = "https://api.tiingo.com/iex/"

    _EOD_COLUMNS = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjOpen",
        "adjHigh",
        "adjLow",
        "adjClose",
        "adjVolume",
        "divCash",
        "splitFactor",
    )
    _IEX_HISTORICAL_COLUMNS = ("open", "high", "low", "close", "volume")
    _IEX_LATEST_COLUMNS = (
        "timestamp",
        "quoteTimestamp",
        "lastSaleTimestamp",
        "last",
        "lastSize",
        "tngoLast",
        "prevClose",
        "open",
        "high",
        "low",
        "mid",
        "volume",
        "bidSize",
        "bidPrice",
        "askSize",
        "askPrice",
    )
    _EOD_FREQUENCIES = ("daily", "weekly", "monthly", "annually")
    _INTRADAY_FREQUENCY_PATTERN = re.compile(r"[1-9][0-9]*(?:min|hour)")
    _retry_statuses = (429, 500, 502, 503, 504)

    def __init__(
        self,
        token: str,
        *,
        timeout: float | tuple[float, float] = 30.0,
        retries: int = 3,
        validate_token: bool = True,
        session: requests.Session | None = None,
        strict: bool = False,
    ) -> None:
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string")
        if isinstance(timeout, tuple):
            if len(timeout) != 2 or any(value <= 0 for value in timeout):
                raise ValueError("timeout values must be greater than zero")
        elif timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if retries < 0:
            raise ValueError("retries cannot be negative")

        self._token = token
        self._timeout = timeout
        self._strict = strict
        self._owns_session = session is None
        self._session = session or self._create_session(retries)
        self._session.headers.update(
            {
                "Accept": "application/json, text/csv",
                "Authorization": f"Token {token}",
            }
        )

        if validate_token:
            try:
                self._validate_token()
            except Exception:
                self.close()
                raise

    @classmethod
    def _create_session(cls, retries: int) -> requests.Session:
        retry_policy = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            allowed_methods=frozenset({"GET"}),
            status_forcelist=cls._retry_statuses,
            backoff_factor=0.5,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_policy)
        session = requests.Session()
        session.mount("https://", adapter)
        return session

    def __repr__(self) -> str:
        return "<TiingoRESTClient(https://api.tiingo.com)>"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the internally managed HTTP session."""
        if self._owns_session:
            self._session.close()

    def _redact(self, value: object) -> str:
        return str(value).replace(self._token, "<redacted>")

    def _get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response:
        try:
            response = self._session.get(
                url,
                params=params,
                headers=headers,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise TiingoError("The Tiingo request timed out.") from exc
        except requests.HTTPError as exc:
            status = (
                exc.response.status_code
                if exc.response is not None
                else "unknown"
            )
            raise TiingoError(
                f"Tiingo returned HTTP status {status}."
            ) from exc
        except requests.RequestException as exc:
            raise TiingoError(
                f"Could not connect to Tiingo: {self._redact(exc)}"
            ) from exc
        return response

    def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> JSON:
        response = self._get(url, params=params, headers=headers)
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise TiingoError(
                "Tiingo returned an invalid JSON response."
            ) from exc
        if not isinstance(payload, (dict, list)):
            raise TiingoError("Tiingo returned an unexpected JSON response.")
        return payload

    def _validate_token(self) -> None:
        payload = self._get_json(
            self._AUTH_TEST_URL,
            headers={"Content-Type": "application/json"},
        )
        message = payload.get("message") if isinstance(payload, dict) else None
        if message != "You successfully sent a request":
            detail = self._redact(message or "unexpected response")
            raise TiingoError(
                f"Tiingo rejected the authentication token: {detail}"
            )

    @staticmethod
    def _is_valid_date(str_date: str) -> bool:
        if str_date == "":
            return True
        try:
            return date.fromisoformat(str_date).isoformat() == str_date
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _normalize_tickers(tickers: str | Sequence[str]) -> list[str]:
        if isinstance(tickers, str):
            normalized = [tickers]
        else:
            try:
                normalized = list(tickers)
            except TypeError as exc:
                raise TiingoError(
                    "tickers must be a string or a sequence of strings."
                ) from exc
        if not normalized:
            raise TiingoError("At least one ticker is required.")
        if any(
            not isinstance(ticker, str)
            or not ticker
            or ticker != ticker.strip()
            for ticker in normalized
        ):
            raise TiingoError(
                "Tickers must be non-empty strings without surrounding "
                "whitespace."
            )
        return normalized

    def _validate_cols(
        self, endpoint: str, columns: Sequence[str] | None
    ) -> list[str]:
        if not columns:
            return []
        if isinstance(columns, str):
            raise TiingoError("columns must be a sequence of column names.")

        valid_names_by_endpoint = {
            "eod": self._EOD_COLUMNS,
            "iex_last": self._IEX_LATEST_COLUMNS,
            "iex_hist": self._IEX_HISTORICAL_COLUMNS,
        }
        try:
            valid_names = valid_names_by_endpoint[endpoint]
        except KeyError as exc:
            raise ValueError(f"Unknown endpoint: {endpoint}") from exc

        valid_columns = []
        for column in columns:
            if column in valid_names:
                valid_columns.append(column)
            else:
                message = f'Column name "{column}" is invalid'
                if self._strict:
                    raise TiingoError(f"{message}.")
                warnings.warn(
                    f"{message} and was ignored.",
                    UserWarning,
                    stacklevel=2,
                )
        return valid_columns

    @staticmethod
    def _empty_historical(columns: Sequence[str]) -> pd.DataFrame:
        index = pd.MultiIndex.from_arrays([[], []], names=["ticker", "date"])
        return pd.DataFrame(columns=list(columns), index=index)

    @staticmethod
    def _historical_frame(payload: JSON, ticker: str) -> pd.DataFrame:
        if not isinstance(payload, list) or not all(
            isinstance(record, dict) for record in payload
        ):
            raise TiingoError(
                "Tiingo returned an unexpected historical response "
                f'for "{ticker}".'
            )
        if not payload:
            return pd.DataFrame()

        frame = pd.DataFrame.from_records(payload)
        if "date" not in frame.columns:
            raise TiingoError(
                f'Tiingo response for "{ticker}" does not contain a '
                "date column."
            )
        try:
            frame["date"] = pd.to_datetime(
                frame["date"],
                utc=True,
                errors="raise",
            )
        except (TypeError, ValueError) as exc:
            raise TiingoError(
                f'Tiingo response for "{ticker}" contains invalid dates.'
            ) from exc
        return frame.set_index("date")

    def get_stock_metadata(self, ticker: str) -> JSONObject:
        """Return metadata for one ticker."""
        if not isinstance(ticker, str):
            raise TiingoError("ticker must be a string.")
        ticker = self._normalize_tickers(ticker)[0]
        payload = self._get_json(
            f"{self._EOD_BASE_URL}{quote(ticker, safe='')}"
        )
        if not isinstance(payload, dict):
            raise TiingoError(
                "Tiingo returned an unexpected metadata response "
                f"for '{ticker}'."
            )
        return payload

    def get_stock_historical(
        self,
        tickers: str | Sequence[str],
        frequency: str,
        start: str = "",
        end: str = "",
        columns: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """Return historical data indexed consistently by ticker and date."""
        normalized_tickers = self._normalize_tickers(tickers)

        if not isinstance(frequency, str):
            raise TiingoError("frequency must be a string.")
        if self._INTRADAY_FREQUENCY_PATTERN.fullmatch(frequency):
            endpoint = self._IEX_BASE_URL
            endpoint_name = "iex_hist"
            default_columns = self._IEX_HISTORICAL_COLUMNS
        elif frequency in self._EOD_FREQUENCIES:
            endpoint = self._EOD_BASE_URL
            endpoint_name = "eod"
            default_columns = self._EOD_COLUMNS
        else:
            raise TiingoError(
                f'Invalid resample frequency: "{frequency}". '
                f"Valid end-of-day values are {self._EOD_FREQUENCIES}; "
                "intraday values include 5min, 15min, 1hour, and 4hour."
            )

        valid_columns = self._validate_cols(endpoint_name, columns)
        if not self._is_valid_date(start) or not self._is_valid_date(end):
            raise TiingoError(
                'Invalid date format. Valid format is "YYYY-MM-DD".'
            )
        if (
            start
            and end
            and date.fromisoformat(start) > date.fromisoformat(end)
        ):
            raise TiingoError("start cannot be later than end.")

        params = {"format": "json", "resampleFreq": frequency}
        if valid_columns:
            params["columns"] = ",".join(valid_columns)
        if start:
            params["startDate"] = start
        if end:
            params["endDate"] = end

        data: list[pd.DataFrame] = []
        valid_tickers: list[str] = []
        for ticker in normalized_tickers:
            url = f"{endpoint}{quote(ticker, safe='')}/prices"
            try:
                payload = self._get_json(url, params=params)
                frame = self._historical_frame(payload, ticker)
            except TiingoError as exc:
                if self._strict:
                    raise TiingoError(
                        f'Historical request for "{ticker}" failed: {exc}'
                    ) from exc
                warnings.warn(
                    f'Historical request for "{ticker}" was ignored: {exc}',
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue
            if frame.empty:
                continue
            data.append(frame)
            valid_tickers.append(ticker)

        expected_columns = valid_columns or default_columns
        if not data:
            return self._empty_historical(expected_columns)

        return pd.concat(
            data,
            keys=valid_tickers,
            names=["ticker", "date"],
        )

    def get_stock_last(
        self,
        tickers: str | Sequence[str],
        columns: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """Return the last available IEX data indexed by ticker."""
        normalized_tickers = self._normalize_tickers(tickers)
        params = {
            "tickers": ",".join(normalized_tickers),
            "format": "csv",
        }
        valid_columns = self._validate_cols("iex_last", columns)
        if valid_columns:
            params["columns"] = ",".join(valid_columns)

        response = self._get(self._IEX_BASE_URL, params=params)
        try:
            frame = pd.read_csv(StringIO(response.text))
        except (
            pd.errors.EmptyDataError,
            pd.errors.ParserError,
            ValueError,
        ) as exc:
            raise TiingoError(
                "Tiingo returned an invalid CSV response."
            ) from exc
        if "ticker" not in frame.columns:
            raise TiingoError(
                "Tiingo CSV response does not contain a ticker column."
            )
        return frame.set_index("ticker")
