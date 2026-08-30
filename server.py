#!/usr/bin/env python3
"""Local bridge for the Iran options dashboard.

No third-party packages are required. It serves the dashboard and exposes:
  GET /api/live    -> normalized TSETMC stock + option snapshot
  GET /api/health  -> bridge status
  GET /api/proxy?url=<tsetmc-url> -> restricted TSETMC-only proxy
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DASHBOARD = "options_dashboard_AHRAM_LIVE5.html"
VIP_LIST = ("اهرم", "شستا", "وبملت", "فملی")
VIP_INS_CODES = {
    # 62235397452612911 is Darayekom; the previous dashboard used it for Ahrom.
    "اهرم": "17914401175772326",
    "شستا": "2400322364771558",
    "وبملت": "778253364357513",
    "فملی": "35425587644337450",
}
UMAP = {
    "هرم": "اهرم",
    "ستا": "شستا",
    "ملت": "وبملت",
    "ملی": "فملی",
    "ملي": "فملی",
}

OLD_MARKETWATCH_URLS = (
    "https://old.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0",
    "http://old.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0",
    "https://cdn.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0",
    "http://cdn.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0",
)
NEW_MARKETWATCH_URL = (
    "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch"
    "?market=0&industrialGroup="
    "&paperTypes%5B0%5D=1&paperTypes%5B1%5D=2&paperTypes%5B2%5D=3"
    "&paperTypes%5B3%5D=4&paperTypes%5B4%5D=5&paperTypes%5B5%5D=6"
    "&paperTypes%5B6%5D=7&paperTypes%5B7%5D=8&paperTypes%5B8%5D=9"
    "&showTraded=false&withBestLimits=true&hEven=0&RefID=0"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
)
SSL_CONTEXT = ssl.create_default_context()
INSECURE_SSL_CONTEXT = ssl._create_unverified_context()  # known TSETMC hosts only
CACHE_LOCK = threading.Lock()
LIVE_CACHE: dict[str, Any] = {"at": 0.0, "data": None}
CACHE_SECONDS = 4.0


def fa_norm(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.strip()
        .replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .replace("\u200c", "")
        .replace("\u200f", "")
    )


def canon_vip(value: Any) -> str:
    text = fa_norm(value)
    return UMAP.get(text, text)


def to_num(value: Any) -> float:
    if value is None or value == "":
        return 0
    if isinstance(value, (int, float)):
        return value
    text = fa_norm(value).replace(",", "").replace("٬", "").replace("،", "")
    text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    try:
        x = float(text)
        return int(x) if x.is_integer() else x
    except (TypeError, ValueError):
        return 0


def heven_text(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))[-6:].zfill(6)
    if digits == "000000":
        return ""
    return f"{digits[:2]}:{digits[2:4]}:{digits[4:]}"


def normalize_expiry(value: Any) -> str:
    text = fa_norm(value).translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
    if not text:
        return ""
    if re.fullmatch(r"\d{6}", text):
        yy, mm, dd = text[:2], text[2:4], text[4:]
        year = 1400 + int(yy) if int(yy) < 80 else 1300 + int(yy)
        return f"{year:04d}/{int(mm):02d}/{int(dd):02d}"
    if re.fullmatch(r"\d{8}", text):
        year = int(text[:4])
        sep = "/" if 1300 <= year <= 1599 else "-"
        return f"{year:04d}{sep}{int(text[4:6]):02d}{sep}{int(text[6:]):02d}"
    m = re.fullmatch(r"(\d{2,4})/(\d{1,2})/(\d{1,2})", text)
    if m:
        year = int(m.group(1))
        if year < 100:
            year += 1400 if year < 80 else 1300
        return f"{year:04d}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    return text


_OPTION_RE = re.compile(
    r"اختیار\s*([خف])?\s+(.+?)\s*[-_]\s*(\d{3,9})\s*[-_]\s*"
    r"(\d{2,4}/\d{1,2}/\d{1,2}|\d{6,8})"
)


def parse_option(name: Any, symbol: Any) -> dict[str, Any] | None:
    name_n = fa_norm(name)
    sym = fa_norm(symbol)
    match = _OPTION_RE.search(name_n)
    if not match:
        return None
    option_type = "put" if sym.startswith("ط") or match.group(1) == "ف" else "call"
    underlying = canon_vip(match.group(2))
    if underlying not in VIP_LIST:
        # TSETMC option symbols abbreviate the underlying (ضهرم / ضستا / ضملت / ضملی).
        base = re.sub(r"[0-9٠-٩۰-۹]+$", "", sym[1:] if sym[:1] in "ضط" else sym)
        underlying = canon_vip(base)
    if underlying not in VIP_LIST:
        return None
    return {
        "type": option_type,
        "u": underlying,
        "K": int(match.group(3)),
        "expiry": normalize_expiry(match.group(4)),
    }


def _decode_response(resp: Any) -> bytes:
    data = resp.read()
    encoding = (resp.headers.get("Content-Encoding") or "").lower()
    if encoding == "gzip" or data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return data


def fetch_bytes(url: str, timeout: float = 4.0) -> tuple[bytes, str]:
    parsed = urllib.parse.urlparse(url)
    if not (parsed.hostname or "").lower().endswith("tsetmc.com"):
        raise ValueError("Only TSETMC upstreams are allowed")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Encoding": "gzip",
            "Referer": "https://www.tsetmc.com/",
            "Cache-Control": "no-cache",
        },
    )
    # Some official TSETMC hosts have an incomplete/legacy TLS chain. Because the
    # hostname is strictly allow-listed above, use one relaxed TLS attempt instead
    # of retrying every timeout twice.
    ctx = INSECURE_SSL_CONTEXT if parsed.scheme == "https" else None
    try:
        kwargs = {"timeout": timeout}
        if ctx is not None:
            kwargs["context"] = ctx
        with urllib.request.urlopen(req, **kwargs) as resp:
            return _decode_response(resp), resp.headers.get_content_type()
    except Exception as exc:
        raise RuntimeError(f"{parsed.netloc}: {exc}") from exc


def parse_marketwatch_text(text: str, source: str = "TSETMC MarketWatchInit") -> dict[str, Any]:
    parts = text.strip().split("@")
    if len(parts) < 4:
        raise ValueError(f"invalid MarketWatchInit: {len(parts)} sections")

    market_time = (parts[1] or "").replace("\r", "").replace("\n", ",").split(",")[0]
    best: dict[str, dict[str, float]] = {}
    for row in (parts[3] or "").split(";"):
        fields = row.split(",")
        if len(fields) < 6 or fields[1] != "1":
            continue
        best[fields[0]] = {"bid": to_num(fields[4]), "ask": to_num(fields[5])}

    stocks: dict[str, dict[str, Any]] = {}
    options: list[dict[str, Any]] = []
    for row in (parts[2] or "").split(";"):
        fields = row.split(",")
        if len(fields) < 14:
            continue
        ins_code = fields[0].strip()
        symbol = fa_norm(fields[2])
        name = fa_norm(fields[3])
        last = to_num(fields[7])
        close = to_num(fields[6])
        yesterday = to_num(fields[13])
        if not (last or close or yesterday):
            continue
        quote = best.get(ins_code, {})
        instrument_type = int(to_num(fields[22])) if len(fields) > 22 else 0
        parsed_option = parse_option(name, symbol)
        is_option = instrument_type in (311, 312) or symbol.startswith(("ض", "ط")) or parsed_option

        common = {
            "insCode": ins_code,
            "sym": symbol,
            "name": name,
            "last": last,
            "close": close,
            "yesterday": yesterday,
            "volume": to_num(fields[9]),
            "value": to_num(fields[10]),
            "lot": to_num(fields[21]) if len(fields) > 21 else 0,
            "time": heven_text(fields[4]),
            "date": market_time.split(" ")[0] if market_time else "",
            "bid": quote.get("bid", 0),
            "ask": quote.get("ask", 0),
        }
        if is_option:
            if not parsed_option:
                continue
            options.append({**common, **parsed_option, "P": last or close})
        else:
            # Underlying abbreviations (ملت/ملی/ستا/هرم) are valid only inside
            # option tickers. For cash stocks require an exact symbol match;
            # otherwise the independent symbol «ملت» can overwrite «وبملت».
            vip = fa_norm(symbol)
            if vip not in VIP_LIST:
                continue
            stocks[vip] = common

    if not stocks and not options:
        raise ValueError("MarketWatchInit parsed but contained no VIP instruments")
    return {
        "ok": True,
        "source": source,
        "marketTime": market_time,
        "stocks": stocks,
        "options": options,
        "optionsComplete": True,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }


def _pick(mapping: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in mapping and mapping[name] not in (None, ""):
            return mapping[name]
    return None


def parse_new_marketwatch(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("marketwatch") or payload.get("marketWatch") or payload.get("data") or []
    if isinstance(rows, dict):
        rows = rows.get("marketwatch") or rows.get("data") or []
    if not isinstance(rows, list):
        raise ValueError("new API has no marketwatch array")

    stocks: dict[str, dict[str, Any]] = {}
    options: list[dict[str, Any]] = []
    market_time = ""
    market_date = ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        inst = row.get("instrument") if isinstance(row.get("instrument"), dict) else {}
        symbol = fa_norm(_pick(row, "lVal18AFC", "l18", "symbol") or _pick(inst, "lVal18AFC", "l18", "symbol"))
        name = fa_norm(_pick(row, "lVal30", "l30", "name") or _pick(inst, "lVal30", "l30", "name"))
        ins_code = str(_pick(row, "insCode", "inscode") or _pick(inst, "insCode", "inscode") or "")
        if not symbol:
            continue
        last = to_num(_pick(row, "pDrCotVal", "pl", "last"))
        close = to_num(_pick(row, "pClosing", "pc", "close"))
        yesterday = to_num(_pick(row, "priceYesterday", "py", "yesterday"))
        heven = _pick(row, "hEven", "heven", "lastHEven")
        d_even = _pick(row, "dEven", "deven", "finalLastDate")
        if heven:
            market_time = max(market_time, heven_text(heven))
        if d_even:
            market_date = max(market_date, str(d_even))
        best_rows = row.get("blDs") or row.get("bestLimits") or row.get("bestLimit") or []
        bid = ask = 0
        if isinstance(best_rows, list):
            level = next((x for x in best_rows if isinstance(x, dict) and int(to_num(x.get("number"))) == 1), None)
            if level:
                bid = to_num(_pick(level, "pMeDem", "pd", "bid"))
                ask = to_num(_pick(level, "pMeOf", "po", "ask"))
        common = {
            "insCode": ins_code,
            "sym": symbol,
            "name": name,
            "last": last,
            "close": close,
            "yesterday": yesterday,
            "volume": to_num(_pick(row, "qTotTran5J", "tvol", "volume")),
            "value": to_num(_pick(row, "qTotCap", "tval", "value")),
            "lot": to_num(_pick(row, "baseVol", "bvol", "contractSize")),
            "time": heven_text(heven),
            "date": str(d_even or ""),
            "bid": bid,
            "ask": ask,
        }
        parsed_option = parse_option(name, symbol)
        if parsed_option or symbol.startswith(("ض", "ط")):
            if parsed_option and (last or close):
                options.append({**common, **parsed_option, "P": last or close})
        else:
            vip = fa_norm(symbol)
            if vip in VIP_LIST and (last or close or yesterday):
                stocks[vip] = common
    if not stocks and not options:
        raise ValueError("new marketwatch parsed but contained no VIP instruments")
    return {
        "ok": True,
        "source": "TSETMC GetMarketWatch",
        "marketTime": ((market_date + " ") if market_date else "") + market_time,
        "stocks": stocks,
        "options": options,
        "optionsComplete": True,
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
    }


def fetch_closing_stock(name: str, ins_code: str) -> tuple[str, dict[str, Any]]:
    url = f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceInfo/{ins_code}"
    raw, _ = fetch_bytes(url, timeout=7)
    data = json.loads(raw.decode("utf-8-sig"))
    info = data.get("closingPriceInfo") or data
    return name, {
        "insCode": ins_code,
        "sym": name,
        "last": to_num(_pick(info, "pDrCotVal", "pl", "last")),
        "close": to_num(_pick(info, "pClosing", "pc", "close")),
        "yesterday": to_num(_pick(info, "priceYesterday", "py", "yesterday")),
        "volume": to_num(_pick(info, "qTotTran5J", "tvol", "volume")),
        "value": to_num(_pick(info, "qTotCap", "tval", "value")),
        "time": heven_text(_pick(info, "hEven", "lastHEven", "heven")),
        "date": str(_pick(info, "dEven", "finalLastDate", "date") or ""),
    }


def fetch_live_uncached() -> dict[str, Any]:
    errors: list[str] = []
    jobs: list[tuple[str, str]] = [("old", url) for url in OLD_MARKETWATCH_URLS]
    jobs.append(("new", NEW_MARKETWATCH_URL))

    # Race all official endpoints. First normalized snapshot with data wins.
    # shutdown(wait=False) is intentional: a slow duplicate host must not delay a
    # successful response from another official host.
    pool = ThreadPoolExecutor(max_workers=len(jobs))
    future_map = {pool.submit(fetch_bytes, url, 4.0): (kind, url) for kind, url in jobs}
    try:
        for future in as_completed(future_map):
            kind, url = future_map[future]
            try:
                raw, _ = future.result()
                if kind == "old":
                    text = raw.decode("utf-8-sig", errors="replace")
                    snap = parse_marketwatch_text(text, "دیده‌بان رسمی TSETMC")
                else:
                    snap = parse_new_marketwatch(json.loads(raw.decode("utf-8-sig")))
                if snap.get("stocks"):
                    for pending in future_map:
                        pending.cancel()
                    return snap
            except Exception as exc:
                errors.append(f"{urllib.parse.urlparse(url).netloc}: {exc}")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # Final fallback: four official per-symbol endpoints. It repairs base prices even
    # when the bulk endpoint is temporarily unavailable; option data remains absent.
    stocks: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_closing_stock, name, code) for name, code in VIP_INS_CODES.items()]
        for future in as_completed(futures):
            try:
                name, record = future.result()
                if record.get("last") or record.get("close") or record.get("yesterday"):
                    stocks[name] = record
            except Exception as exc:
                errors.append(f"closing: {exc}")
    if stocks:
        return {
            "ok": True,
            "source": "TSETMC ClosingPrice (فقط قیمت پایه)",
            "marketTime": (max((str(x.get("date", "")) for x in stocks.values()), default="") + " " +
                           max((x.get("time", "") for x in stocks.values()), default="")).strip(),
            "stocks": stocks,
            "options": [],
            "optionsComplete": False,
            "warning": "Bulk market watch failed; option chain was not refreshed.",
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "upstreamErrors": errors[-5:],
        }
    raise RuntimeError(" | ".join(errors[-8:]) or "No TSETMC endpoint returned data")


def get_live(force: bool = False) -> dict[str, Any]:
    now = time.time()
    with CACHE_LOCK:
        if not force and LIVE_CACHE["data"] is not None and now - LIVE_CACHE["at"] < CACHE_SECONDS:
            return LIVE_CACHE["data"]
    try:
        data = fetch_live_uncached()
    except Exception:
        # If TSETMC is unreachable, fall back to the last successful snapshot (if
        # any) so the dashboard always has *something* rather than a blank page.
        with CACHE_LOCK:
            if LIVE_CACHE["data"] is not None:
                fallback = dict(LIVE_CACHE["data"])
                fallback["stale"] = True
                fallback["warning"] = "TSETMC در حال حاضر در دسترس نبود؛ آخرین داده نمایش داده می‌شود."
                return fallback
        raise
    with CACHE_LOCK:
        LIVE_CACHE["at"] = time.time()
        LIVE_CACHE["data"] = data
    return data


class DashboardHandler(SimpleHTTPRequestHandler):
    server_version = "IranOptionsDashboard/2.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store" if self.path.startswith("/api/") else "no-cache")
        super().end_headers()

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self.path = "/" + DASHBOARD
            return super().do_GET()
        if parsed.path == "/api/health":
            return self.send_json(200, {"ok": True, "service": "tsetmc-local-bridge", "version": 2})
        if parsed.path == "/api/live":
            query = urllib.parse.parse_qs(parsed.query)
            force = query.get("force", ["0"])[0] in ("1", "true", "yes")
            try:
                return self.send_json(200, get_live(force=force))
            except Exception as exc:
                return self.send_json(
                    502,
                    {
                        "ok": False,
                        "error": "ارتباط با سرویس رسمی TSETMC برقرار نشد",
                        "details": str(exc),
                        "fetchedAt": datetime.now(timezone.utc).isoformat(),
                    },
                )
        if parsed.path == "/api/proxy":
            query = urllib.parse.parse_qs(parsed.query)
            target = query.get("url", [""])[0]
            host = (urllib.parse.urlparse(target).hostname or "").lower()
            if not host.endswith("tsetmc.com"):
                return self.send_json(403, {"ok": False, "error": "Only TSETMC URLs are allowed"})
            try:
                data, content_type = fetch_bytes(target, timeout=10)
                self.send_response(200)
                self.send_header("Content-Type", content_type or "text/plain")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            except Exception as exc:
                return self.send_json(502, {"ok": False, "error": str(exc)})
        return super().do_GET()


def find_port(host: str, preferred: int) -> tuple[ThreadingHTTPServer, int]:
    last_error: Exception | None = None
    for port in range(preferred, preferred + 20):
        try:
            return ThreadingHTTPServer((host, port), DashboardHandler), port
        except OSError as exc:
            last_error = exc
    raise RuntimeError(f"No free port near {preferred}: {last_error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Iran options dashboard local server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if not (ROOT / DASHBOARD).exists():
        raise SystemExit(f"Dashboard file not found: {ROOT / DASHBOARD}")
    httpd, port = find_port(args.host, args.port)
    url_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{url_host}:{port}/"
    print("=" * 68)
    print("داشبورد اختیار معامله آماده است:")
    print(url)
    print("برای توقف، Ctrl+C را بزنید.")
    print("=" * 68)
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
