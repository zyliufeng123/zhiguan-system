import sqlite3, os, re
db = r'C:\zhiguan\zhiguan.db'
if not os.path.exists(db):
    raise SystemExit(f"数据库不存在: {db}")

def normalize(s: str) -> str:
    s = (s or '').strip().lower()
    # 保留括号内说明，去除常见单位与标点（保留中文、字母、数字、括号）
    s = re.sub(r'(kg|g|斤|箱|袋|包|克|千克|公斤)', '', s)
    s = re.sub(r'[^\w\s\(\)\u4e00-\u9fff]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

con = sqlite3.connect(db)
cur = con.cursor()

# 增加列（若已存在则跳过）
cols = [r[1] for r in cur.execute("PRAGMA table_info(products)").fetchall()]
if 'normalized_name' not in cols:
    cur.execute("ALTER TABLE products ADD COLUMN normalized_name TEXT")
    con.commit()

rows = cur.execute("SELECT id, name FROM products").fetchall()
for pid, name in rows:
    nn = normalize(name)
    cur.execute("UPDATE products SET normalized_name=? WHERE id=?", (nn, pid))
con.commit()
con.close()
print(f"已为 {len(rows)} 条 products 记录填充 normalized_name（未创建唯一约束，请先检查重复）")