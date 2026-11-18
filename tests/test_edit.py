"""grm 0.2 against a stand-in GRM that answers as a real one did: the kit, clips' settings, bulk changes, snapshots,
looks and plan files."""

from __future__ import annotations

import json

import yaml

from tests.conftest import answer, body

VIDEO = body("video")
V = VIDEO["id"]
BRAND = body("brand")
B = BRAND["id"]
ASSETS = body("assets")
CLIPS = [a for a in ASSETS if a["kind"] == "clip"]
OTHER = body("clip_other")
OID = OTHER["id"]


def world(grm):
    """The brands, their videos and the video's clips, as grm looks them up by name or by the start of an id."""
    grm.on("GET", "/api/brands", "brands")
    grm.on("GET", f"/api/brands/{B}", "brand")
    grm.on("GET", f"/api/brands/{B}/videos", "videos")
    for b in body("brands"):
        if b["id"] != B:
            grm.on("GET", f"/api/brands/{b['id']}/videos", json_body=[])
            grm.on("GET", f"/api/brands/{b['id']}/snapshots", json_body={"snapshots": []})
    grm.on("GET", f"/api/videos/{V}/assets", "assets")
    grm.on("GET", f"/api/videos/{V}", "video")


def job(grm, started: str, done: str):
    """A started job's answer, and the job when asked after."""
    grm.on("GET", f"/api/jobs/{body(started)['job']['id']}", done)


# ---------- The kit ----------


def test_kit_get_is_the_settings_in_effect_as_a_kit_file_or_one_of_them(grm, run):
    world(grm)
    code, out, _ = run("kit", "get", "shopfloor")
    doc = yaml.safe_load(out)
    assert code == 0 and set(doc) == {"kit", "writing", "pack"}
    assert doc["kit"]["captions"] == BRAND["kit"]["captions"]
    code, out, _ = run("kit", "get", "shopfloor", "--path", "captions.preset")
    assert yaml.safe_load(out) == BRAND["kit"]["captions"]["preset"]
    code, _, err = run("kit", "get", "shopfloor", "--path", "captions.nothing")
    assert code == 2 and "no setting captions.nothing" in err


def test_kit_set_names_settings_as_grm_says_them_and_only_if_unchanged_since_read(grm, run):
    world(grm)
    grm.on("PATCH", f"/api/brands/{B}/settings", "brand_patched")
    code, out, _ = run("kit", "set", "shopfloor", "filter.id=instant", "voice.room=small", "writing.cta=Follow")
    assert code == 0
    assert grm.called("PATCH", f"/api/brands/{B}/settings")[0].json == {
        "set": {"brand_kit.filter.id": "instant", "brand_kit.voice.room": "small", "voice.cta": "Follow"},
        "unset": [],
        "if_version": BRAND["version"],
    }
    assert "filter.id: " in out and "→ instant" in out and "voice.room: (none) → small" in out
    assert "writing.cta" in out and "brand_kit" not in out


def test_kit_set_changed_meanwhile_ends_with_exit_5(grm, run):
    world(grm)
    grm.on("PATCH", f"/api/brands/{B}/settings", "error_changed")
    code, _, err = run("kit", "set", "shopfloor", "filter.id=instant")
    assert code == 5 and answer("error_changed")["body"]["title"] in err


def test_kit_unset_puts_settings_back_to_the_defaults(grm, run):
    world(grm)
    grm.on("PATCH", f"/api/brands/{B}/settings", "brand_patched")
    code, out, _ = run("kit", "unset", "shopfloor", "voice.room", "writing.cta")
    assert code == 0 and "back to the defaults" in out
    assert grm.called("PATCH", f"/api/brands/{B}/settings")[0].json["unset"] == ["brand_kit.voice.room", "voice.cta"]


def test_a_kit_file_is_compared_and_applied_as_settings_take_effect(grm, run, tmp_path):
    world(grm)
    grm.on("PATCH", f"/api/brands/{B}/settings", "brand_patched")
    preset = BRAND["kit"]["captions"]["preset"]
    f = tmp_path / "kit.yaml"
    # The preset already as it is: not a difference. The filter and the call to action are.
    f.write_text(f"kit:\n  filter: {{id: instant}}\n  captions: {{preset: {preset}}}\nwriting:\n  cta: Follow\n")
    code, out, _ = run("kit", "diff", "shopfloor", str(f))
    assert code == 0 and "filter.id" in out and "writing.cta" in out and "captions.preset" not in out
    code, out, _ = run("kit", "apply", "shopfloor", str(f), "--dry-run")
    assert code == 0 and "nothing is saved" in out and not grm.called("PATCH", f"/api/brands/{B}/settings")
    code, out, _ = run("kit", "apply", "shopfloor", str(f))
    assert code == 0
    assert grm.called("PATCH", f"/api/brands/{B}/settings")[0].json["set"] == {
        "brand_kit.filter.id": "instant",
        "voice.cta": "Follow",
    }
    f.write_text(f"kit:\n  captions: {{preset: {preset}}}\n")
    code, out, _ = run("kit", "diff", "shopfloor", str(f))
    assert code == 0 and "matches" in out
    f.write_text("colours: {bg: red}\n")
    code, _, err = run("kit", "apply", "shopfloor", str(f))
    assert code == 2 and "isn't a kit file" in err


def test_kit_history_says_paths_as_grm_does(grm, run):
    world(grm)
    grm.on("GET", f"/api/brands/{B}/history", "brand_history")
    code, out, _ = run("kit", "history", "shopfloor")
    assert code == 0 and "filter.id, voice.room, writing.cta" in out and "brand_kit." not in out


def test_kit_restore_says_what_went_back(grm, run):
    world(grm)
    grm.routes[("GET", f"/api/brands/{B}")] = []
    grm.on("GET", f"/api/brands/{B}", "brand_patched")
    grm.on("POST", f"/api/brands/{B}/versions/1/restore", "brand_restored")
    code, out, _ = run("kit", "restore", "shopfloor", "1")
    assert code == 0 and "back to version 1" in out and "filter.id: instant →" in out


# ---------- A clip's settings ----------


def test_clip_set_takes_its_words_either_side_of_its_options(grm, run):
    world(grm)
    c = next(x for x in CLIPS if x["id"] == OID)
    grm.on("PATCH", f"/api/assets/{OID}", "clip_patched")
    code, out, _ = run("clip", "set", OID[:8], "--video", V[:8], "hook=Your wife isn't a spreadsheet", "thumb.t=3.2")
    assert code == 0
    assert grm.called("PATCH", f"/api/assets/{OID}")[0].json == {
        "set": {"spec.hook": "Your wife isn't a spreadsheet", "spec.thumb.t": 3.2},
        "unset": [],
        "if_version": c["version"],
    }
    assert "hook: " in out and "→ Your wife isn't a spreadsheet" in out and "thumb.t: (none) → 3.2" in out
    code, out, _ = run("clip", "set", "--match", c["title"].lower(), "--video", V[:8], "thumb.t=1")
    assert code == 0 and grm.called("PATCH", f"/api/assets/{OID}")[1].json["set"] == {"spec.thumb.t": 1}


def test_a_clip_title_cant_be_unset_and_a_version_is_a_number(grm, run):
    world(grm)
    grm.on("GET", f"/api/assets/{OID}", "clip_other")
    code, _, err = run("clip", "unset", OID, "title")
    assert code == 2 and "title can't be unset" in err
    code, _, err = run("clip", "restore", OID, "one")
    assert code == 2 and "isn't a version number" in err
    code, _, err = run("clip", "set", OID)
    assert code == 2
    assert not [s for s in grm.sent if s.method != "GET"]


def test_clip_restore_says_each_setting_that_went_back(grm, run):
    grm.on("GET", f"/api/assets/{OID}", "clip_patched")
    grm.on("POST", f"/api/assets/{OID}/versions/1/restore", "clip_restored")
    code, out, _ = run("clip", "restore", OID, "1")
    assert code == 0 and "back to version 1" in out
    assert "hook: Your wife isn't a spreadsheet → " in out and "thumb.t: 3.2 → (none)" in out


def test_clip_rewrite_follows_its_job_and_prints_the_text_it_made(grm, run):
    grm.on("GET", f"/api/assets/{OID}", "clip_other").on("GET", f"/api/assets/{OID}", "clip_rewritten")
    grm.on("POST", f"/api/assets/{OID}/rewrite", "rewrite_started")
    job(grm, "rewrite_started", "rewrite_job")
    made = body("rewrite_job")["result"]["with"]["new_variant"]
    text = body("clip_rewritten")["spec"]["copy"]["tiktok"]["variants"][made]["text"]
    code, out, err = run("clip", "rewrite", OID, "--field", "tiktok", "make", "it", "shorter")
    assert code == 0 and out.strip() == text and "paid" in err
    assert grm.called("POST", f"/api/assets/{OID}/rewrite")[0].json == {
        "instruction": "make it shorter",
        "field": "tiktok",
        "variant": 0,
    }
    code, out, _ = run("clip", "rewrite", OID, "--dry-run", "shorter")
    assert code == 0 and "Would rewrite" in out and len(grm.called("POST", f"/api/assets/{OID}/rewrite")) == 1


def test_clip_history(grm, run):
    grm.on("GET", f"/api/assets/{OID}", "clip_other")
    grm.on("GET", f"/api/assets/{OID}/history", "clip_history")
    code, out, _ = run("clip", "history", OID)
    assert code == 0 and "hook, thumb.t" in out


def test_bulk_changes_every_clip_of_a_video_in_one_save(grm, run):
    world(grm)
    grm.on("POST", f"/api/videos/{V}/bulk", "bulk")
    code, out, _ = run("bulk", V[:8], "set", "captions.preset=bold")
    assert code == 0
    assert grm.called("POST", f"/api/videos/{V}/bulk")[0].json == {"set": {"spec.captions.preset": "bold"}}
    assert f"{body('bulk')['changed']} of {len(CLIPS)} clips changed" in out
    assert out.count("captions.preset: (none) → bold") == len(CLIPS)
    code, out, _ = run("bulk", V[:8], "unset", "captions.preset")
    assert grm.called("POST", f"/api/videos/{V}/bulk")[1].json == {"unset": ["spec.captions.preset"]}


# ---------- Snapshots ----------

SNAP = body("snapshot")


def snapshots(grm):
    world(grm)
    grm.on("GET", f"/api/brands/{B}/snapshots", "snapshots")


def test_a_snapshot_of_the_kit_and_one_videos_clips(grm, run):
    snapshots(grm)
    grm.on("POST", f"/api/brands/{B}/snapshots", "snapshot")
    code, out, _ = run("snapshot", "shopfloor", "before the look", "--video", V[:8])
    assert code == 0 and SNAP["id"][:8] in out and "one video's clips" in out
    assert grm.called("POST", f"/api/brands/{B}/snapshots")[0].json == {"name": "before the look", "video_id": V}
    code, out, _ = run("snapshots", "shopfloor")
    assert code == 0 and "before the look" in out


def test_a_snapshot_diffed_and_put_back_by_the_start_of_its_id(grm, run):
    snapshots(grm)
    grm.on("GET", f"/api/snapshots/{SNAP['id']}/diff", "snapshot_diff")
    grm.on("POST", f"/api/snapshots/{SNAP['id']}/restore", "snapshot_restored")
    code, out, _ = run("snapshot", "diff", SNAP["id"][:8])
    assert code == 0 and "Since “before the look”" in out
    assert "captions.preset: bold (was (none))" in out and "hook: Your wife isn't a spreadsheet" in out
    code, out, _ = run("snapshot", "restore", SNAP["id"][:8], "--only", "clips")
    assert code == 0 and "kit: left" in out
    assert f"clips put back: {len(body('snapshot_restored')['restored'])}" in out
    assert grm.called("POST", f"/api/snapshots/{SNAP['id']}/restore")[0].json == {"only": ["clips"]}


def test_deleting_a_snapshot_needs_yes(grm, run):
    snapshots(grm)
    grm.on("DELETE", f"/api/snapshots/{SNAP['id']}", status=204, content=b"")
    code, _, err = run("snapshot", "delete", SNAP["id"][:8])
    assert code == 2 and "--yes" in err and not grm.called("DELETE", f"/api/snapshots/{SNAP['id']}")
    code, out, _ = run("snapshot", "delete", SNAP["id"][:8], "--yes")
    assert code == 0 and "Deleted" in out and grm.called("DELETE", f"/api/snapshots/{SNAP['id']}")


# ---------- Looks ----------


def link(url: str) -> str:
    return url.split("?")[0]


def test_look_draws_stills_and_saves_them_named_for_the_clip(grm, run, tmp_path):
    grm.on("GET", f"/api/assets/{OID}", "clip_other")
    grm.on("POST", f"/api/assets/{OID}/stills", "stills_started")
    job(grm, "stills_started", "stills_job")
    stills = body("stills_job")["result"]["stills"]
    for s in stills:
        grm.on("GET", link(s["url"]), content=b"png")
    code, out, err = run("look", OID, "--at", "2", "--width", "360", "--out", str(tmp_path))
    assert code == 0 and "pays no provider" in err
    assert grm.called("POST", f"/api/assets/{OID}/stills")[0].json == {
        "aspect": "9:16",
        "width": 360,
        "at": [2.0],
        "sheet": False,
    }
    f = tmp_path / "what_did_you_do_in_that_at_2.png"
    assert out.strip() == str(f) and f.read_bytes() == b"png"


def test_look_tries_variants_side_by_side_without_saving_them(grm, run, tmp_path):
    grm.on("GET", f"/api/assets/{OID}", "clip_other")
    grm.on("POST", f"/api/assets/{OID}/stills", "stills_started")
    job(grm, "stills_started", "stills_job")
    for s in body("stills_job")["result"]["stills"]:
        grm.on("GET", link(s["url"]), content=b"png")
    code, _, _ = run("look", OID, "--at", "3", "--try", "captions.preset=bold,subtitle", "--out", str(tmp_path))
    sent = grm.called("POST", f"/api/assets/{OID}/stills")[0].json
    assert code == 0 and sent["sheet"] is True
    assert sent["variants"] == [
        {"label": "bold", "set": {"spec.captions.preset": "bold"}},
        {"label": "subtitle", "set": {"spec.captions.preset": "subtitle"}},
    ]
    code, _, err = run("look", OID, "--try", "captions.preset=bold")
    assert code == 2 and "2 to 4 values" in err
    assert not [s for s in grm.sent if s.method != "GET"][1:]  # only the first look was asked for


def test_thumbs_is_every_thumbnail_on_one_picture(grm, run, tmp_path):
    world(grm)
    grm.on("GET", f"/api/videos/{V}/thumbnails/sheet", "sheet_started")
    job(grm, "sheet_started", "sheet_job")
    grm.on("GET", link(body("sheet_job")["result"]["url"]), content=b"sheet")
    code, out, _ = run("thumbs", V[:8], "--width", "600", "--out", str(tmp_path))
    f = tmp_path / "rebuilding_after_the_fire_thumbnails.png"
    assert code == 0 and out.strip() == str(f) and f.read_bytes() == b"sheet"
    assert grm.called("GET", f"/api/videos/{V}/thumbnails/sheet")[0].params == {"width": "600"}


def test_listen_saves_the_mix_and_says_its_levels(grm, run, tmp_path):
    grm.on("GET", f"/api/assets/{OID}", "clip_other")
    grm.on("POST", f"/api/assets/{OID}/sound", "sound_started")
    job(grm, "sound_started", "sound_job")
    result = body("sound_job")["result"]
    grm.on("GET", link(result["url"]), content=b"mp3")
    code, out, _ = run("listen", OID, "--out", str(tmp_path))
    assert code == 0 and (tmp_path / "what_did_you_do_in_that_sound.mp3").read_bytes() == b"mp3"
    assert f"Loudness of the mix: {result['lufs']:g} LUFS" in out and "Music: no music" in out
    assert grm.called("POST", f"/api/assets/{OID}/sound")[0].json == {"music": True}
    code, out, _ = run("listen", OID, "--out", str(tmp_path), "--json")
    assert json.loads(out)["lufs"] == result["lufs"]


# ---------- Plan files ----------

A, C = CLIPS[0], CLIPS[1]


def plan(tmp_path, text: str) -> str:
    f = tmp_path / "plan.yaml"
    f.write_text(text)
    return str(f)


def plan_world(grm):
    world(grm)
    grm.on("GET", "/api/meta", "meta")
    grm.on("POST", f"/api/brands/{B}/snapshots", "snapshot")
    grm.on("PATCH", f"/api/brands/{B}/settings", "brand_patched")
    grm.on("POST", f"/api/videos/{V}/bulk", "bulk_clips")


def kyree(tmp_path) -> str:
    return plan(
        tmp_path,
        f"brand: shopfloor\nvideo: {V[:8]}\nsnapshot: before the plan\nkit:\n  set:\n    voice.room: small\n"
        f"clips:\n  {A['id'][:8]}:\n    hook: The worst advice I ever got\n    thumb.t: 3.2\n"
        f"  {C['id'][:8]}:\n    music: off\n",
    )


def test_a_plan_takes_a_snapshot_then_changes_the_kit_then_every_clip_in_one_save(grm, run, tmp_path):
    plan_world(grm)
    code, out, err = run("apply", kyree(tmp_path))
    assert code == 0 and "Done." in out and "snapshot restore" in err
    writes = [(s.method, s.path) for s in grm.sent if s.method != "GET"]
    assert writes == [
        ("POST", f"/api/brands/{B}/snapshots"),
        ("PATCH", f"/api/brands/{B}/settings"),
        ("POST", f"/api/videos/{V}/bulk"),
    ]
    assert grm.called("PATCH", f"/api/brands/{B}/settings")[0].json["set"] == {"brand_kit.voice.room": "small"}
    assert grm.called("POST", f"/api/videos/{V}/bulk")[0].json == {
        "clips": {
            A["id"]: {"set": {"spec.hook": "The worst advice I ever got", "spec.thumb.t": 3.2}, "unset": []},
            C["id"]: {"set": {"spec.music.on": False}, "unset": []},
        }
    }


def test_a_plan_dry_run_says_everything_and_sends_nothing(grm, run, tmp_path):
    plan_world(grm)
    code, out, _ = run("apply", kyree(tmp_path), "--dry-run")
    assert code == 0 and "Nothing was saved" in out
    assert "kit voice.room: (none) → small" in out and f"{C['id'][:8]} music.on: true → false" in out
    assert not [s for s in grm.sent if s.method != "GET"]


def test_a_plan_with_nothing_to_change_takes_no_snapshot(grm, run, tmp_path):
    plan_world(grm)
    f = plan(
        tmp_path,
        f"brand: shopfloor\nvideo: {V[:8]}\nsnapshot: s\nclips:\n  {A['id'][:8]}:\n    hook: {A['spec']['hook']}\n",
    )
    code, out, _ = run("apply", f)
    assert code == 0 and "nothing to change" in out and not [s for s in grm.sent if s.method != "GET"]


def test_a_plan_needs_a_grm_that_saves_every_clip_together(grm, run, tmp_path):
    plan_world(grm)
    grm.routes[("GET", "/api/meta")] = []
    grm.on("GET", "/api/meta", json_body={**body("meta"), "api": 1})
    code, out, err = run("apply", kyree(tmp_path), "--json")
    assert code == 1 and "older than grm apply needs" in err
    assert json.loads(out)["error"]["code"] == "server_too_old"
    assert not [s for s in grm.sent if s.method != "GET"]


def test_a_plan_whose_clips_fail_says_how_to_put_the_kit_back(grm, run, tmp_path):
    plan_world(grm)
    grm.routes[("POST", f"/api/videos/{V}/bulk")] = []
    grm.on("POST", f"/api/videos/{V}/bulk", "error_bulk_stranger")
    code, _, err = run("apply", kyree(tmp_path))
    assert code == 1 and answer("error_bulk_stranger")["body"]["title"] in err
    assert f"grm snapshot restore {SNAP['id'][:8]} puts the kit back" in err


def test_a_plan_makes_music_last_and_with_wait_puts_the_first_track_on(grm, run, tmp_path):
    plan_world(grm)
    grm.on("POST", f"/api/assets/{A['id']}/music/make", status=202, json_body={"job": {"id": "j-music"}})
    grm.on(
        "GET",
        "/api/jobs/j-music",
        json_body={
            "id": "j-music",
            "kind": "music",
            "status": "done",
            "progress": 1,
            "detail": "",
            "children": [],
            "result": {"with": {"new": ["t-1", "t-2"]}},
        },
    )
    grm.on("GET", f"/api/assets/{A['id']}", json_body={**A, "version": 9})
    grm.on("PATCH", f"/api/assets/{A['id']}", json_body=A)
    f = plan(
        tmp_path, f"brand: shopfloor\nvideo: {V[:8]}\nclips:\n  {A['id'][:8]}:\n    music: {{make: low strings}}\n"
    )
    code, out, err = run("apply", f, "--dry-run")
    assert code == 0 and "make two tracks, “low strings” (paid: ElevenLabs)" in out
    code, out, err = run("apply", f, "--wait")
    assert code == 0
    assert grm.called("POST", f"/api/assets/{A['id']}/music/make")[0].json == {"description": "low strings"}
    assert grm.called("PATCH", f"/api/assets/{A['id']}")[0].json == {
        "set": {"spec.music.on": True, "spec.music.track": {"source": "made", "id": "t-1"}},
        "if_version": 9,
    }


def test_a_plan_file_is_checked_before_anything_is_sent(grm, run, tmp_path):
    plan_world(grm)
    code, _, err = run("apply", plan(tmp_path, "brand: shopfloor\ncolours: red\n"))
    assert code == 2 and "colours" in err
    code, _, err = run("apply", plan(tmp_path, f"brand: shopfloor\nclips:\n  {A['id'][:8]}: {{hook: x}}\n"))
    assert code == 2 and "names no video" in err
    code, _, err = run("apply", plan(tmp_path, f"brand: shopfloor\nvideo: {V[:8]}\nclips:\n  0000ffff: {{hook: x}}\n"))
    assert code == 2 and "no clip" in err
    assert not [s for s in grm.sent if s.method != "GET"]
