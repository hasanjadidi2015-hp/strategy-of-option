# -*- coding: utf-8 -*-
"""
ahram_engine_v5.py — Self-contained LIVE5 engine (NO legacy modules required).

Legacy `ahram_pro_v5.py` needs collector/strategy/option_selector/... modules that
are not in the repository.  This engine replaces that whole pipeline with the
modules that ARE present, so it runs on a bare checkout:

    collector  (tsetmc_collector_v5.py, talks to TSETMC)  ->  SQLite
    greek_engine_v2 / iv_engine_v2 / risk_engine_v2
        / contract_scoring_engine_v2 / decision_engine_v2 / sentiment_engine_v2
    strategy_bridge_v5.py   ->  ahram_strategy_data_v5.json
    connect_strategy_dashboard_v5.py  ->  options_dashboard_AHRAM_LIVE5.html

Usage:
    python ahram_engine_v5.py --once          # one cycle, then finish
    python ahram_engine_v5.py                 # loop every NCYCLE seconds
    python ahram_engine_v5.py --once --offline   # read sample_marketwatch.txt

Because the engines themselves have no TSETMC dependency, `--offline` lets the
whole pipeline (except the network fetch) be tested on a recorded snapshot.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime

# keep the console on Windows happy with Persian output
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from jalali_v5 import today_tehran
import tsetmc_collector_v5 as collector
import strategy_bridge_v5 as bridge
import connect_strategy_dashboard_v5 as connect

HERE = os.path.dirname(os.path.abspath(__file__))
NCYCLE = int(os.environ.get("AHRAM_CYCLE", "300"))


# ---------------------------------------------------------------- simple technicals
def compute_technicals(db_path: str, stock_price: float):
    """A small, dependency-free technical proxy for the V2 decision engine.

    Uses the stored price snapshots (last vs closing vs previous closing).  When
    only one snapshot exists (fresh DB), it falls back to last vs closing.
    """
    conf = {"action": "WATCH", "score": 0, "confidence": 30, "price": stock_price}
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT last_price, closing_price FROM prices WHERE last_price IS NOT NULL "
            "ORDER BY id DESC LIMIT 6").fetchall()
        con.close()
        if not rows:
            return conf
        last = rows[0][0] or 0
        close = rows[0][1] or last
        prev = None
        for i in range(1, len(rows)):
            if rows[i][1]:
                prev = rows[i][1]
                break
        if not last:
            return conf
        up = last > close
        trend = close - (prev or close)
        score = 0
        if up and (prev is None or close >= prev):
            score = 55
            conf["action"] = "BUY"
            conf["confidence"] = 70
        elif (not up) and (prev is None or close <= prev):
            score = -55
            conf["action"] = "SELL"
            conf["confidence"] = 70
        else:
            score = 10
            conf["action"] = "WATCH"
            conf["confidence"] = 35
        # small momentum adjustment
        if trend and last:
            if trend > 0:
                score += 8
            elif trend < 0:
                score -= 8
        conf["score"] = int(round(max(-100.0, min(100.0, float(score)))))
    except Exception:
        pass
    return conf


# ---------------------------------------------------------------- DB read helpers
def latest_price(con: sqlite3.Connection):
    try:
        row = con.execute("SELECT last_price, closing_price FROM prices ORDER BY id DESC LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return {"last": row[0], "close": row[1]}


def latest_options(con: sqlite3.Connection):
    try:
        latest = con.execute("SELECT MAX(id) FROM options").fetchone()[0]
    except sqlite3.OperationalError:
        return None, []
    if latest is None:
        return None, []
    t = con.execute("SELECT time FROM options WHERE id=?", (latest,)).fetchone()
    t = t[0] if t else None
    rows = con.execute(
        "SELECT symbol, option_type, stock_price, option_price, strike_price, expire_date, "
        "days_to_expire, volume, value_traded, open_interest, bid_price, ask_price "
        "FROM options WHERE time=? ORDER BY strike_price, option_type",
        (t,)).fetchall()
    cols = ["symbol", "option_type", "stock_price", "option_price", "strike_price",
            "expire_date", "days_to_expire", "volume", "value_traded", "open_interest",
            "bid_price", "ask_price"]
    return t, [dict(zip(cols, r)) for r in rows]


# ---------------------------------------------------------------- analyze one symbol
def analyze_symbol(symbol: dict, write_signal: bool = True) -> dict:
    db = symbol["db"]
    con = sqlite3.connect(db)
    try:
        price = latest_price(con)
        time_, options = latest_options(con)
    finally:
        con.close()

    stock_price = ((price or {}).get("last") or 0) if price else 0
    if not stock_price and price:
        stock_price = price.get("close") or 0
    if not stock_price:
        return {"symbol": symbol["name"], "ok": False, "reason": "no stock price"}

    import greek_engine_v2 as gk
    import iv_engine_v2 as iv
    import risk_engine_v2 as rk
    import contract_scoring_engine_v2 as sc
    import decision_engine_v2 as dc
    import sentiment_engine_v2 as sen

    technicals = compute_technicals(db, stock_price)

    # Greeks for every option
    contracts = []
    for o in options:
        try:
            c = gk.analyze_contract(
                o["symbol"], float(stock_price), float(o["strike_price"]),
                float(o["option_price"]), int(o["days_to_expire"] or 0),
                str(o["option_type"]).upper() or "CALL",
                db_path=db, volume=o["volume"], oi=o["open_interest"])
            contracts.append(c)
        except Exception:
            continue
    if not contracts:
        return {"symbol": symbol["name"], "ok": True, "options": len(options),
                "decision": "WATCH", "reason": "no analyzable contract"}

    # IV engine (record + analyze) using an ATM IV if derivable
    iv_analysis = None
    atm = min(contracts, key=lambda c: abs(c["stock_price"] - c["strike_price"]))
    atm_iv = atm.get("iv")
    try:
        if atm_iv:
            iv.record_daily_iv(db, atm_iv)
        iv_analysis = iv.analyze_iv(db, current_iv=atm_iv)
    except Exception:
        iv_analysis = None

    # Decision engine (ranks internally: risk + scoring)
    decision = dc.make_decision(symbol["name"], technicals, contracts, iv_analysis=iv_analysis)

    # Sentiment V2
    sentiment = None
    try:
        sentiment = sen.analyze_sentiment(db_path=db, market_data={}, wiv_data=None,
                                          iv_rank_data=None, options_data=options)
    except Exception:
        sentiment = None

    # Persist a signal-history row so the dashboard bridge can read it
    if write_signal:
        try:
            _write_signal(db, symbol["name"], technicals, decision, contracts, stock_price)
        except Exception:
            pass

    return {
        "symbol": symbol["name"], "ok": True, "options": len(options),
        "stock_price": stock_price, "technicals": technicals,
        "decision": decision.get("decision"), "v2_score": decision.get("final_score"),
        "best": (decision.get("best_contract") or {}).get("symbol"),
        "sentiment": (sentiment or {}).get("fear_greed", {}).get("fear_greed"),
        "sentiment_level": (sentiment or {}).get("fear_greed", {}).get("level"),
    }


def _write_signal(db, name, technicals, decision, contracts, stock_price):
    symbol = (decision.get("best_contract") or {}).get("symbol")
    price = (decision.get("best_contract") or {}).get("contract_analysis", {}).get("option_price")
    strike = (decision.get("best_contract") or {}).get("contract_analysis", {}).get("strike_price")
    details = {
        "v2_decision": decision,
        "option": {"symbol": symbol, "option_price": price, "strike_price": strike,
                   "stock_price": stock_price},
        "wiv": None,
    }
    con = sqlite3.connect(db)
    try:
        con.execute(
            "INSERT INTO signal_history (time, symbol, signal_type, composite_score, "
            "option_symbol, option_price, strike_price, outcome, details, v2_score, "
            "v2_decision, v2_best_symbol) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name,
             decision.get("decision", "WATCH"), decision.get("final_score", 0),
             symbol, price, strike, "PENDING",
             json.dumps(details, ensure_ascii=False, default=str),
             decision.get("final_score"), decision.get("decision"),
             symbol))
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- cycle
def run_cycle(symbols, offline=False, write_signal=True):
    res = collector.run_cycle(symbols, offline=offline, write=True)
    summary = []
    for s in symbols:
        try:
            r = analyze_symbol(s, write_signal=write_signal)
            summary.append(r)
        except Exception as exc:
            summary.append({"symbol": s["name"], "ok": False, "reason": str(exc)})
    return res, summary


def build_dashboard():
    # Rebuild the bridge JSON (reads the DBs) and then inject it into the template.
    payload = bridge.build_payload()
    with open("ahram_strategy_data_v5.json", "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    connect.main()
    return payload


def main():
    p = argparse.ArgumentParser(description="Self-contained AHRAM LIVE5 engine")
    p.add_argument("--once", action="store_true", help="run one cycle and exit")
    p.add_argument("--offline", action="store_true", help="use sample_marketwatch.txt")
    p.add_argument("--db", default=None, help="single db override (testing)")
    p.add_argument("--cycle", type=int, default=NCYCLE, help="seconds between cycles")
    args = p.parse_args()

    symbols = collector.load_symbols()
    if args.db:
        for s in symbols:
            s["db"] = args.db

    print(f"🔬 AHRAM LIVE5 (self-contained) | نمادها: {', '.join(s['name'] for s in symbols)}")
    while True:
        try:
            res, summary = run_cycle(symbols, offline=args.offline)
            print("marketTime:", res.get("marketTime"))
            for r in summary:
                if r.get("ok"):
                    print(f"  {r['symbol']}: {r.get('options')} قرارداد | "
                          f"قیمت {r.get('stock_price')} | "
                          f"V2 {r.get('v2_score')} {r.get('decision')} | "
                          f"FG {r.get('sentiment')} {r.get('sentiment_level')}")
                else:
                    print(f"  {r['symbol']}: FAIL {r.get('reason')}")
            payload = build_dashboard()
            print("✅ LIVE5 ساخته شد:", "ahram_strategy_data_v5.json",
                  f"({len(payload.get('symbols', {}))} نماد)")
            if args.once:
                break
            print(f"⏳ سیکل بعدی {args.cycle}s ...")
            time.sleep(args.cycle)
        except KeyboardInterrupt:
            print("\n🛑 متوقف شد.")
            break
        except Exception as exc:
            print("❌", exc)
            time.sleep(30)


if __name__ == "__main__":
    main()
