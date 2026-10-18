from __future__ import annotations
import time, uuid
from datetime import date
from . import PARSER_VERSION
from .client import FetchFailure, fetch_report
from .config import FetchConfig, SOURCE_URL
from .parser import parse_report, ParserError
from .storage import EventStore
from .timestamps import iso_taipei, iso_utc, utc_now
from .validation import validate_snapshot, ValidationError

def _event(day: date, run_id: str, attempt: dict, final: bool, attempts_count: int) -> dict:
    return {
      "event_id":str(uuid.uuid4()),"run_id":run_id,"attempt_number":attempt["attempt_number"],
      "expected_trade_date":day.isoformat(),"trade_date":None,
      "request_started_at_utc":attempt["request_started_at_utc"],
      "response_received_at_utc":attempt.get("response_received_at_utc"),
      "validated_at_utc":None,"observed_at_taipei":attempt.get("observed_at_taipei") or iso_taipei(utc_now()),
      "first_seen_at_utc":None,"http_status":attempt.get("http_status"),
      "fetch_status":attempt.get("fetch_status","HTTP_ERROR"),"reason":attempt.get("reason"),
      "content_sha256":None,"normalized_data_sha256":None,"source_url":SOURCE_URL,
      "parser_version":PARSER_VERSION,"attempts":attempts_count,"duration_ms":attempt.get("duration_ms",0),
    }

def collect(day: date, store: EventStore, config: FetchConfig = FetchConfig(), fetcher=fetch_report) -> dict:
    started=utc_now(); t0=time.monotonic(); run_id=str(uuid.uuid4())
    body=None; history=[]
    try:
        fetched=fetcher(day,config)
        if len(fetched)==4:
            body,status,attempts,history=fetched
        else:
            body,status,attempts=fetched
            received=utc_now()
            history=[{"attempt_number":attempts,"request_started_at_utc":iso_utc(started),
                      "response_received_at_utc":iso_utc(received),"observed_at_taipei":iso_taipei(received),
                      "http_status":status,"fetch_status":"HTTP_RESPONSE","reason":None,
                      "duration_ms":round((time.monotonic()-t0)*1000)}]
        body=body if isinstance(body,bytes) else body.encode()
        parsed=parse_report(body.decode("utf-8",errors="replace"),day)
        validate_snapshot(parsed,day)
        validated_at=iso_utc(utc_now())
        snapshot={"schema_version":"1.0","source":"TAIFEX","session":"NIGHT",
          "trade_date":parsed["trade_date"],"expected_trade_date":day.isoformat(),
          "first_seen_at_utc":None,"validated_at_utc":validated_at,"status":"VALIDATED",
          "units":{"volume":"contracts","value":"thousand_NTD"},"instruments":parsed["instruments"]}
        events=[]
        for attempt in history[:-1]:
            event=_event(day,run_id,attempt,False,len(history)); store.write_event(event,attempt.get("response_body"))
            events.append(event)
        final=history[-1]
        event=_event(day,run_id,final,True,len(history))
        event["trade_date"]=parsed["trade_date"]; event["validated_at_utc"]=validated_at
        event["fetch_status"]="SUCCESS"; event["reason"]=None
        store.write_event(event,body,snapshot)
        events.append(event)
        snapshot["first_seen_at_utc"]=event["first_seen_at_utc"]
        return {"event":event,"events":events,"snapshot":snapshot}
    except FetchFailure as exc:
        history=exc.attempt_events
        if not history:
            now=utc_now()
            history=[{"attempt_number":1,"request_started_at_utc":iso_utc(started),
              "response_received_at_utc":iso_utc(now),"observed_at_taipei":iso_taipei(now),
              "http_status":exc.http_status,"fetch_status":exc.status,"reason":str(exc),
              "duration_ms":round((time.monotonic()-t0)*1000)}]
        events=[]
        for attempt in history:
            event=_event(day,run_id,attempt,True,len(history))
            store.write_event(event,attempt.get("response_body")); events.append(event)
        return {"event":events[-1],"events":events,"snapshot":None}
    except (ParserError,ValidationError) as exc:
        # One HTTP 200 attempt produced an unpublishable response; retain that request as an event.
        status=("NOT_YET_AVAILABLE" if "NOT_YET_AVAILABLE" in str(exc) else
                "DATE_MISMATCH" if str(exc).startswith("DATE_MISMATCH") else
                "VALIDATION_FAILED" if isinstance(exc,ValidationError) else "PARSER_ERROR")
        if not history:
            now=utc_now()
            history=[{"attempt_number":1,"request_started_at_utc":iso_utc(started),
              "response_received_at_utc":iso_utc(now),"observed_at_taipei":iso_taipei(now),
              "http_status":200,"fetch_status":status,"reason":str(exc),
              "duration_ms":round((time.monotonic()-t0)*1000)}]
        events=[]
        for attempt in history[:-1]:
            event=_event(day,run_id,attempt,False,len(history)); store.write_event(event,attempt.get("response_body")); events.append(event)
        attempt=history[-1]; attempt.update(fetch_status=status,reason=str(exc))
        event=_event(day,run_id,attempt,True,len(history))
        event["response_received_at_utc"]=attempt.get("response_received_at_utc") or iso_utc(utc_now())
        event["duration_ms"]=attempt.get("duration_ms",0)
        store.write_event(event,attempt.get("response_body",body),None); events.append(event)
        return {"event":event,"events":events,"snapshot":None}
    except Exception as exc:
        now=utc_now()
        attempt={"attempt_number":1,"request_started_at_utc":iso_utc(started),
          "response_received_at_utc":iso_utc(now),"observed_at_taipei":iso_taipei(now),
          "http_status":None,"fetch_status":"PARSER_ERROR","reason":f"{type(exc).__name__}: {exc}",
          "duration_ms":round((time.monotonic()-t0)*1000)}
        event=_event(day,run_id,attempt,True,1); store.write_event(event,body,None)
        return {"event":event,"events":[event],"snapshot":None}
