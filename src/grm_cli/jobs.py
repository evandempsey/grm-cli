"""Following work GRM does in the background: every long task is a job (GET /api/jobs/{id}).

grm asks after a job at the pace the server's Retry-After sets, says on stderr how it stands (and each of its children,
one line each, as they change), and ends when the job does.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from grm_cli.client import Client
from grm_cli.errors import GAVE_UP, GrmError
from grm_cli.output import Out

ENDED = ("done", "failed")

# Kept here so the tests can wait without the wall clock.
sleep: Callable[[float], None] = time.sleep
monotonic: Callable[[], float] = time.monotonic


def parse_timeout(text: str | None) -> float | None:
    """'30m', '90s', '2h' or a number of seconds; None for no limit."""
    if not text:
        return None
    text = text.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600}
    try:
        if text[-1] in units:
            return float(text[:-1]) * units[text[-1]]
        return float(text)
    except (ValueError, IndexError) as e:
        raise GrmError(f"“{text}” isn't a length of time", "Say it like 90s, 30m or 2h.", code="usage", exit=2) from e


def line(job: dict[str, Any]) -> str:
    """How a job stands, in one line: 'transcribe running 40% Transcribing'."""
    pct = f"{round(float(job.get('progress') or 0) * 100)}%" if job.get("status") == "running" else ""
    return " ".join(x for x in (job.get("kind", ""), job.get("status", ""), pct, job.get("detail") or "") if x)


def failed(job: dict[str, Any]) -> GrmError:
    err = job.get("error") or {}
    return GrmError(
        err.get("title") or f"The {job.get('kind', 'job')} failed",
        err.get("fix") or "",
        code=err.get("code") or "failed",
        extra={"job": job.get("id")},
    )


def follow(client: Client, job_id: str, out: Out, timeout: float | None = None) -> dict[str, Any]:
    """Ask after a job until it ends. Returns it done; raises its error when it fails, and gives up (exit 3) when
    `timeout` seconds pass first."""
    deadline = monotonic() + timeout if timeout else None
    seen: dict[str, str] = {}
    while True:
        answer = client.request("GET", f"/api/jobs/{job_id}")
        job = answer.body
        for j in [job, *(job.get("children") or [])]:
            said = line(j)
            if seen.get(j["id"]) != said:
                seen[j["id"]] = said
                out.say(("  " if j is not job else "") + said)
        if job["status"] == "done":
            return job
        if job["status"] == "failed":
            raise failed(job)
        wait = answer.retry_after()
        if deadline is not None and monotonic() + wait > deadline:
            raise GrmError(
                f"Gave up waiting: the {job.get('kind', 'job')} is still {job['status']}",
                f"It carries on without you. Ask again with grm job wait {job_id}.",
                code="timeout",
                exit=GAVE_UP,
                extra={"job": job_id},
            )
        sleep(wait)
