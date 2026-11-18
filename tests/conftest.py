"""A stand-in GRM for the unit tests: it answers each route with what a real GRM answered (tests/answers/, recorded
by tests/record.py), and notes every request grm sent."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from grm_cli import client as client_module
from grm_cli import config, jobs
from grm_cli.main import main

ANSWERS = Path(__file__).parent / "answers"
URL = "http://grm.test"


def answer(name: str) -> dict[str, Any]:
    """A recorded answer: {status, retry_after, body}."""
    return json.loads((ANSWERS / f"{name}.json").read_text())


def body(name: str) -> Any:
    return answer(name)["body"]


@dataclass
class Sent:
    method: str
    path: str
    params: dict[str, str]
    headers: httpx.Headers
    content: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.content) if self.content else None


@dataclass
class FakeGrm:
    routes: dict[tuple[str, str], list[httpx.Response]] = field(default_factory=dict)
    sent: list[Sent] = field(default_factory=list)

    def on(
        self,
        method: str,
        path: str,
        recorded: str | None = None,
        *,
        status: int = 200,
        json_body: Any = None,
        retry_after: str | None = None,
        content: bytes | None = None,
    ) -> FakeGrm:
        """Answer `method path` (each time, or in turn when given more than once) as recorded or as given."""
        if recorded is not None:
            a = answer(recorded)
            status, json_body, retry_after = a["status"], a["body"], retry_after or a.get("retry_after")
        headers = {"Retry-After": retry_after} if retry_after else {}
        r = (
            httpx.Response(status, content=content, headers=headers)
            if content is not None
            else httpx.Response(status, json=json_body, headers=headers)
        )
        self.routes.setdefault((method.upper(), path), []).append(r)
        return self

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        path = url.path if url.host == "grm.test" else str(url.copy_with(query=None))
        self.sent.append(Sent(request.method, path, dict(url.params), request.headers, request.read()))
        queue = self.routes.get((request.method, path))
        if not queue:
            return httpx.Response(404, json={"title": f"Nothing here for {request.method} {path}", "code": "not_found"})
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def called(self, method: str, path: str) -> list[Sent]:
        return [s for s in self.sent if s.method == method and s.path == path]


@pytest.fixture
def grm(monkeypatch, tmp_path) -> FakeGrm:
    fake = FakeGrm()
    monkeypatch.setattr(client_module, "TRANSPORT", httpx.MockTransport(fake.handle))
    monkeypatch.setenv("GRM_URL", URL)
    monkeypatch.setenv("GRM_TOKEN", "grm_test_token")
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.yaml")
    waits: list[float] = []
    monkeypatch.setattr(jobs, "sleep", waits.append)
    clock = [0.0]

    def tick() -> float:
        clock[0] += 0.001
        return clock[0] + sum(waits)

    monkeypatch.setattr(jobs, "monotonic", tick)
    fake.waits = waits  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def run(capsys):
    """Run grm with these arguments: (exit code, stdout, stderr)."""

    def go(*args: str) -> tuple[int, str, str]:
        code = main(list(args))
        out = capsys.readouterr()
        return code, out.out, out.err

    return go
