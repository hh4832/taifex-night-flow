import json
from datetime import date
from pathlib import Path
import pytest
from taifex_night_flow.storage import EventStore
from taifex_night_flow.collector import collect
from taifex_night_flow.config import FetchConfig
from taifex_night_flow.client import FetchFailure
from taifex_night_flow.reader import read_snapshot, ReaderError

FIX=Path(__file__).parent/"fixtures"

def fake_fetch(day,config):
    body=(FIX/"source_html"/f"taifex_{day.isoformat()}.html").read_bytes()
    return body,200,1

def test_first_seen_is_from_first_valid_observation_and_same_data_is_unchanged(tmp_path):
    store=EventStore(tmp_path)
    first=collect(date(2026,10,16),store,fetcher=fake_fetch)
    seen=first["event"]["first_seen_at_utc"]
    second=collect(date(2026,10,16),store,fetcher=fake_fetch)
    assert first["event"]["fetch_status"]=="SUCCESS_FIRST_SEEN"
    assert second["event"]["fetch_status"]=="SUCCESS_UNCHANGED"
    assert second["event"]["first_seen_at_utc"]==seen
    assert len(store.events())==2

def test_revision_keeps_previous_snapshot_and_first_seen(tmp_path):
    store=EventStore(tmp_path)
    first=collect(date(2026,10,16),store,fetcher=fake_fetch)
    original=first["event"]["normalized_data_sha256"]
    def revised(day,config):
        html=(FIX/"source_html"/"taifex_2026-10-16.html").read_text()
        html=html.replace("24,854","24,855").replace("772","773")
        return html.encode(),200,1
    changed=collect(date(2026,10,16),store,fetcher=revised)
    assert changed["event"]["fetch_status"]=="SUCCESS_REVISED"
    assert changed["event"]["normalized_data_sha256"]!=original
    assert changed["event"]["first_seen_at_utc"]==first["event"]["first_seen_at_utc"]
    store.export()
    assert len(list((tmp_path/"snapshots"/"20261016").glob("*.parquet")))==2

def test_duplicate_event_id_is_rejected_and_export_is_append_only(tmp_path):
    store=EventStore(tmp_path)
    result=collect(date(2026,10,16),store,fetcher=fake_fetch)
    event=result["event"]
    store.export()
    path=next((tmp_path/"observations").glob("*/*.json"))
    before=path.read_bytes()
    with pytest.raises(ValueError,match="duplicate event_id"):
        store.write_event(event)
    store.export()
    assert path.read_bytes()==before

def test_retry_failure_requests_are_individual_observation_events(tmp_path):
    store=EventStore(tmp_path)
    def flaky(day,config):
        body=(FIX/"source_html"/"taifex_2026-10-16.html").read_bytes()
        history=[
          {"attempt_number":1,"request_started_at_utc":"2026-10-18T13:00:00Z","response_received_at_utc":"2026-10-18T13:00:01Z","observed_at_taipei":"2026-10-18T21:00:01+08:00","http_status":None,"fetch_status":"HTTP_TIMEOUT","reason":"timeout","duration_ms":1000},
          {"attempt_number":2,"request_started_at_utc":"2026-10-18T13:00:03Z","response_received_at_utc":"2026-10-18T13:00:04Z","observed_at_taipei":"2026-10-18T21:00:04+08:00","http_status":200,"fetch_status":"HTTP_RESPONSE","reason":None,"duration_ms":1000},
        ]
        return body,200,2,history
    result=collect(date(2026,10,16),store,fetcher=flaky)
    events=store.events()
    assert len(events)==2
    assert [e["fetch_status"] for e in events]==["HTTP_TIMEOUT","SUCCESS_FIRST_SEEN"]
    assert len({e["run_id"] for e in events})==1

def test_reader_rejects_stale_invalid_and_missing_timestamps(tmp_path):
    result=collect(date(2026,10,16),EventStore(tmp_path),fetcher=fake_fetch)
    path=tmp_path/"snapshot.json"
    path.write_text(json.dumps(result["snapshot"]))
    assert read_snapshot(path,date(2026,10,16))["status"]=="VALIDATED"
    with pytest.raises(ReaderError,match="wrong trade_date"):
        read_snapshot(path,date(2026,10,15))
    invalid=dict(result["snapshot"],status="INVALID")
    path.write_text(json.dumps(invalid))
    with pytest.raises(ReaderError,match="not VALIDATED"): read_snapshot(path,date(2026,10,16))
    invalid=dict(result["snapshot"],first_seen_at_utc=None)
    path.write_text(json.dumps(invalid))
    with pytest.raises(ReaderError,match="missing first_seen_at_utc"): read_snapshot(path,date(2026,10,16))

def test_drive_failure_does_not_publish_or_advance_latest(tmp_path,monkeypatch):
    import taifex_night_flow.cli as cli
    from taifex_night_flow.drive_sync import DriveSyncError
    event={"event_id":"evt","run_id":"run","attempt_number":1,"expected_trade_date":"2026-10-16","trade_date":"2026-10-16",
      "request_started_at_utc":"2026-10-18T13:00:00Z","response_received_at_utc":"2026-10-18T13:00:01Z",
      "validated_at_utc":"2026-10-18T13:00:02Z","observed_at_taipei":"2026-10-18T21:00:01+08:00",
      "first_seen_at_utc":"2026-10-18T13:00:01Z","http_status":200,"fetch_status":"SUCCESS_FIRST_SEEN","reason":None,
      "content_sha256":None,"normalized_data_sha256":"abc123","source_url":"https://example.test","parser_version":"0.1.0","attempts":1,"duration_ms":100}
    snapshot={"schema_version":"1.0","source":"TAIFEX","session":"NIGHT","trade_date":"2026-10-16","expected_trade_date":"2026-10-16",
      "first_seen_at_utc":event["first_seen_at_utc"],"validated_at_utc":event["validated_at_utc"],"status":"VALIDATED",
      "units":{"volume":"contracts","value":"thousand_NTD"},
      "instruments":{"TX":{"foreign_net":1},"MTX":{"foreign_net":1},"TMF":{"foreign_net":1}}}
    monkeypatch.setattr(cli,"collect",lambda *args,**kwargs:{"event":event,"snapshot":snapshot})
    monkeypatch.setattr(cli,"sync_tree",lambda *args,**kwargs:(_ for _ in ()).throw(DriveSyncError("offline")))
    code=cli.main(["--date","2026-10-16","--data-dir",str(tmp_path),"--rclone-remote","drive"])
    assert code==4
    assert not (tmp_path/"latest.json").exists()
