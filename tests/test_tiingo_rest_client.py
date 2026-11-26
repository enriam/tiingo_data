import unittest

import pandas as pd
import requests

from tiingo_data import TiingoError, TiingoRESTClient


class FakeResponse:
    def __init__(self, *, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    def __init__(self, responses=()):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []
        self.closed = False

    def get(self, url, *, params=None, timeout=None):
        self.calls.append(
            {"url": url, "params": params, "timeout": timeout}
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def close(self):
        self.closed = True


class TiingoRESTClientTests(unittest.TestCase):
    token = "secret-token"

    def make_client(self, responses=(), **kwargs):
        session = FakeSession(responses)
        client = TiingoRESTClient(
            self.token,
            validate_token=False,
            session=session,
            **kwargs,
        )
        return client, session

    def test_token_validation_uses_authorization_header_not_query_string(self):
        response = FakeResponse(
            payload={"message": "You successfully sent a request"}
        )
        session = FakeSession([response])

        TiingoRESTClient(self.token, session=session)

        self.assertEqual(
            session.calls[0]["url"],
            "https://api.tiingo.com/api/test/",
        )
        self.assertIsNone(session.calls[0]["params"])
        self.assertEqual(
            session.headers["Authorization"],
            f"Token {self.token}",
        )

    def test_http_error_does_not_expose_token(self):
        client, _ = self.make_client(
            [FakeResponse(status_code=401)],
        )

        with self.assertRaises(TiingoError) as context:
            client.get_stock_metadata("spy")

        self.assertNotIn(self.token, str(context.exception))
        self.assertIn("401", str(context.exception))

    def test_rejected_token_is_redacted_from_error(self):
        response = FakeResponse(
            payload={"message": f"Rejected token {self.token}"}
        )
        session = FakeSession([response])

        with self.assertRaises(TiingoError) as context:
            TiingoRESTClient(self.token, session=session)

        self.assertNotIn(self.token, str(context.exception))
        self.assertIn("<redacted>", str(context.exception))

    def test_invalid_json_is_translated_to_tiingo_error(self):
        client, _ = self.make_client(
            [FakeResponse(payload=ValueError("invalid JSON"))],
        )

        with self.assertRaisesRegex(TiingoError, "invalid JSON"):
            client.get_stock_metadata("spy")

    def test_timeout_is_translated_to_tiingo_error(self):
        client, _ = self.make_client(
            [requests.Timeout(f"timeout for {self.token}")],
        )

        with self.assertRaisesRegex(TiingoError, "timed out"):
            client.get_stock_metadata("spy")

    def test_strict_mode_rejects_invalid_columns_before_requesting_data(self):
        client, session = self.make_client(strict=True)

        with self.assertRaisesRegex(TiingoError, '"clsoe" is invalid'):
            client.get_stock_historical(
                "spy", "daily", columns=["close", "clsoe"]
            )
        with self.assertRaisesRegex(TiingoError, '"clsoe" is invalid'):
            client.get_stock_last("spy", columns=["last", "clsoe"])

        self.assertEqual(session.calls, [])

    def test_strict_mode_stops_at_first_failed_historical_download(self):
        payload = [{"date": "2024-01-02", "close": 10.0}]
        client, session = self.make_client(
            [FakeResponse(payload=payload), FakeResponse(status_code=503)],
            strict=True,
        )

        with self.assertRaisesRegex(TiingoError, '"tlt" failed:.*503'):
            client.get_stock_historical(["spy", "tlt", "qqq"], "daily")

        self.assertEqual(len(session.calls), 2)

    def test_default_mode_warns_and_keeps_successful_downloads(self):
        payload = [{"date": "2024-01-02", "close": 10.0}]
        client, _ = self.make_client(
            [FakeResponse(status_code=503), FakeResponse(payload=payload)]
        )

        with self.assertWarnsRegex(RuntimeWarning, '"tlt".*503'):
            frame = client.get_stock_historical(["tlt", "spy"], "daily")

        self.assertEqual(
            frame.index.get_level_values("ticker").tolist(), ["spy"]
        )

    def test_strict_mode_accepts_valid_empty_historical_response(self):
        client, _ = self.make_client(
            [FakeResponse(payload=[])], strict=True
        )

        frame = client.get_stock_historical("spy", "daily", columns=["close"])

        self.assertTrue(frame.empty)
        self.assertEqual(frame.columns.tolist(), ["close"])

    def test_historical_output_always_uses_ticker_date_multiindex(self):
        first = [
            {"date": "2024-01-02T00:00:00Z", "close": 10.0},
            {"date": "2024-01-03T00:00:00Z", "close": 11.0},
        ]
        second = [
            {"date": "2024-01-02T00:00:00Z", "close": 20.0},
        ]
        client, session = self.make_client(
            [
                FakeResponse(payload=first),
                FakeResponse(payload=second),
            ]
        )

        with self.assertWarnsRegex(UserWarning, '"not-a-column" is invalid'):
            frame = client.get_stock_historical(
                ["spy", "tlt"],
                "daily",
                columns=["close", "not-a-column"],
            )

        self.assertEqual(frame.index.names, ["ticker", "date"])
        self.assertEqual(frame.columns.tolist(), ["close"])
        self.assertEqual(
            frame.loc[
                ("spy", pd.Timestamp("2024-01-02", tz="UTC")),
                "close",
            ],
            10.0,
        )
        self.assertEqual(
            session.calls[0]["params"],
            {
                "format": "json",
                "resampleFreq": "daily",
                "columns": "close",
            },
        )

    def test_single_ticker_uses_same_historical_shape(self):
        payload = [{"date": "2024-01-02", "close": 10.0}]
        client, _ = self.make_client([FakeResponse(payload=payload)])

        frame = client.get_stock_historical(
            "spy",
            "daily",
            columns=["close"],
        )

        self.assertEqual(frame.index.names, ["ticker", "date"])
        self.assertEqual(frame.index.get_level_values("ticker").tolist(), ["spy"])

    def test_empty_historical_response_has_stable_schema(self):
        client, _ = self.make_client([FakeResponse(payload=[])])

        frame = client.get_stock_historical(
            "spy",
            "daily",
            columns=["close"],
        )

        self.assertTrue(frame.empty)
        self.assertEqual(frame.index.names, ["ticker", "date"])
        self.assertEqual(frame.columns.tolist(), ["close"])

    def test_malformed_historical_response_is_ignored_safely(self):
        client, _ = self.make_client(
            [FakeResponse(payload=[{"close": 10.0}])]
        )

        with self.assertWarnsRegex(RuntimeWarning, "date column"):
            frame = client.get_stock_historical(
                "spy",
                "daily",
                columns=["close"],
            )

        self.assertTrue(frame.empty)
        self.assertEqual(frame.index.names, ["ticker", "date"])

    def test_ticker_path_is_encoded_and_query_uses_params(self):
        payload = [{"date": "2024-01-02", "close": 10.0}]
        client, session = self.make_client([FakeResponse(payload=payload)])

        client.get_stock_historical(
            "BRK/A",
            "daily",
            start="2024-01-01",
            end="2024-01-31",
        )

        self.assertTrue(session.calls[0]["url"].endswith("BRK%2FA/prices"))
        self.assertEqual(session.calls[0]["params"]["startDate"], "2024-01-01")
        self.assertEqual(session.calls[0]["params"]["endDate"], "2024-01-31")

    def test_start_cannot_be_later_than_end(self):
        client, session = self.make_client()

        with self.assertRaisesRegex(TiingoError, "start cannot"):
            client.get_stock_historical(
                "spy",
                "daily",
                start="2024-02-01",
                end="2024-01-01",
            )

        self.assertEqual(session.calls, [])

    def test_historical_rejects_dates_outside_documented_format(self):
        client, session = self.make_client()

        for start in ("20240101", "2024-W01-1", "2024-02-30"):
            with self.subTest(start=start):
                with self.assertRaisesRegex(TiingoError, "YYYY-MM-DD"):
                    client.get_stock_historical("spy", "daily", start=start)

        self.assertEqual(session.calls, [])

    def test_invalid_frequency_is_rejected_before_request(self):
        client, session = self.make_client()

        for frequency in (None, "0min"):
            with self.subTest(frequency=frequency):
                with self.assertRaises(TiingoError):
                    client.get_stock_historical("spy", frequency)

        self.assertEqual(session.calls, [])

    def test_metadata_requires_one_ticker_string(self):
        client, session = self.make_client()

        with self.assertRaisesRegex(TiingoError, "ticker must be a string"):
            client.get_stock_metadata(["spy", "tlt"])

        self.assertEqual(session.calls, [])

    def test_historical_rejects_mixed_record_shapes(self):
        payload = [{"date": "2024-01-02", "close": 10.0}, None]
        valid = [{"date": "2024-01-02", "close": 20.0}]
        client, _ = self.make_client(
            [FakeResponse(payload=payload), FakeResponse(payload=valid)]
        )

        with self.assertWarnsRegex(RuntimeWarning, "historical response"):
            frame = client.get_stock_historical(["spy", "tlt"], "daily")

        self.assertEqual(
            frame.index.get_level_values("ticker").tolist(), ["tlt"]
        )

    def test_tickers_must_be_a_string_or_sequence(self):
        client, session = self.make_client()

        with self.assertRaisesRegex(TiingoError, "tickers must"):
            client.get_stock_historical(None, "daily")

        self.assertEqual(session.calls, [])

    def test_columns_cannot_be_one_string(self):
        client, session = self.make_client()

        with self.assertRaisesRegex(TiingoError, "columns must"):
            client.get_stock_historical("spy", "daily", columns="close")

        self.assertEqual(session.calls, [])

    def test_invalid_csv_schema_is_rejected(self):
        client, _ = self.make_client(
            [FakeResponse(text='{"message": "error"}')]
        )

        with self.assertRaisesRegex(TiingoError, "ticker column"):
            client.get_stock_last("spy")

    def test_context_manager_does_not_close_injected_session(self):
        session = FakeSession()

        with TiingoRESTClient(
            self.token,
            validate_token=False,
            session=session,
        ):
            pass

        self.assertFalse(session.closed)

    def test_default_session_has_retry_policy(self):
        client = TiingoRESTClient(
            self.token,
            validate_token=False,
            retries=2,
        )
        self.addCleanup(client.close)

        retry_policy = client._session.get_adapter("https://").max_retries
        self.assertEqual(retry_policy.total, 2)
        self.assertEqual(
            set(retry_policy.status_forcelist),
            {429, 500, 502, 503, 504},
        )


if __name__ == "__main__":
    unittest.main()
