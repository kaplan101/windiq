from datetime import UTC, datetime

import httpx
import pytest

from app.integration.windiq_api.client import WindiqApiClient, WindiqApiError

SINCE = datetime(2026, 1, 1, tzinfo=UTC)


def measurement(hour: int) -> dict:
    return {
        "timestamp": f"2026-01-01T{hour:02d}:00:00Z",
        "wind_speed": 5.0,
        "unit": "m/s",
        "wind_direction_deg": 180,
        "version": 1,
        "updated_at": f"2026-01-01T{hour:02d}:05:00Z",
    }


class FakeApi:
    """Simuliert die WindIQ-API; `measurement_responses` werden der Reihe nach ausgeliefert."""

    def __init__(self, measurement_responses: list[httpx.Response]):
        self.measurement_responses = measurement_responses
        self.token_requests = 0
        self.measurement_requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            self.token_requests += 1
            return httpx.Response(200, json={"access_token": f"token-{self.token_requests}", "token_type": "Bearer", "expires_in": 3600})
        self.measurement_requests.append(request)
        return self.measurement_responses.pop(0)


def make_client(api: FakeApi, max_attempts: int = 5) -> WindiqApiClient:
    http = httpx.Client(base_url="https://api.test", transport=httpx.MockTransport(api.handle))
    return WindiqApiClient(http, "id", "secret", max_attempts=max_attempts, sleep=lambda seconds: None)


def page(hours: list[int], next_cursor: str | None) -> httpx.Response:
    return httpx.Response(200, json={"data": [measurement(h) for h in hours], "next_cursor": next_cursor})


def test_follows_cursor_until_last_page():
    api = FakeApi([page([0, 1], "c1"), page([2], None)])

    pages = list(make_client(api).iter_measurement_pages(SINCE))

    assert [len(p) for p in pages] == [2, 1]
    assert "cursor" not in api.measurement_requests[0].url.params
    assert api.measurement_requests[1].url.params["cursor"] == "c1"
    assert api.measurement_requests[1].url.params["updated_since"] == SINCE.isoformat()


def test_reuses_token_across_requests():
    api = FakeApi([page([0], "c1"), page([1], None)])

    list(make_client(api).iter_measurement_pages(SINCE))

    assert api.token_requests == 1
    assert all(r.headers["Authorization"] == "Bearer token-1" for r in api.measurement_requests)


def test_retries_on_503_and_succeeds():
    api = FakeApi([httpx.Response(503), httpx.Response(503), page([0], None)])

    pages = list(make_client(api).iter_measurement_pages(SINCE))

    assert len(pages) == 1
    assert len(api.measurement_requests) == 3


def test_gives_up_after_max_attempts():
    api = FakeApi([httpx.Response(503)] * 3)

    with pytest.raises(WindiqApiError):
        list(make_client(api, max_attempts=3).iter_measurement_pages(SINCE))


def test_refreshes_token_once_on_401():
    api = FakeApi([httpx.Response(401), page([0], None)])

    pages = list(make_client(api).iter_measurement_pages(SINCE))

    assert len(pages) == 1
    assert api.token_requests == 2
    assert api.measurement_requests[1].headers["Authorization"] == "Bearer token-2"


def test_does_not_retry_client_errors():
    api = FakeApi([httpx.Response(422)])

    with pytest.raises(httpx.HTTPStatusError):
        list(make_client(api).iter_measurement_pages(SINCE))

    assert len(api.measurement_requests) == 1
