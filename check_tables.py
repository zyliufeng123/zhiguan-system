import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'zhiguan.db')

def rebuild_customers_table():
    """重建 customers 表"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        print("开始重建 customers 表...")
        print()
        
        # 1. 备份旧数据（如果需要）
        cur.execute("SELECT * FROM customers")
        old_data = cur.fetchall()
        if old_data:
            print(f"⚠️  警告：旧表中有 {len(old_data)} 条数据")
            print("   旧数据：", old_data)
            print()
        
        # 2. 删除旧表
        cur.execute("DROP TABLE IF EXISTS customers")
        print("✅ 已删除旧的 customers 表")
        
        # 3. 创建新表
        cur.execute('''CREATE TABLE customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_code VARCHAR(20) UNIQUE NOT NULL,
            customer_name VARCHAR(100) NOT NULL,
            contact_person VARCHAR(50),
            contact_phone VARCHAR(20),
            address TEXT,
            remarks TEXT,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            update_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )''')
        print("✅ 已创建新的 customers 表")
        
        # 4. 创建索引
        cur.execute('CREATE INDEX IF NOT EXISTS idx_customers_name ON customers(customer_name)')
        cur.execute('CREATE INDEX IF NOT EXISTS idx_customers_code ON customers(customer_code)')
        print("✅ 已创建索引")
        
        conn.commit()
        print()
        print("=" * 80)
        print("✅ customers 表重建成功！")
        print("=" * 80)
        
    except Exception as e:
        conn.rollback()
        print(f"❌ 重建失败: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        conn.close()


def check_tables():
    """检查订单系统表是否创建成功"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # 需要检查的表
    tables = [
        'customers', 'suppliers', 'sales_orders', 'sales_order_items',
        'purchase_orders', 'purchase_order_items', 'picking_labels'
    ]
    
    print("=" * 80)
    print("📋 订单系统数据库表检查报告")
    print("=" * 80)
    print()
    
    all_success = True
    
    for table in tables:
        try:
            # 检查表是否存在
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            
            # 获取表结构
            cur.execute(f"PRAGMA table_info({table})")
            columns = cur.fetchall()
            column_names = [col[1] for col in columns]
            
            # 检查字段数是否正确
            expected_fields = {
                'customers': 9,
                'suppliers': 9,
                'sales_orders': 12,
                'sales_order_items': 12,
                'purchase_orders': 12,
                'purchase_order_items': 11,
                'picking_labels': 15
            }
            
            expected = expected_fields.get(table, 0)
            is_correct = len(column_names) == expected
            status = "✅" if is_correct else "⚠️ "
            
            print(f"{status} {table:<25} 存在 | 记录数: {count:>5} | 字段数: {len(column_names):>2}/{expected}")
            print(f"   字段: {', '.join(column_names[:5])}{'...' if len(column_names) > 5 else ''}")
            
            if not is_correct:
                print(f"   ⚠️  警告：字段数不正确！期望 {expected} 个字段")
                all_success = False
            
            print()
            
        except Exception as e:
            print(f"❌ {table:<25} 不存在或错误: {str(e)}")
            print()
            all_success = False
    
    conn.close()
    
    print("=" * 80)
    if all_success:
        print("✅ 所有订单系统表已成功创建且结构正确！")
    else:
        print("❌ 部分表结构不正确，需要重建")
    print("=" * 80)
    
    return all_success


if __name__ == '__main__':
    # 先检查表结构
    all_ok = check_tables()
    
    # 如果 customers 表结构不对，询问是否重建
    if not all_ok:
        print()
        print("检测到 customers 表结构不正确")
        response = input("是否重建 customers 表？(y/n): ")
        
        if response.lower() == 'y':
            print()
            rebuild_customers_table()
            print()
            print("重建完成，再次验证...")
            print()
            check_tables()