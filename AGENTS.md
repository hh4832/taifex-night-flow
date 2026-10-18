# Repository Guidance

- This repository collects and preserves TAIFEX night-session foreign institutional data only.
- Use Python 3.11. Keep collection, parsing, validation, event storage, Drive transport, and reader responsibilities separate.
- Never infer a report date from a request parameter. The date must be read from the report body and exactly match the requested date.
- Preserve every HTTP attempt as a distinct observation event. Never rewrite observations or content-addressed source HTML.
- Store contract values in thousand NTD and volumes in contracts.
- Automatic date selection must fail closed without a verified TAIFEX open-date entry in calendar/verified_open_dates.txt.
- Never add signals, score thresholds, forecasts, or backtests to this repository.
- Run .venv/bin/pytest (or pytest in Python 3.11) before committing.
- Keep credentials, local databases, runtime outputs, and .venv out of Git.
