# -*- coding: utf-8 -*-
"""
AHRAM AI PRO - Greek Engine V2 - نسخه مخصوص بازار ایران
ماژول 1 از 6 - Greek Engine واقعی

این ماژول:
- آپشن‌های آمریکایی بورس ایران را با درخت دوجمله‌ای قیمت‌گذاری می‌کند (نه فقط اروپایی Black-Scholes)
- Greeks را به صورت عددی و پایدار برای حالت آمریکایی حساب می‌کند
- داده‌های واقعی بازار ایران (Bid/Ask, OI, Volume, Spread, نقدشوندگی) را ترکیب می‌کند
- خروجی کامل برای هر قرارداد می‌دهد (همان فرمتی که کاربر خواست)

فرق با نسخه قبلی:
- قبلی: فقط Black-Scholes اروپایی + Advanced Greeks عددی ساده
- جدید: binomial آمریکایی + Greeks عددی آمریکایی + داده‌های تابلو + امتیازدهی + ریسک
"""

import math
import sqlite3
import os
from datetime import datetime

try:
    import config
    RISK_FREE = getattr(config, "RISK_FREE_RATE", 0.30)  # برای ایران حدود 30% - از config می‌خونه
except:
    RISK_FREE = 0.30

# ==================== ریاضیات پایه ====================

def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def bs_price(S, K, T, r, sigma, option_type="CALL"):
    """قیمت اروپایی Black-Scholes - فقط برای مرجع"""
    if T <= 0 or S <= 0 or K <= 0 or sigma <= 0:
        if option_type == "CALL":
            return max(0.0, S - K)
        else:
            return max(0.0, K - S)
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        if option_type == "CALL":
            return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        else:
            return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    except:
        return 0.0

def binomial_price(S, K, T, r, sigma, option_type="CALL", steps=100):
    """قیمت آمریکایی با درخت دوجمله‌ای - مخصوص بورس ایران (قابل اعمال زودهنگام)"""
    S, K = float(S), float(K)
    if T <= 0:
        return max(0.0, S - K) if option_type == "CALL" else max(0.0, K - S)
    if sigma <= 0:
        sigma = 0.0001
    n = steps
    dt = T / n
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    growth = math.exp(r * dt)
    p = (growth - d) / (u - d)
    p = min(max(p, 0.0), 1.0)
    disc = math.exp(-r * dt)

    # قیمت‌های انتهایی
    prices = [S * (u ** j) * (d ** (n - j)) for j in range(n + 1)]
    if option_type == "CALL":
        values = [max(0.0, px - K) for px in prices]
    else:
        values = [max(0.0, K - px) for px in prices]

    # برگشت به عقب با چک اعمال زودهنگام
    for i in range(n - 1, -1, -1):
        next_values = values
        values = []
        for j in range(i + 1):
            continuation = disc * (p * next_values[j + 1] + (1 - p) * next_values[j])
            spot = S * (u ** j) * (d ** (i - j))
            exercise = max(0.0, spot - K) if option_type == "CALL" else max(0.0, K - spot)
            values.append(max(continuation, exercise))
    return values[0]

def implied_volatility(market_price, S, K, T, r, option_type="CALL", verbose=False):
    """استخراج IV با Newton + Bisection - نسخه مقاوم"""
    if market_price <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    intrinsic = max(0, S - K) if option_type == "CALL" else max(0, K - S)
    if market_price < intrinsic * 0.90:
        if verbose:
            print(f"[IV] قیمت بازار {market_price} کمتر از ذاتی {intrinsic} -> IV=None")
        return None

    # Newton
    sigma = 0.5
    best_sigma = sigma
    best_diff = abs(market_price)
    for _ in range(80):
        price = binomial_price(S, K, T, r, sigma, option_type, steps=80)
        diff = price - market_price
        if abs(diff) < abs(best_diff):
            best_diff = abs(diff)
            best_sigma = sigma
        if abs(diff) < 0.5:
            return sigma
        # Vega عددی
        bump = 0.01
        price_up = binomial_price(S, K, T, r, sigma + bump, option_type, steps=80)
        vega = (price_up - price) / bump
        if abs(vega) < 1e-8:
            break
        sigma = sigma - diff / vega
        sigma = min(max(sigma, 0.05), 4.0)

    # Bisection fallback
    lo, hi = 0.05, 4.0
    for _ in range(50):
        mid = (lo + hi) / 2
        price = binomial_price(S, K, T, r, mid, option_type, steps=80)
        if abs(price - market_price) < 0.5:
            return mid
        if price > market_price:
            hi = mid
        else:
            lo = mid
    if best_diff < market_price * 0.15:
        return best_sigma
    return None

# ==================== Greeks آمریکایی (عددی) ====================

def calculate_greeks_american(S, K, T, r, sigma, option_type="CALL"):
    """
    محاسبه Greeks برای آپشن آمریکایی با تفاضل محدود
    خروجی: Delta, Gamma, Theta (روزانه), Vega (برای 1% IV), Rho (برای 1% نرخ بهره)
    """
    if T <= 0 or S <= 0 or K <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0, "available": False}

    # قیمت پایه
    base_price = binomial_price(S, K, T, r, sigma, option_type, steps=100)

    # Delta: تغییر قیمت سهم 1%
    dS = S * 0.01
    price_up = binomial_price(S + dS, K, T, r, sigma, option_type, steps=100)
    price_down = binomial_price(S - dS, K, T, r, sigma, option_type, steps=80)
    delta = (price_up - price_down) / (2 * dS)
    if option_type == "PUT":
        # برای PUT دلتا منفی است، ولی فرمول بالا خودش منفی میده
        pass

    # Gamma: تغییر Delta
    price_up2 = binomial_price(S + dS, K, T, r, sigma, option_type, steps=80)
    price_mid = base_price
    price_down2 = binomial_price(S - dS, K, T, r, sigma, option_type, steps=80)
    gamma = (price_up2 - 2 * price_mid + price_down2) / (dS * dS)
    # Gamma همیشه باید >=0 باشه (هم Call هم Put) - اگر به خاطر اعمال زودهنگام آمریکایی منفی شد، صفرش می‌کنیم
    # این باگ تو تست طهرم8034 دیده شد: Gamma -0.000108 داده بود
    gamma = max(gamma, 0.0)

    # Theta: گذشت یک روز
    one_day = 1.0 / 365.0
    T_tomorrow = max(T - one_day, 0.0001)
    price_tomorrow = binomial_price(S, K, T_tomorrow, r, sigma, option_type, steps=80)
    theta_daily = price_tomorrow - base_price  # معمولا منفی

    # Vega: تغییر 1% IV - همیشه >=0
    bump_iv = 0.01
    price_iv_up = binomial_price(S, K, T, r, sigma + bump_iv, option_type, steps=80)
    price_iv_down = binomial_price(S, K, T, r, max(sigma - bump_iv, 0.01), option_type, steps=80)
    vega_1pct = (price_iv_up - price_iv_down) / 2.0  # تغییر قیمت برای 1% تغییر IV
    vega_1pct = max(vega_1pct, 0.0)

    # Rho: تغییر 1% نرخ بهره
    bump_r = 0.01
    price_r_up = binomial_price(S, K, T, r + bump_r, sigma, option_type, steps=80)
    price_r_down = binomial_price(S, K, T, r - bump_r, sigma, option_type, steps=80)
    rho_1pct = (price_r_up - price_r_down) / 2.0

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta_daily": round(theta_daily, 3),
        "vega_1pct": round(vega_1pct, 3),
        "rho_1pct": round(rho_1pct, 3),
        "price_american": round(base_price, 2),
        "available": True
    }

def calculate_advanced_greeks_american(S, K, T, r, sigma, option_type="CALL"):
    """Charm, Color, Vanna, Volga برای حالت آمریکایی"""
    if T < 2/365 or S <= 0 or K <= 0 or sigma <= 0:
        return {"available": False, "risk_level": "UNKNOWN", "reasons": ["داده کافی نیست"]}

    base = calculate_greeks_american(S, K, T, r, sigma, option_type)
    if not base.get("available"):
        return {"available": False, "risk_level": "UNKNOWN", "reasons": ["Greeks پایه در دسترس نیست"]}

    one_day = 1.0 / 365.0
    # Charm: Delta فردا - Delta امروز
    greeks_tomorrow = calculate_greeks_american(S, K, max(T - one_day, 0.001), r, sigma, option_type)
    charm = greeks_tomorrow["delta"] - base["delta"]

    # Color: Gamma فردا - Gamma امروز
    color = greeks_tomorrow["gamma"] - base["gamma"]
    color_pct = (color / base["gamma"] * 100) if base["gamma"] != 0 else 0.0

    # Vanna: تغییر Delta با 1% تغییر IV
    bump = 0.01
    greeks_iv_up = calculate_greeks_american(S, K, T, r, sigma + bump, option_type)
    greeks_iv_down = calculate_greeks_american(S, K, T, r, max(sigma - bump, 0.01), option_type)
    vanna = (greeks_iv_up["delta"] - greeks_iv_down["delta"]) / 2.0

    # Volga: تغییر Vega با 1% تغییر IV
    volga = (greeks_iv_up["vega_1pct"] - greeks_iv_down["vega_1pct"]) / 2.0

    # ارزیابی ریسک
    reasons = []
    points = 0
    dte = int(T * 365)
    if dte <= 10:
        points += 1
        reasons.append("سررسید نزدیک (<=10 روز)")
    if abs(charm) >= 0.02:
        points += 1
        reasons.append(f"Charm بالا {charm:.4f}: Delta با گذر زمان تغییر محسوسی دارد")
    if abs(color_pct) >= 20:
        points += 1
        reasons.append(f"Color بالا {color_pct:.1f}%: Gamma ناپایدار است")
    if abs(vanna) >= 0.005:
        points += 1
        reasons.append(f"Vanna بالا {vanna:.5f}: Delta به IV حساس است")
    if abs(volga) >= max(0.02, abs(base["vega_1pct"]) * 0.20):
        points += 1
        reasons.append(f"Volga بالا {volga:.4f}: Vega با IV تغییر می‌کند")

    level = "LOW" if points <= 1 else ("MEDIUM" if points <= 3 else "HIGH")
    if not reasons:
        reasons = ["ریسک Greeks پیشرفته در محدوده عادی"]

    return {
        "available": True,
        "risk_level": level,
        "risk_points": points,
        "charm_1d": round(charm, 5),
        "color_1d": round(color, 8),
        "color_pct_1d": round(color_pct, 1),
        "vanna_1pct": round(vanna, 5),
        "volga_1pct": round(volga, 5),
        "dte": dte,
        "reasons": reasons
    }

# ==================== داده بازار ایران ====================

def get_option_market_data(db_path, option_symbol):
    """خواندن OI, Volume, Bid/Ask, Spread از دیتابیس‌های AHRAM"""
    result = {"oi": None, "volume": None, "bid": None, "ask": None, "spread_pct": None, "last_price": None}
    if not os.path.exists(db_path):
        return result
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        # آخرین رکورد آپشن
        cur.execute("SELECT option_price, volume, open_interest FROM options WHERE symbol=? ORDER BY id DESC LIMIT 1", (option_symbol,))
        row = cur.fetchone()
        if row:
            result["last_price"] = row[0]
            result["volume"] = row[1]
            result["oi"] = row[2]
        # Bid/Ask از order_book اگر وجود داشته باشه
        try:
            cur.execute("SELECT bid_price, ask_price FROM option_order_book WHERE symbol=? ORDER BY id DESC LIMIT 1", (option_symbol,))
            row = cur.fetchone()
            if row and row[0] and row[1]:
                result["bid"] = float(row[0])
                result["ask"] = float(row[1])
                if result["ask"] > 0:
                    result["spread_pct"] = round((result["ask"] - result["bid"]) / result["ask"] * 100, 2)
        except:
            # اگر جدول option_order_book نبود، از bid/ask خود options استفاده کن (اگر باشه)
            try:
                cur.execute("SELECT bid_price, ask_price FROM options WHERE symbol=? ORDER BY id DESC LIMIT 1", (option_symbol,))
                row = cur.fetchone()
                if row and row[0] and row[1]:
                    result["bid"] = float(row[0])
                    result["ask"] = float(row[1])
                    if result["ask"] > 0:
                        result["spread_pct"] = round((result["ask"] - result["bid"]) / result["ask"] * 100, 2)
            except:
                pass
        conn.close()
    except Exception as e:
        print(f"[WARN] market data {option_symbol}: {e}")
    return result

def assess_liquidity(volume, oi, spread_pct):
    """ارزیابی نقدشوندگی مخصوص ایران"""
    score = 0
    reasons = []
    if volume is None or volume < 100:
        reasons.append("حجم بسیار پایین")
    elif volume < 500:
        score += 1
        reasons.append("حجم پایین")
    elif volume >= 2000:
        score += 3
    else:
        score += 2

    if oi is None or oi < 500:
        reasons.append("OI بسیار پایین")
    elif oi < 1000:
        score += 1
        reasons.append("OI پایین")
    elif oi >= 5000:
        score += 3
    else:
        score += 2

    if spread_pct is None:
        reasons.append("اسپرد نامشخص")
    elif spread_pct > 20:
        score -= 2
        reasons.append(f"اسپرد بزرگ {spread_pct}%")
    elif spread_pct > 10:
        score += 1
        reasons.append(f"اسپرد متوسط {spread_pct}%")
    else:
        score += 2

    if score >= 5:
        level = "Good"
    elif score >= 3:
        level = "Medium"
    else:
        level = "Poor"

    return {"level": level, "score": score, "reasons": reasons}

# ==================== موتور اصلی - خروجی کامل ====================

def analyze_contract(symbol, stock_price, strike_price, option_price, days_to_expire, option_type, db_path=None, volume=None, oi=None):
    """
    تحلیل کامل یک قرارداد - خروجی دقیقا همون فرمتی که کاربر خواست
    """
    S = float(stock_price)
    K = float(strike_price)
    market_price = float(option_price)
    T = max(int(days_to_expire), 0) / 365.0
    r = RISK_FREE

    # IV
    iv = implied_volatility(market_price, S, K, T, r, option_type)
    sigma_for_greeks = iv if iv and iv > 0 else 0.5  # اگر IV نبود از 50% استفاده کن

    # Greeks آمریکایی
    greeks = calculate_greeks_american(S, K, T, r, sigma_for_greeks, option_type)
    adv = calculate_advanced_greeks_american(S, K, T, r, sigma_for_greeks, option_type)

    # داده بازار
    market_data = {}
    if db_path:
        market_data = get_option_market_data(db_path, symbol)
        if volume is None:
            volume = market_data.get("volume")
        if oi is None:
            oi = market_data.get("oi")
    else:
        market_data = {"bid": None, "ask": None, "spread_pct": None}

    # اگر volume/oi از ورودی نیومده بود
    if volume is None:
        volume = market_data.get("volume")
    if oi is None:
        oi = market_data.get("oi")

    liquidity = assess_liquidity(volume, oi, market_data.get("spread_pct"))

    # امتیازدهی ساده اولیه (برای ماژول 5 بعدا کامل میشه)
    call_score = 0
    score_reasons = []
    if greeks.get("delta"):
        ad = abs(greeks["delta"])
        if 0.45 <= ad <= 0.65:
            call_score += 25
            score_reasons.append(f"Delta مناسب {ad} +25")
        elif 0.35 <= ad < 0.45 or 0.65 < ad <= 0.75:
            call_score += 15
            score_reasons.append(f"Delta قابل قبول {ad} +15")

    if greeks.get("theta_daily"):
        theta_burn = abs(greeks["theta_daily"]) / market_price * 100 if market_price > 0 else 0
        if theta_burn < 1.0:
            call_score += 10
            score_reasons.append(f"Theta کم {theta_burn:.2f}% +10")
        elif theta_burn > 3.0:
            call_score -= 10
            score_reasons.append(f"Theta بالا {theta_burn:.2f}% -10")

    if liquidity["level"] == "Good":
        call_score += 15
        score_reasons.append("نقدشوندگی خوب +15")
    elif liquidity["level"] == "Poor":
        call_score -= 15
        score_reasons.append("نقدشوندگی ضعیف -15")

    if market_data.get("spread_pct") is not None and market_data["spread_pct"] <= 10:
        call_score += 7
        score_reasons.append(f"اسپرد کم {market_data['spread_pct']}% +7")

    # ریسک‌ها
    risks = []
    if iv and iv > 0.8:
        risks.append(f"IV بالا {iv:.2%} - ریسک IV Crush")
    if greeks.get("theta_daily") and abs(greeks["theta_daily"]) > market_price * 0.02:
        risks.append(f"Theta بالا {greeks['theta_daily']} - فرسایش سریع")
    if market_data.get("spread_pct") and market_data["spread_pct"] > 15:
        risks.append(f"اسپرد بزرگ {market_data['spread_pct']}%")
    if adv.get("risk_level") == "HIGH":
        risks.append(f"Advanced Greeks ریسک HIGH: {', '.join(adv.get('reasons', [])[:2])}")

    return {
        "symbol": symbol,
        "stock_price": S,
        "strike_price": K,
        "option_price": market_price,
        "days_to_expire": int(days_to_expire),
        "option_type": option_type,
        "iv": round(iv, 4) if iv else None,
        "iv_percent": round(iv * 100, 2) if iv else None,
        "greeks": greeks,
        "advanced_greeks": adv,
        "market_data": {
            "volume": volume,
            "open_interest": oi,
            "bid": market_data.get("bid"),
            "ask": market_data.get("ask"),
            "spread_pct": market_data.get("spread_pct"),
            "last_price": market_data.get("last_price"),
        },
        "liquidity": liquidity,
        "score": max(0, min(100, call_score)),
        "score_reasons": score_reasons,
        "risks": risks,
        "risk_free": r,
        "pricing_model": "Binomial American (100 steps)",
    }

def print_contract_report(analysis):
    """چاپ گزارش کامل یک قرارداد - دقیقا فرمتی که کاربر خواست"""
    print("="*60)
    print(f"OPTION: {analysis['symbol']}")
    print("-"*60)
    print(f"Price: {analysis['option_price']} | Underlying: {analysis['stock_price']} | Strike: {analysis['strike_price']} | Days: {analysis['days_to_expire']} | Type: {analysis['option_type']}")
    print()
    print(f"IV: {analysis['iv_percent']}% | IV raw: {analysis['iv']}")
    g = analysis['greeks']
    print(f"Delta: {g.get('delta')} | Gamma: {g.get('gamma')} | Theta (daily): {g.get('theta_daily')} | Vega (1%): {g.get('vega_1pct')} | Rho (1%): {g.get('rho_1pct')}")
    print(f"American Price (model): {g.get('price_american')}")
    adv = analysis['advanced_greeks']
    if adv.get("available"):
        print(f"Charm (1d): {adv.get('charm_1d')} | Color (1d): {adv.get('color_1d')} ({adv.get('color_pct_1d')}%) | Vanna (1%): {adv.get('vanna_1pct')} | Volga (1%): {adv.get('volga_1pct')} | Risk: {adv.get('risk_level')}")
    else:
        print(f"Advanced Greeks: {adv.get('reasons')}")
    print()
    md = analysis['market_data']
    print(f"OI: {md.get('open_interest')} | Volume: {md.get('volume')} | Bid: {md.get('bid')} | Ask: {md.get('ask')} | Spread: {md.get('spread_pct')}%")
    liq = analysis['liquidity']
    print(f"Liquidity: {liq.get('level')} (score {liq.get('score')}) - {', '.join(liq.get('reasons')[:3])}")
    print()
    print(f"CALL SCORE: {analysis['score']}/100")
    for r in analysis['score_reasons']:
        print(f"  + {r}")
    print()
    print("RISK:")
    if analysis['risks']:
        for r in analysis['risks']:
            print(f"  - {r}")
    else:
        print("  - ریسک خاصی شناسایی نشد")
    print("="*60)

# ==================== تست ====================

if __name__ == "__main__":
    # تست با داده‌های واقعی اهرم از لاگ قبلی
    print("\n--- تست 1: اهرم ضهرم6049 از لاگ ---")
    test1 = analyze_contract(
        symbol="ضهرم6049",
        stock_price=56762.0,
        strike_price=62000,
        option_price=1804,
        days_to_expire=20,
        option_type="CALL",
        volume=5640,
        oi=10000
    )
    print_contract_report(test1)

    print("\n--- تست 2: وبملت ضملت6022 ---")
    test2 = analyze_contract(
        symbol="ضملت6022",
        stock_price=1489.0,
        strike_price=1354,
        option_price=133,
        days_to_expire=13,
        option_type="CALL",
        volume=10575,
        oi=8000
    )
    print_contract_report(test2)

    print("\n--- تست 3: خواندن از دیتابیس واقعی اگر وجود داشت ---")
    for db in ["ahram_v2.db", "webmellt.db", "shasta.db"]:
        if os.path.exists(db):
            print(f"\nدیتابیس پیدا شد: {db}")
            try:
                conn = sqlite3.connect(db)
                cur = conn.cursor()
                cur.execute("SELECT symbol, stock_price, strike_price, option_price, days_to_expire, option_type, volume, open_interest FROM options ORDER BY id DESC LIMIT 2")
                rows = cur.fetchall()
                for row in rows:
                    sym, s_price, k_price, o_price, dte, o_type, vol, oi_val = row
                    if s_price and k_price and o_price and dte:
                        print(f"\nتحلیل از DB: {sym}")
                        a = analyze_contract(sym, s_price, k_price, o_price, dte, o_type, db_path=db, volume=vol, oi=oi_val)
                        print_contract_report(a)
                conn.close()
            except Exception as e:
                print(f"خطا خواندن {db}: {e}")
            break
