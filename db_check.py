import sqlite3

DB_PATH = 'zhiguan.db'
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 查表名
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("现有表:", [t[0] for t in tables])

# 假设你的报价表是'quotes'或类似，查行数/样例
try:
    cursor.execute("SELECT COUNT(*) FROM quotes;")
    count = cursor.fetchone()[0]
    print(f"quotes表行数: {count}")
    if count > 0:
        cursor.execute("SELECT * FROM quotes LIMIT 3;")
        sample = cursor.fetchall()
        print("样例数据:", sample)
except sqlite3.OperationalError:
    print("quotes表不存在或列错，试试其他表名如'quote_data'")

conn.close()
