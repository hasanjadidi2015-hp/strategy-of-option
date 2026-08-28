# -*- coding: utf-8 -*-
# AHRAM AI V2 CONFIG - نسخه نهایی

INS_CODE = "17914401175772326"
DATABASE_NAME = "ahram_v2.db"
UPDATE_INTERVAL = 300
EMA_FAST = 9
EMA_SLOW = 21
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_PERIOD = 14
RISK_REWARD = 2.0
RISK_PER_TRADE = 0.05
INITIAL_CAPITAL = 100000000
COMMISSION = 0.0015
MIN_CONFIDENCE = 40
STOP_LOSS_PERCENT = 0.02
TAKE_PROFIT_PERCENT = 0.04
UNDERLYING = "اهرم"
OPTION_ROOT = "هرم"
MARKET_WATCH_URL = "https://old.tsetmc.com/tsev2/data/MarketWatchInit.aspx?h=0&r=0"
OPTION_TYPE = "CALL"
OPTION_MIN_VOLUME = 5000
STRIKE_RATIO_MIN = 0.90
STRIKE_RATIO_MAX = 1.10
OPTION_MIN_DAYS = 7
BLACK_SCHOLES_VOL = 0.90
RISK_FREE_RATE = 0.30
SIGNAL_ONLY = True
TRADING_MODE = "scalping"
MIN_ALIGNED_INDICATORS = 4
BUY_THRESHOLD = 45
SELL_THRESHOLD = -45
COMPOSITE_BUY_THRESHOLD = 50
MOMENTUM_LOOKBACK = 5
MOMENTUM_THRESHOLD = 0.4
MOMENTUM_BONUS = 12

# ===== تنظیمات صف =====
QUEUE_GAP_MIN = 1.5

# ===== نمادها (با دامنه نوسان صحیح) =====
SYMBOLS = [
    {"name": "اهرم", "ins_code": "17914401175772326", "db": "ahram_v2.db", "option_root": "هرم", "queue_gap": 4.0},
    {"name": "وبملت", "ins_code": "778253364357513", "db": "webmellt.db", "option_root": "ملت", "queue_gap": 3.0},
    {"name": "شستا", "ins_code": "2400322364771558", "db": "shasta.db", "option_root": "ستا", "queue_gap": 3.0},
    {"name": "فملی", "ins_code": "35425587644337450", "db": "fameli.db", "option_root": "ملی", "queue_gap": 3.0},
]