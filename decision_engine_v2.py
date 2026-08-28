# -*- coding: utf-8 -*-
"""
AHRAM AI PRO - Decision Engine V2 - ماژول 5 و 6 از 6 (نهایی)
نسخه مخصوص بازار ایران - تبدیل از سیگنال‌دهنده ساده به Option Decision System

این ماژول:
- تحلیل تکنیکال (Ichimoku, VWAP, Price Action, Market Regime) + Greeks + IV + Risk + Scoring را ترکیب می‌کند
- خروجی نهایی می‌دهد: CALL SCORE 82/100 با breakdown دقیق + RISK + توصیه
- جایگزین BUY/CONFIDENCE 100 ساده قبلی

ورودی:
- technicals: از strategy.py (action, score, confidence, price, reasons)
- ranked_contracts: از contract_scoring_engine_v2.rank_contracts
- iv_analysis: از iv_engine_v2
- market_data: indices, money_flow, order_book

خروجی:
- تصمیم نهایی: BUY_CALL / BUY_PUT / WATCH
- امتیاز نهایی 0-100 با breakdown
- بهترین قرارداد + اهداف + حد ضرر
- ریسک‌ها
"""

from greek_engine_v2 import analyze_contract
from risk_engine_v2 import analyze_risk
from contract_scoring_engine_v2 import rank_contracts
from iv_engine_v2 import analyze_iv
import math

def calculate_targets(option_price, days_to_expire):
    """محاسبه حد ضرر و اهداف - از ahram_pro.py"""
    entry = float(option_price)
    dte = int(days_to_expire)
    if entry <= 0:
        return None
    if dte <= 7:
        sl_pct = 0.10
    elif dte <= 21:
        sl_pct = 0.12
    else:
        sl_pct = 0.15
    t1_pct = 0.15
    t2_pct = 0.30
    return {
        "entry": round(entry),
        "stop_loss": round(entry * (1 - sl_pct)),
        "stop_loss_pct": round(sl_pct * 100),
        "target1": round(entry * (1 + t1_pct)),
        "target1_pct": round(t1_pct * 100),
        "target2": round(entry * (1 + t2_pct)),
        "target2_pct": round(t2_pct * 100),
    }

def make_decision(symbol_name, technicals, contracts, iv_analysis=None, market_data=None):
    """
    تصمیم نهایی
    symbol_name: اهرم / وبملت / شستا
    technicals: {"action": "BUY", "score": 55, "confidence": 70, "price": 1489, "reasons": []}
    contracts: لیست قراردادهای تحلیل شده با greek_engine_v2
    iv_analysis: از iv_engine_v2
    """
    # اگر تکنیکال WATCH باشه، مستقیم WATCH
    action = technicals.get("action", "WATCH")
    tech_score = technicals.get("score", 0)
    confidence = technicals.get("confidence", 0)

    if action == "WATCH" or abs(tech_score) < 20:
        return {
            "symbol": symbol_name,
            "decision": "WATCH",
            "final_score": max(0, int(tech_score)),
            "reason": "تحلیل تکنیکال خنثی یا ضعیف",
            "best_contract": None,
            "breakdown": [f"Technicals WATCH {tech_score}"],
            "risks": ["شرایط تکنیکال مناسب نیست"],
            "targets": None,
            "message": f"\n{symbol_name}: WATCH (امتیاز تکنیکال {tech_score})\n"
        }

    # رتبه‌بندی قراردادها
    ranked = rank_contracts(contracts, technicals=technicals, iv_analysis=iv_analysis)

    if not ranked:
        return {
            "symbol": symbol_name,
            "decision": "WATCH",
            "final_score": 0,
            "reason": "هیچ قرارداد واجد شرایطی پیدا نشد",
            "best_contract": None,
            "breakdown": ["No valid contracts"],
            "risks": ["نقدشوندگی یا فیلترها اجازه نداد"],
            "targets": None,
            "message": f"\n{symbol_name}: WATCH - قرارداد مناسب نیست\n"
        }

    best = ranked[0]
    best_score = best["score"]

    # تصمیم نهایی بر اساس نوع قرارداد و تکنیکال
    if best["option_type"] == "CALL" and action in ("BUY", "STRONG BUY") and best_score >= 45:
        decision = "BUY_CALL"
    elif best["option_type"] == "PUT" and action in ("SELL", "STRONG SELL") and best_score >= 45:
        decision = "BUY_PUT"
    else:
        # اگر بهترین قرارداد امتیازش کم باشه یا جهت مخالف باشه
        if best_score < 35:
            decision = "WATCH"
        else:
            # حتی اگر جهت مخالف باشه ولی امتیاز بالا باشه، باز WATCH میدیم تا ریسک نکنیم
            decision = "WATCH"

    # اگر تصمیم WATCH شد ولی شرایط تکنیکال برای BUY کافی بود و قرارداد نبود، لاگ هشدار
    warning = None
    if decision == "WATCH" and best_score < 35 and abs(tech_score) >= 40:
        warning = f"⚠️ شرایط تکنیکال/چک‌ها برای BUY کافی بود (امتیاز {tech_score}) ولی هیچ آپشنی با امتیاز بالا انتخاب نشد -> WATCH"

    # اهداف
    targets = None
    if decision in ("BUY_CALL", "BUY_PUT"):
        contract_analysis = best["contract_analysis"]
        targets = calculate_targets(contract_analysis["option_price"], contract_analysis["days_to_expire"])

    # پیام نهایی - فرمتی که کاربر خواست (CALL SCORE 82/100 با breakdown)
    final_score = best_score if decision != "WATCH" else max(0, int((best_score + tech_score) / 2))

    # ساخت breakdown نهایی برای نمایش
    final_breakdown = []
    final_breakdown.append(f"Underlying: {action} {tech_score} (confidence {confidence}%)")
    final_breakdown.extend(best["breakdown"])
    if best["penalties"]:
        final_breakdown.append("Penalties:")
        final_breakdown.extend(best["penalties"])

    # ریسک‌های نهایی
    final_risks = []
    risk_analysis = best.get("risk_analysis", {})
    if risk_analysis:
        for k in ["theta_risk", "iv_crush_risk", "liquidity_risk", "expiry_risk"]:
            r = risk_analysis.get(k, {})
            if r.get("level") in ("HIGH", "EXTREME"):
                final_risks.append(f"{k}: {r.get('level')} - {r.get('details')}")
    if not final_risks:
        final_risks = ["ریسک خاصی در محدوده HIGH نیست"]

    # پیام
    if decision == "WATCH":
        msg = f"\n{symbol_name}: WATCH (امتیاز نهایی {final_score})\n"
        if warning:
            msg += warning + "\n"
    else:
        # پیام BUY_CALL / BUY_PUT با فرمت جدید
        lines = []
        lines.append("="*50)
        if decision == "BUY_CALL":
            lines.append(f"🟢 {symbol_name} - سیگنال خرید کال - CALL SCORE: {final_score}/100")
        else:
            lines.append(f"🔴 {symbol_name} - سیگنال خرید پوت - PUT SCORE: {final_score}/100")
        lines.append("="*50)
        lines.append(f"قرارداد: {best['symbol']} | قیمت: {best['contract_analysis']['option_price']} | اعمال: {best['contract_analysis']['strike_price']} | سررسید: {best['contract_analysis']['days_to_expire']} روز")
        lines.append("")
        lines.append("Breakdown:")
        for b in final_breakdown[:10]:  # فقط 10 تای اول
            lines.append(f"  {b}")
        lines.append("")
        lines.append("RISK:")
        for r in final_risks[:5]:
            lines.append(f"  - {r}")
        if targets:
            lines.append("")
            lines.append(f"Entry: {targets['entry']} | Stop: {targets['stop_loss']} (-{targets['stop_loss_pct']}%) | Target1: {targets['target1']} (+{targets['target1_pct']}%) | Target2: {targets['target2']} (+{targets['target2_pct']}%)")
        lines.append("="*50)
        msg = "\n".join(lines)

    return {
        "symbol": symbol_name,
        "decision": decision,
        "final_score": final_score,
        "best_contract": best,
        "all_ranked": ranked,
        "breakdown": final_breakdown,
        "risks": final_risks,
        "targets": targets,
        "technicals": technicals,
        "iv_analysis": iv_analysis,
        "warning": warning,
        "message": msg
    }

def print_decision(decision_data):
    print(decision_data["message"])
    if decision_data.get("best_contract"):
        best = decision_data["best_contract"]
        print(f"\nبهترین قرارداد: {best['symbol']} با امتیاز {best['score']}")
        if len(decision_data["all_ranked"]) > 1:
            print(f"تعداد کل قراردادهای بررسی شده: {len(decision_data['all_ranked'])}")
            print(f"دومین: {decision_data['all_ranked'][1]['symbol']} امتیاز {decision_data['all_ranked'][1]['score']}")

# ==================== تست ====================

if __name__ == "__main__":
    from greek_engine_v2 import analyze_contract

    print("\n=== تست 1: اهرم صعودی قوی + 3 قرارداد ===")
    technicals = {"action": "BUY", "score": 65, "confidence": 80, "price": 56762}
    contracts = [
        analyze_contract("ضهرم6049", 56762, 62000, 1804, 20, "CALL", volume=5640, oi=10000),
        analyze_contract("ضهرم7062", 56762, 62000, 4238, 55, "CALL", volume=5320, oi=12000),
        analyze_contract("ضهرم6048", 56762, 56000, 4999, 20, "CALL", volume=4608, oi=8000),
    ]
    decision = make_decision("اهرم", technicals, contracts)
    print_decision(decision)

    print("\n=== تست 2: وبملت صعودی متوسط + IV ارزون (فرصت) ===")
    technicals2 = {"action": "BUY", "score": 46, "confidence": 75, "price": 1489}
    iv_low = {"iv_rank": {"iv_rank": 25}}
    contracts2 = [
        analyze_contract("ضملت6022", 1489, 1354, 133, 13, "CALL", volume=10575, oi=8000),
        analyze_contract("ضملت6023", 1489, 1454, 69, 13, "CALL", volume=9139, oi=7000),
        analyze_contract("ضملت6021", 1489, 1254, 218, 13, "CALL", volume=8048, oi=6000),
    ]
    decision2 = make_decision("وبملت", technicals2, contracts2, iv_analysis=iv_low)
    print_decision(decision2)

    print("\n=== تست 3: تکنیکال WATCH -> باید WATCH بده ===")
    technicals_watch = {"action": "WATCH", "score": 10, "confidence": 30, "price": 1489}
    decision3 = make_decision("شستا", technicals_watch, contracts2)
    print_decision(decision3)

    print("\n=== تست 4: قراردادها امتیاز پایین + تکنیکال قوی -> WATCH با هشدار ===")
    technicals_strong = {"action": "BUY", "score": 70, "confidence": 85, "price": 56762}
    contracts_poor = [
        analyze_contract("طهرم8034", 56762, 80000, 25880, 83, "PUT", volume=4, oi=100),
    ]
    contracts_poor[0]["market_data"]["spread_pct"] = 25
    decision4 = make_decision("اهرم", technicals_strong, contracts_poor)
    print_decision(decision4)
