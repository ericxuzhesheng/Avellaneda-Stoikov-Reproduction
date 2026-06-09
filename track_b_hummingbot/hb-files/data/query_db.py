import glob
import sqlite3

for f in sorted(glob.glob("data/*.sqlite")):
    con = sqlite3.connect(f)
    try:
        tables = [r[0] for r in con.execute(
            "select name from sqlite_master where type='table'").fetchall()]
        n = 0
        if "TradeFill" in tables:
            n = con.execute("select count(*) from TradeFill").fetchone()[0]
        print(f"{f}: TradeFill rows = {n}")
        if n:
            rows = con.execute(
                "select timestamp, trade_type, price, amount from TradeFill "
                "order by timestamp limit 5").fetchall()
            for r in rows:
                print("   ", r)
    finally:
        con.close()
