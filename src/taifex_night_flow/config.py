from dataclasses import dataclass

SOURCE_URL = "https://www.taifex.com.tw/cht/3/futContractsDateAhExcel"
DRIVE_FOLDER_ID = "1bHNCF59WGheGa5Tmo_GDK53T4fxU00oD"
SYMBOLS = {
    "臺股期貨": "TX",
    "小型臺指期貨": "MTX",
    "微型臺指期貨": "TMF",
}

@dataclass(frozen=True)
class FetchConfig:
    timeout_seconds: float = 20.0
    max_attempts: int = 3
    backoff_seconds: float = 1.0
    jitter_seconds: float = 0.25
