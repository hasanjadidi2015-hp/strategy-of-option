# -*- coding: utf-8 -*-
"""
تابلوخوانی زنده -- عمق سفارش خرید/فروش (۵ ردیف اول) خود سهم، از TSETMC.

⚠️ نکته‌ی مهم: endpoint اصلی (BestLimits) از یه مرجع مستقل (فهرست کامل
API های TSETMC) تأیید شده، ولی اسم دقیق فیلدهای داخل پاسخ (zOrdMeDem و
غیره) بر پایه‌ی رایج‌ترین قرارداد استفاده‌شده در کتابخونه‌های عمومی TSETMC
حدس زده شده -- **اولین اجرا رو حتماً تست کن**. اگه فیلدها فرق داشت،
پیام خطا دقیقاً شکل خام پاسخ رو چاپ می‌کنه تا بشه فیلدها رو یک‌راست اصلاح
کرد.
"""
import requests
import sqlite3
import time
from datetime import datetime

import config

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.tsetmc.com/",
}


def fetch_order_book(ins_code=None, max_retries=3):
    ins_code = ins_code or config.INS_CODE
    url = f"https://cdn.tsetmc.com/api/BestLimits/{ins_code}"
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
        except requests.exceptions.RequestException as e:
            print("ORDER-BOOK CONNECTION ERROR:", e)
            time.sleep(2)
            continue
        if response.status_code != 200:
            print("ORDER-BOOK SERVER ERROR:", response.status_code)
            time.sleep(2)
            continue
        if not response.text or not response.text.strip():
            print(f"ORDER-BOOK EMPTY RESPONSE (attempt {attempt}/{max_retries}) -> RETRYING")
            time.sleep(2)
            continue
        try:
            data = response.json()
        except ValueError:
            print("ORDER-BOOK INVALID JSON:", response.text[:300])
            time.sleep(2)
            continue
        levels = data.get("bestLimitsInfo") or data.get("bestLimits")
        if not levels:
            print("ORDER-BOOK UNEXPECTED RESPONSE SHAPE -- فیلدها رو با این چک کن:", data)
            return None
        return levels
    print("ORDER-BOOK FAILED AFTER", max_retries, "ATTEMPTS")
    return None


def _ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS order_book (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT,
            level INTEGER,
            buy_count INTEGER,
            buy_volume REAL,
            buy_price REAL,
            sell_price REAL,
            sell_volume REAL,
            sell_count INTEGER
        )
    """)
    # اگه یه نسخه‌ی قدیمی/ناقص از این جدول از قبل وجود داشته باشه (مثلاً از
    # یه تست قبلی)، CREATE TABLE IF NOT EXISTS کاری نمی‌کنه -- پس خودمون
    # ستون‌های لازم رو چک و اضافه می‌کنیم.
    cur.execute("PRAGMA table_info(order_book)")
    existing = {r[1] for r in cur.fetchall()}
    required = {
        "time": "TEXT", "level": "INTEGER", "buy_count": "INTEGER",
        "buy_volume": "REAL", "buy_price": "REAL", "sell_price": "REAL",
        "sell_volume": "REAL", "sell_count": "INTEGER",
    }
    for col, coltype in required.items():
        if col not in existing:
            try:
                cur.execute(f"ALTER TABLE order_book ADD COLUMN {col} {coltype}")
            except Exception:
                pass


def _get_field(lv, *names):
    for n in names:
        if n in lv and lv[n] is not None:
            return lv[n]
    return 0


def collect_order_book(db_path=None):
    """عمق سفارش رو می‌گیره، توی دیتابیس ذخیره می‌کنه، و یه خلاصه‌ی تحلیلی
    (فشار خرید/فروش در صف سفارش، نه صرفاً معاملات انجام‌شده) برمی‌گردونه."""
    db_path = db_path or config.DATABASE_NAME
    levels = fetch_order_book()
    if not levels:
        return None

    rows = []
    for lv in levels:
        try:
            rows.append((
                int(_get_field(lv, "number") or 0),
                int(_get_field(lv, "zOrdMeDem", "buyOrderCount") or 0),
                float(_get_field(lv, "qTitMeDem", "buyVolume") or 0),
                float(_get_field(lv, "pMeDem", "buyPrice") or 0),
                float(_get_field(lv, "pMeArz", "sellPrice") or 0),
                float(_get_field(lv, "qTitMeArz", "sellVolume") or 0),
                int(_get_field(lv, "zOrdMeArz", "sellOrderCount") or 0),
            ))
        except Exception:
            continue

    if not rows:
        print("ORDER-BOOK: هیچ ردیف قابل‌پردازشی نبود -- فیلدهای زیر رو چک کن:", levels[:1] if levels else None)
        return None

    rows.sort(key=lambda r: r[0])  # مرتب بر اساس شماره‌ی ردیف (1 تا 5)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        _ensure_table(cur)
        for level, bc, bv, bp, sp, sv, sc in rows:
            cur.execute(
                "INSERT INTO order_book(time, level, buy_count, buy_volume, buy_price, "
                "sell_price, sell_volume, sell_count) VALUES (?,?,?,?,?,?,?,?)",
                (now, level, bc, bv, bp, sp, sv, sc),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print("ORDER-BOOK DB ERROR:", e)

    total_buy_vol = sum(r[2] for r in rows)
    total_sell_vol = sum(r[5] for r in rows)
    total_buy_cnt = sum(r[1] for r in rows)
    total_sell_cnt = sum(r[6] for r in rows)
    best_buy = rows[0][3] if rows else None
    best_sell = rows[0][4] if rows else None
    spread = (best_sell - best_buy) if (best_buy and best_sell) else None
    spread_pct = round((spread / best_buy) * 100, 3) if (spread and best_buy) else None

    # اعتبارسنجی دو طرف قبل از محاسبه‌ی فشار: اگه یه طرف کاملاً خالیه (نه
    # قیمت داره، نه حجم، نه تعداد سفارش)، باید فرق بذاریم بین «صف واقعی
    # قفل‌شده» (که یه پدیده‌ی واقعی بازاره) و «داده‌ی ناقص/خراب از API» --
    # هر دو ظاهرشون توی حجم خام یکسانه، ولی معنیشون کاملاً فرق داره.
    buy_side_empty = (best_buy in (None, 0)) and total_buy_vol == 0 and total_buy_cnt == 0
    sell_side_empty = (best_sell in (None, 0)) and total_sell_vol == 0 and total_sell_cnt == 0

    if buy_side_empty and sell_side_empty:
        market_state = "NO_DATA"          # هیچ طرفی داده نداره -- به‌احتمال زیاد خرابی/خالی بودن پاسخ
    elif sell_side_empty and not buy_side_empty:
        market_state = "LOCKED_BUY_QUEUE"  # صف خرید قفل‌شده -- هیچ فروشنده‌ای نیست (پدیده‌ی واقعی بازار)
    elif buy_side_empty and not sell_side_empty:
        market_state = "LOCKED_SELL_QUEUE"  # صف فروش قفل‌شده -- هیچ خریداری نیست
    else:
        market_state = "TWO_SIDED"        # هر دو طرف داده‌ی معتبر دارن -- محاسبه‌ی فشار قابل‌اتکاست

    imbalance = None
    if market_state == "TWO_SIDED" and (total_buy_vol + total_sell_vol) > 0:
        imbalance = round(
            (total_buy_vol - total_sell_vol) / (total_buy_vol + total_sell_vol) * 100, 1
        )

    if market_state in ("LOCKED_BUY_QUEUE", "LOCKED_SELL_QUEUE", "NO_DATA"):
        pressure = market_state
    elif imbalance is None:
        pressure = "UNKNOWN"
    elif imbalance > 20:
        pressure = "BUY_HEAVY"
    elif imbalance < -20:
        pressure = "SELL_HEAVY"
    else:
        pressure = "BALANCED"

    return {
        "time": now,
        "best_buy": best_buy,
        "best_sell": best_sell,
        "spread": spread,
        "spread_pct": spread_pct,
        "total_buy_volume": total_buy_vol,
        "total_sell_volume": total_sell_vol,
        "total_buy_count": total_buy_cnt,
        "total_sell_count": total_sell_cnt,
        "market_state": market_state,
        "imbalance_pct": imbalance,
        "pressure": pressure,
        "levels": rows,
    }


if __name__ == "__main__":
    result = collect_order_book()
    if result:
        print("=" * 50)
        print("عمق سفارش (تابلوخوانی زنده)")
        print("=" * 50)
        print(f"وضعیت بازار: {result['market_state']}")
        print(f"بهترین خرید: {result['best_buy']} | بهترین فروش: {result['best_sell']}")
        print(f"اسپرد: {result['spread']} ({result['spread_pct']}%)")
        print(f"حجم صف خرید (۵ ردیف): {result['total_buy_volume']:,.0f}")
        print(f"حجم صف فروش (۵ ردیف): {result['total_sell_volume']:,.0f}")
        print(f"بایاس: {result['imbalance_pct']}% -> {result['pressure']}")
    else:
        print("داده‌ای دریافت نشد -- پیام‌های بالا رو برای من بفرست تا فیلدها رو اصلاح کنم.")