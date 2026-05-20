"""HTTP helpers for live-safe MLB source fetches."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

import requests

TRANSIENT_HTTP_STATUS_CODES = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524})


def request_with_retries(
    session: requests.Session | None,
    method: str,
    url: str,
    *,
    timeout: int | float,
    retries: int | None = None,
    backoff_seconds: float | None = None,
    transient_status_codes: set[int] | frozenset[int] | None = None,
    **kwargs: Any,
) -> requests.Response:
    """Run a bounded HTTP request with retry for transient network/provider failures."""

    attempts = max(1, 1 + _env_int("ATLAS_MLB_FETCH_RETRIES", 2) if retries is None else 1 + int(retries))
    backoff = _env_float("ATLAS_MLB_FETCH_BACKOFF_S", 0.75) if backoff_seconds is None else float(backoff_seconds)
    transient_codes = transient_status_codes or TRANSIENT_HTTP_STATUS_CODES
    client = session or requests.Session()
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        response: requests.Response | None = None
        try:
            response = client.request(method.upper(), url, timeout=timeout, **kwargs)
            if response.status_code not in transient_codes:
                return response
            try:
                response.raise_for_status()
            except requests.HTTPError as exc:
                last_exc = exc
            if attempt >= attempts:
                return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
        _sleep_before_retry(attempt=attempt, backoff=backoff, response=response)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"HTTP request failed without response: {method} {url}")


def get_with_retries(
    url: str,
    *,
    session: requests.Session | None = None,
    timeout: int | float,
    retries: int | None = None,
    backoff_seconds: float | None = None,
    **kwargs: Any,
) -> requests.Response:
    return request_with_retries(
        session,
        "GET",
        url,
        timeout=timeout,
        retries=retries,
        backoff_seconds=backoff_seconds,
        **kwargs,
    )


def _sleep_before_retry(*, attempt: int, backoff: float, response: requests.Response | None) -> None:
    if backoff <= 0:
        return
    retry_after = _retry_after_seconds(response.headers if response is not None else {})
    sleep_for = retry_after if retry_after is not None else backoff * attempt
    if sleep_for > 0:
        time.sleep(min(sleep_for, _env_float("ATLAS_MLB_FETCH_MAX_BACKOFF_S", 8.0)))


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    value = str(headers.get("Retry-After") or "").strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
