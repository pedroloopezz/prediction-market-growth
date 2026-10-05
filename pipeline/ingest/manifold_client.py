"""Thin client for Manifold's public REST API.

Three responsibilities, nothing more:
  1. Rate limiting: never send requests faster than MIN_SECONDS_BETWEEN_REQUESTS, even when
     several threads share one client (a lock hands out request slots one at a time).
  2. Retries: exponential backoff with jitter on 429, 5xx and network errors, bounded attempts.
  3. Pagination: walk /markets with the `before=<last id>` cursor.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx

from pipeline.config import MANIFOLD_BASE_URL, MIN_SECONDS_BETWEEN_REQUESTS

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ManifoldClient:
    def __init__(
        self,
        base_url: str = MANIFOLD_BASE_URL,
        min_interval: float = MIN_SECONDS_BETWEEN_REQUESTS,
        max_attempts: int = 6,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,  # injected in tests
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": "predmarket-pipeline (personal research project)"},
        )
        self._min_interval = min_interval
        self._max_attempts = max_attempts
        self._last_request = 0.0
        self._lock = threading.Lock()
        self.n_requests = 0

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ManifoldClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- core request with rate limit + retries -------------------------------------------
    def _wait_for_slot(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()
            self.n_requests += 1

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(1, self._max_attempts + 1):
            self._wait_for_slot()
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                error = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code not in RETRYABLE_STATUS:
                    resp.raise_for_status()
                error = f"HTTP {resp.status_code}"
            if attempt == self._max_attempts:
                raise RuntimeError(f"GET {path} failed after {attempt} attempts ({error})")
            # 1s, 2s, 4s, 8s, ... plus jitter so retries don't synchronise
            backoff = 2 ** (attempt - 1) + random.uniform(0, 0.5)
            log.warning("GET %s -> %s; retry %d in %.1fs", path, error, attempt, backoff)
            time.sleep(backoff)
        raise AssertionError("unreachable")

    # ---- endpoints ---------------------------------------------------------------------------
    def iter_market_pages(self, page_size: int = 1000) -> Iterator[list[dict]]:
        """Yield pages of lite markets, newest first, until the API runs out."""
        before: str | None = None
        while True:
            params: dict[str, Any] = {"limit": page_size}
            if before:
                params["before"] = before
            page = self.get("/markets", params)
            if not page:
                return
            yield page
            if len(page) < page_size:
                return
            before = page[-1]["id"]

    def get_market(self, market_id: str) -> dict:
        """Full market: adds topics (groupSlugs) and answers for multi-outcome markets."""
        return self.get(f"/market/{market_id}")

    def get_last_bet_before(self, contract_id: str, before_ms: int) -> dict | None:
        """Most recent bet strictly before `before_ms` (bets are returned newest first)."""
        bets = self.get("/bets", {"contractId": contract_id, "beforeTime": before_ms, "limit": 1})
        return bets[0] if bets else None
