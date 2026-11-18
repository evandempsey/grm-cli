"""Record the answers the unit tests are run against, from a local GRM with its stand-in services.

    uv run python tests/record.py --url http://localhost:8010 --file path/to/video.mp4

It makes an account of its own (as the smoke test does), processes the video, approves a clip and exports it, then
saves what GRM answered to each route grm calls in tests/answers/, ids and all. Record again after GRM's public API
changes (its `api` in /api/meta goes up), and the unit tests check grm against what GRM now says.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

import httpx

ANSWERS = Path(__file__).parent / "answers"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8010")
    p.add_argument("--file", required=True)
    a = p.parse_args()
    tag = uuid.uuid4().hex[:8]
    web = httpx.Client(base_url=a.url.rstrip("/"), timeout=120)
    web.post(
        "/api/auth/register",
        json={"email": f"rec-{tag}@example.com", "password": f"rec-{tag}-long-pw", "name": "Ada Okafor"},
    ).raise_for_status()
    ws = web.post("/api/workspaces", json={"name": "Okafor Media"}).json()
    web.headers["X-Workspace"] = ws["id"]
    brand = web.post("/api/brands", json={"name": "The Shop Floor"}).json()
    web.post("/api/brands", json={"name": "The Shop Talk"}).raise_for_status()  # for a name that matches two
    token = web.post(
        "/api/tokens", json={"name": "record", "scopes": ["read", "edit", "generate", "approve", "export"], "days": 1}
    ).json()["secret"]
    api = httpx.Client(base_url=a.url.rstrip("/"), timeout=120, headers={"Authorization": f"Bearer {token}"})
    saved: dict[str, object] = {}

    def keep(name: str, r: httpx.Response) -> dict:
        r.raise_for_status()
        saved[name] = {"status": r.status_code, "retry_after": r.headers.get("Retry-After"), "body": r.json()}
        return r.json()

    keep("meta", api.get("/api/meta"))
    keep("me", api.get("/api/me"))
    keep("brands", api.get("/api/brands"))
    data = Path(a.file).read_bytes()
    up = keep(
        "upload",
        api.post(
            "/api/uploads", json={"filename": "episode.mp4", "size_bytes": len(data), "content_type": "video/mp4"}
        ),
    )
    for n in range(1, up["part_count"] + 1):
        api.put(
            f"/api/uploads/{up['id']}/parts/{n}", content=data[(n - 1) * up["part_bytes"] : n * up["part_bytes"]]
        ).raise_for_status()
    api.post(f"/api/uploads/{up['id']}/complete").raise_for_status()
    video = keep(
        "video_created",
        api.post(
            "/api/videos",
            json={
                "brand_id": brand["id"],
                "upload_id": up["id"],
                "title": "Rebuilding after the fire",
                "external_ref": "drive:1AbC",
            },
        ),
    )
    keep("video_started", api.post(f"/api/videos/{video['id']}/start"))
    while (v := api.get(f"/api/videos/{video['id']}").json())["status"] not in ("review", "failed"):
        if v.get("job"):
            keep("job_running", api.get(f"/api/jobs/{v['job']}")) if v["status"] == "processing" else None
        time.sleep(2)
    keep("video", api.get(f"/api/videos/{video['id']}"))
    keep("job_done", api.get(f"/api/jobs/{v['job']}"))
    keep("videos", api.get(f"/api/brands/{brand['id']}/videos"))
    keep("videos_by_ref", api.get(f"/api/brands/{brand['id']}/videos", params={"ref": "drive:1AbC"}))
    keep("transcript", api.get(f"/api/videos/{video['id']}/transcript"))
    assets = keep("assets", api.get(f"/api/videos/{video['id']}/assets"))
    clip = next(x for x in assets if x["kind"] == "clip")
    keep("clip", api.get(f"/api/assets/{clip['id']}"))
    api.post(f"/api/assets/{clip['id']}/status", json={"status": "approved"}).raise_for_status()
    ex = keep("export_started", api.post(f"/api/videos/{video['id']}/export", json={"ready": False, "editor": False}))
    while api.get(f"/api/videos/{video['id']}/export").json()["export"]["status"] not in ("done", "failed"):
        time.sleep(2)
    keep("export", api.get(f"/api/videos/{video['id']}/export"))
    keep("export_job", api.get(f"/api/jobs/{ex['export']['job']}"))
    keep("exports", api.get(f"/api/videos/{video['id']}/exports"))
    keep("jobs", api.get("/api/jobs", params={"video": video["id"]}))

    def done(started: dict) -> httpx.Response:
        while (r := api.get(f"/api/jobs/{started['job']['id']}")).json()["status"] not in ("done", "failed"):
            time.sleep(1)
        return r

    # 0.2: the kit, a clip's settings, snapshots, a rewrite, looks.
    b = keep("brand", api.get(f"/api/brands/{brand['id']}"))
    keep(
        "brand_patched",
        api.patch(
            f"/api/brands/{brand['id']}/settings",
            json={
                "set": {"brand_kit.filter.id": "instant", "brand_kit.voice.room": "small", "voice.cta": "Follow"},
                "if_version": b["version"],
            },
        ),
    )
    keep("brand_history", api.get(f"/api/brands/{brand['id']}/history"))
    keep("brand_restored", api.post(f"/api/brands/{brand['id']}/versions/1/restore"))
    other = ([x for x in assets if x["kind"] == "clip" and x["id"] != clip["id"]] or [clip])[0]
    snap = keep(
        "snapshot",
        api.post(f"/api/brands/{brand['id']}/snapshots", json={"name": "before the look", "video_id": video["id"]}),
    )
    keep("snapshots", api.get(f"/api/brands/{brand['id']}/snapshots"))
    c2 = keep("clip_other", api.get(f"/api/assets/{other['id']}"))
    keep(
        "clip_patched",
        api.patch(
            f"/api/assets/{other['id']}",
            json={
                "set": {"spec.hook": "Your wife isn't a spreadsheet", "spec.thumb.t": 3.2},
                "if_version": c2["version"],
            },
        ),
    )
    keep("clip_history", api.get(f"/api/assets/{other['id']}/history"))
    keep("bulk", api.post(f"/api/videos/{video['id']}/bulk", json={"set": {"spec.captions.preset": "bold"}}))
    keep("snapshot_diff", api.get(f"/api/snapshots/{snap['id']}/diff"))
    keep("snapshot_restored", api.post(f"/api/snapshots/{snap['id']}/restore", json={"only": ["clips"]}))
    keep("clip_restored", api.post(f"/api/assets/{other['id']}/versions/1/restore"))
    keep(
        "bulk_clips",
        api.post(f"/api/videos/{video['id']}/bulk", json={"clips": {other["id"]: {"set": {"spec.music.on": False}}}}),
    )
    r = api.post(f"/api/videos/{video['id']}/bulk", json={"clips": {str(uuid.uuid4()): {"set": {"spec.hook": "x"}}}})
    saved["error_bulk_stranger"] = {"status": r.status_code, "body": r.json()}
    rw = keep(
        "rewrite_started",
        api.post(
            f"/api/assets/{other['id']}/rewrite",
            json={"instruction": "make it shorter", "field": "tiktok", "variant": 0},
        ),
    )
    keep("rewrite_job", done(rw))
    keep("clip_rewritten", api.get(f"/api/assets/{other['id']}"))
    st = keep(
        "stills_started",
        api.post(f"/api/assets/{other['id']}/stills", json={"aspect": "9:16", "width": 360, "at": [2], "sheet": False}),
    )
    keep("stills_job", done(st))
    sh = keep("sheet_started", api.get(f"/api/videos/{video['id']}/thumbnails/sheet", params={"width": 600}))
    keep("sheet_job", done(sh))
    snd = keep("sound_started", api.post(f"/api/assets/{other['id']}/sound", json={"music": True}))
    keep("sound_job", done(snd))
    # Errors, as GRM says them.
    reader = web.post("/api/tokens", json={"name": "reader", "scopes": ["read"], "days": 1}).json()["secret"]
    r = httpx.post(
        f"{a.url.rstrip('/')}/api/assets/{clip['id']}/status",
        json={"status": "review"},
        headers={"Authorization": f"Bearer {reader}"},
    )
    saved["error_scope"] = {"status": r.status_code, "body": r.json()}
    r = httpx.get(f"{a.url.rstrip('/')}/api/me", headers={"Authorization": "Bearer grm_not_a_token"})
    saved["error_signed_out"] = {"status": r.status_code, "body": r.json()}
    r = api.patch(f"/api/assets/{clip['id']}", json={"set": {"spec.captions.perBeat": 2}, "if_version": 0})
    saved["error_changed"] = {"status": r.status_code, "body": r.json()}
    ANSWERS.mkdir(exist_ok=True)
    for name, answer in saved.items():
        (ANSWERS / f"{name}.json").write_text(json.dumps(answer, indent=1, ensure_ascii=False) + "\n")
    print(f"recorded {len(saved)} answers in {ANSWERS}")


if __name__ == "__main__":
    main()
