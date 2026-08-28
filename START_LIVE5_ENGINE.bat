@echo off
echo AHRAM LIVE5 V5 + Sentiment - One cycle test
echo Fetching TSETMC + 6 V2 engines including Fear & Greed Iran...
echo Market closed outside Sat-Wed 09:00-12:30 is normal
python ahram_pro_v5.py --test
python strategy_bridge_v5.py
python connect_strategy_dashboard_v5.py
echo Done - Opening LIVE5 with Fear & Greed...
start options_dashboard_AHRAM_LIVE5.html
pause
