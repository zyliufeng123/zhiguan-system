from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, session
import sqlite3
import pandas as pd
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # 改成随机密钥
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # 如果用SQLAlchemy，暂不

# DB连接（你的zhiguan.db）
DB_PATH = 'zhiguan.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# 登录检查（简单版，admin/123）
def login_required(f):
    def wrap(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # 防护：检查键存在，避免KeyError
        if 'username' not in request.form or 'password' not in request.form:
            flash('表单数据不完整，请重试')
            return render_template('login.html')
        
        username = request.form['username']
        password = request.form['password']
        
        if username == 'admin' and password == '123':
            session['user'] = 'admin'
            flash('登录成功！')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('已登出')
    return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    # 仪表板卡片：统计数据
    conn = get_db()
    quote_count = conn.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]  # 假设表名quotes
    order_count = conn.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    conn.close()
    return render_template('dashboard.html', quotes=quote_count, orders=order_count)

# ========== 智能报价模块（核心修复：确保路由+模板全载） ==========
@app.route('/smart_quote', methods=['GET', 'POST'])
@login_required
def smart_quote():
    conn = get_db()
    # 筛选逻辑（产品/日期/公司）
    product_filter = request.args.get('product', '')
    date_filter = request.args.get('date', '')
    company_filter = request.args.get('company', '')
    
    query = '''
    SELECT * FROM quotes 
    WHERE 1=1 
    '''
    params = []
    if product_filter:
        query += ' AND product LIKE ?'
        params.append(f'%{product_filter}%')
    if date_filter:
        query += ' AND bid_date LIKE ?'
        params.append(f'%{date_filter}%')
    if company_filter:
        query += ' AND company LIKE ?'
        params.append(f'%{company_filter}%')
    
    quotes = conn.execute(query, params).fetchall()
    conn.close()
    
    # 测试点：原有267行数据加载OK，AJAX刷新不影响
    print(f"Loaded {len(quotes)} quotes")  # 调试print
    return render_template('smart_quote.html', quotes=quotes)  # 确保模板路径对

@app.route('/smart_quote/data', methods=['GET'])
def smart_quote_data():  # 无@login_required，AJAX独立session查
    if 'user' not in session:
        return jsonify({"error": "Unauthorized", "data": []}), 401  # JSON 401，防HTML重定向
    try:
        conn = get_db()
        data = conn.execute('SELECT * FROM quotes').fetchall()
        conn.close()
        json_data = [dict(row) for row in data]
        print(f"JSON数据: {len(json_data)} 行")  # 调试：终端看行数
        return jsonify(json_data)  # 纯JSON数组
    except Exception as e:
        print(f"AJAX错误: {e}")  # 终端log
        return jsonify({"error": str(e), "data": []}), 500

@app.route('/smart_quote/bulk', methods=['GET', 'POST'])
@login_required
def smart_quote_bulk():
    if request.method == 'POST':
        step = request.form.get('step', '1')
        if step == '1':  # 上传
            file = request.files.get('file')
            if file and file.filename.lower().endswith(('.csv', '.xls', '.xlsx')):
                try:
                    if file.filename.endswith('.csv'):
                        df = pd.read_csv(file, encoding='utf-8')
                    else:
                        df = pd.read_excel(file)
                    # 日期转str
                    date_cols = [col for col in df.columns if '日期' in col or 'date' in col or 'bid' in col]
                    if date_cols:
                        df[date_cols[0]] = pd.to_datetime(df[date_cols[0]], errors='coerce').dt.strftime('%Y-%m-%d')
                    session['df_data'] = df.to_dict('records')  # 存session
                    session['columns'] = df.columns.tolist()
                    return render_template('smart_quote_bulk.html', columns=df.columns.tolist())
                except Exception as e:
                    flash(f'上传失败: {e}')
            else:
                flash('无效文件')
        elif step == '2':  # 匹配
            df_data = session.get('df_data', [])
            # 映射 (request.form['map_product'] 等重命名df列)
            map_dict = {
                request.form.get('map_product', ''): 'product',
                request.form.get('map_company', ''): 'company',
                request.form.get('map_price', ''): 'price',
                request.form.get('map_qty', ''): 'qty',
                request.form.get('map_date', ''): 'bid_date',
                request.form.get('map_remarks', ''): 'remarks',
                request.form.get('map_bid', ''): 'default_bid'
            }
            # 预览前5行 (转dict，N/A默认)
            preview_table = []
            for row in df_data[:5]:
                preview = {}
                for old_col, new_col in map_dict.items():
                    preview[new_col] = row.get(old_col, 'N/A')
                preview_table.append(preview)
            return render_template('smart_quote_bulk.html', preview_table=preview_table)
        elif step == '3':  # 导入
            df_data = session.get('df_data', [])
            conn = get_db()
            imported = 0
            for row in df_data:
                # 自动新增产品/客户
                product = row.get('产品', row.get('product', ''))
                if product:
                    conn.execute('INSERT OR IGNORE INTO products (name) VALUES (?)', (product,))
                company = row.get('公司', row.get('company', ''))
                if company:
                    conn.execute('INSERT OR IGNORE INTO customers (name) VALUES (?)', (company,))
                # 插quotes (忽略隐藏列，如 if 'hidden' in row: continue)
                conn.execute('''
                    INSERT INTO quotes (product, company, price, qty, bid_date, remarks, default_bid)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (row.get('产品', row.get('product')), row.get('公司', row.get('company')), 
                      row.get('价格', row.get('price')), row.get('数量', row.get('qty')), 
                      row.get('日期', row.get('bid_date')), row.get('备注', row.get('remarks')), 
                      row.get('默认中标价', row.get('default_bid'))))
                imported += 1
            conn.commit()
            conn.close()
            flash(f'成功导入 {imported} 行！')
            session.pop('df_data', None)
            session.pop('columns', None)
            return redirect(url_for('smart_quote'))
    return render_template('smart_quote_bulk.html')  # GET: 步1

@app.route('/formula', methods=['GET', 'POST'])
@login_required
def formula():
    if request.method == 'POST':
        formula_text = request.form['formula']
        # 安全eval：{mid_price}/{qty} 等，sum/avg
        try:
            result = eval(formula_text, {"__builtins__": {}}, {"sum": sum, "avg": lambda x: sum(x)/len(x)})  # 安全
            flash(f'预览结果: {result}')
        except:
            flash('公式错误')
        # 保存到settings表
        conn = get_db()
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('formula', formula_text))
        conn.commit()
        conn.close()
    return render_template('formula.html')

# 操作：编辑/删（AJAX示例）
@app.route('/smart_quote/delete/<int:id>')
@login_required
def delete_quote(id):
    conn = get_db()
    conn.execute('DELETE FROM quotes WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('删除成功')
    return redirect(url_for('smart_quote'))

# ========== 订单管理模块（完整：AJAX列表/筛选/CRUD/批量 + 总价sum/库存联动预备） ==========
from datetime import datetime  # 如果缺，加import

@app.route('/order', methods=['GET', 'POST'])
@login_required
def order():
    conn = get_db()
    # 筛选
    type_filter = request.args.get('type', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    customer_filter = request.args.get('customer', '')
    status_filter = request.args.get('status', '')
    
    query = 'SELECT * FROM orders WHERE 1=1'
    params = []
    if type_filter:
        query += ' AND type = ?'
        params.append(type_filter)
    if date_from:
        query += ' AND date >= ?'
        params.append(date_from)
    if date_to:
        query += ' AND date <= ?'
        params.append(date_to)
    if customer_filter:
        query += ' AND customer LIKE ?'
        params.append(f'%{customer_filter}%')
    if status_filter:
        query += ' AND status = ?'
        params.append(status_filter)
    
    orders = conn.execute(query, params).fetchall()
    
    # 下拉数据
    types = [('销售', '销售'), ('采购', '采购')]
    statuses = [('待确认', '待确认'), ('已确认', '已确认'), ('完成', '完成')]
    customers = conn.execute('SELECT name FROM customers').fetchall()  # 简单list
    
    conn.close()
    # 加这行（计算当前日期）
    from datetime import datetime  # 如果顶部无，加import
    current_date = datetime.now().strftime('%Y-%m-%d')

# 原return改
    return render_template('order.html', orders=orders, types=types, statuses=statuses, customers=customers, current_date=current_date)

@app.route('/order/data', methods=['GET'])
def order_data():
    if 'user' not in session:
        return jsonify({"error": "Unauthorized", "data": []}), 401
    try:
        conn = get_db()
        type_filter = request.args.get('type', '')
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        customer_filter = request.args.get('customer', '')
        status_filter = request.args.get('status', '')
        
        query = 'SELECT * FROM orders WHERE 1=1'
        params = []
        if type_filter:
            query += ' AND type = ?'
            params.append(type_filter)
        if date_from:
            query += ' AND date >= ?'
            params.append(date_from)
        if date_to:
            query += ' AND date <= ?'
            params.append(date_to)
        if customer_filter:
            query += ' AND customer LIKE ?'
            params.append(f'%{customer_filter}%')
        if status_filter:
            query += ' AND status = ?'
            params.append(status_filter)
        
        data = conn.execute(query, params).fetchall()
        conn.close()
        json_data = [dict(row) for row in data]
        print(f"订单JSON数据: {len(json_data)} 行")  # 终端调试
        return jsonify(json_data)
    except Exception as e:
        print(f"订单AJAX错误: {e}")
        return jsonify({"error": str(e), "data": []}), 500

@app.route('/order/add', methods=['POST'])
@login_required
def add_order():
    conn = get_db()
    customer_name = request.form['customer']
    # 自动新增客户
    cursor = conn.execute('SELECT id FROM customers WHERE name = ?', (customer_name,))
    row = cursor.fetchone()
    if not row:
        conn.execute('INSERT INTO customers (name) VALUES (?)', (customer_name,))
        customer_id = conn.lastrowid
    else:
        customer_id = row[0]
    
    # 总价sum（假设明细从form details_json JSON解析）
    details_json = request.form.get('details_json', '[]')
    import json
    details = json.loads(details_json) if details_json else []
    total_price = sum(float(d.get('price', 0) * d.get('qty', 0)) for d in details)
    details_count = len(details)
    
    conn.execute('''
        INSERT INTO orders (type, customer_id, date, total_price, status, details_count)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (request.form['type'], customer_id, request.form['date'], total_price, request.form['status'], details_count))
    
    # 插明细 (order_details表)
    order_id = conn.lastrowid
    for d in details:
        product_name = d['product']
        # 自动新增产品
        cursor = conn.execute('SELECT id FROM products WHERE name = ?', (product_name,))
        p_row = cursor.fetchone()
        if not p_row:
            conn.execute('INSERT INTO products (name) VALUES (?)', (product_name,))
            product_id = conn.lastrowid
        else:
            product_id = p_row[0]
        conn.execute('INSERT INTO order_details (order_id, product_id, qty, price) VALUES (?, ?, ?, ?)',
                     (order_id, product_id, d['qty'], d['price']))
    
    conn.commit()
    conn.close()
    flash('订单新增成功！')
    return redirect(url_for('order'))

@app.route('/order/update/<int:id>', methods=['POST'])
@login_required
def update_order(id):
    conn = get_db()
    # 类似add，更新总价
    details_json = request.form.get('details_json', '[]')
    details = json.loads(details_json)
    total_price = sum(float(d.get('price', 0) * d.get('qty', 0)) for d in details)
    details_count = len(details)
    
    conn.execute('''
        UPDATE orders SET type=?, customer_id=?, date=?, total_price=?, status=?, details_count=?
        WHERE id=?
    ''', (request.form['type'], request.form['customer_id'], request.form['date'], total_price, request.form['status'], details_count, id))
    
    # 更新明细 (删旧加新)
    conn.execute('DELETE FROM order_details WHERE order_id = ?', (id,))
    for d in details:
        # 类似add，自动新增产品
        product_name = d['product']
        cursor = conn.execute('SELECT id FROM products WHERE name = ?', (product_name,))
        p_row = cursor.fetchone()
        if not p_row:
            conn.execute('INSERT INTO products (name) VALUES (?)', (product_name,))
            product_id = conn.lastrowid
        else:
            product_id = p_row[0]
        conn.execute('INSERT INTO order_details (order_id, product_id, qty, price) VALUES (?, ?, ?, ?)',
                     (id, product_id, d['qty'], d['price']))
    
    conn.commit()
    conn.close()
    flash('订单更新成功！')
    return redirect(url_for('order'))

@app.route('/order/delete/<int:id>')
@login_required
def delete_order(id):
    conn = get_db()
    conn.execute('DELETE FROM order_details WHERE order_id = ?', (id,))
    conn.execute('DELETE FROM orders WHERE id = ?', (id,))
    conn.commit()
    conn.close()
    flash('订单删除成功！')
    return redirect(url_for('order'))

@app.route('/order/bulk', methods=['GET', 'POST'])
@login_required
def order_bulk():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            if file.filename.endswith('.csv'):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
            conn = get_db()
            imported = 0
            for _, row in df.iterrows():
                customer_name = row['customer']
                conn.execute('INSERT OR IGNORE INTO customers (name) VALUES (?)', (customer_name,))
                total_price = row['total_price']  # 或sum明细列
                conn.execute('INSERT INTO orders (type, customer, date, total_price, status) VALUES (?, ?, ?, ?, ?)',
                             (row['type'], customer_name, row['date'], total_price, row['status']))
                imported += 1
            conn.commit()
            conn.close()
            flash(f'批量导入 {imported} 订单！')
            return redirect(url_for('order'))
    return render_template('order_bulk.html')  # 向导：上传/预览/导入
    
# ========== 整体导航/错误处理（新增，确保页面不丢） ==========
@app.route('/<path:path>')
@login_required
def catch_all(path):
    flash(f'页面 {path} 未找到，返回仪表板')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    # 创建表（如果缺，首次跑）
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS quotes 
                    (id INTEGER PRIMARY KEY, product TEXT, company TEXT, price REAL, qty INTEGER, 
                     bid_date TEXT, remarks TEXT, default_bid REAL)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS orders 
                    (id INTEGER PRIMARY KEY, type TEXT, customer TEXT, date TEXT, total_price REAL, 
                     status TEXT, details_count INTEGER)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
   # 客户表（订单联表）
    conn.execute('''CREATE TABLE IF NOT EXISTS customers 
                (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
# 样例客户
    conn.execute("INSERT OR IGNORE INTO customers (name) VALUES ('ABC公司')")
    conn.execute("INSERT OR IGNORE INTO customers (name) VALUES ('DEF公司')")
    conn.commit()
    conn.close()
    app.run(debug=True, port=5000)
    # ========== 库存管理模块（新：CRUD + 订单联动） ==========
@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    conn = get_db()
    # 筛选：仓库/分类/产品/日期
    warehouse_filter = request.args.get('warehouse', '')
    category_filter = request.args.get('category', '')
    product_filter = request.args.get('product', '')
    
    query = '''
    SELECT i.*, p.name as product_name, w.name as warehouse_name, c.name as category_name 
    FROM inventory i 
    LEFT JOIN products p ON i.product_id = p.id 
    LEFT JOIN warehouses w ON i.warehouse_id = w.id 
    LEFT JOIN categories c ON i.category_id = c.id 
    WHERE 1=1
    '''
    params = []
    if warehouse_filter:
        query += ' AND w.name LIKE ?'
        params.append(f'%{warehouse_filter}%')
    if category_filter:
        query += ' AND c.name LIKE ?'
        params.append(f'%{category_filter}%')
    if product_filter:
        query += ' AND p.name LIKE ?'
        params.append(f'%{product_filter}%')
    
    items = conn.execute(query, params).fetchall()
    # 仓库/分类/产品下拉数据
    warehouses = conn.execute('SELECT id, name FROM warehouses').fetchall()
    categories = conn.execute('SELECT id, name FROM categories').fetchall()
    products = conn.execute('SELECT id, name FROM products').fetchall()
    conn.close()
    
    # 测试点：原有模块不影响，库存独立
    return render_template('inventory.html', items=items, warehouses=warehouses, categories=categories, products=products)

@app.route('/inventory/data', methods=['GET'])  # AJAX JSON
@login_required
def inventory_data():
    conn = get_db()
    data = conn.execute('''
        SELECT i.*, p.name as product_name, w.name as warehouse_name, c.name as category_name 
        FROM inventory i LEFT JOIN products p ON i.product_id = p.id 
        LEFT JOIN warehouses w ON i.warehouse_id = w.id 
        LEFT JOIN categories c ON i.category_id = c.id 
    ''').fetchall()
    conn.close()
    return jsonify([dict(row) for row in data])

@app.route('/inventory/add', methods=['POST'])
@login_required
def add_inventory():
    conn = get_db()
    conn.execute('''
        INSERT INTO inventory (product_id, warehouse_id, category_id, qty, last_update)
        VALUES (?, ?, ?, ?, ?)
    ''', (request.form['product_id'], request.form['warehouse_id'], request.form['category_id'], 
          request.form['qty'], datetime.now().strftime('%Y-%m-%d')))
    conn.commit()
    conn.close()
    flash('库存新增成功！')
    return redirect(url_for('inventory'))

@app.route('/inventory/update/<int:id>', methods=['POST'])
@login_required
def update_inventory(id):
    conn = get_db()
    conn.execute('''
        UPDATE inventory SET product_id=?, warehouse_id=?, category_id=?, qty=?, last_update=?
        WHERE id=?
    ''', (request.form['product_id'], request.form['warehouse_id'], request.form['category_id'], 
          request.form['qty'], datetime.now().strftime('%Y-%m-%d'), id))
    conn.commit()
    conn.close()
    flash('库存更新成功！')
    return redirect(url_for('inventory'))

@app.route('/inventory/delete/<int:id>')
@login_required
def delete_inventory(id):
    conn = get_db()
    conn.execute('DELETE FROM inventory WHERE id=?', (id,))
    conn.commit()
    conn.close()
    flash('库存删除成功！')
    return redirect(url_for('inventory'))

# 订单确认时联动：扣/增QTY（示例：在order确认路由加钩子）
# e.g., 在order() POST确认时：
# conn.execute('UPDATE inventory SET qty = qty - ? WHERE product_id = ? AND warehouse_id = ?', (details_qty, product_id, warehouse_id))
# 负库存闪警戒：if new_qty < 0: flash('低库存警戒！')

# DB表创建（加到if __name__ CREATE后）
conn = get_db()
conn.execute('''CREATE TABLE IF NOT EXISTS warehouses 
                (id INTEGER PRIMARY KEY, name TEXT)''')
conn.execute('''CREATE TABLE IF NOT EXISTS categories 
                (id INTEGER PRIMARY KEY, name TEXT)''')
conn.execute('''CREATE TABLE IF NOT EXISTS inventory 
                (id INTEGER PRIMARY KEY, product_id INTEGER, warehouse_id INTEGER, category_id INTEGER, 
                 qty INTEGER, last_update TEXT)''')
# 样例数据
conn.execute("INSERT OR IGNORE INTO warehouses (id, name) VALUES (1, '主仓库'), (2, '备用仓')")
conn.execute("INSERT OR IGNORE INTO categories (id, name) VALUES (1, '电子'), (2, '家电')")
conn.execute("INSERT OR IGNORE INTO products (id, name) VALUES (1, '苹果手机'), (2, '三星电视')")
conn.execute("INSERT OR IGNORE INTO inventory (product_id, warehouse_id, category_id, qty, last_update) VALUES (1, 1, 1, 100, '2025-10-08')")
conn.commit()
conn.close()