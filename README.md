# grm-cli

The command line for [Generational Run Machine](https://app.generationalrunmachine.com) (GRM): add a video, wait for
its clips, look them over and export them, from a terminal or a script. Results go to stdout and progress to stderr,
`--json` makes stdout one JSON document, and the exit code says how it went, so a script (or an agent) can drive it.

## Install and sign in

```sh
uv tool install grm-cli          # or: pipx install grm-cli
grm login                        # asks for a token, and keeps it in your keychain
grm whoami                       # who you are, which workspace, what the token may do, which server
```

Make the token in GRM, on **Settings, API tokens**: tick what it may do (Read and Edit to start; Generate to process
videos, which pays for transcription and models; Approve; Export). A token belongs to one person and one workspace.

- The token is kept in the operating system's keychain. It is never taken as a command argument, which would land in
  shell history: `grm login` asks for it, or reads it from stdin (`grm login < token.txt`).
- `GRM_TOKEN` (and `GRM_URL`) in the environment are for CI and win over the keychain.
- The server is GRM's own unless `--url` at login, `GRM_URL` or a profile says otherwise. Profiles keep more than one:
  `grm login --profile dev --url http://localhost:8000`, then `grm … --profile dev` (or `GRM_PROFILE=dev`).
- Python 3.11 or later.

## Commands

```text
grm brands                                       the brands in your workspace
grm videos <brand> [--status review] [--ref …]   a brand's videos
grm video add <brand> <file|link> [--title …] [--ref drive:1AbC…] [--clips|--one] [--wait review] [--dry-run]
grm video show <video>
grm video wait <video> [--until review] [--timeout 30m]
grm transcript <video> [--words|--srt]
grm job <job> | grm job wait <job> [--timeout 10m] | grm jobs <video>
grm clips <video> [--status review]              id, status, length, title, hook
grm clip show <clip> | --match "words of its title" [--video <video>]
grm export <video> [--out ./export/] [--ready] [--no-wait] [--timeout 1h]
grm exports <video>                              each asset, and whether its files are ready
grm api GET /api/videos/<id>/spares              any route, with the token filled in (like gh api)
grm api POST /api/assets/<id>/status -f status=approved
```

- **Names instead of ids.** A brand by its name, code or handle (`shopfloor`, `@shopfloor`, or the start of its
  name). A video or a clip by the first 8 characters of its id, as the lists show it, or a clip by words of its title
  (`--match`). A name that matches two things is refused, with both listed.
- **Waiting is done by grm.** `video add --wait`, `video wait`, `job wait` and `export` ask after the work at the pace
  the server sets (its `Retry-After`), say how it stands on stderr (each stage of processing on a line of its own),
  and end when it does. `--timeout` gives up (exit 3) and leaves the work running.
- **Adding the same file twice.** `video add --ref <where it came from>` with a ref already there says so, prints
  that video's id and adds nothing, unless `--again`.
- **Paying.** Processing a video pays for transcription and the language models: `video add` says so, and
  `--dry-run` says what it would do and does nothing.
- **Exports.** `export --out <folder>` waits for every file, downloads them into the folders the pack uses (TikTok,
  Instagram, …), each clip's SRT and VTT captions included, and prints their paths, one per line.

Exit codes:

| Code | Means |
|---|---|
| 0 | Done |
| 1 | Failed (the error's title and fix on stderr; its `code` in `--json`) |
| 2 | Wrong use of the command (including a name that matches nothing, or two things) |
| 3 | Gave up waiting (`--timeout`) |
| 4 | The token lacks the scope |
| 5 | Changed since you read it |

`grm api` reaches any route. The ones grm calls are GRM's public API (tagged `public` in its `/openapi.json`); what
they take changes only with the `api` version in `/api/meta`, which `grm whoami` shows. Other routes can change without
notice.

## Try the whole loop for free

GRM runs with stand-ins for every paid service (transcription, models, pictures, music, rendering), so the whole loop
costs nothing on a local GRM. In a checkout of GRM, start its test stack:

```sh
scripts/e2e_stack.sh start       # GRM's API on http://localhost:8010 and its web app on :5183, with the stand-ins
```

Sign up at http://localhost:5183, make a brand and a token (Settings, API tokens), then:

```sh
grm login --profile local --url http://localhost:8010
grm video add "My brand" episode.mp4 --wait review --profile local
grm clips <video> --profile local
grm api POST /api/assets/<clip>/status -f status=approved --profile local
grm export <video> --out ./export/ --profile local
```

## Working on grm

```sh
uv sync
uv run pytest                          # unit tests: grm against answers a real GRM gave (tests/answers/)
uv run ruff check src tests && uv run ruff format src tests
```

- **The smoke test** runs grm's whole loop against a local GRM. It makes its own account, workspace, brand and
  token, so sign-up must be open, as it is on the test stack:

  ```sh
  uv run python tests/smoke.py --url http://localhost:8010 --file path/to/video.mp4
  ```

  GRM's own CI runs it against GRM's test stack, so a change to GRM can't quietly break grm.
- **Recorded answers.** `tests/answers/` is what a real GRM answered to each route grm calls. Record them again after
  GRM's public API changes: `uv run python tests/record.py --url http://localhost:8010 --file path/to/video.mp4`.
- **Releasing.** Push a tag matching the version in `pyproject.toml` (`v0.1.0`): GitHub Actions tests it, builds it and
  publishes it to PyPI with trusted publishing, so no PyPI token is stored anywhere. Versions stay `0.x` until GRM's
  public API has held for a month.
