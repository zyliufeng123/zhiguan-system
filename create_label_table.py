import sqlite3

conn = sqlite3.connect('zhiguan.db')
cursor = conn.cursor()

# 先删除旧表（如果存在）
cursor.execute('DROP TABLE IF EXISTS picking_labels')

# 创建新表
cursor.execute('''
    CREATE TABLE picking_labels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label_code TEXT UNIQUE NOT NULL,
        order_id INTEGER NOT NULL,
        order_code TEXT NOT NULL,
        customer_name TEXT NOT NULL,
        product_name TEXT NOT NULL,
        category TEXT,
        specification TEXT,
        quantity REAL NOT NULL,
        unit TEXT DEFAULT '件',
        delivery_date TEXT,
        label_status TEXT DEFAULT '待打印',
        print_count INTEGER DEFAULT 0,
        remarks TEXT,
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        create_user TEXT
    )
''')

# 创建索引
cursor.execute('CREATE INDEX idx_labels_order ON picking_labels(order_id)')
cursor.execute('CREATE INDEX idx_labels_status ON picking_labels(label_status)')

conn.commit()
conn.close()

print("✅ 分拣标签表创建成功！")