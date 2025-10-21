import sqlite3, os, sys
db = r'C:\zhiguan\zhiguan.db'
if not os.path.exists(db):
    print("数据库不存在：", db); sys.exit(1)
con = sqlite3.connect(db)
cur = con.cursor()
cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_normalized_name ON products(normalized_name);")
con.commit()
con.close()
print("索引已创建：idx_products_normalized_name")