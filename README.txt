AHRAM LIVE5 - CLEAN PORTABLE - فقط LIVE5
==========================================

این پکیج فقط داشبورد LIVE5 با 5 موتور V2 است.
هیچ ارتباطی به داشبورد محرمانه اهرم (dashboard.html) ندارد.
فقط یک فایل HTML تولید می‌کند: options_dashboard_AHRAM_LIVE5.html

فایل‌ها:
- options_dashboard_AHRAM.html : قالب اصلی (1.3M)
- strategy_bridge_v5.py : خواندن DB ها + V2 -> JSON
- connect_strategy_dashboard_v5.py : JSON -> LIVE5 HTML
- greek_engine_v2.py, iv_engine_v2.py, risk_engine_v2.py, contract_scoring_engine_v2.py, decision_engine_v2.py : 5 موتور V2
- ahram_v2.db, webmellt.db, shasta.db : دیتابیس‌ها (خالی یا با داده قبلی)
- config.py : تنظیمات نمادها

دستورات دقیق:
--------------
1. START_LIVE5_DASHBOARD.bat : فقط LIVE5 می‌سازد و یک صفحه باز می‌کند
   - هیچ داشبورد دیگری باز نمی‌کند
   - به داشبورد محرمانه دست نمی‌زند

2. START_LIVE5_ENGINE.bat : یک سیکل TSETMC + V2 + LIVE5
   - حتی وقتی بازار بسته است کار می‌کند
   - فقط LIVE5 را آپدیت می‌کند

تست:
-----
START_LIVE5_DASHBOARD.bat
-> باید فقط یک صفحه باز شود: options_dashboard_AHRAM_LIVE5.html
-> پایین صفحه بخش بنفش V5 با 72 قرارداد اهرم

اگر فقط 1 نماد دیدی:
- اول START_LIVE5_ENGINE.bat بزن تا هر 3 DB پر شود

نسخه: V5 CLEAN - بدون دست زدن به پروژه محرمانه
