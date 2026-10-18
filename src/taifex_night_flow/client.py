from __future__ import annotations
import random, time
from datetime import date
import requests
from .config import FetchConfig, SOURCE_URL
from .timestamps import iso_utc, iso_taipei, utc_now

class FetchFailure(RuntimeError):
    def __init__(self, status: str, message: str, attempts: int, http_status: int | None = None, attempt_events=None):
        super().__init__(message); self.status=status; self.attempts=attempts; self.http_status=http_status; self.attempt_events=attempt_events or []

def fetch_report(day: date, config: FetchConfig = FetchConfig(), session=None, sleep=time.sleep, random_fn=random.random):
    session=session or requests.Session()
    params={"queryType":"1","goDay":"","queryDate":day.strftime("%Y/%m/%d"),"commodityId":""}
    last=None; history=[]
    for attempt in range(1,config.max_attempts+1):
        started=utc_now(); tick=time.monotonic()
        try:
            response=session.get(SOURCE_URL,params=params,timeout=config.timeout_seconds,headers={"User-Agent":"taifex-night-flow/0.1.0"})
            received=utc_now()
            record={"attempt_number":attempt,"request_started_at_utc":iso_utc(started),"response_received_at_utc":iso_utc(received),"observed_at_taipei":iso_taipei(received),"http_status":response.status_code,"fetch_status":"HTTP_RESPONSE","reason":None,"duration_ms":round((time.monotonic()-tick)*1000),"response_body":response.content}
            if response.status_code >= 500 or response.status_code == 429:
                last=FetchFailure("HTTP_ERROR",f"temporary HTTP {response.status_code}",attempt,response.status_code)
                record.update(fetch_status="HTTP_ERROR",reason=str(last)); history.append(record)
            elif response.status_code != 200:
                failure=FetchFailure("HTTP_ERROR",f"HTTP {response.status_code}",attempt,response.status_code)
                record.update(fetch_status="HTTP_ERROR",reason=str(failure)); history.append(record)
                raise FetchFailure(failure.status,str(failure),attempt,response.status_code,history)
            else:
                history.append(record)
                return response.content, response.status_code, attempt, history
        except requests.Timeout as exc:
            last=FetchFailure("HTTP_TIMEOUT",str(exc) or "request timed out",attempt)
            received=utc_now(); history.append({"attempt_number":attempt,"request_started_at_utc":iso_utc(started),"response_received_at_utc":iso_utc(received),"observed_at_taipei":iso_taipei(received),"http_status":None,"fetch_status":"HTTP_TIMEOUT","reason":str(last),"duration_ms":round((time.monotonic()-tick)*1000)})
        except requests.RequestException as exc:
            last=FetchFailure("HTTP_ERROR",str(exc),attempt)
            received=utc_now(); history.append({"attempt_number":attempt,"request_started_at_utc":iso_utc(started),"response_received_at_utc":iso_utc(received),"observed_at_taipei":iso_taipei(received),"http_status":None,"fetch_status":"HTTP_ERROR","reason":str(last),"duration_ms":round((time.monotonic()-tick)*1000)})
        if attempt < config.max_attempts:
            sleep(config.backoff_seconds * (2 ** (attempt-1)) + random_fn()*config.jitter_seconds)
    raise FetchFailure(last.status if last else "HTTP_ERROR",str(last),config.max_attempts,last.http_status if last else None,history)
