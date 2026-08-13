"""Rate limiter in-memory simple (fenêtre glissante), sans dépendance externe."""
import threading
import time


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int):
        self.max_attempts = max_attempts
        self.window = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        """Retourne (autorisé?, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            lst = self._hits.setdefault(key, [])
            lst[:] = [t for t in lst if now - t < self.window]
            if len(lst) >= self.max_attempts:
                retry = int(self.window - (now - lst[0])) + 1
                return False, retry
            lst.append(now)
            return True, 0

    def clear(self):
        with self._lock:
            self._hits.clear()


def client_ip(request) -> str:
    """IP du client — derrière un reverse proxy local, X-Forwarded-For = l'IP réelle."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"