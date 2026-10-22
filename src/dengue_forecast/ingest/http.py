"""Cliente HTTP com rate limit, retries e User-Agent educado."""

from __future__ import annotations

import time
from collections.abc import Mapping
from threading import Lock

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from dengue_forecast.config import Settings, get_settings
from dengue_forecast.logging_setup import get_logger

log = get_logger(__name__)


class RateLimiter:
    """Token-bucket simples (por processo)."""

    def __init__(self, rps: float) -> None:
        self._min_interval = 1.0 / max(rps, 0.1)
        self._lock = Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last = time.monotonic()


class HttpClient:
    """Wrapper httpx com retries e rate limiting."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._limiter = RateLimiter(self.settings.rate_limit_rps)
        self._client = httpx.Client(
            timeout=self.settings.http_timeout_s,
            headers={"User-Agent": self.settings.user_agent},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_text(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> str:
        return self._request("GET", url, params=params, headers=headers).text

    def get_bytes(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return self._request("GET", url, params=params, headers=headers).content

    def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        return self._request("GET", url, params=params, headers=headers).json()

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str | int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        @retry(
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            wait=wait_exponential_jitter(initial=1, max=30),
            stop=stop_after_attempt(self.settings.http_max_retries),
            reraise=True,
        )
        def _do() -> httpx.Response:
            self._limiter.wait()
            log.debug("http_request", method=method, url=url, params=dict(params or {}))
            resp = self._client.request(method, url, params=params, headers=headers)
            if resp.status_code in {429, 500, 502, 503, 504}:
                resp.raise_for_status()
            resp.raise_for_status()
            return resp

        return _do()
