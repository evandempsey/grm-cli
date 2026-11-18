"""What goes wrong, said as GRM says it (a title, and what to do about it) with the exit code a script can branch on.

| Exit | Means |
|---|---|
| 0 | Done |
| 1 | Failed (the error's title and fix on stderr, its code in --json) |
| 2 | Wrong use of the command |
| 3 | Gave up waiting (--timeout) |
| 4 | The token lacks the scope |
| 5 | Changed since you read it |
"""

from __future__ import annotations

from typing import Any

FAILED, USAGE, GAVE_UP, SCOPE, CHANGED = 1, 2, 3, 4, 5


class GrmError(Exception):
    """A failure with a title, what to do about it, GRM's error code, and the exit code it ends the command with."""

    def __init__(
        self,
        title: str,
        fix: str = "",
        *,
        code: str = "failed",
        exit: int = FAILED,
        status: int | None = None,
        extra: dict[str, Any] | None = None,
    ):
        super().__init__(title)
        self.title, self.fix, self.code, self.exit, self.status = title, fix, code, exit, status
        self.extra = extra or {}

    def as_json(self) -> dict[str, Any]:
        return {"error": {"title": self.title, "fix": self.fix, "code": self.code, **self.extra}}


def usage(title: str, fix: str = "") -> GrmError:
    """The command was used wrongly: a name that matches nothing, or two things."""
    return GrmError(title, fix, code="usage", exit=USAGE)


def from_answer(status: int, body: Any) -> GrmError:
    """An error answer from GRM, as an error with the exit code its `code` calls for."""
    body = body if isinstance(body, dict) else {}
    title = str(body.get("title") or f"GRM answered {status}")
    fix = str(body.get("fix") or "")
    code = str(body.get("code") or ("signed_out" if status == 401 else "failed"))
    extra = {k: v for k, v in body.items() if k not in ("title", "fix", "code")}
    if code == "signed_out":
        # GRM says to sign in again; from a terminal that is grm login.
        return GrmError(
            title, "Make a new token on Settings, API tokens, then run grm login.", code=code, status=status
        )
    if code == "scope_missing":
        return GrmError(title, fix, code=code, exit=SCOPE, status=status, extra=extra)
    if code == "busy" and "version" in body:
        # Changed since it was read: the answer says the version it is at now.
        return GrmError(title, fix, code=code, exit=CHANGED, status=status, extra=extra)
    return GrmError(title, fix, code=code, status=status, extra=extra)
