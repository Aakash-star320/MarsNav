"""A cap on how much remote data the analyzer may read.

Every analysis reads small windows of big remote files (elevation rows, spectral bands) by HTTP range request. Two
limits keep that bounded and visible:

* a per-analysis cap (default 64 MiB): the elevation and spectral reads of one analysis together;
* a per-session cap (default 256 MiB): everything read since the backend started.

A request that would go over either is refused *before* it is sent (``DataBudgetError``). Bytes are reserved under a lock
before the fetch, so concurrent row reads cannot overshoot, and the reservation is released if the fetch fails.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

RangeFetcher = Callable[[int, int], bytes]
MIB = 1024 * 1024


def _mb(n: int) -> str:
    return f"{n / MIB:.0f} MB"


class DataBudgetError(RuntimeError):
    """A read was refused because it would exceed a data limit. ``scope`` is ``analysis`` or ``session``."""

    code = "data_budget"

    def __init__(self, scope: str, limit_bytes: int) -> None:
        self.scope, self.limit_bytes = scope, limit_bytes
        if scope == "analysis":
            msg = f"this analysis would read more data than the limit of {_mb(limit_bytes)}; choose a smaller area"
        else:
            msg = f"the data limit for this session ({_mb(limit_bytes)}) has been reached; restart the backend to reset it, or reuse an earlier analysis"
        super().__init__(msg)


@dataclass
class JobMeter:
    """What one analysis has used so far, and the refusal that ended it (if any)."""
    used_bytes: int = 0
    refused: DataBudgetError | None = None
    _reserved: int = field(default=0, repr=False)


class DataBudget:
    def __init__(self, per_analysis_cap_bytes: int = 64 * MIB, session_cap_bytes: int = 256 * MIB) -> None:
        if per_analysis_cap_bytes <= 0 or session_cap_bytes <= 0:
            raise ValueError("data caps must be positive")
        self.per_analysis_cap_bytes, self.session_cap_bytes = per_analysis_cap_bytes, session_cap_bytes
        self._lock = threading.Lock()
        self._session_used = 0
        self._session_reserved = 0
        self._analyses = 0

    def start_job(self) -> JobMeter:
        with self._lock:
            self._analyses += 1
        return JobMeter()

    def metered(self, fetch: RangeFetcher, job: JobMeter) -> RangeFetcher:
        """Wrap a ``(first, last) -> bytes`` fetcher: count its bytes, and refuse over-limit requests before sending them."""
        def wrapped(first: int, last: int) -> bytes:
            need = last - first + 1
            self._reserve(job, need)
            try:
                data = fetch(first, last)
            except BaseException:
                self._release(job, need)
                raise
            self._commit(job, need, len(data))
            return data
        return wrapped

    def _reserve(self, job: JobMeter, need: int) -> None:
        with self._lock:
            if job.used_bytes + job._reserved + need > self.per_analysis_cap_bytes:
                job.refused = DataBudgetError("analysis", self.per_analysis_cap_bytes)
                raise job.refused
            if self._session_used + self._session_reserved + need > self.session_cap_bytes:
                job.refused = DataBudgetError("session", self.session_cap_bytes)
                raise job.refused
            job._reserved += need
            self._session_reserved += need

    def _release(self, job: JobMeter, need: int) -> None:
        with self._lock:
            job._reserved -= need
            self._session_reserved -= need

    def _commit(self, job: JobMeter, reserved: int, actual: int) -> None:
        with self._lock:
            job._reserved -= reserved
            self._session_reserved -= reserved
            job.used_bytes += actual
            self._session_used += actual

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {"per_analysis_cap_bytes": self.per_analysis_cap_bytes, "session_cap_bytes": self.session_cap_bytes,
                    "session_used_bytes": self._session_used, "analyses_counted": self._analyses}


@lru_cache
def get_budget() -> DataBudget:
    """The one budget of this backend process, sized from settings."""
    from app.core.config import settings
    return DataBudget(settings.analyzer_max_download_bytes, settings.analyzer_session_cap_bytes)
