"""
AHRAM AI PRO - پل مستقل داده برای داشبورد استراتژی

این فایل فقط دیتابیس‌ها را می‌خواند و یک JSON مستقل تولید می‌کند.
هیچ فایل اصلی، سیگنال، امتیاز، پوزیشن یا محاسبه‌ای را تغییر نمی‌دهد.
"""

import argparse
import json
import os
import sqlite3
from datetime import datetime

DATABASES = {
    "اهرم": "ahram_v2.db",
    "وبملت": "webmellt.db",
    "شستا": "shasta.db",
}

OUTPUT_FILE = "ahram_strategy_data.json"


def safe_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def row_dict(cursor, row):
    return {description[0]: value for description, value in zip(cursor.description, row)}


def get_latest_price(connection):
    try:
        row = connection.execute(
            """
            SELECT id, time, last_price, closing_price, volume, trades
            FROM prices
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return {
        "id": row[0],
        "time": row[1],
        "last_price": safe_float(row[2]),
        "closing_price": safe_float(row[3]),
        "volume": safe_float(row[4]),
        "trades": safe_float(row[5]),
    }


def get_latest_signal(connection):
    try:
        row = connection.execute(
            """
            SELECT id, time, symbol, signal_type, composite_score,
                   option_symbol, option_price, strike_price,
                   outcome, outcome_pct, details
            FROM signal_history
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    if not row:
        return None
    return {
        "id": row[0],
        "time": row[1],
        "symbol": row[2],
        "signal_type": row[3],
        "score": safe_float(row[4]),
        "option_symbol": row[5],
        "option_price": safe_float(row[6]),
        "strike_price": safe_float(row[7]),
        "outcome": row[8],
        "outcome_pct": safe_float(row[9]),
        "details": row[10],
    }


def get_latest_options(connection):
    try:
        latest = connection.execute("SELECT MAX(id) FROM options").fetchone()[0]
    except sqlite3.OperationalError:
        return None, []
    if latest is None:
        return None, []

    latest_time = connection.execute(
        "SELECT time FROM options WHERE id=?", (latest,)
    ).fetchone()[0]

    # جداول options در دیتابیس‌ها کاملاً یکسان نیستند؛ فقط ستون‌های موجود خوانده می‌شوند.
    available = {
        row[1] for row in connection.execute("PRAGMA table_info(options)").fetchall()
    }
    wanted = [
        "id", "time", "symbol", "option_type", "stock_price", "option_price",
        "strike_price", "expire_date", "days_to_expire", "volume",
        "value_traded", "open_interest", "implied_volatility", "delta",
        "gamma", "theta", "vega",
    ]
    selected = [column for column in wanted if column in available]
    query = "SELECT " + ", ".join(selected) + " FROM options WHERE time=? ORDER BY strike_price, option_type, symbol"
    rows = connection.execute(query, (latest_time,)).fetchall()

    options = []
    for raw in rows:
        item = dict(zip(selected, raw))
        options.append({
            "id": item.get("id"),
            "time": item.get("time"),
            "symbol": item.get("symbol"),
            "option_type": item.get("option_type"),
            "stock_price": safe_float(item.get("stock_price")),
            "option_price": safe_float(item.get("option_price")),
            "strike_price": safe_float(item.get("strike_price")),
            "expire_date": item.get("expire_date"),
            "days_to_expire": item.get("days_to_expire"),
            "volume": safe_float(item.get("volume")),
            "value_traded": safe_float(item.get("value_traded")),
            "open_interest": safe_float(item.get("open_interest")),
            "implied_volatility": safe_float(item.get("implied_volatility")),
            "delta": safe_float(item.get("delta")),
            "gamma": safe_float(item.get("gamma")),
            "theta": safe_float(item.get("theta")),
            "vega": safe_float(item.get("vega")),
        })
    return latest_time, options

def get_latest_max_pain(connection):
    try:
        rows = connection.execute(
            """
            SELECT expiry, stock_price, max_pain_strike,
                   current_distance_pct, data_quality,
                   contracts_count, contracts_with_oi, time
            FROM max_pain_history
            WHERE id IN (
                SELECT MAX(id) FROM max_pain_history GROUP BY expiry
            )
            ORDER BY expiry
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    return [
        {
            "expiry": row[0],
            "stock_price": safe_float(row[1]),
            "max_pain_strike": safe_float(row[2]),
            "distance_pct": safe_float(row[3]),
            "data_quality": row[4],
            "contracts_count": row[5],
            "contracts_with_oi": row[6],
            "time": row[7],
        }
        for row in rows
    ]


def calculate_chain_metrics(options, stock_price):
    """شاخص‌های اکتشافی زنجیره؛ فقط برای ثبت و بررسی، بدون اثر بر سیگنال."""
    calls = [x for x in options if str(x.get("option_type") or "").upper() == "CALL"]
    puts = [x for x in options if str(x.get("option_type") or "").upper() == "PUT"]

    def total(items, field):
        return sum((safe_float(x.get(field)) or 0.0) for x in items)

    call_volume = total(calls, "volume")
    put_volume = total(puts, "volume")
    call_oi = total(calls, "open_interest")
    put_oi = total(puts, "open_interest")
    oi_contracts = sum(1 for x in options if (safe_float(x.get("open_interest")) or 0) > 0)

    nearest_strike = None
    nearest_distance_pct = None
    if stock_price and stock_price > 0:
        strikes = [safe_float(x.get("strike_price")) for x in options]
        strikes = sorted({x for x in strikes if x and x > 0})
        if strikes:
            nearest_strike = min(strikes, key=lambda strike: abs(strike - stock_price))
            nearest_distance_pct = ((nearest_strike - stock_price) / stock_price) * 100.0

    return {
        "available": bool(options),
        "contracts_total": len(options),
        "calls_count": len(calls),
        "puts_count": len(puts),
        "contracts_with_oi": oi_contracts,
        "call_volume": call_volume,
        "put_volume": put_volume,
        "call_put_volume_ratio": (call_volume / put_volume) if put_volume > 0 else None,
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
        "call_put_oi_ratio": (call_oi / put_oi) if put_oi > 0 else None,
        "nearest_strike": nearest_strike,
        "nearest_strike_distance_pct": nearest_distance_pct,
        "quality": "HIGH" if oi_contracts >= 10 and len(options) >= 20 else ("MEDIUM" if oi_contracts >= 5 else "LOW"),
        "role": "exploratory_only",
    }


def build_symbol_data(name, db_path):
    if not os.path.exists(db_path):
        return {"database": db_path, "available": False, "reason": "file not found"}

    connection = sqlite3.connect(db_path)
    try:
        # هر بخش جدا try میشه تا اگه یک جدول برای یک نماد وجود نداشت، کل اسکریپت برای همه نمادها کرش نکنه
        try:
            latest_options_time, options = get_latest_options(connection)
        except Exception as e:
            latest_options_time, options = None, []
            print(f"[WARN] {name}: options خوانده نشد - {e}")

        try:
            price = get_latest_price(connection)
        except Exception as e:
            price = None
            print(f"[WARN] {name}: prices خوانده نشد - {e}")

        try:
            signal = get_latest_signal(connection)
        except Exception as e:
            signal = None
            print(f"[WARN] {name}: signal_history خوانده نشد - {e}")

        try:
            max_pain = get_latest_max_pain(connection)
        except Exception as e:
            max_pain = []
            print(f"[WARN] {name}: max_pain خوانده نشد - {e}")

        stock_price = None
        if price:
            stock_price = (price or {}).get("last_price") or (price or {}).get("closing_price")

        try:
            chain_metrics = calculate_chain_metrics(options, stock_price)
        except Exception as e:
            chain_metrics = {"available": False, "error": str(e)}

        return {
            "name": name,
            "database": db_path,
            "available": True,
            "price": price,
            "signal": signal,
            "options_snapshot_time": latest_options_time,
            "options": options,
            "chain_metrics": chain_metrics,
            "max_pain": max_pain,
        }
    except Exception as e:
        print(f"[ERROR] {name}: خطای کلی در build_symbol_data - {e}")
        return {"database": db_path, "available": False, "reason": str(e)}
    finally:
        try:
            connection.close()
        except:
            pass


def build_payload():
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "AHRAM AI PRO SQLite databases",
        "read_only": True,
        "signals_modified": False,
        "symbols": {
            name: build_symbol_data(name, db_path)
            for name, db_path in DATABASES.items()
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Export read-only AHRAM data for the strategy dashboard"
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_FILE,
        help="نام فایل JSON خروجی",
    )
    args = parser.parse_args()

    payload = build_payload()
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)

    print("✅ پل مستقل اجرا شد")
    print("OUTPUT:", args.output)
    print("READ ONLY: True")
    for name, data in payload["symbols"].items():
        option_count = len(data.get("options", [])) if data.get("available") else 0
        max_pain_count = len(data.get("max_pain", [])) if data.get("available") else 0
        print(f"{name}: options={option_count} | max_pain={max_pain_count}")


if __name__ == "__main__":
    main()
