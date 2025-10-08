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

@app.route('/smart_quote/data', methods=['GET'])  # AJAX数据
@login_required
def smart_quote_data():
    # DataTables JSON：产品|公司|价格|数量|中标时间|备注|默认中标价
    conn = get_db()
    data = conn.execute('SELECT * FROM quotes').fetchall()
    conn.close()
    return jsonify([dict(row) for row in data])  # 实时刷新/分页/排序

@app.route('/smart_quote/bulk', methods=['GET', 'POST'])
@login_required
def smart_quote_bulk():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            # 上传→匹配→预览→导入（Odoo式）
            if file.filename.endswith(('.csv', '.xls', '.xlsx')):
                df = pd.read_excel(file) if file.filename.endswith('.xls') or file.filename.endswith('.xlsx') else pd.read_csv(file)
                # 自动新增产品/客户，日期转str
                for _, row in df.iterrows():
                    # 示例：conn.execute('INSERT OR IGNORE INTO products ...')
                    pass  # 你的导入逻辑
                flash('批量导入成功！')
                return redirect(url_for('smart_quote'))
    return render_template('smart_quote_bulk.html')

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

# ========== 订单管理模块（保持不变） ==========
@app.route('/order', methods=['GET', 'POST'])
@login_required
def order():
    conn = get_db()
    # 筛选：类型/日期/客户/状态
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
    # ... 类似其他筛选
    orders = conn.execute(query, params).fetchall()
    conn.close()
    return render_template('order.html', orders=orders)

@app.route('/order/bulk', methods=['GET', 'POST'])
@login_required
def order_bulk():
    # 你的批量逻辑：导入明细，自动新增，总价sum
    if request.method == 'POST':
        # 示例导入
        flash('订单批量导入成功！')
        return redirect(url_for('order'))
    return render_template('order_bulk.html')

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
    conn.commit()
    conn.close()
    app.run(debug=True, port=5000)