import sqlite3
import os
import sys

# SQL 文件相对于本脚本的位置
sql_file = os.path.join(os.path.dirname(__file__), 'create_price_meta.sql')

# 指定项目根下的 SQLite 文件（与 app.py 中 DB_PATH 保持一致）
# 本脚本位于 c:\zhiguan\migrations\apply_migration.py，
# 所以项目根是其父目录，数据库文件为 c:\zhiguan\zhiguan.db
db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'zhiguan.db')

if not os.path.exists(sql_file):
    print("找不到 SQL 文件:", sql_file)
    sys.exit(1)

print("Applying migration SQL to:", db_path)
with open(sql_file, 'r', encoding='utf-8') as fh:
    sql = fh.read()

conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.executescript(sql)
conn.commit()
conn.close()
print("migrations applied to", db_path)