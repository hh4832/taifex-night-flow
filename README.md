# TAIFEX Night Flow Data Collector

Version: **v0.1.0** · Python **3.11**

This repository captures TAIFEX's official night-session, by-contract foreign institutional report. It records every HTTP attempt, response hash, report date, validation time, and data revision. It does not create trading signals.

**Source:** [TAIFEX night-session report](https://www.taifex.com.tw/cht/3/futContractsDateAhExcel)  
**Drive root folder ID:** 1bHNCF59WGheGa5Tmo_GDK53T4fxU00oD

## Data and trust model

- Instruments: TX (臺股期貨), MTX (小型臺指期貨), TMF (微型臺指期貨).
- Only foreign institutional rows are collected.
- Volume unit: contracts. Contract-value unit: **thousand NTD**, exactly as TAIFEX labels it.
- The report date is parsed from HTML and must equal the requested trade date. HTTP 200 alone is never success.
- HTML rows are interpreted within each product's fixed three-row group (dealer, investment trust, foreign) after expanding merged cells. Conflicting duplicate candidates fail closed.
- Each HTTP attempt is its own event, including timeouts and retryable HTTP failures. first_seen_at_utc is the response time of this system's first successfully validated observation; it is not an official TAIFEX publication timestamp.
- The content hash identifies the captured HTML. The normalized hash covers the date, session, source, schema, and instrument values, not observation timestamps. A same-data poll is SUCCESS_UNCHANGED; changed values are SUCCESS_REVISED.
- SQLite is a rebuildable local index. Immutable JSON observation envelopes and content-addressed raw HTML are the Drive audit record. Re-running a poll creates new observation events and never replaces an old event.
- The GitHub Actions workflow serializes all scheduled and manual runs. Do not run a Colab Drive writer at the same time as an Actions collection. The Colab notebook has an explicit Drive-save switch; leave it off when an Actions run may be active.

## Repository contents

- src/taifex_night_flow/: collector, parser, calendar guard, validation, timestamps, local event ledger, Drive transport, CLI, and stable Reader.
- notebooks/run_taifex_night_flow.ipynb: interactive Colab flow with Drive folder-ID verification.
- .github/workflows/collect_night_flow.yml: schedule and manual collector.
- tests/fixtures/source_html/: minimized offline HTML excerpts from 10 official TAIFEX reports, preserved separately from expectations.
- tests/fixtures/expected/: frozen parsed values for 10 dates × 3 instruments. The prompt-provided net references for 10/08, 10/15, and 10/16 are asserted explicitly.
- calendar/verified_open_dates.txt: TAIFEX 2026 open dates from 2026-10-19 through year-end, transcribed from the official [2026 Trading Calendar PDF](https://www.taifex.com.tw/file/taifex/eng/eng4/2026Calendar_en.pdf). Extend it from a newly published official calendar before automatic polling enters a later calendar year. Unknown dates are skipped.

## Local setup and run

    uv python install 3.11
    uv venv --python 3.11 .venv
    uv pip install --python .venv/bin/python -e '.[test]'
    .venv/bin/pytest

Manual date smoke test (makes a real request):

    .venv/bin/taifex-night-flow --date 2026-10-16 --data-dir data --no-drive

Automatic date (only when Taipei time is 06:30–08:45 and the exact date is in the verified calendar):

    .venv/bin/taifex-night-flow --date auto --data-dir data

Dry run fetches and validates without retaining the event or publishing a pointer:

    .venv/bin/taifex-night-flow --date 2026-10-16 --dry-run

A NOT_YET_AVAILABLE response is retained as an observation. A report-date mismatch, parser failure, validation failure, timeout, or HTTP failure never updates latest.json.

## Output layout

The folder ID above is the data root.

    raw/<sha256>.html
    observations/YYYYMMDD/<request_timestamp>_<event_id>.json
    snapshots/YYYYMMDD/<normalized_hash>.parquet
    daily/YYYYMMDD_<normalized_hash>.json
    logs/fetch_events.csv
    manifest.json
    latest.json

Observation JSON envelopes contain the request event and, when validated, its standard snapshot. Parquet files contain one row per instrument and retain unit labels. Snapshot and event names are unique/content-addressed. manifest.json and CSV are rebuildable indexes; latest.json is updated only after validation and successful storage synchronization.

## Stable Reader

Use the Reader rather than parsing TAIFEX HTML in downstream repositories:

    from datetime import date
    from taifex_night_flow.reader import read_snapshot

    snapshot = read_snapshot(
        "data/daily/20261016_<hash>.json",
        expected_date=date(2026, 10, 16),
    )
    print(snapshot["instruments"]["TX"]["foreign_net"])

The Reader rejects unsupported schemas, invalid status, stale dates, missing timestamps, and incomplete instruments. It defaults to the exact expected date and zero-day freshness tolerance.

## Colab

Open notebooks/run_taifex_night_flow.ipynb in Colab. The notebook clones this repository, installs dependencies, mounts Drive interactively, verifies the configured folder ID via Drive API, copies prior audit data to a local working directory, runs the collector, and appends immutable evidence before publishing the pointer. TARGET_DATE, SAVE_TO_DRIVE, and DRY_RUN are top-level parameters. Drive mount is for a human-operated Colab session only.

## GitHub Actions and Drive Secrets

The scheduled workflow polls every 15 minutes from **06:30 to 08:45 Asia/Taipei** on weekdays. The UTC cron is split across 22:30–23:45 UTC on the preceding UTC day and 00:00–00:45 UTC on the local weekday. Actions schedules can be delayed or skipped; all stored timestamps are taken from the actual request.

To enable unattended Drive writes:

1. Install rclone locally and configure an OAuth-backed Google Drive remote named drive using the Google account that can access the destination folder.
2. Confirm that rclone lsf drive: --drive-root-folder-id 1bHNCF59WGheGa5Tmo_GDK53T4fxU00oD can list that folder.
3. Base64-encode the complete rclone configuration file without line wrapping (Linux: base64 -w0 rclone.conf; macOS: base64 < rclone.conf | tr -d '\n').
4. In the GitHub repository, open **Settings → Secrets and variables → Actions → New repository secret** and add RCLONE_CONFIG_B64 with that encoded value. Never commit the config or token.
5. The workflow decodes the secret into a permission-restricted runner file, verifies the Drive folder, hydrates prior events, and uploads. Logs never print the secret.
6. If this secret is absent, collection still runs locally and uploads a GitHub Actions artifact. Drive is not marked successful.

If a configured Drive read or write fails, the job fails and does not advance the pointer. The workflow artifact is retained for diagnostics. latest.json is published only after the immutable records have uploaded and the pointer itself is verified.

## Tests and smoke checks

- Offline parser/validation, 10 report fixtures × 3 products (30 rows), supplied historical net values, merged cells, duplicate conflicts, date mismatch, and no-data response.
- Timeout retry count and per-request times; non-trading auto skip; timezone conversion.
- First-seen derivation, unchanged/revised snapshots, append-only events, duplicate event rejection, and Reader freshness/status checks.
- A live TAIFEX smoke test is optional and must be requested explicitly with a known trade date. CI has no dependency on TAIFEX availability.

## Scope limits

- No inference or trading recommendation is produced.
- Automatic calendar coverage ends on 2026-12-31 and intentionally fails closed outside the verified set until the next official calendar is added.
- Actual Drive write verification is recorded separately from code/test success; GitHub Actions needs RCLONE_CONFIG_B64 configured.
