from __future__ import annotations
import argparse, json, os, sys
from datetime import date, datetime
from pathlib import Path
import tempfile
from .calendar import expected_trade_date, CalendarUnavailable
from .collector import collect
from .config import DRIVE_FOLDER_ID
from .drive_sync import sync_tree, DriveSyncError
from .storage import EventStore

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--date",default="auto",help="YYYY-MM-DD or auto")
    p.add_argument("--data-dir",default="data")
    p.add_argument("--calendar-file",default="calendar/verified_open_dates.txt")
    p.add_argument("--rclone-remote",default=os.getenv("RCLONE_REMOTE"))
    p.add_argument("--no-drive",action="store_true")
    p.add_argument("--dry-run",action="store_true")
    args=p.parse_args(argv)
    if args.date=="auto":
        days=set()
        try:
            days={date.fromisoformat(x.strip()) for x in Path(args.calendar_file).read_text().splitlines() if x.strip() and not x.startswith("#")}
            day=expected_trade_date(verified_open_dates=days)
        except (OSError,ValueError,CalendarUnavailable) as exc:
            print(json.dumps({"status":"SKIPPED_NON_TRADING_DAY","reason":str(exc)})); return 3
    else:
        day=date.fromisoformat(args.date)
    if args.dry_run:
        with tempfile.TemporaryDirectory(prefix="taifex-night-flow-dry-run-") as temp:
            result=collect(day,EventStore(temp))
        print(json.dumps({"dry_run":True,"status":result["event"]["fetch_status"],"event":result["event"],"snapshot":result["snapshot"]},ensure_ascii=False))
        return 0 if result["snapshot"] is not None else 2
    store=EventStore(args.data_dir)
    result=collect(day,store)
    event=result["event"]
    store.export()
    if result["snapshot"] is not None:
        folder=Path(args.data_dir)/"daily"; folder.mkdir(parents=True,exist_ok=True)
        result["snapshot"]["first_seen_at_utc"]=event["first_seen_at_utc"]
        content=json.dumps(result["snapshot"],ensure_ascii=False,indent=2)
        revision=folder/f"{day:%Y%m%d}_{event['normalized_data_sha256'][:12]}.json"
        if not revision.exists(): revision.write_text(content,encoding="utf-8")
        pointer={"schema_version":"1.0","trade_date":day.isoformat(),"status":"VALIDATED",
                 "first_seen_at_utc":event["first_seen_at_utc"],"validated_at_utc":event["validated_at_utc"],
                 "normalized_data_sha256":event["normalized_data_sha256"],"snapshot_path":str(revision.relative_to(args.data_dir))}
        if not args.no_drive and args.rclone_remote:
            try:
                sync_tree(args.data_dir,args.rclone_remote,DRIVE_FOLDER_ID)
                latest=Path(args.data_dir)/"latest.json"
                previous=latest.read_bytes() if latest.exists() else None
                fd,tmp_name=tempfile.mkstemp(dir=latest.parent,prefix="latest.",suffix=".tmp")
                with os.fdopen(fd,"w",encoding="utf-8") as f: json.dump(pointer,f,ensure_ascii=False,indent=2)
                Path(tmp_name).replace(latest)
                try:
                    from .drive_sync import publish_latest
                    publish_latest(latest,args.rclone_remote,DRIVE_FOLDER_ID)
                except DriveSyncError:
                    if previous is None: latest.unlink(missing_ok=True)
                    else: latest.write_bytes(previous)
                    raise
            except DriveSyncError as exc:
                print(json.dumps({"status":"DRIVE_ERROR","reason":str(exc),"event":event},ensure_ascii=False)); return 4
        else:
            latest=Path(args.data_dir)/"latest.json"
            temp=latest.with_suffix(".tmp")
            temp.write_text(json.dumps(pointer,ensure_ascii=False,indent=2),encoding="utf-8"); temp.replace(latest)
            print("Drive sync skipped: no rclone remote configured; local evidence retained.",file=sys.stderr)
    elif not args.no_drive and args.rclone_remote:
        # Failed HTTP/parser/validation observations are still evidence and must reach Drive.
        try:
            sync_tree(args.data_dir,args.rclone_remote,DRIVE_FOLDER_ID)
        except DriveSyncError as exc:
            print(json.dumps({"status":"DRIVE_ERROR","reason":str(exc),"event":event},ensure_ascii=False)); return 4
    elif args.no_drive or not args.rclone_remote:
        print("Drive sync skipped: no rclone remote configured; local failure evidence retained.",file=sys.stderr)
    print(json.dumps(result,ensure_ascii=False,default=str))
    return 0 if event["fetch_status"].startswith("SUCCESS") else 2

if __name__=="__main__": raise SystemExit(main())
