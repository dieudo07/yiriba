"""Yiriba SaaS — In-memory rate limiting middleware.

Implémente un limiteur par fenêtre fixe (IP, et IP+email sur le login).
Les buckets vivent en mémoire : suffisant pour un nœud unique.
À remplacer par un stockage partagé (Redis) en mode multi-nœuds.
"""

import logging
import re
import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("yiriba")

_RATIO_RE = re.compile(r"^(\d+)\s*/\s*(\d+)\s*(s|m|h|d)?$")


def parse_rate(spec: str) -> tuple[int, float]:
    """Parse '10/minute' -> (max_requests, window_seconds).

    '0' (ou tout ratio débutant par 0) désactive le limiteur.
    """
    cleaned = spec.strip().lower()
    m = _RATIO_RE.match(cleaned)
    if not m:
        if cleaned in ("0", "0/", "0/min", "0/s"):
            return 0, 60.0
        return 100, 60.0
    count = int(m.group(1))
    if count <= 0:
        return 0, 60.0
    period = int(m.group(2))
    unit = m.group(3) or "s"
    seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return count, seconds * period


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window limiter.

    - /api/auth/* : limité par IP (settings.RATE_LIMIT_LOGIN).
    - Autres /api/* : limité par IP (settings.RATE_LIMIT_API).
    """

    def __init__(self, app, login_rate: str = "5/minute", api_rate: str = "60/minute") -> None:
        super().__init__(app)
        self.login_limit, self.login_window = parse_rate(login_rate)
        self.api_limit, self.api_window = parse_rate(api_rate)
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = __import__("threading").Lock()

    def _check(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = [t for t in self._buckets[key] if now - t < window]
            if len(hits) >= limit:
                self._buckets[key] = hits
                return False
            hits.append(now)
            self._buckets[key] = hits
            return True

    async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path.startswith("/api/"):
            ip = request.client.host if request.client else "unknown"
            is_login = path.startswith("/api/auth/")
            limit = self.login_limit if is_login else self.api_limit
            window = self.login_window if is_login else self.api_window

            # Un quota de 0 désactive le limitateur (ex. environnement de test).
            if limit > 0:
                key = f"{ip}{'/auth' if is_login else '/api'}"

                if not self._check(key, limit, window):
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Trop de requêtes. Réessayez dans quelques minutes."},
                    )
        return await call_next(request)
