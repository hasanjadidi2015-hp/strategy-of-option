# -*- coding: utf-8 -*-
"""
AHRAM AI PRO - IV Engine V2 - ماژول 2 از 6
نسخه مخصوص بازار ایران

این ماژول:
- IV را از قیمت بازار استخراج می‌کند (از greek_engine_v2)
- IV Rank, IV Percentile, IV Change, IV Skew, IV Term Structure را حساب می‌کند
- رژیم IV را تشخیص می‌دهد (Rising, Falling, High, Low)
- هشدار IV Crush / IV Expansion می‌دهد

فرق با iv_rank.py قبلی:
- قبلی: فقط Rank و Percentile ساده
- جدید: Rank + Percentile + Change (روزانه/هفتگی) + Skew (Call/Put, OTM/ATM) + Term Structure + رژیم
"""

import sqlite3
import os
import math
from datetime import datetime, timedelta
from collections import defaultdict

try:
    import config
    MIN_DAYS = 10
except:
    MIN_DAYS = 10

# ==================== جدول‌ها ====================

def _ensure_tables(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS iv_history (
            date TEXT PRIMARY KEY,
            atm_iv REAL,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS iv_skew_history (
            date TEXT,
            expiry TEXT,
            atm_iv REAL,
            otm_call_iv REAL,
            otm_put_iv REAL,
            call_put_skew REAL,
            otm_atm_skew REAL,
            PRIMARY KEY (date, expiry)
        )
    """)

def record_daily_iv(db_path, atm_iv):
    """ثبت IV روزانه - یک ردیف در روز (از iv_rank قبلی)"""
    if not atm_iv or atm_iv <= 0:
        return
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        _ensure_tables(cur)
        today = datetime.now().strftime("%Y-%m-%d")
        cur.execute(
            "INSERT INTO iv_history(date, atm_iv, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(date) DO UPDATE SET atm_iv=excluded.atm_iv, updated_at=excluded.updated_at",
            (today, float(atm_iv), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def record_skew(db_path, expiry, atm_iv, otm_call_iv=None, otm_put_iv=None):
    """ثبت Skew روزانه برای هر سررسید"""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        _ensure_tables(cur)
        today = datetime.now().strftime("%Y-%m-%d")
        call_put_skew = None
        otm_atm_skew = None
        if otm_call_iv and otm_put_iv:
            # Call IV معمولا کمتر از Put IV در بازارهای نزولی (skew)
            call_put_skew = round(otm_put_iv - otm_call_iv, 4)
        if atm_iv and otm_call_iv:
            otm_atm_skew = round(otm_call_iv - atm_iv, 4)
        cur.execute(
            "INSERT INTO iv_skew_history(date, expiry, atm_iv, otm_call_iv, otm_put_iv, call_put_skew, otm_atm_skew) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(date, expiry) DO UPDATE SET "
            "atm_iv=excluded.atm_iv, otm_call_iv=excluded.otm_call_iv, otm_put_iv=excluded.otm_put_iv, "
            "call_put_skew=excluded.call_put_skew, otm_atm_skew=excluded.otm_atm_skew",
            (today, expiry, atm_iv, otm_call_iv, otm_put_iv, call_put_skew, otm_atm_skew)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[WARN] record_skew: {e}")

# ==================== محاسبات Rank / Percentile / Change ====================

def compute_iv_rank_percentile(db_path, current_iv=None):
    """محاسبه IV Rank و Percentile - نسخه بهبود یافته"""
    empty = {"iv_rank": None, "iv_percentile": None, "days": 0, "ready": False, "min_iv": None, "max_iv": None, "avg_iv": None}
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        _ensure_tables(cur)
        cur.execute("SELECT date, atm_iv FROM iv_history ORDER BY date")
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return empty

    ivs = [r[1] for r in rows if r[1] and r[1] > 0]
    if len(ivs) < 2:
        return {"iv_rank": None, "iv_percentile": None, "days": len(ivs), "ready": False, "min_iv": min(ivs) if ivs else None, "max_iv": max(ivs) if ivs else None, "avg_iv": sum(ivs)/len(ivs) if ivs else None}

    cur_iv = current_iv
    if cur_iv is None:
        today = datetime.now().strftime("%Y-%m-%d")
        today_rows = [r[1] for r in rows if r[0] == today and r[1]]
        cur_iv = today_rows[-1] if today_rows else ivs[-1]

    lo, hi = min(ivs), max(ivs)
    avg = sum(ivs) / len(ivs)
    if hi > lo:
        raw_rank = ((cur_iv - lo) / (hi - lo)) * 100
        # Clamp به 0-100 - اگر IV فعلی کمتر از کمینه تاریخچه باشه منفی میشد (مثل تست ahram_v2.db که -29% داد)
        iv_rank = round(max(0.0, min(100.0, raw_rank)), 1)
    else:
        iv_rank = 50.0
    below = sum(1 for v in ivs if v < cur_iv)
    iv_percentile = round((below / len(ivs)) * 100, 1)

    return {
        "iv_rank": iv_rank,
        "iv_percentile": iv_percentile,
        "days": len(ivs),
        "ready": len(ivs) >= MIN_DAYS,
        "min_iv": round(lo, 4),
        "max_iv": round(hi, 4),
        "avg_iv": round(avg, 4),
        "current_iv": round(cur_iv, 4)
    }

def compute_iv_change(db_path):
    """تغییر IV روزانه و هفتگی"""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        _ensure_tables(cur)
        cur.execute("SELECT date, atm_iv FROM iv_history ORDER BY date DESC LIMIT 10")
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return {"daily_change": None, "weekly_change": None, "trend": "UNKNOWN"}

    if len(rows) < 2:
        return {"daily_change": None, "weekly_change": None, "trend": "UNKNOWN"}

    # rows[0] = امروز، rows[1] = دیروز، rows[5] = هفته قبل تقریبا
    today_iv = rows[0][1]
    yesterday_iv = rows[1][1] if len(rows) > 1 else None
    week_ago_iv = rows[5][1] if len(rows) > 5 else (rows[-1][1] if len(rows) >= 7 else None)

    daily_change = round(((today_iv - yesterday_iv) / yesterday_iv * 100), 2) if yesterday_iv and yesterday_iv > 0 else None
    weekly_change = round(((today_iv - week_ago_iv) / week_ago_iv * 100), 2) if week_ago_iv and week_ago_iv > 0 else None

    # تشخیص روند
    if daily_change is None:
        trend = "UNKNOWN"
    elif daily_change > 5:
        trend = "Rising"
    elif daily_change < -5:
        trend = "Falling"
    else:
        trend = "Stable"

    return {
        "daily_change_pct": daily_change,
        "weekly_change_pct": weekly_change,
        "trend": trend,
        "today_iv": today_iv,
        "yesterday_iv": yesterday_iv,
        "week_ago_iv": week_ago_iv
    }

# ==================== Skew و Term Structure ====================

def compute_iv_skew_from_chain(options_chain):
    """
    محاسبه Skew از زنجیره آپشن‌های یک روز
    options_chain: لیست dict با فیلدهای option_type, strike_price, implied_volatility, expire_date
    خروجی: برای هر سررسید، ATM IV, OTM Call IV, OTM Put IV, Skewها
    """
    # گروه‌بندی بر اساس سررسید
    by_expiry = defaultdict(list)
    for opt in options_chain:
        exp = str(opt.get("expire_date") or "").strip()
        if not exp:
            continue
        if opt.get("implied_volatility") and opt["implied_volatility"] > 0:
            by_expiry[exp].append(opt)

    result = {}
    for expiry, opts in by_expiry.items():
        calls = [o for o in opts if str(o.get("option_type","")).upper() == "CALL"]
        puts = [o for o in opts if str(o.get("option_type","")).upper() == "PUT"]
        if not calls or not puts:
            continue

        # پیدا کردن ATM: نزدیک‌ترین Strike به قیمت سهم
        # فرض: همه opts یک stock_price دارن
        stock_prices = [o.get("stock_price") for o in opts if o.get("stock_price")]
        stock_price = stock_prices[0] if stock_prices else None
        if not stock_price:
            continue

        # مرتب‌سازی بر اساس فاصله از ATM
        calls_sorted = sorted(calls, key=lambda x: abs(float(x.get("strike_price",0)) - stock_price))
        puts_sorted = sorted(puts, key=lambda x: abs(float(x.get("strike_price",0)) - stock_price))

        atm_call = calls_sorted[0] if calls_sorted else None
        atm_put = puts_sorted[0] if puts_sorted else None
        atm_iv = None
        if atm_call and atm_put:
            atm_iv = (float(atm_call.get("implied_volatility",0)) + float(atm_put.get("implied_volatility",0))) / 2
        elif atm_call:
            atm_iv = float(atm_call.get("implied_volatility",0))
        elif atm_put:
            atm_iv = float(atm_put.get("implied_volatility",0))

        # OTM: Call با Strike بالاتر از سهم (10% بالاتر)، Put با Strike پایین‌تر (10% پایین‌تر)
        otm_calls = [c for c in calls if float(c.get("strike_price",0)) > stock_price * 1.05]
        otm_puts = [p for p in puts if float(p.get("strike_price",0)) < stock_price * 0.95]

        otm_call_iv = None
        otm_put_iv = None
        if otm_calls:
            # نزدیک‌ترین OTM Call
            otm_calls_sorted = sorted(otm_calls, key=lambda x: float(x.get("strike_price",0)))
            otm_call_iv = float(otm_calls_sorted[0].get("implied_volatility",0))
        if otm_puts:
            otm_puts_sorted = sorted(otm_puts, key=lambda x: float(x.get("strike_price",0)), reverse=True)
            otm_put_iv = float(otm_puts_sorted[0].get("implied_volatility",0))

        call_put_skew = round(otm_put_iv - otm_call_iv, 4) if otm_call_iv and otm_put_iv else None
        otm_atm_skew = round(otm_call_iv - atm_iv, 4) if otm_call_iv and atm_iv else None

        result[expiry] = {
            "stock_price": stock_price,
            "atm_iv": round(atm_iv, 4) if atm_iv else None,
            "otm_call_iv": round(otm_call_iv, 4) if otm_call_iv else None,
            "otm_put_iv": round(otm_put_iv, 4) if otm_put_iv else None,
            "call_put_skew": call_put_skew,
            "otm_atm_skew": otm_atm_skew,
            "calls_count": len(calls),
            "puts_count": len(puts),
        }

    return result

def compute_term_structure(db_path):
    """ساختار زمانی IV: IV در سررسیدهای مختلف"""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        _ensure_tables(cur)
        cur.execute("SELECT date, expiry, atm_iv FROM iv_skew_history ORDER BY date DESC, expiry")
        rows = cur.fetchall()
        conn.close()
    except Exception:
        return {}

    # آخرین تاریخ
    if not rows:
        return {}

    latest_date = rows[0][0]
    latest = [r for r in rows if r[0] == latest_date]

    term = {}
    for date, expiry, atm_iv in latest:
        term[expiry] = atm_iv

    # تشخیص Contango / Backwardation
    expiries_sorted = sorted(term.keys())
    if len(expiries_sorted) >= 2:
        first_iv = term[expiries_sorted[0]]
        last_iv = term[expiries_sorted[-1]]
        if first_iv and last_iv:
            if last_iv > first_iv * 1.05:
                structure = "Contango (IV دورتر بیشتر - نرمال)"
            elif last_iv < first_iv * 0.95:
                structure = "Backwardation (IV نزدیک بیشتر - ریسک رویداد)"
            else:
                structure = "Flat"
        else:
            structure = "Unknown"
    else:
        structure = "Single expiry"

    return {"term": term, "structure": structure, "latest_date": latest_date}

# ==================== موتور اصلی ====================

def analyze_iv(db_path, current_iv=None, options_chain=None):
    """
    تحلیل کامل IV برای یک نماد
    """
    rank_data = compute_iv_rank_percentile(db_path, current_iv)
    change_data = compute_iv_change(db_path)
    term_data = compute_term_structure(db_path)

    skew_data = {}
    if options_chain:
        skew_data = compute_iv_skew_from_chain(options_chain)

    # تشخیص رژیم IV
    regime = "UNKNOWN"
    risk = []
    if rank_data.get("ready"):
        iv_rank = rank_data.get("iv_rank")
        if iv_rank is not None:
            if iv_rank >= 80:
                regime = "High"
                risk.append(f"IV Rank بالا {iv_rank}% - پرمیوم گرون، ریسک IV Crush")
            elif iv_rank <= 20:
                regime = "Low"
                risk.append(f"IV Rank پایین {iv_rank}% - پرمیوم ارزون، فرصت خرید Vol")
            else:
                regime = "Normal"

    if change_data.get("trend") == "Rising":
        risk.append(f"IV در حال افزایش {change_data.get('daily_change_pct')}% - نوسان در راه")
    elif change_data.get("trend") == "Falling":
        risk.append(f"IV در حال کاهش {change_data.get('daily_change_pct')}% - آرامش")

    # Skew هشدار
    for expiry, s in skew_data.items():
        if s.get("call_put_skew") and abs(s["call_put_skew"]) > 0.1:
            risk.append(f"Skew بالا در {expiry}: Call/Put skew {s['call_put_skew']}")

    return {
        "iv_rank": rank_data,
        "iv_change": change_data,
        "iv_term_structure": term_data,
        "iv_skew": skew_data,
        "regime": regime,
        "risks": risk,
        "ready": rank_data.get("ready", False)
    }

def print_iv_report(analysis, symbol_name=""):
    print("="*60)
    print(f"IV ENGINE V2 - {symbol_name}")
    print("="*60)
    rank = analysis.get("iv_rank", {})
    print(f"IV Rank: {rank.get('iv_rank')}% | Percentile: {rank.get('iv_percentile')}% | Days: {rank.get('days')}/{MIN_DAYS} | Ready: {rank.get('ready')}")
    print(f"  Min: {rank.get('min_iv')} | Max: {rank.get('max_iv')} | Avg: {rank.get('avg_iv')} | Current: {rank.get('current_iv')}")
    change = analysis.get("iv_change", {})
    print(f"IV Change: Daily {change.get('daily_change_pct')}% | Weekly {change.get('weekly_change_pct')}% | Trend: {change.get('trend')}")
    term = analysis.get("iv_term_structure", {})
    print(f"Term Structure: {term.get('structure')} | Data: {term.get('term')}")
    skew = analysis.get("iv_skew", {})
    if skew:
        print("Skew per expiry:")
        for exp, data in skew.items():
            print(f"  {exp}: ATM IV {data.get('atm_iv')} | OTM Call {data.get('otm_call_iv')} | OTM Put {data.get('otm_put_iv')} | C/P Skew {data.get('call_put_skew')} | OTM/ATM Skew {data.get('otm_atm_skew')}")
    else:
        print("Skew: داده زنجیره موجود نیست (options_chain ندادی)")
    print(f"Regime: {analysis.get('regime')}")
    print("Risks:")
    for r in analysis.get("risks", []):
        print(f"  - {r}")
    print("="*60)

# ==================== تست ====================

if __name__ == "__main__":
    print("\n--- تست 1: IV Rank با دیتابیس واقعی ---")
    for db in ["ahram_v2.db", "webmellt.db", "shasta.db"]:
        if os.path.exists(db):
            print(f"\nDB: {db}")
            result = analyze_iv(db, current_iv=0.55)
            print_iv_report(result, symbol_name=db)
            break
    else:
        print("هیچ دیتابیسی پیدا نشد - تست با داده ساختگی")
        # تست با داده ساختگی
        import tempfile
        tmp = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(tmp)
        cur = conn.cursor()
        _ensure_tables(cur)
        # 12 روز داده ساختگی
        for i in range(12):
            date = (datetime.now() - timedelta(days=12-i)).strftime("%Y-%m-%d")
            iv = 0.4 + (i % 5) * 0.05 + (0.1 if i > 8 else 0)
            cur.execute("INSERT INTO iv_history(date, atm_iv, updated_at) VALUES (?,?,?)", (date, iv, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
        result = analyze_iv(tmp, current_iv=0.65)
        print_iv_report(result, symbol_name="TEST FAKE")
        os.remove(tmp)

    print("\n--- تست 2: Skew از زنجیره ساختگی ---")
    fake_chain = [
        {"expire_date": "2026-09-18", "option_type": "CALL", "strike_price": 1400, "implied_volatility": 0.50, "stock_price": 1489},
        {"expire_date": "2026-09-18", "option_type": "CALL", "strike_price": 1550, "implied_volatility": 0.55, "stock_price": 1489},
        {"expire_date": "2026-09-18", "option_type": "CALL", "strike_price": 1600, "implied_volatility": 0.60, "stock_price": 1489},
        {"expire_date": "2026-09-18", "option_type": "PUT", "strike_price": 1400, "implied_volatility": 0.52, "stock_price": 1489},
        {"expire_date": "2026-09-18", "option_type": "PUT", "strike_price": 1350, "implied_volatility": 0.58, "stock_price": 1489},
        {"expire_date": "2026-09-18", "option_type": "PUT", "strike_price": 1300, "implied_volatility": 0.65, "stock_price": 1489},
        {"expire_date": "2026-10-16", "option_type": "CALL", "strike_price": 1400, "implied_volatility": 0.55, "stock_price": 1489},
        {"expire_date": "2026-10-16", "option_type": "PUT", "strike_price": 1400, "implied_volatility": 0.57, "stock_price": 1489},
    ]
    skew = compute_iv_skew_from_chain(fake_chain)
    print(f"Skew result: {skew}")
    analysis = analyze_iv(db_path=":memory:", current_iv=0.55, options_chain=fake_chain)
    print_iv_report(analysis, symbol_name="FAKE CHAIN")
