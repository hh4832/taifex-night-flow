from __future__ import annotations
import re
from datetime import date
from bs4 import BeautifulSoup
from .config import SYMBOLS

class ParserError(ValueError):
    pass

def _expand_table(table):
    """Expand rowspan/colspan into a rectangular logical row grid."""
    grid, pending = [], {}
    for tr in table.find_all("tr"):
        row, col = [], 0
        while col in pending:
            value, remaining = pending[col]
            row.append(value)
            if remaining <= 1:
                del pending[col]
            else:
                pending[col] = (value, remaining - 1)
            col += 1
        cells = tr.find_all(["td", "th"], recursive=False)
        for cell in cells:
            while col in pending:
                value, remaining = pending[col]
                row.append(value)
                if remaining <= 1:
                    del pending[col]
                else:
                    pending[col] = (value, remaining - 1)
                col += 1
            value = " ".join(cell.stripped_strings)
            colspan = int(cell.get("colspan", 1) or 1)
            rowspan = int(cell.get("rowspan", 1) or 1)
            for offset in range(colspan):
                row.append(value)
                if rowspan > 1:
                    pending[col + offset] = (value, rowspan - 1)
            col += colspan
        if pending:
            max_col = max(pending)
            while len(row) <= max_col:
                col2 = len(row)
                if col2 in pending:
                    value, remaining = pending[col2]
                    row.append(value)
                    if remaining <= 1:
                        del pending[col2]
                    else:
                        pending[col2] = (value, remaining - 1)
                else:
                    row.append("")
        grid.append(row)
    return grid

def _number(text: str) -> int:
    value = text.strip().replace(",", "").replace("−", "-")
    if not re.fullmatch(r"-?\d+", value):
        raise ParserError(f"invalid integer field: {text!r}")
    return int(value)

def parse_report(html: str, expected_date: date) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    page_text = " ".join(soup.stripped_strings)
    if "查無資料" in page_text or "尚無資料" in page_text or "沒有資料" in page_text:
        raise ParserError("NOT_YET_AVAILABLE: TAIFEX reports no rows for the requested date")
    date_match = re.search(r"日期\s*(\d{4})/(\d{1,2})/(\d{1,2})", page_text)
    if not date_match:
        date_match = re.search(r"(?:報表日期|資料日期)\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})", page_text)
    if not date_match:
        raise ParserError("report date not found in page content")
    report_date = date(*(int(x) for x in date_match.groups()))
    if report_date != expected_date:
        raise ParserError(f"DATE_MISMATCH: requested {expected_date}, report says {report_date}")

    rows = []
    for table in soup.find_all("table"):
        rows.extend(_expand_table(table))
    normalized = [[re.sub(r"\s+", "", c) for c in row] for row in rows]

    parsed = {}
    for product_name, symbol in SYMBOLS.items():
        anchors = []
        for idx, row in enumerate(normalized):
            # Product row must be a numbered row containing the product name.
            joined = "".join(row)
            if product_name in joined and "自營商" in row and any(re.fullmatch(r"\d+", c) for c in row):
                anchors.append(idx)
        candidates = []
        for anchor in anchors:
            # Roles are in fixed product-local rows: dealer, trust, foreign.
            if anchor + 2 >= len(normalized):
                continue
            foreign_row = normalized[anchor + 2]
            if "外資" not in foreign_row:
                continue
            # Numeric cells on the same row: long qty/value, short qty/value, net qty/value.
            numeric = []
            for cell in foreign_row:
                if re.fullmatch(r"-?[\d,−]+", cell):
                    numeric.append(_number(cell))
            # The product sequence number is repeated by its rowspan in the
            # expanded grid; the six final values are the trading fields.
            if len(numeric) >= 7:
                numeric = numeric[-6:]
            if len(numeric) != 6:
                continue
            candidates.append({
                "foreign_long": numeric[0], "foreign_long_value_thousand_ntd": numeric[1],
                "foreign_short": numeric[2], "foreign_short_value_thousand_ntd": numeric[3],
                "foreign_net": numeric[4], "foreign_net_value_thousand_ntd": numeric[5],
            })
        distinct = {tuple(sorted(c.items())) for c in candidates}
        if not candidates:
            raise ParserError(f"missing foreign row for {symbol}")
        if len(distinct) != 1:
            raise ParserError(f"conflicting candidate rows for {symbol}")
        parsed[symbol] = candidates[0]

    if set(parsed) != {"TX", "MTX", "TMF"}:
        raise ParserError("required instrument set incomplete")
    return {"trade_date": report_date.isoformat(), "instruments": parsed}
