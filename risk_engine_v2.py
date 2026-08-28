# -*- coding: utf-8 -*-
"""
AHRAM AI PRO - Risk Engine V2 - ماژول 3 از 6
نسخه مخصوص بازار ایران

این ماژول:
- ریسک‌های مختلف هر قرارداد آپشن را می‌سنجد
- Theta Risk, IV Crush Risk, Gamma Risk, Liquidity Risk, Spread Risk, Expiry Risk
- امتیاز ریسک کلی 0-100 می‌دهد (0 = کم‌ریسک، 100 = پرریسک)
- هشدارهای قابل فهم برای معامله‌گر ایرانی

ورودی: خروجی greek_engine_v2 + iv_engine_v2 + داده بازار
خروجی: ریسک‌ها + امتیاز ریسک + توصیه
"""

import math
import os

# ==================== ریسک‌ها ====================

def assess_theta_risk(theta_daily, option_price, days_to_expire):
    """
    ریسک فرسایش زمانی
    Theta منفی یعنی هر روز چقدر از ارزش آپشن کم میشه
    """
    if not theta_daily or not option_price or option_price <= 0:
        return {"level": "UNKNOWN", "score": 0, "details": "داده کافی نیست"}

    theta_pct = abs(theta_daily) / option_price * 100  # درصد فرسایش روزانه
    dte = int(days_to_expire)

    if dte <= 5:
        # نزدیک سررسید، Theta خیلی خطرناکه
        if theta_pct > 5:
            level = "EXTREME"
            score = 90
        elif theta_pct > 2:
            level = "HIGH"
            score = 70
        else:
            level = "MEDIUM"
            score = 50
    elif dte <= 15:
        if theta_pct > 3:
            level = "HIGH"
            score = 70
        elif theta_pct > 1:
            level = "MEDIUM"
            score = 40
        else:
            level = "LOW"
            score = 20
    else:
        if theta_pct > 2:
            level = "MEDIUM"
            score = 40
        elif theta_pct > 0.5:
            level = "LOW"
            score = 20
        else:
            level = "VERY LOW"
            score = 10

    return {
        "level": level,
        "score": score,
        "theta_pct_daily": round(theta_pct, 2),
        "theta_daily": theta_daily,
        "details": f"Theta {theta_daily} ({theta_pct:.2f}% روزانه) - DTE {dte} روز - ریسک {level}"
    }

def assess_iv_crush_risk(iv, iv_rank, iv_percentile, historical_vol=None):
    """
    ریسک IV Crush - وقتی IV خیلی بالاست و بعد از رویداد می‌ریزه
    """
    if not iv or iv <= 0:
        return {"level": "UNKNOWN", "score": 0, "details": "IV موجود نیست"}

    score = 0
    level = "LOW"
    reasons = []

    # IV مطلق بالا
    if iv > 1.0:
        score += 40
        reasons.append(f"IV خیلی بالا {iv:.1%}")
        level = "HIGH"
    elif iv > 0.7:
        score += 25
        reasons.append(f"IV بالا {iv:.1%}")
        level = "MEDIUM"

    # IV Rank بالا
    if iv_rank is not None:
        if iv_rank >= 80:
            score += 35
            reasons.append(f"IV Rank بالا {iv_rank}% - پرمیوم گرون")
            level = "HIGH" if level != "HIGH" else "EXTREME" if score > 70 else "HIGH"
        elif iv_rank >= 60:
            score += 15
            reasons.append(f"IV Rank متوسط بالا {iv_rank}%")

    # IV/HV ratio
    if historical_vol and historical_vol > 0:
        ratio = iv / historical_vol
        if ratio > 2.0:
            score += 30
            reasons.append(f"IV/HV ratio {ratio:.2f}x - حباب")
            level = "HIGH"
        elif ratio > 1.5:
            score += 15
            reasons.append(f"IV/HV ratio {ratio:.2f}x - Elevated")

    if not reasons:
        reasons = ["IV در محدوده نرمال"]

    if score >= 70:
        level = "EXTREME" if score >= 85 else "HIGH"
    elif score >= 40:
        level = "MEDIUM"
    elif score >= 20:
        level = "LOW"
    else:
        level = "VERY LOW"

    return {
        "level": level,
        "score": min(100, score),
        "iv": iv,
        "iv_rank": iv_rank,
        "iv_hv_ratio": round(iv / historical_vol, 2) if historical_vol else None,
        "details": "; ".join(reasons)
    }

def assess_gamma_risk(gamma, delta, stock_price, option_type="CALL"):
    """
    ریسک Gamma - شتاب تغییر Delta
    Gamma بالا = Delta سریع تغییر می‌کنه = نیاز به هج مداوم
    """
    if gamma is None or delta is None:
        return {"level": "UNKNOWN", "score": 0, "details": "Greeks موجود نیست"}

    ad = abs(delta)
    # Gamma معمولا برای ATM بالاست
    # برای بازار ایران، Gamma بالا در سهام با نوسان زیاد ریسک داره

    if ad < 0.2 or ad > 0.8:
        # Deep OTM یا Deep ITM - Gamma کم
        level = "LOW"
        score = 15
        details = f"Gamma {gamma} کم چون Delta {delta} دور از ATM"
    elif 0.4 <= ad <= 0.6:
        # ATM - Gamma بالا
        if gamma > 0.01:
            level = "HIGH"
            score = 70
            details = f"Gamma بالا {gamma} نزدیک ATM - Delta سریع تغییر می‌کنه"
        elif gamma > 0.001:
            level = "MEDIUM"
            score = 40
            details = f"Gamma متوسط {gamma} نزدیک ATM"
        else:
            level = "LOW"
            score = 20
            details = f"Gamma {gamma} نزدیک ATM"
    else:
        level = "MEDIUM"
        score = 35
        details = f"Gamma {gamma} با Delta {delta}"

    return {
        "level": level,
        "score": score,
        "gamma": gamma,
        "delta": delta,
        "details": details
    }

def assess_liquidity_risk(volume, open_interest, spread_pct, bid=None, ask=None):
    """
    ریسک نقدشوندگی - مخصوص بازار ایران (خیلی مهم)
    """
    score = 0
    level = "LOW"
    reasons = []

    if volume is None or volume < 10:
        score += 40
        reasons.append(f"حجم بسیار پایین {volume}")
        level = "EXTREME"
    elif volume < 100:
        score += 30
        reasons.append(f"حجم پایین {volume}")
        level = "HIGH"
    elif volume < 500:
        score += 15
        reasons.append(f"حجم متوسط پایین {volume}")
        level = "MEDIUM"
    else:
        reasons.append(f"حجم خوب {volume}")

    if open_interest is None or open_interest < 100:
        score += 35
        reasons.append(f"OI بسیار پایین {open_interest}")
        level = "EXTREME" if level != "EXTREME" else level
    elif open_interest < 1000:
        score += 20
        reasons.append(f"OI پایین {open_interest}")
        if level == "LOW":
            level = "MEDIUM"
    else:
        reasons.append(f"OI خوب {open_interest}")

    if spread_pct is None:
        score += 15
        reasons.append("اسپرد نامشخص - ریسک")
        if level == "LOW":
            level = "MEDIUM"
    elif spread_pct > 20:
        score += 35
        reasons.append(f"اسپرد بزرگ {spread_pct}% - هزینه زیاد")
        level = "EXTREME"
    elif spread_pct > 10:
        score += 20
        reasons.append(f"اسپرد متوسط {spread_pct}%")
        level = "HIGH" if level in ["LOW", "MEDIUM"] else level
    elif spread_pct > 5:
        score += 5
        reasons.append(f"اسپرد قابل قبول {spread_pct}%")
    else:
        reasons.append(f"اسپرد کم {spread_pct}% - خوب")

    if bid is None or ask is None:
        score += 10
        reasons.append("Bid/Ask موجود نیست")

    if score >= 70:
        level = "EXTREME"
    elif score >= 45:
        level = "HIGH"
    elif score >= 25:
        level = "MEDIUM"
    elif score >= 10:
        level = "LOW"
    else:
        level = "VERY LOW"

    return {
        "level": level,
        "score": min(100, score),
        "volume": volume,
        "open_interest": open_interest,
        "spread_pct": spread_pct,
        "details": "; ".join(reasons)
    }

def assess_expiry_risk(days_to_expire, theta_daily, option_price):
    """
    ریسک سررسید - نزدیک سررسید ریسک Theta و Gamma زیاد میشه
    """
    dte = int(days_to_expire)
    if dte <= 3:
        level = "EXTREME"
        score = 90
        details = f"سررسید خیلی نزدیک {dte} روز - Theta و Gamma انفجاری"
    elif dte <= 7:
        level = "HIGH"
        score = 70
        details = f"سررسید نزدیک {dte} روز - ریسک بالا"
    elif dte <= 15:
        level = "MEDIUM"
        score = 45
        details = f"سررسید {dte} روز - متوسط"
    elif dte <= 30:
        level = "LOW"
        score = 25
        details = f"سررسید {dte} روز - قابل قبول"
    else:
        level = "VERY LOW"
        score = 10
        details = f"سررسید دور {dte} روز - ریسک کم"

    # اگر Theta خیلی بالا باشه، حتی با DTE دور هم ریسک بالاست
    if theta_daily and option_price and option_price > 0:
        theta_pct = abs(theta_daily) / option_price * 100
        if theta_pct > 5 and dte > 7:
            score += 20
            details += f" + Theta بالا {theta_pct:.1f}%"

    return {
        "level": level,
        "score": min(100, score),
        "dte": dte,
        "details": details
    }

def assess_advanced_greeks_risk(advanced_greeks):
    """
    ریسک Greeks پیشرفته: Charm, Color, Vanna, Volga
    """
    if not advanced_greeks or not advanced_greeks.get("available"):
        return {"level": "UNKNOWN", "score": 0, "details": "Advanced Greeks موجود نیست"}

    level = advanced_greeks.get("risk_level", "UNKNOWN")
    points = advanced_greeks.get("risk_points", 0)

    if level == "HIGH":
        score = 70
    elif level == "MEDIUM":
        score = 40
    elif level == "LOW":
        score = 15
    else:
        score = 0

    return {
        "level": level,
        "score": score,
        "risk_points": points,
        "charm": advanced_greeks.get("charm_1d"),
        "color": advanced_greeks.get("color_1d"),
        "vanna": advanced_greeks.get("vanna_1pct"),
        "volga": advanced_greeks.get("volga_1pct"),
        "details": "; ".join(advanced_greeks.get("reasons", []))
    }

# ==================== موتور اصلی ====================

def analyze_risk(greek_analysis, iv_analysis=None):
    """
    تحلیل کامل ریسک یک قرارداد
    greek_analysis: خروجی greek_engine_v2.analyze_contract
    iv_analysis: خروجی iv_engine_v2.analyze_iv (اختیاری)
    """
    symbol = greek_analysis.get("symbol", "UNKNOWN")
    greeks = greek_analysis.get("greeks", {})
    adv = greek_analysis.get("advanced_greeks", {})
    md = greek_analysis.get("market_data", {})
    stock_price = greek_analysis.get("stock_price")
    option_price = greek_analysis.get("option_price")
    dte = greek_analysis.get("days_to_expire", 30)
    option_type = greek_analysis.get("option_type", "CALL")
    iv = greek_analysis.get("iv")

    # داده‌های IV از iv_analysis اگر موجود باشه
    iv_rank = None
    iv_percentile = None
    hv = None
    if iv_analysis:
        rank_data = iv_analysis.get("iv_rank", {})
        iv_rank = rank_data.get("iv_rank")
        iv_percentile = rank_data.get("iv_percentile")

    # محاسبه تک‌تک ریسک‌ها
    theta_risk = assess_theta_risk(greeks.get("theta_daily"), option_price, dte)
    iv_risk = assess_iv_crush_risk(iv, iv_rank, iv_percentile, hv)
    gamma_risk = assess_gamma_risk(greeks.get("gamma"), greeks.get("delta"), stock_price, option_type)
    liq_risk = assess_liquidity_risk(md.get("volume"), md.get("open_interest"), md.get("spread_pct"), md.get("bid"), md.get("ask"))
    expiry_risk = assess_expiry_risk(dte, greeks.get("theta_daily"), option_price)
    adv_risk = assess_advanced_greeks_risk(adv)

    # امتیاز کلی ریسک (میانگین وزنی)
    # وزن‌ها برای بازار ایران: نقدشوندگی و اسپرد خیلی مهم‌تر از بقیه
    weights = {
        "theta": 0.20,
        "iv": 0.20,
        "gamma": 0.15,
        "liquidity": 0.25,  # مهم‌ترین برای ایران
        "expiry": 0.10,
        "advanced": 0.10
    }

    total_score = (
        theta_risk["score"] * weights["theta"] +
        iv_risk["score"] * weights["iv"] +
        gamma_risk["score"] * weights["gamma"] +
        liq_risk["score"] * weights["liquidity"] +
        expiry_risk["score"] * weights["expiry"] +
        adv_risk["score"] * weights["advanced"]
    )

    # سطح کلی
    if total_score >= 70:
        overall_level = "EXTREME - معامله نکن"
    elif total_score >= 50:
        overall_level = "HIGH - با احتیاط زیاد"
    elif total_score >= 30:
        overall_level = "MEDIUM - قابل قبول با مدیریت ریسک"
    elif total_score >= 15:
        overall_level = "LOW - کم‌ریسک"
    else:
        overall_level = "VERY LOW - خیلی کم‌ریسک"

    return {
        "symbol": symbol,
        "overall_score": round(total_score, 1),
        "overall_level": overall_level,
        "theta_risk": theta_risk,
        "iv_crush_risk": iv_risk,
        "gamma_risk": gamma_risk,
        "liquidity_risk": liq_risk,
        "expiry_risk": expiry_risk,
        "advanced_greeks_risk": adv_risk,
        "weights": weights
    }

def print_risk_report(risk_analysis):
    print("="*70)
    print(f"RISK ENGINE V2 - {risk_analysis['symbol']} - امتیاز کلی: {risk_analysis['overall_score']}/100 - {risk_analysis['overall_level']}")
    print("="*70)
    for key in ["theta_risk", "iv_crush_risk", "gamma_risk", "liquidity_risk", "expiry_risk", "advanced_greeks_risk"]:
        data = risk_analysis.get(key, {})
        print(f"{key:25} | {data.get('level'):12} | Score {data.get('score'):3} | {data.get('details')}")
    print("="*70)

# ==================== تست ====================

if __name__ == "__main__":
    # تست با داده‌های greek_engine_v2
    from greek_engine_v2 import analyze_contract

    print("\n--- تست 1: اهرم ضهرم6049 - ریسک بالا Theta ---")
    greek = analyze_contract("ضهرم6049", 56762, 62000, 1804, 20, "CALL", volume=5640, oi=10000)
    risk = analyze_risk(greek)
    print_risk_report(risk)

    print("\n--- تست 2: وبملت ضملت6022 - کم‌ریسک ---")
    greek2 = analyze_contract("ضملت6022", 1489, 1354, 133, 13, "CALL", volume=10575, oi=8000)
    risk2 = analyze_risk(greek2)
    print_risk_report(risk2)

    print("\n--- تست 3: طهرم8034 - نقدشوندگی ضعیف + IV بالا ---")
    greek3 = analyze_contract("طهرم8034", 56762, 80000, 25880, 83, "PUT", volume=4, oi=100)
    # IV بالا
    greek3["iv"] = 1.089
    iv_fake = {"iv_rank": {"iv_rank": 85, "iv_percentile": 90}}
    risk3 = analyze_risk(greek3, iv_analysis=iv_fake)
    print_risk_report(risk3)

    print("\n--- تست 4: قرارداد با اسپرد بزرگ ---")
    greek4 = analyze_contract("ضهرم6049", 56762, 62000, 1804, 20, "CALL", volume=5640, oi=10000)
    greek4["market_data"]["spread_pct"] = 22.5
    greek4["market_data"]["bid"] = 1400
    greek4["market_data"]["ask"] = 1804
    risk4 = analyze_risk(greek4)
    print_risk_report(risk4)
