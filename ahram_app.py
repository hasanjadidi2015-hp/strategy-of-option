# -*- coding: utf-8 -*-
"""
ahram_app.py — ONE self-contained program for AHRAM LIVE5.

Everything the previous multi-window setup did, in a single process, so there is
nothing to point at, open, or keep track of:

  * an HTTP server that serves the LIVE5 dashboard, the bridge JSON and exposes
    /api/live (live TSETMC stock + option snapshot for the big ticker/strategies),
  * a continuous engine loop that refetches prices from TSETMC, runs the 6 V2
    engines + sentiment, and rewrites ahram_strategy_data_v5.json so the purple
    panel stays LIVE,
  * opens the browser once the server is up,
  * writes a single ark_debug.log (also mirrors to the console window).

Run with:   python ahram_app.py
Run offline (sample data, e.g. to preview without a market):
            python ahram_app.py --offline
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import server as srv
import ahram_engine_v5 as engine
import tsetmc_collector_v5 as collector

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, "ark_debug.log")
REFRESH = 60  # seconds between engine cycles during the market

# Iran market hours. Iran is UTC+3:30 (no DST). Sat..Wed = 9:00..12:30.
def tehran_now():
    from datetime import timezone
    import datetime as _dt
    # Iran is +03:30, no DST -> fixed offset. Robust and dependency-free.
    return datetime.now(timezone.utc) + _dt.timedelta(hours=3, minutes=30)


def market_is_open(now=None):
    if now is None:
        now = tehran_now()
    # Iran weekday: the datetime we compute is already Tehran local.
    dow = now.weekday()  # Mon=0..Sun=6. Iran trading days = Sat(5), Sun(6), Mon(0), Tue(1), Wed(2).
    trading_days = (5, 6, 0, 1, 2)
    if dow not in trading_days:
        return False
    t = now.time()
    from datetime import time as dtime
    return dtime(9, 0) <= t <= dtime(12, 30)


def cycle_seconds(open_):
    """During the market refresh often; outside, refresh slowly (still alive)."""
    return 60 if open_ else 300



def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def start_bridge(host: str = "127.0.0.1", preferred: int = 8765) -> tuple:
    """Start the dashboard/live HTTP server on a free port. Returns (httpd, port)."""
    httpd, port = srv.find_port(host, preferred)
    threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.4},
                     daemon=True).start()
    return httpd, port


def engine_loop(offline: bool, symbols: list, stop: threading.Event) -> None:
    """Continuously refetch + rebuild the bridge JSON until `stop` is set."""
    while not stop.is_set():
        t0 = time.time()
        open_ = market_is_open()
        secs = cycle_seconds(open_)
        try:
            if offline:
                log("چرخه: حالت آفلاین (داده نمونه) — برای قیمت زنده بدون --offline اجرا کنید.")
            elif not open_:
                log("چرخه: بازار بسته است؛ قیمت پایانی/ثابت است. (برای قیمت لحظه‌ای در ساعات 09:00–12:30 اجرا کنید.)")
            else:
                log("چرخه: بازار باز است؛ دریافت قیمت زنده از TSETMC…")
            res, summary = engine.run_cycle(symbols, offline=offline)
            mt = res.get("marketTime")
            log(f"   marketTime={mt!r}")
            for r in summary:
                if r.get("ok"):
                    log(f"   {r['symbol']}: {r.get('options')} قرارداد | قیمت {r.get('stock_price')} | "
                        f"V2 {r.get('v2_score')} {r.get('decision')} | FG {r.get('sentiment')} {r.get('sentiment_level')}")
                else:
                    log(f"   {r['symbol']}: FAIL {r.get('reason')}")
            engine.build_dashboard()
            log("   JSON + LIVE5 به‌روز شد.")
        except Exception as exc:
            log(f"⚠️ خطای سیکل: {exc}")
        # Next cycle: during the market every 60s, otherwise every 5 minutes.
        if secs != REFRESH:
            log(f"   (بازار {'باز' if open_ else 'بسته'}؛ سیکل بعدی در {secs}s)")
        remain = secs - (time.time() - t0)
        if remain > 0:
            stop.wait(remain)


def main() -> None:
    global REFRESH
    p = argparse.ArgumentParser(description="AHRAM LIVE5 all-in-one app")
    p.add_argument("--offline", action="store_true", help="use sample_marketwatch.txt (no network)")
    p.add_argument("--no-browser", action="store_true", help="do not open the browser")
    p.add_argument("--port", type=int, default=8765, help="preferred port")
    p.add_argument("--refresh", type=int, default=REFRESH, help="seconds between engine cycles")
    args = p.parse_args()

    REFRESH = max(10, args.refresh)

    if not os.path.exists(srv.DASHBOARD):
        raise SystemExit(f"Dashboard not found: {srv.DASHBOARD}")
    if not os.path.exists("options_dashboard_AHRAM.html"):
        raise SystemExit("Template not found: options_dashboard_AHRAM.html")
    if not os.path.exists("sample_marketwatch.txt") and args.offline:
        raise SystemExit("sample_marketwatch.txt not found (needed for --offline)")

    log("=" * 60)
    log("AHRAM LIVE5 (all-in-one) — شروع")
    log(f"   پوشه: {HERE}")
    log(f"   حالت: {'آفلاین (داده نمونه)' if args.offline else 'زنده (TSETMC)'}")

    symbols = collector.load_symbols()

    # Ensure fresh DB schemas exist up-front.
    for s in symbols:
        try:
            collector.ensure_schema(s["db"])
        except Exception as exc:
            log(f"   [WARN] ساخت DB {s['db']}: {exc}")

    # First cycle runs synchronously so the JSON + dashboard exist before we open.
    log("   [1/2] ساخت اولیه (داده + ۶ موتور V2 + پنل)...")
    try:
        res, summary = engine.run_cycle(symbols, offline=args.offline)
        log(f"   marketTime={res.get('marketTime')!r}")
        for r in summary:
            log(f"   {r.get('symbol')}: {r.get('options')} قرارداد | قیمت {r.get('stock_price')} | "
                f"V2 {r.get('v2_score')} {r.get('decision')}")
        engine.build_dashboard()
        log("   ✅ ساخت اولیه کامل شد.")
    except Exception as exc:
        log(f"   ❌ ساخت اولیه خطا داد: {exc}")
        log("   (صفحه با داده قبلی/نمونه باز می‌شود)")

    # Start the live bridge / HTTP server.
    httpd, port = start_bridge(host="127.0.0.1", preferred=args.port)
    url = f"http://127.0.0.1:{port}/"
    log(f"   [2/2] سرور زنده روی {url}")

    # Open the browser once the server is up.
    if not args.no_browser:
        webbrowser.open(url)
        log("   مرورگر باز شد.")

    # Keep the engine refreshing the panel in the background.
    stop = threading.Event()
    t = threading.Thread(target=engine_loop, args=(args.offline, symbols, stop),
                         daemon=True)
    t.start()
    log(" چرخهٔ به‌روزرسانی هر %d ثانیه فعال است. (برای توقف: Ctrl+C)" % REFRESH)
    log(" مرورگر را باز نگه دارید؛ برای دیدن قیمت زنده در ساعت بازار اجرا کنید.")

    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        stop.set()
        log("\n🛑 متوقف شد.")


if __name__ == "__main__":
    main()
