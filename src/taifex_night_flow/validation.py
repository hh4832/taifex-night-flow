from datetime import date
from .parser import ParserError

class ValidationError(ValueError):
    pass

def validate_snapshot(data: dict, expected_date: date) -> None:
    if data.get("trade_date") != expected_date.isoformat():
        raise ValidationError("report date does not match expected_trade_date")
    instruments = data.get("instruments")
    if not isinstance(instruments, dict) or set(instruments) != {"TX", "MTX", "TMF"}:
        raise ValidationError("TX, MTX and TMF are all required")
    fields = ("foreign_long", "foreign_short", "foreign_net",
              "foreign_long_value_thousand_ntd", "foreign_short_value_thousand_ntd",
              "foreign_net_value_thousand_ntd")
    for symbol, row in instruments.items():
        if any(not isinstance(row.get(k), int) for k in fields):
            raise ValidationError(f"{symbol}: all six values must be integers")
        if row["foreign_long"] - row["foreign_short"] != row["foreign_net"]:
            raise ValidationError(f"{symbol}: long - short != net")
        if row["foreign_long_value_thousand_ntd"] - row["foreign_short_value_thousand_ntd"] != row["foreign_net_value_thousand_ntd"]:
            raise ValidationError(f"{symbol}: contract value long - short != net")
