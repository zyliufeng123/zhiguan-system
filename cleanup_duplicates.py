import sqlite3
import os

def cleanup_duplicate_quotes():
    """清理 quotes 表中的重复记录，保留最新的"""
    db_path = os.path.join(os.path.dirname(__file__), 'zhiguan.db')
    
    if not os.path.exists(db_path):
        print(f"数据库文件不存在: {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    try:
        print("开始清理重复记录...")
        
        # 查找重复记录（相同产品+公司+日期）
        cur.execute('''
            SELECT product, company, bid_date, COUNT(*) as count, GROUP_CONCAT(id ORDER BY id DESC) as ids
            FROM quotes 
            WHERE product IS NOT NULL AND company IS NOT NULL AND bid_date IS NOT NULL
            GROUP BY product, company, bid_date 
            HAVING COUNT(*) > 1
            ORDER BY count DESC
        ''')
        
        duplicates = cur.fetchall()
        
        if not duplicates:
            print("没有发现重复记录")
            return
        
        total_removed = 0
        
        for product, company, bid_date, count, ids in duplicates:
            id_list = ids.split(',')
            # 保留第一个ID（最新的），删除其余的
            keep_id = id_list[0]
            remove_ids = id_list[1:]
            
            print(f"产品: {product[:20]}{'...' if len(product) > 20 else ''}")
            print(f"  公司: {company}, 日期: {bid_date}")
            print(f"  发现 {count} 条重复记录，保留ID {keep_id}，删除 {len(remove_ids)} 条")
            
            # 删除重复记录
            for remove_id in remove_ids:
                cur.execute("DELETE FROM quotes WHERE id = ?", (remove_id,))
                total_removed += 1
        
        conn.commit()
        print(f"\n清理完成！总共删除了 {total_removed} 条重复记录")
        
        # 显示清理后的统计
        cur.execute("SELECT COUNT(*) FROM quotes")
        remaining = cur.fetchone()[0]
        print(f"清理后剩余记录数: {remaining}")
        
    except Exception as e:
        print(f"清理过程中出错: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    cleanup_duplicate_quotes()