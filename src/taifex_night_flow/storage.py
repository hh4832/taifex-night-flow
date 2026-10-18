from __future__ import annotations
import hashlib, json, sqlite3
from datetime import date
from pathlib import Path
import csv
from .timestamps import iso_utc
from .__init__ import SCHEMA_VERSION

def canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def normalized_payload(snapshot: dict) -> dict:
    return {"schema_version": snapshot.get("schema_version", SCHEMA_VERSION),
            "source": snapshot.get("source", "TAIFEX"), "session": snapshot.get("session", "NIGHT"),
            "trade_date": snapshot["trade_date"], "instruments": snapshot["instruments"]}

class EventStore:
    """Append-only local SQLite event ledger; blob bytes are content-addressed."""
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root/".state").mkdir(exist_ok=True)
        self.db_path = self.root / ".state" / "observations.sqlite3"
        self.blob_dir = self.root / "raw"
        self.blob_dir.mkdir(exist_ok=True)
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, attempt_number INTEGER NOT NULL, expected_trade_date TEXT NOT NULL, trade_date TEXT,
              request_started_at_utc TEXT NOT NULL, response_received_at_utc TEXT,
              validated_at_utc TEXT, observed_at_taipei TEXT NOT NULL,
              first_seen_at_utc TEXT, http_status INTEGER, fetch_status TEXT NOT NULL,
              reason TEXT, content_sha256 TEXT, normalized_data_sha256 TEXT,
              source_url TEXT NOT NULL, parser_version TEXT NOT NULL, attempts INTEGER NOT NULL,
              duration_ms INTEGER
            );
            CREATE TABLE IF NOT EXISTS snapshots (
              trade_date TEXT NOT NULL, normalized_data_sha256 TEXT NOT NULL,
              first_seen_at_utc TEXT NOT NULL, snapshot_json TEXT NOT NULL,
              PRIMARY KEY(trade_date, normalized_data_sha256)
            );
            """)
        self._hydrate()
    def _connect(self):
        db=sqlite3.connect(self.db_path, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA busy_timeout=30000")
        return db
    def _hydrate(self):
        """Rebuild disposable SQLite indexes from immutable Drive event envelopes."""
        for path in sorted((self.root/"observations").glob("*/*.json")):
            try:
                envelope=json.loads(path.read_text(encoding="utf-8")); event=envelope["event"]; snapshot=envelope.get("snapshot")
                with self._connect() as db:
                    if db.execute("SELECT 1 FROM events WHERE event_id=?",(event["event_id"],)).fetchone(): continue
                    if snapshot:
                        digest=event.get("normalized_data_sha256")
                        first_seen=event.get("first_seen_at_utc") or event.get("validated_at_utc")
                        db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?)",(snapshot["trade_date"],digest,first_seen,canonical_json(snapshot).decode()))
                    keys=list(event)
                    db.execute(f"INSERT INTO events ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[event[k] for k in keys])
            except (OSError,ValueError,KeyError,json.JSONDecodeError,sqlite3.Error):
                continue
    def known_hash(self, day: str):
        with self._connect() as db:
            row=db.execute("SELECT normalized_data_sha256 FROM snapshots WHERE trade_date=? ORDER BY rowid DESC LIMIT 1",(day,)).fetchone()
        return row[0] if row else None
    def first_seen(self, day: str):
        with self._connect() as db:
            row=db.execute("SELECT first_seen_at_utc FROM snapshots WHERE trade_date=? ORDER BY rowid LIMIT 1",(day,)).fetchone()
        return row[0] if row else None
    def write_event(self, event: dict, html: bytes | None = None, snapshot: dict | None = None):
        run_id=event["run_id"]
        if html is not None:
            digest=sha256(html)
            event["content_sha256"]=digest
            path=self.blob_dir / f"{digest}.html"
            if not path.exists():
                temp=path.with_suffix(".tmp")
                temp.write_bytes(html)
                temp.replace(path)
        with self._connect() as db:
            if db.execute("SELECT 1 FROM events WHERE event_id=?",(event["event_id"],)).fetchone():
                raise ValueError(f"duplicate event_id: {event['event_id']}")
            if snapshot is not None:
                digest=sha256(canonical_json(normalized_payload(snapshot)))
                event["normalized_data_sha256"]=digest
                day=snapshot["trade_date"]
                existing=db.execute("SELECT first_seen_at_utc FROM snapshots WHERE trade_date=? ORDER BY rowid LIMIT 1",(day,)).fetchone()
                previous=db.execute("SELECT normalized_data_sha256 FROM snapshots WHERE trade_date=? ORDER BY rowid DESC LIMIT 1",(day,)).fetchone()
                first_seen=existing[0] if existing else (event.get("response_received_at_utc") or event["validated_at_utc"])
                event["first_seen_at_utc"]=first_seen
                db.execute("INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?)",(day,digest,first_seen,canonical_json(snapshot).decode()))
                event["fetch_status"]="SUCCESS_FIRST_SEEN" if existing is None else ("SUCCESS_UNCHANGED" if previous and digest==previous[0] else "SUCCESS_REVISED")
            keys=list(event)
            db.execute(f"INSERT INTO events ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",[event[k] for k in keys])
        return event
    def events(self):
        with self._connect() as db:
            db.row_factory=sqlite3.Row
            return [dict(x) for x in db.execute("SELECT * FROM events ORDER BY request_started_at_utc")]

    def export(self):
        """Write immutable observation envelopes and rebuild audit indexes."""
        events=self.events()
        observation_root=self.root/"observations"
        for event in events:
            stamp=event["request_started_at_utc"].replace(":", "").replace("-", "")
            day=event["expected_trade_date"].replace("-", "")
            path=observation_root/day/f"{stamp}_{event['event_id']}.json"
            path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():
                payload={"event":event,"snapshot":None}
                with self._connect() as db:
                    row=db.execute("SELECT snapshot_json FROM snapshots WHERE trade_date=? AND normalized_data_sha256=?",(event["trade_date"],event["normalized_data_sha256"])).fetchone() if event["trade_date"] and event["normalized_data_sha256"] else None
                if row:
                    payload["snapshot"]=json.loads(row[0]); payload["snapshot"]["first_seen_at_utc"]=event["first_seen_at_utc"]
                path.write_bytes(canonical_json(payload)+b"\n")
        (self.root/"manifest.json").write_text(json.dumps({"schema_version":"1.0","event_count":len(events),"events":[{"event_id":e["event_id"],"run_id":e["run_id"],"attempt_number":e["attempt_number"],"expected_trade_date":e["expected_trade_date"],"trade_date":e["trade_date"],"fetch_status":e["fetch_status"],"request_started_at_utc":e["request_started_at_utc"],"normalized_data_sha256":e["normalized_data_sha256"]} for e in events]},ensure_ascii=False,indent=2),encoding="utf-8")
        (self.root/"logs").mkdir(exist_ok=True)
        with (self.root/"logs"/"fetch_events.csv").open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(events[0]) if events else ["run_id"]); writer.writeheader(); writer.writerows(events)
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            with self._connect() as db:
                snapshots=db.execute("SELECT trade_date,normalized_data_sha256,first_seen_at_utc,snapshot_json FROM snapshots").fetchall()
            for day,digest,first_seen,snapshot_json in snapshots:
                snapshot=json.loads(snapshot_json); snapshot["first_seen_at_utc"]=first_seen
                records=[{"schema_version":SCHEMA_VERSION,"source":"TAIFEX","session":"NIGHT","trade_date":day,"first_seen_at_utc":first_seen,"validated_at_utc":snapshot.get("validated_at_utc"),"status":"VALIDATED","symbol":symbol,**values} for symbol,values in snapshot["instruments"].items()]
                target=self.root/"snapshots"/day.replace("-","")/f"{digest}.parquet"
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists(): pq.write_table(pa.Table.from_pylist(records),target)
        except ImportError:
            pass
