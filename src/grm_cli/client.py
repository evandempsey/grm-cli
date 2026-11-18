"""Talking to GRM: every request with the token, every error answer as a GrmError with its exit code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from grm_cli import __version__
from grm_cli.errors import GrmError, from_answer

AGENT = f"grm-cli/{__version__}"
# How requests leave grm: the network, or a stand-in GRM in the tests.
TRANSPORT: httpx.BaseTransport | None = None


@dataclass
class Answer:
    status: int
    body: Any
    headers: httpx.Headers

    def retry_after(self, default: int = 5) -> int:
        """How long the server asks a caller to wait before asking again, in seconds (1 to 30)."""
        try:
            return max(1, min(30, int(self.headers.get("Retry-After") or default)))
        except ValueError:
            return default


class Client:
    def __init__(self, url: str, token: str | None, transport: httpx.BaseTransport | None = None):
        if not token:
            raise GrmError(
                "You're not signed in",
                "Make a token on Settings, API tokens, then run grm login (or set GRM_TOKEN).",
                code="signed_out",
            )
        self.url = url.rstrip("/")
        transport = transport or TRANSPORT
        self._transport = transport
        self.http = httpx.Client(
            base_url=self.url,
            headers={"Authorization": f"Bearer {token}", "User-Agent": AGENT},
            timeout=httpx.Timeout(120, connect=15),
            transport=transport,
            follow_redirects=False,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Answer:
        try:
            r = self.http.request(method, path, json=json, params=params, content=content, headers=headers)
        except httpx.HTTPError as e:
            raise GrmError(
                f"Couldn't reach {self.url}", f"Check the address and your connection. ({e})", code="unreachable"
            ) from e
        try:
            body: Any = r.json() if r.content else None
        except ValueError:
            body = r.text
        if r.status_code >= 400:
            raise from_answer(r.status_code, body)
        return Answer(r.status_code, body, r.headers)

    def get(self, path: str, **params: Any) -> Any:
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None} or None).body

    def post(self, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
        return self.request("POST", path, json=body, headers=headers).body

    def patch(self, path: str, body: Any = None) -> Any:
        return self.request("PATCH", path, json=body).body

    # ---------- Files ----------

    def absolute(self, url: str) -> str:
        """A link from an answer as a full address (local storage answers with paths on the server)."""
        return url if url.startswith(("http://", "https://")) else urljoin(self.url + "/", url.lstrip("/"))

    def put_bytes(self, url: str, data: bytes) -> None:
        """Send a part of an upload to an address storage signed: no token goes with it."""
        try:
            with httpx.Client(timeout=httpx.Timeout(300, connect=15), transport=self._transport) as plain:
                r = plain.put(self.absolute(url), content=data)
        except httpx.HTTPError as e:
            raise GrmError("A part of the upload didn't arrive", f"Try again. ({e})", code="upload_failed") from e
        if r.status_code >= 400:
            raise GrmError(
                "Storage refused a part of the upload", f"It answered {r.status_code}. Try again.", code="upload_failed"
            )

    def download(self, url: str, dest: Path) -> int:
        """Save a file from a signed link (or, from local storage, a path on the server). Returns its size."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(f".{dest.name}.part")
        target = self.absolute(url)
        # A signed link carries its own permission; a path on GRM itself needs the token.
        own = target.startswith(self.url)
        client = self.http if own else httpx.Client(timeout=httpx.Timeout(300, connect=15), transport=self._transport)
        size = 0
        try:
            with client.stream("GET", target, follow_redirects=True) as r:
                if r.status_code >= 400:
                    raise GrmError(f"Couldn't download {dest.name}", f"It answered {r.status_code}.", code="failed")
                with open(partial, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
                        size += len(chunk)
            partial.replace(dest)
        except httpx.HTTPError as e:
            raise GrmError(f"Couldn't download {dest.name}", f"Try again. ({e})", code="failed") from e
        finally:
            partial.unlink(missing_ok=True)
            if not own:
                client.close()
        return size
