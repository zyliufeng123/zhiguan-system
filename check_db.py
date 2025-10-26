import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'zhiguan.db')

def check_database():
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        # 检查quotes表是否存在
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quotes'")
        table_exists = cur.fetchone()
        
        if table_exists:
            print("✅ quotes表存在")
            
            # 检查表结构
            cur.execute("PRAGMA table_info(quotes)")
            columns = cur.fetchall()
            print("表结构：")
            for col in columns:
                print(f"  - {col[1]} ({col[2]})")
                
            # 检查数据数量
            cur.execute("SELECT COUNT(*) FROM quotes")
            count = cur.fetchone()[0]
            print(f"数据条数：{count}")
            
            if count > 0:
                # 显示前几条数据
                cur.execute("SELECT * FROM quotes LIMIT 3")
                rows = cur.fetchall()
                print("前3条数据：")
                for i, row in enumerate(rows):
                    print(f"  第{i+1}条: {row}")
            
        else:
            print("❌ quotes表不存在")
            
            # 查看都有什么表
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cur.fetchall()
            print("现有表：")
            for table in tables:
                print(f"  - {table[0]}")
        
        conn.close()
        
    except Exception as e:
        print(f"数据库检查失败：{e}")

if __name__ == "__main__":
    check_database()