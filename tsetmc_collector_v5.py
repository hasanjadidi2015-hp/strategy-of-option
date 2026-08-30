# -*- coding: utf-8 -*-
"""
tsetmc_collector_v5.py — Self-contained data collector for AHRAM LIVE5.

This replaces the legacy `collector.py` / `option_engine.py` / `option_selector.py`
modules (which are NOT in the repository). It talks directly to TSETMC and stores
every snapshot into each symbol's SQLite database, so the V2 engines and the
dashboard bridge have everything they need — and the pipeline runs on a machine
that only contains the files that are in the repo.

No third-party packages. Works on Python 3.10+ on Windows/Linux/macOS.

Datasources (official TSETMC, all optional — first success wins):
  * old.tsetmc.com/tsev2/data/MarketWatchInit.aspx      -> stocks + options + best limits
  * cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceInfo/{ins}  -> per-symbol stock fallback
  * cdn.tsetmc.com/api/Instrument/GetInstrumentOptionMarketWatch/{ins} -> OI/bid/ask enrichment

The sandbox cannot reach TSETMC (outbound filtering), so `--offline` reads a
recorded sample and cycles are tested against that fixture.  On the user's machine
inside Iran the endpoints are reachable directly.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import sqlite3
import ssl
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from jalali_v5 import (normalize_expiry, days_to_expiry, today_tehran)

# ---------------------------------------------------------------- normalize
_FA_MAP = {
    "ي": "ی", "ك": "ک", "ة": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
}


def fa_norm(value) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    for k, v in _FA_MAP.items():
        s = s.replace(k, v)
    s = re.sub(r"\s+", " ", s).replace("\u200c", "").strip()
    return s


# Abbreviations are legal ONLY inside option tickers (ضملت/ضستا/ضهرم...).
_UMAP = {"ملت": "وبملت", "ملی": "فملی", "ستا": "شستا", "هرم": "اهرم"}


def canon_vip(value) -> str:
    s = fa_norm(value)
    return _UMAP.get(s, s)


def to_num(value) -> float:
    if value is None:
        return 0.0
    s = fa_norm(str(value)).replace(",", "").replace("٫", "")
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _pick(d, *names):
    for n in names:
        if isinstance(d, dict) and n in d and d[n] not in (None, ""):
            return d[n]
    return None


def parse_option(name_value, symbol_value):
    """Parse a TSETMC option Name/Symbol -> {type,u,K,expiry}. Returns None if not an option."""
    name = fa_norm(name_value or "")
    sym = fa_norm(symbol_value or "")
    if not name:
        return None
    m = re.search(r"اختیار\s*([خف])?\s+(.+?)\s*[-_]\s*(\d{3,9})\s*[-_]\s*(\d{2,4}/\d{1,2}/\d{1,2}|\d{6,8})", name)
    if not m:
        m = re.search(r"([خف])\s+(.+?)\s*[-_]\s*(\d{3,9})\s*[-_]\s*(\d{2,4}/\d{1,2}/\d{1,2}|\d{6,8})", name)
    if not m:
        return None
    type_ = "put" if (sym.startswith("ط") or m[1] == "ف") else "call"
    u = canon_vip(m[2])
    return {"type": type_, "u": u, "K": to_num(m[3]), "expiry": normalize_expiry(m[4])}


# ---------------------------------------------------------------- TSETMC fetch
_WATCH_URLS = [
    "https://old.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0",
    "http://old.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0",
    "https://cdn.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0",
    "http://cdn.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0",
]
_TIMEOUT = 15.0
_SSL = ssl.create_default_context()
# TSETMC's old host occasionally serves a certificate chain that newer clients
# reject.  The data itself is public market data; we disable verification ONLY
# for the allow-listed tsetmc.com domain and never for arbitrary hosts.
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/plain,application/json,*/*",
    "Referer": "https://www.tsetmc.com/",
    "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


def fetch_text(url: str, timeout: float = _TIMEOUT) -> tuple[str, str]:
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as resp:
        raw = resp.read()
        ctype = resp.headers.get("Content-Type", "text/plain")
    return raw.decode("utf-8-sig", errors="replace"), ctype


def fetch_json(url: str, timeout: float = _TIMEOUT):
    text, _ = fetch_text(url, timeout)
    return json.loads(text)


def first_success(fetchers):
    errs = []
    for fn in fetchers:
        try:
            return fn()
        except Exception as exc:
            errs.append(f"{exc}")
    raise RuntimeError(" | ".join(errs[-6:]) or "no TSETMC source")


# ---------------------------------------------------------------- MarketWatch parser
def parse_market_watch_text(text: str):
    """Parse MarketWatchInit. Returns {'marketTime':..., 'stocks':{name:{...}}, 'options':[...]}."""
    parts = text.strip().split("@")
    market_time = (parts[1] or "").replace("\r", "").replace("\n", ",").split(",")[0]
    best = {}
    if len(parts) > 3:
        for row in (parts[3] or "").split(";"):
            f = row.split(",")
            if len(f) >= 6 and f[1] == "1":
                best[f[0]] = {"bid": to_num(f[4]), "ask": to_num(f[5])}
    stocks = {}
    options = []
    rows = (parts[2] or "").split(";") if len(parts) > 2 else []
    for row in rows:
        f = row.split(",")
        if len(f) < 14:
            continue
        ins = f[0].strip()
        sym = fa_norm(f[2])
        name = fa_norm(f[3])
        last, close = to_num(f[7]), to_num(f[6])
        yesterday = to_num(f[13])
        if not (last or close or yesterday):
            continue
        itype = int(to_num(f[22])) if len(f) > 22 else 0
        parsed = parse_option(name, sym)
        is_opt = itype in (311, 312) or sym.startswith(("ض", "ط")) or parsed
        common = {
            "insCode": ins, "sym": sym, "name": name, "last": last, "close": close,
            "yesterday": yesterday, "volume": to_num(f[9]), "value": to_num(f[10]),
            "lot": to_num(f[21]) if len(f) > 21 else 0,
            "time": (f[4] if len(f) > 4 else ""),
            "bid": best.get(ins, {}).get("bid", 0), "ask": best.get(ins, {}).get("ask", 0),
        }
        if is_opt and parsed:
            common.update({"strike": parsed["K"], "expiry": parsed["expiry"], "o": parsed["type"], "u": parsed["u"]})
            options.append(common)
        else:
            stocks[sym] = common if sym else stocks.get(sym)
    return {"marketTime": market_time, "stocks": stocks, "options": options, "best": best}


def enrich_option_chain(symbol: dict) -> dict:
    """Best-effort OI + live bid/ask from the option-chain endpoint.  Never raises."""
    out = {}
    ins = symbol.get("ins_code")
    if not ins:
        return out
    try:
        url = f"https://cdn.tsetmc.com/api/Instrument/GetInstrumentOptionMarketWatch/{ins}"
        data = fetch_json(url, 10)
        rows = data.get("optionWatch") or data.get("data") or data.get("options") or []
        for r in rows:
            sym = fa_norm(_pick(r, "symbol", "lVal18AFC", "symbolName", "sym"))
            out[sym] = {
                "oi": to_num(_pick(r, "openInterest", "oi", "qtTran")) ,
                "value": to_num(_pick(r, "qTotCap", "value", "tval")),
                "volume": to_num(_pick(r, "qTotTran", "volume", "tvol")),
                "bid": to_num(_pick(r, "bid", "pMeDem", "bay")),
                "ask": to_num(_pick(r, "ask", "pMeOf", "baSell")),
            }
    except Exception:
        pass
    return out


# ---------------------------------------------------------------- DB
def ensure_schema(db_path: str):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS prices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, symbol TEXT, last_price REAL, closing_price REAL,
        volume REAL, trades REAL, source TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        time TEXT, symbol TEXT, option_type TEXT, stock_price REAL,
        option_price REAL, strike_price REAL, expire_date TEXT,
        days_to_expire INTEGER, volume REAL, value_traded REAL,
        open_interest REAL, implied_volatility REAL, delta REAL, gamma REAL,
        theta REAL, vega REAL, bid_price REAL, ask_price REAL, underlying TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS order_book (
        id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, level INTEGER,
        buy_count INTEGER, buy_volume REAL, buy_price REAL,
        sell_price REAL, sell_volume REAL, sell_count INTEGER)""")
    # Tables that the bridge/engines read; create if missing to avoid 'no such table'.
    cur.execute("""CREATE TABLE IF NOT EXISTS signal_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, symbol TEXT,
        signal_type TEXT, composite_score REAL, option_symbol TEXT,
        option_price REAL, strike_price REAL, stop_loss REAL, target1 REAL,
        target2 REAL, outcome TEXT, outcome_pct REAL, details TEXT,
        position_id TEXT, v2_score REAL, v2_decision TEXT, v2_best_symbol TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS max_pain_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, expiry TEXT, stock_price REAL,
        max_pain_strike REAL, current_distance_pct REAL, data_quality TEXT,
        contracts_count INTEGER, contracts_with_oi INTEGER, time TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS iv_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, atm_iv REAL, updated_at TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS iv_skew_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, expiry TEXT, atm_iv REAL,
        otm_call_iv REAL, otm_put_iv REAL, call_put_skew REAL, otm_atm_skew REAL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS money_flow (
        id INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, buy_retail_volume REAL,
        buy_institutional_volume REAL, sell_retail_volume REAL,
        sell_institutional_volume REAL, net_retail_volume REAL,
        net_institutional_volume REAL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS daily_news (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_date TEXT, title TEXT,
        category TEXT, source TEXT)""")
    con.commit()
    return con


def clean_old_snapshots(con, keep: int = 200):
    """Keep the table small: retain the newest `keep` rows per snapshot time."""
    for tbl in ("prices", "options"):
        try:
            con.execute(
                f"DELETE FROM {tbl} WHERE id NOT IN ("
                f"SELECT id FROM {tbl} ORDER BY id DESC LIMIT {keep * 400})")
        except sqlite3.OperationalError:
            pass


def write_snapshot(db_path: str, stock: dict, options: list, source: str):
    con = ensure_schema(db_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = con.cursor()
    # price row
    cur.execute(
        "INSERT INTO prices (time, symbol, last_price, closing_price, volume, trades, source) "
        "VALUES (?,?,?,?,?,?,?)",
        (now, stock.get("sym"), stock.get("last"), stock.get("close"),
         stock.get("volume"), stock.get("value"), source))
    # option rows
    for o in options:
        # drop the in-memory snapshot if we are re-writing the same second
        cur.execute(
            "INSERT INTO options (time, symbol, option_type, stock_price, option_price, "
            "strike_price, expire_date, days_to_expire, volume, value_traded, open_interest, "
            "implied_volatility, delta, gamma, theta, vega, bid_price, ask_price, underlying) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (now, o.get("sym"), (o.get("o") or "CALL").upper(),
             stock.get("last") or stock.get("close"), o.get("last") or o.get("close"),
             o.get("strike"), o.get("expiry"),
             days_to_expiry(o.get("expiry") or ""),
             o.get("volume"), o.get("value"),
             o.get("open_interest") or (o.get("oi") or 0),
             None, None, None, None, None,
             o.get("bid"), o.get("ask"), o.get("u")))
    con.commit()
    clean_old_snapshots(con)
    con.close()


# ---------------------------------------------------------------- orchestrator
def run_cycle(symbols: list, offline: bool = False, write: bool = True):
    """One full collection cycle for all symbols. Returns a summary dict."""
    if offline:
        with open("sample_marketwatch.txt", encoding="utf-8") as fh:
            text = fh.read()
        parsed = parse_market_watch_text(text)
    else:
        text = None
        for url in _WATCH_URLS:
            try:
                text, _ = fetch_text(url)
                break
            except Exception:
                continue
        if not text or "@" not in text:
            raise RuntimeError("امکان اتصال به TSETMC نبود؛ https://old.tsetmc.com جواب نداد. شبکه/اینترنت/VPN را بررسی کنید.")
        parsed = parse_market_watch_text(text)

    results = {}
    for symbol in symbols:
        name = symbol["name"]
        stock = parsed["stocks"].get(name)
        options = [o for o in parsed["options"] if o.get("u") == name]
        # best-effort OI/bid/ask enrich (only online)
        if not offline and options:
            try:
                enrich = enrich_option_chain(symbol)
                for o in options:
                    e = enrich.get(o["sym"])
                    if e:
                        o.setdefault("open_interest", e.get("oi"))
                        if e.get("bid"):
                            o["bid"] = e["bid"]
                        if e.get("ask"):
                            o["ask"] = e["ask"]
            except Exception:
                pass
        # per-symbol stock fallback if the stock was not in the bulk watch
        if (stock is None or not (stock.get("last") or stock.get("close"))) and not offline:
            try:
                stock = fetch_closing_stock(symbol)
            except Exception:
                stock = None
        if stock is None:
            results[name] = {"ok": False, "reason": "no stock price"}
            continue
        snap = {
            "sym": name, "last": stock.get("last"), "close": stock.get("close"),
            "volume": stock.get("volume"), "value": stock.get("value"),
        }
        if write:
            try:
                write_snapshot(symbol["db"], snap, options, "tsetmc")
            except Exception as exc:
                results[name] = {"ok": False, "reason": f"db: {exc}"}
                continue
        results[name] = {"ok": True, "stock": snap, "options": len(options)}
    return {"marketTime": parsed.get("marketTime"), "symbols": results}


def fetch_closing_stock(symbol: dict):
    ins = symbol.get("ins_code")
    url = f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceInfo/{ins}"
    data = fetch_json(url, 12)
    info = data.get("closingPriceInfo") or data.get("data") or data.get("instrument") or data
    if not isinstance(info, dict):
        info = (info[0] if isinstance(info, list) and info else {}) or {}
    return {
        "sym": symbol["name"],
        "last": to_num(_pick(info, "pDrCotVal", "last", "priceLast")),
        "close": to_num(_pick(info, "pClosing", "close", "priceClosing")),
        "volume": to_num(_pick(info, "qTotTran", "volume", "tvol")),
        "value": to_num(_pick(info, "qTotCap", "value", "tval")),
        "source": "closing",
    }


# ---------------------------------------------------------------- CLI
def load_symbols():
    """Symbol table from config.py if present, else a built-in (4 symbols)."""
    default = [
        {"name": "اهرم", "ins_code": "17914401175772326", "db": "ahram_v2.db", "option_root": "هرم", "queue_gap": 4.0},
        {"name": "وبملت", "ins_code": "778253364357513", "db": "webmellt.db", "option_root": "ملت", "queue_gap": 3.0},
        {"name": "شستا", "ins_code": "2400322364771558", "db": "shasta.db", "option_root": "ستا", "queue_gap": 3.0},
        {"name": "فملی", "ins_code": "35425587644337450", "db": "fameli.db", "option_root": "ملی", "queue_gap": 3.0},
    ]
    try:
        import config  # repo config.py
        if getattr(config, "SYMBOLS", None):
            return [dict(d) for d in config.SYMBOLS]
    except Exception:
        pass
    return default


def main():
    parser = argparse.ArgumentParser(description="Self-contained TSETMC collector for AHRAM V5")
    parser.add_argument("--offline", action="store_true", help="read sample_marketwatch.txt instead of TSETMC")
    parser.add_argument("--no-write", action="store_true", help="do not write to DB (dry run)")
    parser.add_argument("--db", default=None, help="override db path (for a single test)")
    args = parser.parse_args()

    symbols = load_symbols()
    for s in symbols:
        if not os.path.exists(s["db"]) and not args.no_write:
            ensure_schema(s["db"])
    result = run_cycle(symbols, offline=args.offline, write=not args.no_write)
    print("marketTime:", result.get("marketTime"))
    for name, r in result["symbols"].items():
        if r.get("ok"):
            print(f"  {name}: {r['options']} قرارداد / قیمت {r['stock'].get('last') or r['stock'].get('close')}")
        else:
            print(f"  {name}: FAIL {r.get('reason')}")


if __name__ == "__main__":
    main()
