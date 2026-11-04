"""In-process background jobs for analyses: stage/percent progress, cancel, bounded concurrency."""
from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any


class Cancelled(Exception):
    pass


class JobTimeout(Exception):
    pass


class Job:
    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.status = "queued"  # queued | running | done | failed | cancelled
        self.stage = "Queued"
        self.percent = 0
        self.result_id: str | None = None
        self.error: str | None = None
        self.http_status = 500
        self.done = threading.Event()
        self.created = time.monotonic()
        self.cancel_event = threading.Event()

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "stage": self.stage, "percent": self.percent,
                "result_id": self.result_id, "error": self.error}


class JobManager:
    """Runs analyses on a small worker pool. Workers == max concurrent analyses; the rest wait as 'queued'."""

    def __init__(self, workers: int, deadline_s: int, keep: int = 100) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="missync-job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._deadline = deadline_s
        self._keep = keep

    def submit(self, work: Callable[[Callable[[str, int], None]], str], friendly: Callable[[Exception], tuple[int, str]]) -> Job:
        """`work(progress)` returns the saved analysis id. `friendly` maps an exception to (http status, user message)."""
        job = Job()
        with self._lock:
            self._jobs[job.id] = job
            for old in sorted(self._jobs.values(), key=lambda j: j.created)[: max(0, len(self._jobs) - self._keep)]:
                if old.status in ("done", "failed", "cancelled"):
                    self._jobs.pop(old.id, None)

        def progress(stage: str, pct: int) -> None:
            if job.cancel_event.is_set():
                raise Cancelled()
            if time.monotonic() - started > self._deadline:
                raise JobTimeout()
            job.stage, job.percent = stage, pct

        started = time.monotonic()

        def run() -> None:
            nonlocal started
            try:
                if job.cancel_event.is_set():
                    job.status, job.stage = "cancelled", "Cancelled"
                    return
                started = time.monotonic()
                job.status, job.stage = "running", "Starting"
                try:
                    job.result_id = work(progress)
                    job.status, job.stage, job.percent = "done", "Done", 100
                except Cancelled:
                    job.status, job.stage = "cancelled", "Cancelled"
                except JobTimeout:
                    job.status, job.http_status = "failed", 504
                    job.error = f"The analysis exceeded the {self._deadline}s limit and was stopped."
                except Exception as e:
                    job.status = "failed"
                    job.http_status, job.error = friendly(e)
            finally:
                job.done.set()

        self._pool.submit(run)
        return job

    def get(self, jid: str) -> Job | None:
        return self._jobs.get(jid)

    def cancel(self, jid: str) -> bool:
        job = self._jobs.get(jid)
        if not job:
            return False
        job.cancel_event.set()
        return True

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
