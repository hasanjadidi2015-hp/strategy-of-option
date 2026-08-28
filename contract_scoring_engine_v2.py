# -*- coding: utf-8 -*-
"""
AHRAM AI PRO - Contract Scoring Engine V2 - ماژول 4 از 6
نسخه مخصوص بازار ایران

این ماژول:
- بین تمام قراردادهای Call و Put، بهترین را انتخاب می‌کند
- امتیاز 0-100 با breakdown دقیق می‌دهد (مثل 82/100 که کاربر خواست)
- ریسک‌ها را جریمه می‌کند
- نسخه مخصوص ایران: نقدشوندگی و اسپرد وزن بالا

ورودی: لیست قراردادها با Greeks + Market Data + Risk + تحلیل تکنیکال سهم پایه
خروجی: لیست مرتب شده بر اساس امتیاز + بهترین قرارداد
"""

import math
from greek_engine_v2 import analyze_contract
from risk_engine_v2 import analyze_risk

# ==================== امتیازدهی ====================

def score_contract(contract_analysis, risk_analysis, technicals=None, iv_analysis=None):
    """
    امتیازدهی یک قرارداد
    contract_analysis: خروجی greek_engine_v2.analyze_contract
    risk_analysis: خروجی risk_engine_v2.analyze_risk
    technicals: dict با action, score, confidence (از strategy.py)
    iv_analysis: خروجی iv_engine_v2 (اختیاری)
    """
    score = 0
    breakdown = []
    penalties = []

    symbol = contract_analysis.get("symbol", "UNKNOWN")
    greeks = contract_analysis.get("greeks", {})
    adv = contract_analysis.get("advanced_greeks", {})
    md = contract_analysis.get("market_data", {})
    liquidity = contract_analysis.get("liquidity", {})
    iv = contract_analysis.get("iv")
    stock_price = contract_analysis.get("stock_price")
    strike = contract_analysis.get("strike_price")
    dte = contract_analysis.get("days_to_expire", 30)
    option_type = contract_analysis.get("option_type", "CALL")

    # 1. Underlying Direction (از تکنیکال) - وزن 25
    if technicals:
        action = technicals.get("action", "WATCH")
        tech_score = technicals.get("score", 0)
        confidence = technicals.get("confidence", 0)
        # اگر سهم صعودی و قرارداد CALL باشه، امتیاز بالا
        # اگر سهم نزولی و PUT باشه، امتیاز بالا
        if option_type == "CALL" and action in ("BUY", "STRONG BUY"):
            pts = 25 if tech_score >= 50 else (15 if tech_score >= 30 else 5)
            score += pts
            breakdown.append(f"Underlying Bullish {action} {tech_score} +{pts}")
        elif option_type == "PUT" and action in ("SELL", "STRONG SELL"):
            pts = 25 if tech_score <= -50 else (15 if tech_score <= -30 else 5)
            score += pts
            breakdown.append(f"Underlying Bearish {action} {tech_score} +{pts}")
        elif action == "WATCH":
            breakdown.append("Underlying WATCH +0")
        else:
            # جهت مخالف
            score -= 10
            penalties.append(f"Underlying مخالف {action} vs {option_type} -10")

    # 2. Momentum (از تکنیکال یا price action) - وزن 15
    if technicals and technicals.get("score"):
        # اگر امتیاز تکنیکال بالا باشه، مومنتوم قویه
        tech_score_abs = abs(technicals.get("score", 0))
        if tech_score_abs >= 60:
            score += 15
            breakdown.append(f"Momentum Strong {tech_score_abs} +15")
        elif tech_score_abs >= 40:
            score += 10
            breakdown.append(f"Momentum Medium {tech_score_abs} +10")
        elif tech_score_abs >= 20:
            score += 5
            breakdown.append(f"Momentum Weak {tech_score_abs} +5")

    # 3. IV Favorable - وزن 12
    if iv is not None:
        if iv_analysis:
            rank_data = iv_analysis.get("iv_rank", {})
            iv_rank = rank_data.get("iv_rank")
            if iv_rank is not None:
                if iv_rank <= 30:
                    score += 12
                    breakdown.append(f"IV Favorable Rank {iv_rank}% +12 (پرمیوم ارزون)")
                elif iv_rank <= 50:
                    score += 8
                    breakdown.append(f"IV Normal Rank {iv_rank}% +8")
                elif iv_rank >= 80:
                    score -= 10
                    penalties.append(f"IV Expensive Rank {iv_rank}% -10")
        else:
            # بدون Rank، فقط بر اساس IV مطلق
            if iv < 0.5:
                score += 12
                breakdown.append(f"IV Low {iv:.1%} +12")
            elif iv < 0.7:
                score += 6
                breakdown.append(f"IV Medium {iv:.1%} +6")
            elif iv > 1.0:
                score -= 8
                penalties.append(f"IV Very High {iv:.1%} -8")

    # 4. Gamma High - وزن 10
    gamma = greeks.get("gamma")
    if gamma and gamma > 0:
        # Gamma بالا نزدیک ATM خوبه برای حرکت سریع
        if gamma > 0.001:
            score += 10
            breakdown.append(f"Gamma High {gamma} +10")
        elif gamma > 0.0001:
            score += 5
            breakdown.append(f"Gamma Medium {gamma} +5")

    # 5. Theta Acceptable - وزن 8
    theta = greeks.get("theta_daily")
    option_price = contract_analysis.get("option_price", 0)
    if theta and option_price > 0:
        theta_pct = abs(theta) / option_price * 100
        if theta_pct < 1.0:
            score += 8
            breakdown.append(f"Theta Acceptable {theta_pct:.2f}% +8")
        elif theta_pct < 2.5:
            score += 4
            breakdown.append(f"Theta Medium {theta_pct:.2f}% +4")
        elif theta_pct > 5:
            score -= 8
            penalties.append(f"Theta High {theta_pct:.2f}% -8")

    # 6. Liquidity Good - وزن 7
    liq_level = liquidity.get("level")
    if liq_level == "Good":
        score += 7
        breakdown.append(f"Liquidity Good +7 (Vol {md.get('volume')} OI {md.get('open_interest')})")
    elif liq_level == "Medium":
        score += 3
        breakdown.append(f"Liquidity Medium +3")
    elif liq_level == "Poor":
        score -= 10
        penalties.append(f"Liquidity Poor -10 (Vol {md.get('volume')} OI {md.get('open_interest')})")

    # 7. Spread Low - وزن 5 (اضافه برای ایران)
    spread = md.get("spread_pct")
    if spread is not None:
        if spread <= 5:
            score += 5
            breakdown.append(f"Spread Low {spread}% +5")
        elif spread <= 10:
            score += 2
            breakdown.append(f"Spread Acceptable {spread}% +2")
        elif spread > 20:
            score -= 10
            penalties.append(f"Spread High {spread}% -10")

    # 8. Vanna Positive - وزن 5
    vanna = adv.get("vanna_1pct") if adv else None
    if vanna is not None:
        # Vanna مثبت یعنی اگر سهم بالا بره و IV هم بالا بره، Delta بیشتر میشه (خوب برای Call)
        if option_type == "CALL" and vanna > 0.002:
            score += 5
            breakdown.append(f"Vanna Positive {vanna} +5")
        elif option_type == "PUT" and vanna < -0.002:
            score += 5
            breakdown.append(f"Vanna Positive for Put {vanna} +5")

    # 9. DTE مناسب - وزن 5
    if 15 <= dte <= 45:
        score += 5
        breakdown.append(f"DTE Ideal {dte} days +5")
    elif dte < 7:
        score -= 10
        penalties.append(f"DTE Too Close {dte} days -10")
    elif dte > 90:
        score -= 5
        penalties.append(f"DTE Too Far {dte} days -5")

    # 10. Delta مناسب - وزن 8
    delta = greeks.get("delta")
    if delta is not None:
        ad = abs(delta)
        if 0.45 <= ad <= 0.65:
            score += 8
            breakdown.append(f"Delta Ideal {delta} +8")
        elif 0.35 <= ad <= 0.75:
            score += 4
            breakdown.append(f"Delta Acceptable {delta} +4")
        elif ad < 0.2 or ad > 0.85:
            score -= 8
            penalties.append(f"Delta Extreme {delta} -8 (Deep OTM/ITM)")

    # جریمه ریسک کلی از Risk Engine
    if risk_analysis:
        overall_risk = risk_analysis.get("overall_score", 0)
        if overall_risk >= 70:
            score -= 20
            penalties.append(f"Overall Risk EXTREME {overall_risk} -20")
        elif overall_risk >= 50:
            score -= 10
            penalties.append(f"Overall Risk HIGH {overall_risk} -10")
        elif overall_risk <= 20:
            score += 5
            breakdown.append(f"Overall Risk LOW {overall_risk} +5")

    # نمره نهایی 0-100
    final_score = max(0, min(100, score))

    return {
        "symbol": symbol,
        "score": final_score,
        "breakdown": breakdown,
        "penalties": penalties,
        "raw_score": score,
        "greeks": greeks,
        "liquidity": liquidity,
        "risk": risk_analysis.get("overall_score") if risk_analysis else None,
        "dte": dte,
        "option_type": option_type
    }

def rank_contracts(contracts, technicals=None, iv_analysis=None):
    """
    رتبه‌بندی لیست قراردادها
    contracts: لیست خروجی analyze_contract
    """
    scored = []
    for contract in contracts:
        # ریسک هر قرارداد
        risk = analyze_risk(contract, iv_analysis)
        # امتیاز
        scored_data = score_contract(contract, risk, technicals, iv_analysis)
        scored_data["risk_analysis"] = risk
        scored_data["contract_analysis"] = contract
        scored.append(scored_data)

    # مرتب‌سازی بر اساس امتیاز نزولی
    scored_sorted = sorted(scored, key=lambda x: x["score"], reverse=True)
    return scored_sorted

def print_scoring_report(scored_contracts, top_n=5):
    print("="*80)
    print(f"CONTRACT SCORING ENGINE V2 - Top {top_n} از {len(scored_contracts)} قرارداد")
    print("="*80)
    for i, c in enumerate(scored_contracts[:top_n], 1):
        print(f"\n#{i} {c['symbol']} | SCORE: {c['score']}/100 | Type: {c['option_type']} | DTE: {c['dte']} | Risk: {c['risk']}")
        print("  Breakdown:")
        for b in c["breakdown"]:
            print(f"    + {b}")
        if c["penalties"]:
            print("  Penalties:")
            for p in c["penalties"]:
                print(f"    - {p}")
        # خلاصه Greeks
        g = c["greeks"]
        print(f"  Greeks: Delta {g.get('delta')} Gamma {g.get('gamma')} Theta {g.get('theta_daily')} Vega {g.get('vega_1pct')}")
    print("="*80)

# ==================== تست ====================

if __name__ == "__main__":
    print("\n--- تست 1: امتیازدهی 3 قرارداد اهرم با تکنیکال صعودی ---")
    from greek_engine_v2 import analyze_contract

    technicals_bullish = {"action": "BUY", "score": 55, "confidence": 70}

    contracts = [
        analyze_contract("ضهرم6049", 56762, 62000, 1804, 20, "CALL", volume=5640, oi=10000),
        analyze_contract("ضهرم7062", 56762, 62000, 4238, 55, "CALL", volume=5320, oi=12000),
        analyze_contract("ضهرم6048", 56762, 56000, 4999, 20, "CALL", volume=4608, oi=8000),
    ]

    ranked = rank_contracts(contracts, technicals=technicals_bullish)
    print_scoring_report(ranked, top_n=3)

    print("\n--- تست 2: وبملت با تکنیکال صعودی + IV Rank پایین (فرصت) ---")
    technicals = {"action": "BUY", "score": 46, "confidence": 75}
    iv_fake_low = {"iv_rank": {"iv_rank": 25, "iv_percentile": 20}}  # IV ارزون

    contracts2 = [
        analyze_contract("ضملت6022", 1489, 1354, 133, 13, "CALL", volume=10575, oi=8000),
        analyze_contract("ضملت6023", 1489, 1454, 69, 13, "CALL", volume=9139, oi=7000),
        analyze_contract("ضملت6021", 1489, 1254, 218, 13, "CALL", volume=8048, oi=6000),
    ]

    ranked2 = rank_contracts(contracts2, technicals=technicals, iv_analysis=iv_fake_low)
    print_scoring_report(ranked2, top_n=3)

    print("\n--- تست 3: قرارداد با اسپرد بزرگ و نقدشوندگی ضعیف (جریمه) ---")
    contracts3 = [
        analyze_contract("طهرم8034", 56762, 80000, 25880, 83, "PUT", volume=4, oi=100),
        analyze_contract("ضهرم6049", 56762, 62000, 1804, 20, "CALL", volume=5640, oi=10000),
    ]
    # اضافه کردن اسپرد بزرگ به اولی
    contracts3[0]["market_data"]["spread_pct"] = 25
    contracts3[0]["market_data"]["bid"] = 20000
    contracts3[0]["market_data"]["ask"] = 25880

    ranked3 = rank_contracts(contracts3, technicals=technicals_bullish)
    print_scoring_report(ranked3, top_n=2)
