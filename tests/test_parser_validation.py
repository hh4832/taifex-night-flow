import json
from datetime import date
from pathlib import Path
import pytest
from taifex_night_flow.parser import parse_report, ParserError
from taifex_night_flow.validation import validate_snapshot, ValidationError

ROOT=Path(__file__).parent/"fixtures"

def test_ten_historical_fixtures_match_expected_values():
    full=json.loads((ROOT/"expected"/"historical_full.json").read_text())
    nets=json.loads((ROOT/"expected"/"historical_nets.json").read_text())
    assert len(full)==10
    count=0
    for day,expected in full.items():
        html=(ROOT/"source_html"/f"taifex_{day}.html").read_text(errors="replace")
        parsed=parse_report(html,date.fromisoformat(day))
        validate_snapshot(parsed,date.fromisoformat(day))
        assert parsed==expected
        for symbol,value in nets[day].items():
            assert parsed["instruments"][symbol]["foreign_net"]==value
            count+=1
    assert count==30

def test_prompt_historical_net_references():
    nets=json.loads((ROOT/"expected"/"historical_nets.json").read_text())
    assert nets["2026-10-08"]=={"TX":-2794,"MTX":-3849,"TMF":-3933}
    assert nets["2026-10-15"]=={"TX":-2103,"MTX":-2276,"TMF":-6999}
    assert nets["2026-10-16"]=={"TX":772,"MTX":819,"TMF":5450}

def test_actual_october_16_full_contract_volumes():
    data=json.loads((ROOT/"expected"/"historical_full.json").read_text())["2026-10-16"]
    assert data["instruments"]["TX"]["foreign_long"]==24854
    assert data["instruments"]["TX"]["foreign_short"]==24082
    assert data["instruments"]["MTX"]["foreign_long"]==65751
    assert data["instruments"]["MTX"]["foreign_short"]==64932
    assert data["instruments"]["TMF"]["foreign_long"]==114274
    assert data["instruments"]["TMF"]["foreign_short"]==108824

def _small_html(extra=""):
    return f'''<html><div>單位：口數；千元 日期2026/10/16</div><table>
    <tr><td>1</td><td rowspan="3">臺股期貨</td><td>自營商</td><td>10</td><td>100</td><td>5</td><td>50</td><td>5</td><td>50</td></tr>
    <tr><td>投信</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>
    <tr><td>外資</td><td>12</td><td>120</td><td>10</td><td>100</td><td>2</td><td>20</td></tr>
    <tr><td>2</td><td rowspan="3">小型臺指期貨</td><td>自營商</td><td>10</td><td>100</td><td>5</td><td>50</td><td>5</td><td>50</td></tr>
    <tr><td>投信</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>
    <tr><td>外資</td><td>12</td><td>120</td><td>10</td><td>100</td><td>2</td><td>20</td></tr>
    <tr><td>3</td><td rowspan="3">微型臺指期貨</td><td>自營商</td><td>10</td><td>100</td><td>5</td><td>50</td><td>5</td><td>50</td></tr>
    <tr><td>投信</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>
    <tr><td>外資</td><td>12</td><td>120</td><td>10</td><td>100</td><td>2</td><td>20</td></tr>{extra}</table></html>'''

def test_duplicate_conflicting_product_fails_closed():
    duplicate='''<tr><td>4</td><td rowspan="3">臺股期貨</td><td>自營商</td><td>10</td><td>100</td><td>5</td><td>50</td><td>5</td><td>50</td></tr><tr><td>投信</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr><tr><td>外資</td><td>13</td><td>120</td><td>10</td><td>100</td><td>3</td><td>20</td></tr>'''
    with pytest.raises(ParserError,match="conflicting candidate rows"):
        parse_report(_small_html(duplicate),date(2026,10,16))

def test_date_mismatch_is_rejected():
    with pytest.raises(ParserError,match="DATE_MISMATCH"):
        parse_report(_small_html(),date(2026,10,15))

def test_long_short_net_validation():
    data=parse_report(_small_html(),date(2026,10,16))
    validate_snapshot(data,date(2026,10,16))
    data["instruments"]["TX"]["foreign_net"]=3
    with pytest.raises(ValidationError,match="long - short != net"):
        validate_snapshot(data,date(2026,10,16))

def test_no_data_page_is_not_a_success():
    html=(ROOT/"source_html"/"taifex_2026-10-09.html").read_text(errors="replace")
    with pytest.raises(ParserError,match="NOT_YET_AVAILABLE"):
        parse_report(html,date(2026,10,9))
