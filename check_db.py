import sqlite3, os, sys
db = r'C:\zhiguan\zhiguan.db'
if not os.path.exists(db):
    print("数据库文件不存在：", db)
    sys.exit(1)
con = sqlite3.connect(db)
cur = con.cursor()
print("Tables:")
for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(" -", row[0])
print("\nSchemas:")
for row in cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
    print("\n==", row[0], "==")
    print(row[1])
con.close()