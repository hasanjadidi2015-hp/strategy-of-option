# -*- coding: utf-8 -*-
"""
AHRAM AI PRO - Sentiment Engine V2 - ماژول سنتیمنتال مخصوص ایران
تطبیق 5 شاخص جهانی + 3 لایه تکمیلی با بازار ایران

این ماژول:
- VIX ایرانی (Iran VIX Proxy) از WIV و IV
- Fear & Greed Iran 0-100 (ترکیب 5 فاکتور)
- BPI Iran (درصد صعودی)
- High-Low Iran (قدرت روند - پروکسی)
- Put/Call Ratio, OI, Money Flow, Order Book, News

ورودی: DB path + market_data (indices, money_flow, order_book, news)
خروجی: Fear & Greed 0-100 + Iran VIX + BPI + HighLow + Risks + Opportunities
"""

import sqlite3
import os
import math
from datetime import datetime, timedelta

# ==================== Iran VIX Proxy ====================

def compute_iran_vix(db_path=None, wiv_data=None, iv_rank_data=None):
    """
    VIX ایرانی = میانگین IV یا WIV
    WIV داریم، اگر نبود از iv_history میانگین می‌گیریم
    """
    vix = None
    source = "UNKNOWN"
    try:
        # از WIV اگر موجود باشه
        if wiv_data and wiv_data.get("wiv_pct") is not None:
            # WIV به صورت درصد است (مثلا 76.7) -> به 0-100 تبدیل
            vix = float(wiv_data.get("wiv_pct"))
            source = "WIV"
        elif iv_rank_data and iv_rank_data.get("avg_iv") is not None:
            # avg_iv از iv_history - مثلا 0.55 -> 55%
            avg_iv = iv_rank_data.get("avg_iv")
            if avg_iv and avg_iv < 5:  # اگر به صورت 0.55 باشد
                vix = avg_iv * 100
            else:
                vix = avg_iv
            source = "IV_HISTORY_AVG"
        else:
            # از DB بخوان
            if db_path and os.path.exists(db_path):
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                try:
                    cur.execute("SELECT atm_iv FROM iv_history ORDER BY date DESC LIMIT 10")
                    rows = cur.fetchall()
                    ivs = [r[0] for r in rows if r[0] and r[0] > 0]
                    if ivs:
                        avg = sum(ivs) / len(ivs)
                        vix = avg * 100 if avg < 5 else avg
                        source = "IV_HISTORY_DB"
                except:
                    pass
                conn.close()
    except Exception as e:
        print(f"[WARN] Iran VIX: {e}")

    # تفسیر
    level = "UNKNOWN"
    if vix is not None:
        if vix >= 80:
            level = "EXTREME FEAR"
        elif vix >= 60:
            level = "FEAR"
        elif vix >= 40:
            level = "NEUTRAL"
        elif vix >= 20:
            level = "GREED"
        else:
            level = "EXTREME GREED"

    return {"vix": round(vix, 1) if vix is not None else None, "level": level, "source": source}

# ==================== Put/Call Ratio ====================

def compute_put_call_ratio(db_path=None, options_data=None):
    """
    Put/Call Ratio - از volume_analysis یا مستقیم از DB
    """
    pc_vol = None
    pc_oi = None
    try:
        if db_path and os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            # آخرین زمان options
            cur.execute("SELECT MAX(time) FROM options")
            max_time = cur.fetchone()[0]
            if max_time:
                cur.execute("SELECT option_type, volume, open_interest FROM options WHERE time=?", (max_time,))
                rows = cur.fetchall()
                call_vol = sum(r[1] or 0 for r in rows if str(r[0]).upper() == "CALL")
                put_vol = sum(r[1] or 0 for r in rows if str(r[0]).upper() == "PUT")
                call_oi = sum(r[2] or 0 for r in rows if str(r[0]).upper() == "CALL")
                put_oi = sum(r[2] or 0 for r in rows if str(r[0]).upper() == "PUT")
                if call_vol > 0:
                    pc_vol = round(put_vol / call_vol, 2)
                if call_oi > 0:
                    pc_oi = round(put_oi / call_oi, 2)
            conn.close()
        elif options_data:
            calls = [x for x in options_data if str(x.get("option_type")).upper() == "CALL"]
            puts = [x for x in options_data if str(x.get("option_type")).upper() == "PUT"]
            call_vol = sum(x.get("volume", 0) or 0 for x in calls)
            put_vol = sum(x.get("volume", 0) or 0 for x in puts)
            call_oi = sum(x.get("open_interest", 0) or 0 for x in calls)
            put_oi = sum(x.get("open_interest", 0) or 0 for x in puts)
            if call_vol > 0:
                pc_vol = round(put_vol / call_vol, 2)
            if call_oi > 0:
                pc_oi = round(put_oi / call_oi, 2)
    except Exception as e:
        print(f"[WARN] P/C Ratio: {e}")

    # تفسیر ایران
    sentiment = "NEUTRAL"
    score = 50  # 0 ترس شدید، 100 طمع شدید
    # P/C بالا = ترس (همه پوت می‌خرن)
    # P/C پایین = طمع (همه کال می‌خرن)
    pc = pc_oi if pc_oi is not None else pc_vol
    if pc is not None:
        if pc >= 1.5:
            sentiment = "EXTREME FEAR"
            score = 10
        elif pc >= 1.2:
            sentiment = "FEAR"
            score = 25
        elif pc >= 0.9:
            sentiment = "NEUTRAL"
            score = 50
        elif pc >= 0.6:
            sentiment = "GREED"
            score = 75
        else:
            sentiment = "EXTREME GREED"
            score = 90

    return {"pc_volume": pc_vol, "pc_oi": pc_oi, "pc_combined": pc, "sentiment": sentiment, "score": score}

# ==================== Money Flow Sentiment ====================

def compute_money_flow_sentiment(money_flow_data=None, db_path=None):
    """
    جریان پول حقیقی/حقوقی - بهترین شاخص ایران
    """
    retail_net = None
    inst_net = None
    try:
        if money_flow_data:
            # money_flow_data از money_flow.py
            retail_net = money_flow_data.get("net_retail") or money_flow_data.get("retail_net")
            inst_net = money_flow_data.get("net_institutional") or money_flow_data.get("institutional_net")
            # اگر dict نباشه و مستقیم عدد باشه
            if retail_net is None and isinstance(money_flow_data, dict):
                # تلاش برای خواندن از ساختارهای مختلف
                for k in ["net_retail", "retail", "real_net"]:
                    if k in money_flow_data:
                        retail_net = money_flow_data[k]
                        break
        # از فایل JSON اگر موجود باشه
        if retail_net is None and os.path.exists("money_flow.json"):
            import json
            try:
                with open("money_flow.json", "r", encoding="utf-8") as f:
                    mf = json.load(f)
                    retail_net = mf.get("net_retail")
                    inst_net = mf.get("net_institutional")
            except:
                pass
    except Exception as e:
        print(f"[WARN] Money Flow: {e}")

    sentiment = "NEUTRAL"
    score = 50
    # حقیقی فروش سنگین + حقوقی خرید سنگین = ترس حقیقی، کف نزدیک = فرصت (امتیاز پایین = ترس، ولی برای خرید خوبه)
    # حقیقی خرید سنگین + حقوقی فروش = طمع حقیقی، سقف نزدیک
    if retail_net is not None:
        # فرض: retail_net منفی = حقیقی فروش
        if retail_net < -1_000_000_000:  # فروش بالای 1 میلیارد
            sentiment = "FEAR - حقیقی فروش سنگین، حقوقی در حال جمع‌آوری"
            score = 20
        elif retail_net < -100_000_000:
            sentiment = "MILD FEAR - حقیقی فروش"
            score = 35
        elif retail_net > 1_000_000_000:
            sentiment = "GREED - حقیقی خرید سنگین، حقوقی فروش"
            score = 80
        elif retail_net > 100_000_000:
            sentiment = "MILD GREED - حقیقی خرید"
            score = 65
        else:
            sentiment = "NEUTRAL"
            score = 50

    return {"retail_net": retail_net, "institutional_net": inst_net, "sentiment": sentiment, "score": score}

# ==================== Order Book Sentiment ====================

def compute_order_book_sentiment(order_book_data=None, db_path=None):
    """
    فشار تابلو و صف قفل‌شده - منحصر به ایران
    """
    imbalance = None
    pressure = "UNKNOWN"
    market_state = "UNKNOWN"
    try:
        if order_book_data:
            imbalance = order_book_data.get("imbalance_pct")
            pressure = order_book_data.get("pressure", "UNKNOWN")
            market_state = order_book_data.get("market_state", "UNKNOWN")
        elif db_path and os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT buy_price, sell_price, buy_volume, sell_volume FROM order_book ORDER BY id DESC LIMIT 5")
            rows = cur.fetchall()
            if rows:
                buy_prices = [float(r[0] or 0) for r in rows]
                sell_prices = [float(r[1] or 0) for r in rows]
                buy_vol = sum(float(r[2] or 0) for r in rows)
                sell_vol = sum(float(r[3] or 0) for r in rows)
                has_buy, has_sell = any(buy_prices), any(sell_prices)
                if has_buy and not has_sell:
                    market_state = "LOCKED_BUY_QUEUE"
                    pressure = "BUY_QUEUE"
                elif has_sell and not has_buy:
                    market_state = "LOCKED_SELL_QUEUE"
                    pressure = "SELL_QUEUE"
                elif has_buy and has_sell and buy_vol + sell_vol > 0:
                    market_state = "TWO_SIDED"
                    imbalance = round((buy_vol - sell_vol) / (buy_vol + sell_vol) * 100, 1)
                    if imbalance > 20:
                        pressure = "BUY_HEAVY"
                    elif imbalance < -20:
                        pressure = "SELL_HEAVY"
                    else:
                        pressure = "BALANCED"
            conn.close()
    except Exception as e:
        print(f"[WARN] Order Book: {e}")

    sentiment = "NEUTRAL"
    score = 50
    if market_state == "LOCKED_BUY_QUEUE":
        sentiment = "EXTREME GREED - صف خرید قفل‌شده"
        score = 95
    elif market_state == "LOCKED_SELL_QUEUE":
        sentiment = "EXTREME FEAR - صف فروش قفل‌شده"
        score = 5
    elif imbalance is not None:
        if imbalance > 30:
            sentiment = "GREED - فشار خرید سنگین"
            score = 75
        elif imbalance > 10:
            sentiment = "MILD GREED - فشار خرید"
            score = 60
        elif imbalance < -30:
            sentiment = "FEAR - فشار فروش سنگین"
            score = 25
        elif imbalance < -10:
            sentiment = "MILD FEAR - فشار فروش"
            score = 40

    return {"imbalance_pct": imbalance, "pressure": pressure, "market_state": market_state, "sentiment": sentiment, "score": score}

# ==================== Index & BPI ====================

def compute_bpi_and_index_sentiment(index_data=None, technicals=None):
    """
    BPI Iran - درصد صعودی
    از 3 نماد خودمان یا از شاخص کل
    """
    bpi = None
    sentiment = "NEUTRAL"
    score = 50
    try:
        # اگر technicals لیست 3 نماد باشه
        if technicals and isinstance(technicals, list):
            bullish = sum(1 for t in technicals if t.get("action") in ("BUY", "STRONG BUY"))
            total = len(technicals)
            if total > 0:
                bpi = round(bullish / total * 100, 1)
        # اگر index_data داشته باشیم
        elif index_data:
            # index_data از index_feed - 58 شاخص
            # برای سادگی: اگر شاخص کل مثبت باشه = صعودی
            # در آینده می‌توان از TSETMC تعداد نمادهای مثبت گرفت
            pass
    except Exception as e:
        print(f"[WARN] BPI: {e}")

    if bpi is not None:
        if bpi >= 80:
            sentiment = "EXTREME GREED - 80% نمادها صعودی"
            score = 90
        elif bpi >= 60:
            sentiment = "GREED - بازار صعودی"
            score = 70
        elif bpi >= 40:
            sentiment = "NEUTRAL"
            score = 50
        elif bpi >= 20:
            sentiment = "FEAR - بازار نزولی"
            score = 30
        else:
            sentiment = "EXTREME FEAR - 80% نمادها نزولی"
            score = 10

    return {"bpi_pct": bpi, "sentiment": sentiment, "score": score}

# ==================== News Sentiment ====================

def compute_news_sentiment(news_data=None, db_path=None):
    """
    سنتیمنت اخبار - NLP ساده ایرانی
    """
    news_count = 0
    sentiment_score = 0
    sentiment = "NEUTRAL"
    score = 50
    try:
        news_list = []
        if news_data and isinstance(news_data, list):
            news_list = news_data
        elif db_path and os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT title, category FROM daily_news WHERE event_date=date('now') ORDER BY id DESC LIMIT 20")
            rows = cur.fetchall()
            news_list = [{"title": r[0], "category": r[1]} for r in rows]
            conn.close()

        news_count = len(news_list)
        # امتیازدهی ساده فارسی
        for news in news_list:
            title = str(news.get("title", "")).lower()
            cat = str(news.get("category", "")).lower()
            # کلمات منفی
            if any(w in title or w in cat for w in ["توقف", "عدم تایید", "تعلیق", "لغو", "زیان", "کاهش سود"]):
                sentiment_score -= 3
            if "عدم تایید معاملات" in cat or "توقف نماد" in cat:
                sentiment_score -= 5
            # کلمات مثبت
            if any(w in title or w in cat for w in ["افزایش سرمایه", "افزایش سود", "سود", "مثبت", "رشد"]):
                sentiment_score += 2
            if "افشای اطلاعات بااهمیت" in cat and "الف" in cat:
                sentiment_score += 3

        if sentiment_score <= -10:
            sentiment = "EXTREME FEAR - اخبار منفی سنگین"
            score = 10
        elif sentiment_score <= -5:
            sentiment = "FEAR - اخبار منفی"
            score = 30
        elif sentiment_score >= 10:
            sentiment = "GREED - اخبار مثبت"
            score = 70
        elif sentiment_score >= 5:
            sentiment = "MILD GREED - اخبار مثبت"
            score = 60
        else:
            sentiment = "NEUTRAL"
            score = 50

    except Exception as e:
        print(f"[WARN] News: {e}")

    return {"news_count": news_count, "sentiment_score": sentiment_score, "sentiment": sentiment, "score": score}

# ==================== High-Low Iran (قدرت روند) ====================

def compute_high_low_iran(db_path=None, index_data=None):
    """
    High-Low ایران - قدرت روند
    تعداد نمادهای در سقف/کف 52 هفته
    فعلا پروکسی از 3 نماد خودمان + شاخص کل
    در آینده باید از TSETMC کل بازار گرفت
    """
    # فعلا پروکسی ساده - چون گرفتن کل بازار نیاز به API جدا دارد
    # برای الان: اگر قیمت سهم نزدیک سقف 52 هفته باشد = قدرت روند بالا
    # این تابع فعلا فقط ساختار را برمی‌گرداند، پیاده‌سازی کامل نیاز به history_loader دارد
    return {
        "high_52w_count": None,
        "low_52w_count": None,
        "high_low_ratio": None,
        "sentiment": "NEUTRAL - نیاز به داده کل بازار TSETMC",
        "score": 50,
        "note": "برای پیاده‌سازی کامل باید از TSETMC تعداد نمادهای سقف/کف 52 هفته گرفت - فعلا پروکسی"
    }

# ==================== Fear & Greed Iran - ترکیب نهایی ====================

def compute_fear_greed_iran(components):
    """
    ترکیب 5 فاکتور به یک عدد 0-100
    وزن‌ها مخصوص ایران:
    - Put/Call Ratio 30% (مهم‌ترین برای آپشن)
    - Money Flow 25% (حقیقی/حقوقی)
    - Order Book 20% (صف قفل‌شده - منحصر ایران)
    - BPI/Index 15%
    - News 10%
    """
    weights = {
        "pc": 0.30,
        "money_flow": 0.25,
        "order_book": 0.20,
        "bpi": 0.15,
        "news": 0.10
    }

    total_score = 0
    total_weight = 0
    breakdown = []

    for key, weight in weights.items():
        comp = components.get(key)
        if comp and comp.get("score") is not None:
            total_score += comp["score"] * weight
            total_weight += weight
            breakdown.append(f"{key}: {comp['sentiment']} Score {comp['score']} Weight {weight*100}%")

    if total_weight == 0:
        return {"fear_greed": 50, "level": "NEUTRAL", "breakdown": ["داده کافی نیست"], "opportunity": "UNKNOWN"}

    fear_greed = round(total_score / total_weight, 1)

    # سطح
    if fear_greed <= 20:
        level = "EXTREME FEAR"
        opportunity = "فرصت خرید عالی - ترس شدید"
    elif fear_greed <= 40:
        level = "FEAR"
        opportunity = "فرصت خرید - ترس"
    elif fear_greed <= 60:
        level = "NEUTRAL"
        opportunity = "خنثی"
    elif fear_greed <= 80:
        level = "GREED"
        opportunity = "احتیاط - طمع"
    else:
        level = "EXTREME GREED"
        opportunity = "هشدار سقف - طمع شدید"

    return {
        "fear_greed": fear_greed,
        "level": level,
        "opportunity": opportunity,
        "breakdown": breakdown,
        "weights": weights
    }

# ==================== موتور اصلی ====================

def analyze_sentiment(db_path=None, market_data=None, technicals=None, wiv_data=None, iv_rank_data=None, options_data=None):
    """
    تحلیل کامل سنتیمنتال برای یک نماد
    market_data: {"indices": ..., "money_flow": ..., "order_book": ..., "news": ...}
    """
    market_data = market_data or {}
    # اجزا
    iran_vix = compute_iran_vix(db_path=db_path, wiv_data=wiv_data, iv_rank_data=iv_rank_data)
    pc_ratio = compute_put_call_ratio(db_path=db_path, options_data=options_data)
    money_flow = compute_money_flow_sentiment(money_flow_data=market_data.get("money_flow"), db_path=db_path)
    order_book = compute_order_book_sentiment(order_book_data=market_data.get("order_book"), db_path=db_path)
    bpi = compute_bpi_and_index_sentiment(index_data=market_data.get("indices"), technicals=technicals)
    news = compute_news_sentiment(news_data=market_data.get("news"), db_path=db_path)
    high_low = compute_high_low_iran(db_path=db_path, index_data=market_data.get("indices"))

    components = {
        "pc": pc_ratio,
        "money_flow": money_flow,
        "order_book": order_book,
        "bpi": bpi,
        "news": news,
        "high_low": high_low,
        "vix": iran_vix
    }

    fear_greed = compute_fear_greed_iran(components)

    # ریسک‌ها و فرصت‌ها
    risks = []
    opportunities = []

    if fear_greed["fear_greed"] <= 20:
        opportunities.append(f"ترس شدید {fear_greed['fear_greed']} - فرصت خرید عالی (کف نزدیک)")
    if fear_greed["fear_greed"] >= 80:
        risks.append(f"طمع شدید {fear_greed['fear_greed']} - هشدار سقف (اصلاح نزدیک)")

    if pc_ratio.get("pc_oi") and pc_ratio["pc_oi"] >= 1.5:
        opportunities.append(f"P/C OI بالا {pc_ratio['pc_oi']} - همه پوت می‌خرن - کف نزدیک")
    if pc_ratio.get("pc_oi") and pc_ratio["pc_oi"] <= 0.6:
        risks.append(f"P/C OI پایین {pc_ratio['pc_oi']} - همه کال می‌خرن - سقف نزدیک")

    if order_book.get("market_state") == "LOCKED_BUY_QUEUE":
        risks.append("صف خرید قفل‌شده - طمع شدید - مراقب تله حقوقی باش")
    if order_book.get("market_state") == "LOCKED_SELL_QUEUE":
        opportunities.append("صف فروش قفل‌شده - ترس شدید - فرصت انباشت")

    if money_flow.get("retail_net") and money_flow["retail_net"] < -1_000_000_000:
        opportunities.append(f"حقیقی فروش سنگین {money_flow['retail_net']:,} - حقوقی در حال جمع‌آوری - کف")

    if iran_vix.get("vix") and iran_vix["vix"] >= 80:
        risks.append(f"Iran VIX بالا {iran_vix['vix']}% - نوسان و ترس شدید")

    return {
        "fear_greed": fear_greed,
        "iran_vix": iran_vix,
        "put_call_ratio": pc_ratio,
        "money_flow": money_flow,
        "order_book": order_book,
        "bpi": bpi,
        "news": news,
        "high_low": high_low,
        "components": components,
        "risks": risks,
        "opportunities": opportunities,
        "timestamp": datetime.now().isoformat()
    }

def print_sentiment_report(analysis, symbol_name=""):
    print("="*80)
    print(f"SENTIMENT ENGINE V2 - {symbol_name} - {analysis['fear_greed']['fear_greed']}/100 {analysis['fear_greed']['level']}")
    print("="*80)
    print(f"Iran VIX: {analysis['iran_vix']['vix']}% {analysis['iran_vix']['level']} Source {analysis['iran_vix']['source']}")
    print(f"Put/Call Vol: {analysis['put_call_ratio']['pc_volume']} OI: {analysis['put_call_ratio']['pc_oi']} Sentiment {analysis['put_call_ratio']['sentiment']}")
    print(f"Money Flow: Retail {analysis['money_flow']['retail_net']} Sentiment {analysis['money_flow']['sentiment']}")
    print(f"Order Book: {analysis['order_book']['market_state']} Imbalance {analysis['order_book']['imbalance_pct']}% Pressure {analysis['order_book']['pressure']} Sentiment {analysis['order_book']['sentiment']}")
    print(f"BPI: {analysis['bpi']['bpi_pct']}% Sentiment {analysis['bpi']['sentiment']}")
    print(f"News: Count {analysis['news']['news_count']} Score {analysis['news']['sentiment_score']} Sentiment {analysis['news']['sentiment']}")
    print(f"High-Low: {analysis['high_low']['sentiment']}")
    print("")
    print(f"Fear & Greed Iran: {analysis['fear_greed']['fear_greed']}/100 {analysis['fear_greed']['level']} - {analysis['fear_greed']['opportunity']}")
    print("Breakdown:")
    for b in analysis['fear_greed']['breakdown']:
        print(f"  - {b}")
    print("")
    print("Risks:")
    for r in analysis['risks']:
        print(f"  ⚠️ {r}")
    print("Opportunities:")
    for o in analysis['opportunities']:
        print(f"  ✅ {o}")
    print("="*80)

# ==================== تست ====================

if __name__ == "__main__":
    print("\n--- تست 1: سنتیمنتال با داده ساختگی ترس شدید (کف) ---")
    market_data_fear = {
        "money_flow": {"net_retail": -1_500_000_000, "net_institutional": 1_500_000_000},
        "order_book": {"imbalance_pct": -35, "pressure": "SELL_HEAVY", "market_state": "TWO_SIDED"},
        "news": [{"title": "توقف نماد اهرم", "category": "توقف نماد"}, {"title": "عدم تایید معاملات", "category": "عدم تایید معاملات"}],
        "indices": None
    }
    wiv_fear = {"wiv_pct": 85}
    # P/C بالا = ترس - باید از DB بیاد ولی برای تست دستی می‌سازیم
    # برای تست، db_path None می‌ذاریم و P/C رو دستی بعدا اضافه می‌کنیم
    analysis_fear = analyze_sentiment(db_path=None, market_data=market_data_fear, wiv_data=wiv_fear, options_data=None)
    # دستی P/C بالا برای تست ترس شدید
    analysis_fear["put_call_ratio"] = {"pc_volume": 1.8, "pc_oi": 1.6, "pc_combined": 1.6, "sentiment": "EXTREME FEAR", "score": 10}
    analysis_fear["components"]["pc"] = analysis_fear["put_call_ratio"]
    analysis_fear["fear_greed"] = compute_fear_greed_iran(analysis_fear["components"])
    print_sentiment_report(analysis_fear, "اهرم - ترس شدید (کف)")

    print("\n--- تست 2: سنتیمنتال با داده ساختگی طمع شدید (سقف) ---")
    market_data_greed = {
        "money_flow": {"net_retail": 1_500_000_000, "net_institutional": -1_500_000_000},
        "order_book": {"imbalance_pct": 40, "pressure": "BUY_HEAVY", "market_state": "LOCKED_BUY_QUEUE"},
        "news": [{"title": "افزایش سرمایه اهرم", "category": "افشای اطلاعات بااهمیت - الف"}],
        "indices": None
    }
    wiv_greed = {"wiv_pct": 25}
    analysis_greed = analyze_sentiment(db_path=None, market_data=market_data_greed, wiv_data=wiv_greed)
    analysis_greed["put_call_ratio"] = {"pc_volume": 0.5, "pc_oi": 0.55, "pc_combined": 0.55, "sentiment": "EXTREME GREED", "score": 90}
    analysis_greed["components"]["pc"] = analysis_greed["put_call_ratio"]
    analysis_greed["fear_greed"] = compute_fear_greed_iran(analysis_greed["components"])
    print_sentiment_report(analysis_greed, "اهرم - طمع شدید (سقف)")

    print("\n--- تست 3: سنتیمنتال خنثی ---")
    market_data_neutral = {
        "money_flow": {"net_retail": 50_000_000, "net_institutional": -50_000_000},
        "order_book": {"imbalance_pct": 5, "pressure": "BALANCED", "market_state": "TWO_SIDED"},
        "news": [],
        "indices": None
    }
    wiv_neutral = {"wiv_pct": 50}
    analysis_neutral = analyze_sentiment(db_path=None, market_data=market_data_neutral, wiv_data=wiv_neutral)
    analysis_neutral["put_call_ratio"] = {"pc_volume": 0.95, "pc_oi": 1.0, "pc_combined": 1.0, "sentiment": "NEUTRAL", "score": 50}
    analysis_neutral["components"]["pc"] = analysis_neutral["put_call_ratio"]
    analysis_neutral["fear_greed"] = compute_fear_greed_iran(analysis_neutral["components"])
    print_sentiment_report(analysis_neutral, "اهرم - خنثی")

    print("\n--- تست 4: با DB واقعی اگر موجود باشد ---")
    import os
    if os.path.exists("ahram_v2.db"):
        # از DB واقعی بخوان
        analysis_real = analyze_sentiment(db_path="ahram_v2.db", market_data={}, wiv_data={"wiv_pct": 55})
        print_sentiment_report(analysis_real, "اهرم - DB واقعی")
