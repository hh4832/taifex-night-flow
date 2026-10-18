import requests
import pytest
from datetime import date
from taifex_night_flow.client import fetch_report, FetchFailure
from taifex_night_flow.config import FetchConfig

class Session:
    def __init__(self): self.calls=0
    def get(self,*args,**kwargs):
        self.calls+=1
        if self.calls<3: raise requests.Timeout("timeout")
        class R:
            status_code=200
            content=b"ok"
        return R()

def test_timeout_retries_three_times_and_returns_actual_request_times():
    session=Session(); waits=[]
    body,status,attempts,events=fetch_report(date(2026,10,16),FetchConfig(max_attempts=3),session=session,sleep=waits.append,random_fn=lambda:0)
    assert (body,status,attempts)==(b"ok",200,3)
    assert len(events)==3 and [e["fetch_status"] for e in events]==["HTTP_TIMEOUT","HTTP_TIMEOUT","HTTP_RESPONSE"]
    assert len(waits)==2
    assert all(e["request_started_at_utc"].endswith("Z") for e in events)

def test_permanent_http_error_does_not_retry():
    class Bad:
        def get(self,*a,**k):
            class R: status_code=403; content=b"denied"
            return R()
    with pytest.raises(FetchFailure) as exc:
        fetch_report(date(2026,10,16),FetchConfig(max_attempts=3),session=Bad(),sleep=lambda _:None)
    assert exc.value.attempts==1 and len(exc.value.attempt_events)==1
    assert exc.value.status=="HTTP_ERROR"
