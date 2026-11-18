"""The smoke test: grm's whole loop against a local GRM running with its stand-in services (nothing paid for).

    uv run python tests/smoke.py --url http://localhost:8010 --file path/to/video.mp4

It makes an account of its own on that GRM (sign-up must be open, as it is on a test stack), a workspace, a brand and
a token, then runs grm as a person would: sign in by token, add the video and wait for review, list and show its clips,
approve one, export and download the files, and read its jobs and transcript; then change the kit and clips by
path, take and put back a snapshot, rewrite a text, draw stills, thumbnails and a mix, and apply a plan. Every step
checks what grm printed and the exit code it ended with. GRM's own CI runs it against GRM's test stack, so a change
there can't break grm quietly.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=os.environ.get("GRM_URL", "http://localhost:8010"))
    p.add_argument("--file", required=True, help="a short video with speech, or the test stack's own")
    p.add_argument("--timeout", default="15m")
    a = p.parse_args()
    url = a.url.rstrip("/")

    # An account, a workspace, a brand and a token of its own, through GRM's own sign-up.
    tag = uuid.uuid4().hex[:8]
    web = httpx.Client(base_url=url, timeout=60)
    ok(
        web.post(
            "/api/auth/register",
            json={"email": f"grm-smoke-{tag}@example.com", "password": f"smoke-{tag}-pw-long", "name": "Smoke Test"},
        )
    )
    ws = ok(web.post("/api/workspaces", json={"name": f"Smoke {tag}"}))
    web.headers["X-Workspace"] = ws["id"]
    brand = ok(web.post("/api/brands", json={"name": f"Smoke Brand {tag}"}))
    token = ok(
        web.post(
            "/api/tokens",
            json={"name": "grm smoke test", "scopes": ["read", "edit", "generate", "approve", "export"], "days": 1},
        )
    )["secret"]
    env = {**os.environ, "GRM_URL": url, "GRM_TOKEN": token}

    def grm(*args: str, code: int = 0) -> str:
        r = subprocess.run([sys.executable, "-m", "grm_cli", *args], env=env, capture_output=True, text=True)
        step = " ".join(args)
        if r.returncode != code:
            sys.exit(f"FAILED: grm {step} ended {r.returncode}, not {code}\n{r.stdout}\n{r.stderr}")
        print(f"ok  grm {step}  (exit {r.returncode})")
        return r.stdout

    me = json.loads(grm("whoami", "--json"))
    assert me["user"]["email"].startswith("grm-smoke-") and "generate" in me["scopes"], me
    assert any(b["id"] == brand["id"] for b in json.loads(grm("brands", "--json")))

    ref = f"smoke:{tag}"
    started = time.time()
    video = json.loads(
        grm(
            "video",
            "add",
            brand["name"],
            a.file,
            "--title",
            "Smoke test",
            "--ref",
            ref,
            "--wait",
            "review",
            "--timeout",
            a.timeout,
            "--json",
        )
    )
    assert video["status"] == "review" and video["external_ref"] == ref, video
    print(f"    processed in {time.time() - started:.0f} s")
    # The same --ref again is the same video: nothing is uploaded twice.
    again = json.loads(grm("video", "add", brand["name"], a.file, "--ref", ref, "--json"))
    assert again["id"] == video["id"], again
    vid = video["id"][:8]
    assert json.loads(grm("videos", brand["code"], "--ref", ref, "--json"))[0]["id"] == video["id"]

    clips = json.loads(grm("clips", vid, "--json"))
    assert clips and all(isinstance(c["seconds"], float) for c in clips), clips
    clip = json.loads(grm("clip", "show", clips[0]["id"][:8], "--json"))
    assert clip["id"] == clips[0]["id"]
    grm("api", "POST", f"/api/assets/{clip['id']}/status", "-f", "status=approved")

    with tempfile.TemporaryDirectory() as tmp:
        files = json.loads(grm("export", vid, "--out", tmp, "--timeout", a.timeout, "--json"))["files"]
        assert files and all(Path(f).is_file() and Path(f).stat().st_size > 0 for f in files), files
        assert any(f.endswith(".srt") for f in files) and any(f.endswith(".vtt") for f in files), files
        print(f"    {len(files)} files downloaded")

    jobs = json.loads(grm("jobs", vid, "--json"))
    assert {"process", "export"} <= {j["kind"] for j in jobs}, {j["kind"] for j in jobs}
    grm("job", jobs[0]["id"])
    assert "-->" in grm("transcript", vid, "--srt")
    assert json.loads(grm("api", "GET", "/api/meta"))["api"] >= 1

    # 0.2: the kit, a clip's settings, every clip at once, snapshots, a rewrite, looks and a plan.
    api = json.loads(grm("api", "GET", "/api/meta"))["api"]
    code = brand["code"]
    snap = json.loads(grm("snapshot", code, "before the smoke", "--video", vid, "--json"))
    grm("kit", "set", code, "filter.id=instant", "writing.cta=Follow")
    assert json.loads(grm("kit", "get", code, "--path", "filter.id", "--json")) == "instant"
    assert "filter.id" in grm("kit", "history", code)
    other = clips[-1]["id"][:8]
    grm("clip", "set", other, "--video", vid, "hook=Smoke hook", "thumb.t=1.5")
    assert json.loads(grm("clip", "show", other, "--json"))["spec"]["hook"] == "Smoke hook"
    grm("clip", "unset", other, "thumb")
    assert "hook" in grm("clip", "history", other)
    assert "clips changed" in grm("bulk", vid, "set", "captions.preset=bold")
    assert "Smoke hook" in grm("snapshot", "diff", snap["id"][:8])
    grm("snapshot", "restore", snap["id"][:8])
    shown = json.loads(grm("clip", "show", other, "--json"))
    assert shown["spec"]["hook"] != "Smoke hook", shown["spec"]
    assert (shown["spec"].get("captions") or {}).get("preset") != "bold", shown["spec"]
    assert json.loads(grm("kit", "get", code, "--path", "filter.id", "--json")) != "instant"
    assert grm("clip", "rewrite", other, "--field", "tiktok", "shorter").strip()
    with tempfile.TemporaryDirectory() as tmp:
        kit_file = Path(tmp) / "kit.yaml"
        kit_file.write_text(grm("kit", "get", code))
        assert "matches" in grm("kit", "diff", code, str(kit_file))  # its own settings, read back
        looks = json.loads(grm("look", other, "--at", "1", "--width", "360", "--out", tmp, "--json"))["files"]
        looks.append(
            json.loads(grm("look", other, "--try", "captions.preset=bold,subtitle", "--out", tmp, "--json"))["files"][0]
        )
        looks.append(json.loads(grm("thumbs", vid, "--width", "600", "--out", tmp, "--json"))["file"])
        for f in looks:
            assert Path(f).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", f
        sound = json.loads(grm("listen", other, "--out", tmp, "--json"))
        assert Path(sound["file"]).stat().st_size > 0 and isinstance(sound["lufs"], float), sound
        print(f"    {len(looks)} pictures and a mix of {sound['seconds']} s")
        if api >= 2:
            plan = Path(tmp) / "plan.yaml"
            plan.write_text(
                f"brand: {code}\nvideo: {vid}\nsnapshot: before the plan\nkit:\n  set:\n    voice.room: small\n"
                f"clips:\n  {other}:\n    hook: Plan hook\n    music: off\n"
            )
            assert "Nothing was saved" in grm("apply", str(plan), "--dry-run")
            grm("apply", str(plan))
            shown = json.loads(grm("clip", "show", other, "--json"))
            assert shown["spec"]["hook"] == "Plan hook" and shown["spec"]["music"]["on"] is False, shown["spec"]
            assert "nothing to change" in grm("apply", str(plan))
        else:
            print(f"    grm apply skipped: this GRM speaks api {api}, and a plan needs 2")
    grm("snapshot", "delete", snap["id"][:8], code=2)
    grm("snapshot", "delete", snap["id"][:8], "--yes")

    # Wrong use, and a name that matches nothing, end with 2; a token without the scope with 4.
    grm("clips", "zzzzzzzz", code=2)
    reader = ok(web.post("/api/tokens", json={"name": "grm smoke reader", "scopes": ["read"], "days": 1}))["secret"]
    env["GRM_TOKEN"] = reader
    grm("api", "POST", f"/api/assets/{clip['id']}/status", "-f", "status=review", code=4)
    print("smoke test passed")
    return 0


def ok(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        sys.exit(f"FAILED: {r.request.method} {r.request.url.path} answered {r.status_code}: {r.text[:300]}")
    return r.json()


if __name__ == "__main__":
    raise SystemExit(main())
