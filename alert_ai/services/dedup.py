import logging

from cachetools import TTLCache

from alert_ai.models import AlertGroup

logger = logging.getLogger(__name__)


class AlertDeduplicator:
    """Suppresses duplicate Alertmanager webhook firings within a TTL window.

    Cache key encodes groupKey + status + sorted alert fingerprints so that:
    - The same firing group re-sent within the TTL is suppressed.
    - A status change (e.g. firing → resolved) is always forwarded.
    - A group whose alert set changes (new fingerprint added) is re-analysed.
    """

    def __init__(self, ttl_seconds: int, maxsize: int = 1024) -> None:
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_seconds)

    def _make_key(self, alert_group: AlertGroup) -> str:
        fingerprints = sorted(
            a.fingerprint or "" for a in alert_group.alerts
        )
        return f"{alert_group.groupKey}:{alert_group.status}:{','.join(fingerprints)}"

    def is_duplicate(self, alert_group: AlertGroup) -> bool:
        """Return True (and log) if this alert group was already processed within the TTL."""
        key = self._make_key(alert_group)
        if key in self._cache:
            logger.info(
                "Duplicate alert group suppressed (groupKey=%s, status=%s)",
                alert_group.groupKey,
                alert_group.status,
            )
            return True
        self._cache[key] = True
        return False
