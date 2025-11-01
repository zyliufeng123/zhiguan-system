import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'zhiguan.db')

def verify_import_tables():
    """验证导入配置表是否创建成功"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    print("=" * 80)
    print("📋 通用批量导入数据库表验证报告")
    print("=" * 80)
    print()
    
    # 需要检查的表
    tables = ['import_config', 'import_config_fields']
    
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
            
            print(f"✅ {table:<30} 存在 | 记录数: {count:>5} | 字段数: {len(column_names):>2}")
            print(f"   字段: {', '.join(column_names[:5])}{'...' if len(column_names) > 5 else ''}")
            print()
            
        except Exception as e:
            print(f"❌ {table:<30} 不存在或错误: {str(e)}")
            print()
            all_success = False
    
    # 检查索引
    print("检查索引:")
    cur.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_import%'")
    indexes = cur.fetchall()
    for idx in indexes:
        print(f"  ✅ {idx[0]}")
    print()
    
    conn.close()
    
    print("=" * 80)
    if all_success:
        print("✅ 所有导入配置表已成功创建！")
    else:
        print("❌ 部分表创建失败")
    print("=" * 80)
    
    return all_success


if __name__ == '__main__':
    verify_import_tables()