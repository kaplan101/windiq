import logging
import time
from collections.abc import Callable, Iterator
from datetime import datetime

import httpx

from app.integration.windiq_api.schemas import (
    MastDto,
    MeasurementDto,
    MeasurementPage,
    SiteDto,
    TokenResponse,
    TurbineDto,
)

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
PAGE_SIZE = 500
TOKEN_REFRESH_MARGIN_SECONDS = 60


class WindiqApiError(Exception):
    """Die API war auch nach mehreren Versuchen nicht erreichbar."""


class WindiqApiClient:
    """Zugriff auf die WindIQ-API: Token-Verwaltung, Wiederholungsversuche und Pagination."""

    def __init__(
        self,
        http: httpx.Client,
        client_id: str,
        client_secret: str,
        max_attempts: int = 5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._http = http
        self._client_id = client_id
        self._client_secret = client_secret
        self._max_attempts = max_attempts
        self._sleep = sleep
        self._token: str | None = None
        self._token_valid_until = 0.0

    def get_mast(self) -> MastDto:
        return MastDto.model_validate(self._get_json("/v1/mast"))

    def get_turbine(self) -> TurbineDto:
        return TurbineDto.model_validate(self._get_json("/v1/turbine"))

    def get_site(self) -> SiteDto:
        return SiteDto.model_validate(self._get_json("/v1/site"))

    def iter_measurement_pages(self, updated_since: datetime) -> Iterator[list[MeasurementDto]]:
        """Liefert Seite für Seite alle Messwerte, die sich seit `updated_since` geändert haben."""
        params: dict[str, str | int] = {"updated_since": updated_since.isoformat(), "limit": PAGE_SIZE}
        while True:
            page = MeasurementPage.model_validate(self._get_json("/v1/measurements", params))
            yield page.data
            if page.next_cursor is None:
                return
            params["cursor"] = page.next_cursor

    def _get_json(self, path: str, params: dict | None = None) -> dict:
        response = self._request("GET", path, params=params, headers=self._auth_header())
        if response.status_code == 401:
            # Token abgelaufen oder ungültig: einmal neu anmelden und wiederholen
            self._token = None
            response = self._request("GET", path, params=params, headers=self._auth_header())
        response.raise_for_status()
        return response.json()

    def _auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def _get_token(self) -> str:
        if self._token is None or time.monotonic() >= self._token_valid_until:
            response = self._request(
                "POST",
                "/auth/token",
                json={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            token = TokenResponse.model_validate(response.json())
            self._token = token.access_token
            # Kurz vor Ablauf erneuern, damit kein Request mit abgelaufenem Token losgeht
            self._token_valid_until = time.monotonic() + token.expires_in - TOKEN_REFRESH_MARGIN_SECONDS
        return self._token

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Schickt einen Request; bei Netzwerkfehlern und 429/5xx mit wachsender Pause erneut."""
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                reason = type(exc).__name__
            else:
                if response.status_code not in RETRYABLE_STATUS_CODES:
                    return response
                reason = f"HTTP {response.status_code}"

            if attempt < self._max_attempts:
                delay = 2**attempt
                logger.warning(
                    "%s %s fehlgeschlagen (%s), Versuch %d/%d, nächster in %d s",
                    method, path, reason, attempt, self._max_attempts, delay,
                )
                self._sleep(delay)

        raise WindiqApiError(f"{method} {path} nach {self._max_attempts} Versuchen fehlgeschlagen ({reason})")
