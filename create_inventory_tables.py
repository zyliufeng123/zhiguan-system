import sqlite3

conn = sqlite3.connect('zhiguan.db')
cursor = conn.cursor()

# 先删除旧表（如果存在）
print("正在删除旧表...")
cursor.execute('DROP TABLE IF EXISTS inventory')
cursor.execute('DROP TABLE IF EXISTS inbound_records')
cursor.execute('DROP TABLE IF EXISTS outbound_records')
cursor.execute('DROP TABLE IF EXISTS inventory_check')

# 1. 库存主表
print("创建库存主表...")
cursor.execute('''
    CREATE TABLE inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL,
        category TEXT,
        specification TEXT,
        unit TEXT DEFAULT '件',
        current_stock REAL DEFAULT 0,
        safe_stock REAL DEFAULT 0,
        warehouse_location TEXT,
        remarks TEXT,
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(product_name, specification)
    )
''')

# 2. 入库记录表
print("创建入库记录表...")
cursor.execute('''
    CREATE TABLE inbound_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_code TEXT UNIQUE NOT NULL,
        inbound_type TEXT NOT NULL,
        product_name TEXT NOT NULL,
        category TEXT,
        specification TEXT,
        quantity REAL NOT NULL,
        unit TEXT DEFAULT '件',
        purchase_order_code TEXT,
        supplier_name TEXT,
        inbound_date TEXT NOT NULL,
        operator TEXT,
        remarks TEXT,
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# 3. 出库记录表
print("创建出库记录表...")
cursor.execute('''
    CREATE TABLE outbound_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_code TEXT UNIQUE NOT NULL,
        outbound_type TEXT NOT NULL,
        product_name TEXT NOT NULL,
        category TEXT,
        specification TEXT,
        quantity REAL NOT NULL,
        unit TEXT DEFAULT '件',
        sales_order_code TEXT,
        customer_name TEXT,
        outbound_date TEXT NOT NULL,
        operator TEXT,
        remarks TEXT,
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# 4. 库存盘点表
print("创建库存盘点表...")
cursor.execute('''
    CREATE TABLE inventory_check (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        check_code TEXT UNIQUE NOT NULL,
        product_name TEXT NOT NULL,
        specification TEXT,
        book_stock REAL NOT NULL,
        actual_stock REAL NOT NULL,
        difference REAL NOT NULL,
        check_date TEXT NOT NULL,
        checker TEXT,
        status TEXT DEFAULT '待审核',
        remarks TEXT,
        create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# 创建索引
print("创建索引...")
cursor.execute('CREATE INDEX idx_inventory_product ON inventory(product_name)')
cursor.execute('CREATE INDEX idx_inventory_category ON inventory(category)')
cursor.execute('CREATE INDEX idx_inbound_date ON inbound_records(inbound_date)')
cursor.execute('CREATE INDEX idx_inbound_product ON inbound_records(product_name)')
cursor.execute('CREATE INDEX idx_outbound_date ON outbound_records(outbound_date)')
cursor.execute('CREATE INDEX idx_outbound_product ON outbound_records(product_name)')
cursor.execute('CREATE INDEX idx_check_date ON inventory_check(check_date)')

conn.commit()
conn.close()

print("\n✅ 库存管理表创建成功！")
print("=" * 50)
print("已创建以下数据表：")
print("  ✓ inventory (库存主表)")
print("  ✓ inbound_records (入库记录)")
print("  ✓ outbound_records (出库记录)")
print("  ✓ inventory_check (库存盘点)")
print("=" * 50)