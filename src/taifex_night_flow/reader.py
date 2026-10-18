from __future__ import annotations
import json
from datetime import date, datetime, timezone
from pathlib import Path

class ReaderError(ValueError):
    pass

def read_snapshot(path: str | Path, expected_date: date, *, now: datetime | None = None, max_age_days: int = 0) -> dict:
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != "1.0": raise ReaderError("unsupported schema_version")
    if data.get("status") != "VALIDATED": raise ReaderError("snapshot is not VALIDATED")
    if data.get("trade_date") != expected_date.isoformat(): raise ReaderError("stale or wrong trade_date")
    if data.get("expected_trade_date") != expected_date.isoformat(): raise ReaderError("expected_trade_date mismatch")
    for key in ("validated_at_utc","first_seen_at_utc"):
        value=data.get(key)
        if not value: raise ReaderError(f"missing {key}")
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        if parsed.tzinfo is None: raise ReaderError(f"{key} must be timezone-aware")
    ts=datetime.fromisoformat(data["validated_at_utc"].replace("Z","+00:00"))
    current=now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None: raise ReaderError("reader now must be timezone-aware")
    current=current.astimezone(timezone.utc)
    if ts > current: raise ReaderError("validated_at_utc is in the future")
    if (current.date()-ts.date()).days > max_age_days: raise ReaderError("snapshot exceeds freshness limit")
    if set(data.get("instruments",{})) != {"TX","MTX","TMF"}: raise ReaderError("required instruments missing")
    fields=("foreign_long","foreign_short","foreign_net","foreign_long_value_thousand_ntd","foreign_short_value_thousand_ntd","foreign_net_value_thousand_ntd")
    for symbol,row in data["instruments"].items():
        if any(not isinstance(row.get(key),int) for key in fields): raise ReaderError(f"{symbol} has missing or invalid numeric fields")
        if row["foreign_long"]-row["foreign_short"] != row["foreign_net"]: raise ReaderError(f"{symbol} fails net-volume validation")
    return data
