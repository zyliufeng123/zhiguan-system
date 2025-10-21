import sqlite3, os
db = r'C:\zhiguan\zhiguan.db'
con = sqlite3.connect(db)
cur = con.cursor()
cur.execute("""SELECT normalized_name, COUNT(*) as c, GROUP_CONCAT(id) ids
               FROM products GROUP BY normalized_name HAVING c>1""")
dups = cur.fetchall()
if not dups:
    print("无重复 normalized_name")
else:
    print("发现重复 normalized_name：")
    for name, c, ids in dups:
        print(c, name, "ids:", ids)
con.close()