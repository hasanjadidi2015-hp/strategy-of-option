import sqlite3
from datetime import datetime

import algotik_tse as att

import config


def create_money_flow_table():

    conn = sqlite3.connect(config.DATABASE_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS money_flow (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT,
            buy_retail_volume REAL,
            buy_institutional_volume REAL,
            sell_retail_volume REAL,
            sell_institutional_volume REAL,
            net_retail_volume REAL,
            net_institutional_volume REAL
        )
        """
    )

    conn.commit()
    conn.close()


def fetch_and_save_money_flow():

    create_money_flow_table()

    try:

        market_snapshot = att.get_market_snapshot()
        client_type = att.get_market_client_type()

    except Exception as e:

        print("MONEY FLOW FETCH ERROR:", e)
        return None

    stocks = market_snapshot.get("stocks")

    if stocks is None:

        print("NO MARKET SNAPSHOT DATA")
        return None

    row = stocks[stocks["InsCode"].astype(str) == str(config.INS_CODE)]

    if row.empty:

        print("AHRAM NOT FOUND IN MARKET SNAPSHOT")
        return None

    ins_code = row.iloc[0]["InsCode"]

    ct_row = client_type[
        client_type["InsCode"].astype(str) == str(ins_code)
    ]

    if ct_row.empty:

        print("NO CLIENT TYPE DATA FOR AHRAM")
        return None

    # طبق مستندات algotik_tse: I = حقوقی (Institutional), N = حقیقی (Natural/Retail)
    buy_i = float(ct_row.iloc[0]["Buy_I_Volume"])
    buy_n = float(ct_row.iloc[0]["Buy_N_Volume"])
    sell_i = float(ct_row.iloc[0]["Sell_I_Volume"])
    sell_n = float(ct_row.iloc[0]["Sell_N_Volume"])

    net_institutional = buy_i - sell_i
    net_retail = buy_n - sell_n

    conn = sqlite3.connect(config.DATABASE_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO money_flow
        (
            time,
            buy_retail_volume,
            buy_institutional_volume,
            sell_retail_volume,
            sell_institutional_volume,
            net_retail_volume,
            net_institutional_volume
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            buy_i,
            buy_n,
            sell_i,
            sell_n,
            net_retail,
            net_institutional
        )
    )

    conn.commit()
    conn.close()

    result = {

        "net_retail_volume": net_retail,

        "net_institutional_volume": net_institutional

    }

    print("=" * 50)
    print("MONEY FLOW UPDATED")
    print("NET RETAIL:", net_retail)
    print("NET INSTITUTIONAL:", net_institutional)
    print("=" * 50)

    return result


if __name__ == "__main__":

    print(fetch_and_save_money_flow())