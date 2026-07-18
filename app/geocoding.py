"""Fixed-host Nominatim geocoding with bounded, instance-local state."""

from __future__ import annotations
from typing import Optional

import asyncio
import json
import time
from dataclasses import dataclass

import httpx


_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "DFR-Trigger/0.1"
_CACHE_TTL_SECONDS = 300
_MIN_REQUEST_INTERVAL = 1.0
_MAX_RESPONSE_BYTES = 65_536


@dataclass(frozen=True)
class GeocodeResult:
    latitude: float
    longitude: float
    display_name: str


class Geocoder:
    def __init__(
        self,
        timeout_seconds: float = 5.0,
        min_interval_seconds: float = _MIN_REQUEST_INTERVAL,
        max_response_bytes: int = _MAX_RESPONSE_BYTES,
    ) -> None:
        self._timeout = timeout_seconds
        self._min_interval = min_interval_seconds
        self._max_response_bytes = max_response_bytes
        self._cache: dict[str, tuple[Optional[GeocodeResult], float]] = {}
        self._request_lock = asyncio.Lock()
        self._last_request = 0.0

    def _cached(self, key: str) -> Optional[GeocodeResult]:
        cached = self._cache.get(key)
        if cached is None or time.monotonic() >= cached[1]:
            return _CACHE_MISS
        return cached[0]

    async def search(self, query: str) -> Optional[GeocodeResult]:
        if not query or not query.strip():
            raise ValueError("query is required")
        clean_query = query.strip()
        key = clean_query.lower()
        cached = self._cached(key)
        if cached is not _CACHE_MISS:
            return cached

        async with self._request_lock:
            cached = self._cached(key)
            if cached is not _CACHE_MISS:
                return cached
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(self._timeout),
                    follow_redirects=False,
                    headers={"User-Agent": _USER_AGENT},
                ) as client:
                    async with client.stream(
                        "GET",
                        _NOMINATIM_URL,
                        params={"q": clean_query, "format": "jsonv2", "limit": "1"},
                    ) as response:
                        response.raise_for_status()
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > self._max_response_bytes:
                                raise RuntimeError(
                                    "geocoding provider response too large"
                                )
                data = json.loads(content)
            except httpx.HTTPError as exc:
                raise RuntimeError(f"geocoding provider failure: {exc}") from exc
            except (json.JSONDecodeError, TypeError, KeyError, ValueError) as exc:
                raise RuntimeError(
                    "geocoding provider returned invalid data"
                ) from exc
            finally:
                self._last_request = time.monotonic()

            if not isinstance(data, list):
                raise RuntimeError("geocoding provider returned invalid data")
            if not data:
                result = None
            else:
                try:
                    item = data[0]
                    result = GeocodeResult(
                        latitude=float(item["lat"]),
                        longitude=float(item["lon"]),
                        display_name=str(item.get("display_name", "")),
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise RuntimeError(
                        "geocoding provider returned invalid data"
                    ) from exc
            self._cache[key] = (
                result,
                time.monotonic() + _CACHE_TTL_SECONDS,
            )
            return result


_CACHE_MISS = object()
