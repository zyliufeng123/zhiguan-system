import sqlite3

# 连接数据库（如果不存在，会自动创建）
conn = sqlite3.connect('zhiguan.db')
cursor = conn.cursor()

# 创建products表
cursor.execute('''
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL UNIQUE,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
''')

# 创建quotes表
cursor.execute('''
CREATE TABLE IF NOT EXISTS quotes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL,
  source TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(product_id) REFERENCES products(id)
)
''')

# 创建price_meta表
cursor.execute('''
CREATE TABLE IF NOT EXISTS price_meta (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL,
  bid_month TEXT NOT NULL,
  company TEXT NOT NULL,
  price REAL,
  price_type TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(product_id) REFERENCES products(id)
)
''')

# 创建import_tasks表（用于跟踪导入进度）
cursor.execute('''
CREATE TABLE IF NOT EXISTS import_tasks (
  id TEXT PRIMARY KEY,
  temp_id TEXT,
  filename TEXT,
  mapping TEXT,
  conflict_mode TEXT,
  status TEXT,
  total INTEGER DEFAULT 0,
  success INTEGER DEFAULT 0,
  failed INTEGER DEFAULT 0,
  error_msg TEXT,
  created_at TEXT,
  updated_at TEXT
)
''')

# 创建import_errors表（记录导入错误）
cursor.execute('''
CREATE TABLE IF NOT EXISTS import_errors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT,
  row_no INTEGER,
  raw TEXT,
  error_msg TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(task_id) REFERENCES import_tasks(id)
)
''')

# 提交事务
conn.commit()
conn.close()

print("数据库表创建成功！")