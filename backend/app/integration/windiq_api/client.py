import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime

import httpx
from pydantic import ValidationError

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


@dataclass(frozen=True)
class MeasurementBatch:
    """Eine Seite Messwerte: die lesbaren Datensätze und die Anzahl übersprungener, unlesbarer."""

    valid: list[MeasurementDto]
    skipped: int


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

    def iter_measurement_pages(self, updated_since: datetime) -> Iterator[MeasurementBatch]:
        """Liefert Seite für Seite alle Messwerte, die sich seit `updated_since` geändert haben."""
        params: dict[str, str | int] = {"updated_since": updated_since.isoformat(), "limit": PAGE_SIZE}
        while True:
            page = MeasurementPage.model_validate(self._get_json("/v1/measurements", params))
            yield self._parse_records(page.data)
            if page.next_cursor is None:
                return
            params["cursor"] = page.next_cursor

    @staticmethod
    def _parse_records(records: list[dict]) -> MeasurementBatch:
        # Jeden Datensatz einzeln prüfen: Ein unlesbarer darf nicht die ganze Seite – und damit jeden
        # weiteren Sync – blockieren. Korrigiert die API ihn später, kommt er mit neuem updated_at erneut.
        valid, skipped = [], 0
        for record in records:
            try:
                valid.append(MeasurementDto.model_validate(record))
            except ValidationError as exc:
                skipped += 1
                logger.warning("Unlesbaren Messwert übersprungen: %s – %s", record, describe_error(exc))
        return MeasurementBatch(valid, skipped)

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


def describe_error(exc: Exception) -> str:
    """Kurze, lesbare Fehlerbeschreibung – bei Prüffehlern das erste betroffene Feld, z. B. 'losses.availability: …'."""
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"]) or "Datensatz"
        return f"{field}: {first['msg']}"
    return f"{type(exc).__name__}: {exc}"
