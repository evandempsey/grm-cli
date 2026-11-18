"""grm 0.1 against a stand-in GRM that answers as a real one did (tests/answers/, recorded by tests/record.py)."""

from __future__ import annotations

import io
import json
import sys

import httpx
import keyring
import keyring.backend
import pytest

from grm_cli import client as client_module
from tests.conftest import URL, answer, body

VIDEO = body("video")
V, B, JOB = VIDEO["id"], VIDEO["brand_id"], VIDEO["job"]
CLIPS = [a for a in body("assets") if a["kind"] == "clip"]


def brands(grm):
    grm.on("GET", "/api/brands", "brands")
    grm.on("GET", f"/api/brands/{B}/videos", "videos")
    for b in body("brands")[1:]:
        grm.on("GET", f"/api/brands/{b['id']}/videos", json_body=[])


# ---------- Signing in ----------


def test_whoami_says_who_where_and_what_the_token_may_do(grm, run):
    grm.on("GET", "/api/meta", "meta").on("GET", "/api/me", "me")
    code, out, _ = run("whoami")
    me = body("me")
    assert code == 0
    assert me["user"]["name"] in out and me["workspaces"][0]["name"] in out
    assert "read, edit, generate, approve, export" in out and f"api {body('meta')['api']}" in out
    assert grm.sent[0].headers["Authorization"] == "Bearer grm_test_token"
    assert grm.sent[0].headers["User-Agent"].startswith("grm-cli/")
    code, out, _ = run("whoami", "--json")
    assert json.loads(out)["scopes"] == body("meta")["scopes"]


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self):
        self.kept: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self.kept[(service, username)] = password

    def get_password(self, service, username):
        return self.kept.get((service, username))

    def delete_password(self, service, username):
        if (service, username) not in self.kept:
            raise keyring.errors.PasswordDeleteError(username)
        del self.kept[(service, username)]


def test_login_keeps_the_token_in_the_keychain_and_never_takes_it_as_an_argument(grm, run, monkeypatch):
    kept = MemoryKeyring()
    keyring.set_keyring(kept)
    monkeypatch.delenv("GRM_TOKEN")
    monkeypatch.delenv("GRM_URL")
    grm.on("GET", "/api/meta", "meta").on("GET", "/api/me", "me")
    monkeypatch.setattr(sys, "stdin", io.StringIO("grm_from_stdin\n"))  # piped in, as a script would
    code, out, _ = run("login", "--profile", "dev", "--url", URL)
    assert code == 0 and "Signed in to http://grm.test" in out
    assert kept.kept[("grm-cli", "dev")] == "grm_from_stdin"
    code, _, _ = run("whoami", "--profile", "dev")
    assert code == 0 and grm.sent[-1].headers["Authorization"] == "Bearer grm_from_stdin"
    assert run("logout", "--profile", "dev")[0] == 0 and ("grm-cli", "dev") not in kept.kept
    code, _, err = run("whoami", "--profile", "dev")
    assert code == 1 and "not signed in" in err
    with pytest.raises(SystemExit):  # there is no --token: it would land in shell history
        run("login", "--token", "grm_secret")


# ---------- Names instead of ids ----------


def test_a_brand_by_its_code_or_the_start_of_its_name_and_never_a_guess(grm, run):
    brands(grm)
    code, out, _ = run("videos", "shopfloor")
    assert code == 0 and V[:8] in out and "Rebuilding after the fire" in out
    assert run("videos", "@shopfloor")[0] == 0
    code, _, err = run("videos", "the shop")
    assert code == 2 and "matches 2 brands" in err and "The Shop Floor" in err and "The Shop Talk" in err
    code, _, err = run("videos", "nothing like it")
    assert code == 2 and "No brand is called" in err


def test_a_video_and_a_clip_by_the_start_of_their_ids(grm, run):
    brands(grm)
    grm.on("GET", f"/api/videos/{V}/assets", "assets")
    code, out, _ = run("clips", V[:8])
    assert code == 0
    for c in CLIPS:
        assert c["id"][:8] in out and c["title"] in out
    assert "0:" in out  # each clip's length
    grm.on("GET", "/api/videos/" + V, "video")
    code, out, _ = run("clip", "show", CLIPS[0]["id"][:8], "--json")
    assert code == 0 and json.loads(out)["id"] == CLIPS[0]["id"]
    code, _, err = run("clip", "show", "--match", "the", "--video", V[:8])
    assert code == 2 and "matches" in err


# ---------- Adding a video ----------


def test_a_video_is_uploaded_in_parts_started_and_waited_for(grm, run, tmp_path):
    up = body("upload")
    episode = tmp_path / "episode.mp4"
    episode.write_bytes(b"x" * up["size_bytes"])
    brands(grm)
    grm.on("GET", f"/api/brands/{B}/videos", json_body=[])  # nothing from this --ref yet
    grm.routes[("GET", f"/api/brands/{B}/videos")] = grm.routes[("GET", f"/api/brands/{B}/videos")][-1:]
    grm.on("POST", "/api/uploads", "upload")
    for n in range(1, up["part_count"] + 1):
        grm.on("PUT", f"/api/uploads/{up['id']}/parts/{n}", json_body={"number": n})
    grm.on("POST", f"/api/uploads/{up['id']}/complete", "upload")
    grm.on("POST", "/api/videos", "video_created").on("POST", f"/api/videos/{V}/start", "video_started")
    grm.on("GET", f"/api/videos/{V}", json_body={**VIDEO, "status": "processing"}).on(
        "GET", f"/api/videos/{V}", "video"
    )
    grm.on("GET", f"/api/jobs/{JOB}", "job_running").on("GET", f"/api/jobs/{JOB}", "job_done")
    code, out, err = run(
        "video", "add", "shopfloor", str(episode), "--title", "Rebuilding", "--ref", "drive:1AbC", "--wait", "review"
    )
    assert code == 0 and out.strip() == V
    parts = [s for s in grm.sent if s.method == "PUT"]
    assert [len(p.content) for p in parts] == [up["part_bytes"], up["size_bytes"] - up["part_bytes"]]
    made = grm.called("POST", "/api/videos")[0].json
    assert made == {"brand_id": B, "upload_id": up["id"], "title": "Rebuilding", "external_ref": "drive:1AbC"}
    assert grm.called("POST", f"/api/videos/{V}/start")[0].headers["Idempotency-Key"].startswith("grm-start-")
    assert "pays for transcription" in err and "process running" in err and "process done" in err
    assert "  transcribe done" in err  # each stage, one line each
    assert grm.waits == [int(answer("job_running")["retry_after"])]  # at the server's pace


def test_the_same_ref_again_adds_nothing(grm, run, tmp_path):
    brands(grm)
    grm.routes[("GET", f"/api/brands/{B}/videos")] = []
    grm.on("GET", f"/api/brands/{B}/videos", "videos_by_ref")
    (tmp_path / "e.mp4").write_bytes(b"x")
    code, out, err = run("video", "add", "shopfloor", str(tmp_path / "e.mp4"), "--ref", "drive:1AbC")
    assert code == 0 and out.strip() == V and "already has a video from drive:1AbC" in err
    assert grm.sent[-1].params == {"ref": "drive:1AbC"}
    assert not grm.called("POST", "/api/uploads") and not grm.called("POST", "/api/videos")


def test_a_dry_run_says_what_it_would_do_and_pay_for_and_does_nothing(grm, run, tmp_path):
    brands(grm)
    (tmp_path / "e.mp4").write_bytes(b"x")
    code, _, err = run("video", "add", "shopfloor", str(tmp_path / "e.mp4"), "--dry-run")
    assert code == 0 and "Would upload" in err and "pays for transcription" in err
    assert {s.method for s in grm.sent} == {"GET"}


def test_a_direct_upload_sends_each_part_to_storage_without_the_token(grm, run, tmp_path):
    up = {**body("upload"), "direct": True, "part_count": 1, "size_bytes": 10}
    brands(grm)
    (tmp_path / "e.mp4").write_bytes(b"0123456789")
    grm.on("POST", "/api/uploads", json_body=up)
    grm.on("GET", f"/api/uploads/{up['id']}/parts/1/url", json_body={"url": "https://storage.test/part-1?X-Sig=abc"})
    grm.on("PUT", "https://storage.test/part-1", json_body={})
    grm.on("POST", f"/api/uploads/{up['id']}/complete", json_body=up)
    grm.on("POST", "/api/videos", "video_created").on("POST", f"/api/videos/{V}/start", "video_started")
    assert run("video", "add", "shopfloor", str(tmp_path / "e.mp4"))[0] == 0
    [part] = grm.called("PUT", "https://storage.test/part-1")
    assert part.content == b"0123456789" and "Authorization" not in part.headers


# ---------- Jobs ----------


def test_waiting_gives_up_after_the_timeout_with_exit_3(grm, run):
    grm.on("GET", f"/api/jobs/{JOB}", "job_running")
    code, out, err = run("job", "wait", JOB, "--timeout", "12s", "--json")
    assert code == 3 and "Gave up waiting" in err and f"grm job wait {JOB}" in err
    assert json.loads(out)["error"]["code"] == "timeout"
    assert sum(grm.waits) <= 12


def test_a_failed_job_ends_the_command_with_its_reason(grm, run):
    failed = {
        **body("job_done"),
        "status": "failed",
        "error": {"title": "The file has no sound", "fix": "Upload one with sound."},
    }
    grm.on("GET", f"/api/jobs/{JOB}", json_body=failed)
    code, _, err = run("job", "wait", JOB)
    assert code == 1 and "The file has no sound" in err and "Upload one with sound." in err


def test_a_job_and_a_videos_jobs(grm, run):
    brands(grm)
    grm.on("GET", f"/api/jobs/{JOB}", "job_done").on("GET", "/api/jobs", "jobs")
    code, out, _ = run("job", JOB)
    assert code == 0 and out.startswith("process done") and "  transcribe done" in out
    code, out, _ = run("jobs", V[:8])
    assert code == 0 and "render" in out and "process" in out
    assert grm.called("GET", "/api/jobs")[0].params["video"] == V


# ---------- Errors and exit codes ----------


@pytest.mark.parametrize(
    ("recorded", "exit_code", "words"),
    [("error_scope", 4, "scope"), ("error_signed_out", 1, "grm login"), ("error_changed", 5, "version")],
)
def test_errors_end_with_the_exit_code_a_script_can_branch_on(grm, run, recorded, exit_code, words):
    grm.on("POST", "/api/anything", recorded)
    code, out, err = run("api", "POST", "/api/anything", "--json")
    assert code == exit_code and answer(recorded)["body"]["title"] in err
    assert words in (err + out).lower()
    assert json.loads(out)["error"]["code"] == answer(recorded)["body"]["code"]


def test_a_server_that_cant_be_reached_says_so(run, monkeypatch, grm):
    def refuse(request):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(client_module, "TRANSPORT", httpx.MockTransport(refuse))
    code, _, err = run("brands")
    assert code == 1 and "Couldn't reach http://grm.test" in err


# ---------- Transcripts, exports, any route ----------


def test_a_transcript_as_text_words_or_subtitles(grm, run):
    brands(grm)
    grm.on("GET", f"/api/videos/{V}/transcript", "transcript")
    words = body("transcript")["words"]
    code, out, _ = run("transcript", V[:8], "--srt")
    assert code == 0 and out.startswith("1\n00:00:") and "-->" in out and words[0]["w"] in out
    code, out, _ = run("transcript", V[:8], "--words")
    assert len(out.strip().splitlines()) == len(words)
    code, out, _ = run("transcript", V[:8])
    assert words[1]["w"] in out


def test_an_export_waits_for_its_job_and_downloads_every_file_into_its_folder(grm, run, tmp_path):
    brands(grm)
    started, done = body("export_started"), body("export")
    grm.on("POST", f"/api/videos/{V}/export", "export_started")
    grm.on("GET", f"/api/jobs/{started['export']['job']}", "export_job")
    grm.on("GET", f"/api/videos/{V}/export", "export")
    # Every file: one for each render, and each of the files a render made several of (the SRT and the VTT).
    files = [
        (r.get("folder") or "", f["name"] if "name" in f else r["filename"], f["url"])
        for r in done["export"]["renders"]
        if r["status"] == "done"
        for f in ([r] if r.get("url") else r.get("files") or [])
    ]
    assert any(name.endswith(".srt") for _, name, _ in files) and any(name.endswith(".vtt") for _, name, _ in files)
    for _, name, url in files:
        grm.on("GET", url.split("?")[0], content=f"file {name}".encode())
    code, out, _ = run("export", V[:8], "--out", str(tmp_path))
    assert code == 0
    paths = out.strip().splitlines()
    assert len(paths) == len(files)
    for folder, name, _ in files:
        f = tmp_path / folder / name
        assert str(f) in paths and f.read_bytes() == f"file {name}".encode()
    assert grm.called("POST", f"/api/videos/{V}/export")[0].json == {"ready": False, "editor": False}


def test_any_route_with_the_token_and_fields_as_json(grm, run):
    grm.on("POST", "/api/assets/abc/status", json_body={"status": "approved"})
    code, out, _ = run("api", "post", "/api/assets/abc/status", "-f", "status=approved", "-f", "n=3")
    assert code == 0 and json.loads(out) == {"status": "approved"}
    assert grm.sent[-1].json == {"status": "approved", "n": 3}


def test_the_common_options_may_come_before_the_command_too(grm, run):
    grm.on("GET", "/api/brands", "brands")
    code, out, _ = run("--json", "--profile", "default", "brands")
    assert code == 0 and json.loads(out)[0]["id"] == body("brands")[0]["id"]
    code, out, _ = run("brands", "--json")
    assert code == 0 and json.loads(out)
