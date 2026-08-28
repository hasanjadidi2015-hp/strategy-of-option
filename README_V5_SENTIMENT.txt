AHRAM AI PRO V5 + Sentiment V2 - LIVE5_CLEAN
=============================================
تاریخ: 2026-08-28

6 موتور V2 فعال:
1. greek_engine_v2.py - یونانی‌ها دقیق (BS)
2. iv_engine_v2.py - IV Rank/Percentile/Regime
3. risk_engine_v2.py - مدیریت ریسک پیشرفته
4. contract_scoring_engine_v2.py - امتیاز 0-100
5. decision_engine_v2.py - انتخاب بهترین قرارداد
6. sentiment_engine_v2.py - Fear & Greed Iran (جدید)

Fear & Greed Iran فرمول:
  P/C Ratio 30% + Money Flow 25% + Order Book 20% + BPI 15% + News 10%
  0-20 = ترس شدید = فرصت خرید
  20-40 = ترس
  40-60 = خنثی
  60-80 = طمع
  80-100 = طمع شدید = هشدار سقف

نمونه واقعی 2026-08-28:
  اهرم 66.5/100 GREED - صف خرید قفل‌شده
  وبملت 71/100 GREED - P/C OI 0.2 همه کال می‌خرن
  شستا 71/100 GREED - P/C OI 0.07

دستور اجرا:
  python ahram_pro_v5.py --test
  python strategy_bridge_v5.py
  python connect_strategy_dashboard_v5.py
  start options_dashboard_AHRAM_LIVE5.html

یا:
  START_LIVE5_ENGINE.bat
  START_LIVE5_DASHBOARD.bat

نکته: سیگنال قدیمی همچنان تصمیم‌گیرنده است تا بک‌تست کامل شود.
Fear & Greed فقط نمایش و هشدار - روی BUY/SELL اثر ندارد.
