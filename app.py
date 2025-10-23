from datetime import datetime
from functools import wraps
import os
import re
import uuid
import json
import logging
import sqlite3
import concurrent.futures
import threading
import tempfile
import time
from werkzeug.utils import secure_filename
from flask import Flask, session, request, redirect, url_for, render_template, flash, jsonify

try:
    import pandas as pd
except ImportError:
    pd = None
    print("警告: pandas未安装，部分功能将不可用")

# 可选模糊匹配库，若未安装回退到 difflib（返回 0-100）
try:
    from rapidfuzz import fuzz as _rf_fuzz
except Exception:
    import difflib
    def _rf_fuzz(a, b):
        return int(difflib.SequenceMatcher(None, str(a or ''), str(b or '')).ratio() * 100)

# 日志与上传目录
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 应用常量定义
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 兼容/占位项
_AEVAL_AVAILABLE = False
Interpreter = None

# Flask app（若文件已定义 app，此处不覆盖）
# 确保静态分析能看到 app 的定义：若全局已有 app 则使用，否则创建一个 Flask 实例
if 'app' not in globals() or globals().get('app') is None:
    app = Flask(__name__)
app.config.setdefault('UPLOAD_FOLDER', UPLOAD_FOLDER)

# 添加：会话密钥与上传限制（请在生产环境通过环境变量设置 SECRET_KEY）
import secrets
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config.setdefault('MAX_CONTENT_LENGTH', MAX_UPLOAD_SIZE)

# 数据库路径与简单 get_db 实现
DB_PATH = os.path.join(os.path.dirname(__file__), 'zhiguan.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

_get_conn = get_db

def _locate_temp_file(temp_id: str):
    """在 UPLOAD_FOLDER 中按前缀查找上传的临时文件路径"""
    if not temp_id:
        return None
    for fn in os.listdir(UPLOAD_FOLDER):
        if fn.startswith(temp_id):
            return os.path.join(UPLOAD_FOLDER, fn)
    return None

def _parse_number(v):
    """清理字符串并尝试解析为 float，失败返回 None"""
    if v is None:
        return None
    try:
        s = str(v).strip()
        s = re.sub(r'[^\d\.\-]', '', s)
        if s == '':
            return None
        return float(s)
    except Exception:
        return None

# 简单占位登录装饰器（若项目已有认证逻辑，请替换）
def login_required(f):
    @wraps(f)
    def _wrap(*a, **kw):
        return f(*a, **kw)
    return _wrap

# --- 新增：基础变量与工具函数（必须） ---
# 上传/临时相关常量（放在 imports 之后、app.config 使用之前）
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
ALLOWED_IMPORT_EXT = {'csv', 'xls', 'xlsx'}
TMP_PREFIX = 'zhiguan_'
TMP_EXPIRE_SECONDS = 24 * 3600  # 24 小时

# 轻量异步执行器
_IMPORT_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2)
# 导入任务并发控制（避免同时太多大文件）
_IMPORT_LOCK = threading.Lock()

def cleanup_tmp_files():
    tmpdir = tempfile.gettempdir()
    now = time.time()
    for name in os.listdir(tmpdir):
        if name.startswith(TMP_PREFIX) and name.endswith('.pkl'):
            path = os.path.join(tmpdir, name)
            try:
                if now - os.path.getmtime(path) > TMP_EXPIRE_SECONDS:
                    os.remove(path)
                    logger.info(f"已清理旧临时文件: {path}")
            except Exception:
                pass

cleanup_tmp_files()

# 登录装饰器（使用 wraps 保留函数元信息）
def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return wrap

# 安全表达式解释器（若安装 asteval，使用之；否则受限 eval）
if _AEVAL_AVAILABLE:
    aeval = Interpreter(usersyms={'sum': sum, 'avg': lambda x: sum(x)/len(x) if x else 0})
else:
    aeval = None
    logger.warning("asteval 未安装，formula 将使用受限 eval（推荐安装 asteval）")

def normalize_product_name(name: str) -> str:
    """
    归一化产品名（保留括号内说明）。
    去除常见单位/词，保留中文字母数字和括号，合并多空格，返回小写字符串。
    """
    if not name:
        return ''
    s = str(name).strip().lower()
    # 去掉括号及其内容
    s = re.sub(r'[\(\（].*?[\)\）]', '', s)
    # 去掉单位/常见词
    s = re.sub(r'\b(kg|g|斤|箱|袋|包|克|千克|公斤|kg\.)\b', '', s)
    # 仅保留字母数字、中文、空格和括号
    s = re.sub(r'[^\w\s\(\)\u4e00-\u9fff]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def fuzzy_ratio(a: str, b: str) -> float:
    if _rf_fuzz is not None:
        try:
            return _rf_fuzz.ratio(a, b)
        except Exception:
            pass
    # 回退到 difflib（返回 0-100）
    return int(difflib.SequenceMatcher(None, a, b).ratio() * 100)

def fuzzy_match_product(normalized_name: str, threshold: int = 90, limit: int = 3):
    """
    在 products 表中按 normalized_name 先做精确查找，再模糊匹配返回候选列表：
    返回 [(product_id, name, normalized_name, score), ...]
    """
    if not normalized_name:
        return []
    conn = _get_conn()
    cur = conn.cursor()
    # 精确匹配 normalized_name
    cur.execute("SELECT id, name, COALESCE(normalized_name, '') FROM products WHERE normalized_name = ?", (normalized_name,))
    row = cur.fetchone()
    if row:
        conn.close()
        return [(row[0], row[1], row[2], 100)]
    # 拉取所有候选 normalized_name
    cur.execute("SELECT id, name, COALESCE(normalized_name, '') FROM products")
    rows = cur.fetchall()
    cand = []
    for r in rows:
        pid, pname, pnorm = r
        score = fuzzy_ratio(normalized_name, pnorm or pname or '')
        if score >= threshold:
            cand.append((pid, pname, pnorm, int(score)))
    cand.sort(key=lambda x: x[3], reverse=True)
    conn.close()
    return cand[:limit]

def to_bid_month(s: str, global_month: str = None) -> str:
    """
    将字符串或全局值转为 YYYY-MM，优先解析行值，失败时使用 global_month。
    """
    if s:
        s = str(s).strip()
        for fmt in ('%Y-%m-%d','%Y/%m/%d','%Y.%m.%d','%Y-%m','%Y/%m','%Y.%m','%Y'):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime('%Y-%m')
            except Exception:
                continue
    if global_month:
        try:
            gm = str(global_month).strip()
            if len(gm) >= 7:
                return gm[:7]
            dt = datetime.strptime(gm, '%Y%m')
            return dt.strftime('%Y-%m')
        except Exception:
            pass
    return ''

# ========== 路由：登录/登出 ==========
@app.route('/')
def index():
    # 渲染现有的 dashboard 模板（若不存在可改为其他）
    try:
        return render_template('dashboard.html')
    except Exception:
        return "Dashboard 模板不存在或渲染出错", 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username') or 'user'
        session['user'] = username
        flash('已登录：' + username)
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    flash('已登出')
    return redirect(url_for('login'))

# 添加这个缺失的dashboard路由
@app.route('/dashboard')
@login_required
def dashboard():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 获取基础统计数据
        try:
            quote_count = cur.execute('SELECT COUNT(*) FROM quotes').fetchone()[0]
        except:
            quote_count = 0
            
        try:
            order_count = cur.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
        except:
            order_count = 0
            
        conn.close()
        
        return render_template('dashboard.html', quotes=quote_count, orders=order_count)
    except Exception as e:
        return f"Dashboard页面: {str(e)}", 500


# ========== 智能报价（页面/数据/批量） ==========
@app.route('/smart_quote')
@login_required
def smart_quote():
    conn = get_db()
    product_filter = request.args.get('product', '')
    date_filter = request.args.get('date', '')
    company_filter = request.args.get('company', '')
    query = 'SELECT * FROM quotes WHERE 1=1'
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
    return render_template('smart_quote.html', quotes=quotes)

@app.route('/smart_quote/data')
@login_required
def smart_quote_data():
    try:
        conn = get_db()
        rows = conn.execute('SELECT * FROM quotes').fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        logger.exception("smart_quote/data 错误")
        return jsonify({"error": str(e)}), 500

# 批量导入（上传 -> 映射 -> 导入）
@app.route('/smart_quote/bulk', methods=['GET','POST'])
@login_required
def smart_quote_bulk():
    if request.method == 'GET':
        return render_template('smart_quote_bulk.html')
    
    # POST请求处理 - 处理文件上传
    try:
        if 'file' not in request.files:
            flash('未选择文件')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('未选择文件')
            return redirect(request.url)
        
        if file and file.filename.lower().endswith(('.csv', '.xlsx', '.xls')):
            # 生成临时文件ID
            temp_id = f"quote_{int(time.time())}_{secrets.token_hex(8)}"
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_FOLDER, f"{temp_id}_{filename}")
            file.save(filepath)
            
            # 读取文件预览数据
            try:
                if filename.lower().endswith('.csv'):
                    df = pd.read_csv(filepath, encoding='utf-8', nrows=5)
                else:
                    df = pd.read_excel(filepath, nrows=5)
                
                columns = df.columns.tolist()
                preview_data = df.head().to_dict('records')
                
                # 获取已有公司列表
                conn = get_db()
                companies = conn.execute('SELECT DISTINCT company FROM quotes WHERE company IS NOT NULL AND company != ""').fetchall()
                company_list = [row['company'] for row in companies]
                conn.close()
                
                # 生成年份选项（当前年份前后5年）
                current_year = datetime.now().year
                years = list(range(current_year - 5, current_year + 6))
                months = list(range(1, 13))
                
                return render_template('smart_quote_bulk.html', 
                                     show_mapping=True,
                                     temp_id=temp_id,
                                     columns=columns,
                                     preview_data=preview_data,
                                     companies=company_list,
                                     years=years,
                                     months=months,
                                     current_year=current_year,
                                     current_month=datetime.now().month)
                
            except Exception as e:
                flash(f'文件读取失败: {str(e)}')
                return redirect(request.url)
        else:
            flash('仅支持 CSV、Excel 文件')
            return redirect(request.url)
            
    except Exception as e:
        flash(f'上传失败: {str(e)}')
        return redirect(request.url)
    
@app.route('/api/companies')
@login_required
def api_companies():
    q = request.args.get('q', '')
    conn = get_db()
    if q:
        rows = conn.execute('SELECT name FROM customers WHERE name LIKE ?', (f'%{q}%',)).fetchall()
    else:
        rows = conn.execute('SELECT name FROM customers').fetchall()
    conn.close()
    return jsonify([r['name'] for r in rows])

@app.route('/api/smart_quotes/<int:qid>')
@login_required
def api_smart_quote_get(qid):
    conn = get_db()
    row = conn.execute('SELECT * FROM quotes WHERE id=?', (qid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))

@app.route('/api/smart_quotes/edit', methods=['POST'])
@login_required
def api_smart_quote_edit():
    payload = request.get_json() or {}
    qid = payload.get('id')
    data = payload.get('data', {})
    if not qid:
        return jsonify({"success": False, "error": "missing id"}), 400
    conn = get_db()
    conn.execute('UPDATE quotes SET company=?, price=?, qty=?, bid_date=?, remarks=?, default_bid=? WHERE id=?',
                 (data.get('company'), data.get('price'), data.get('qty'), data.get('bid_date'), data.get('remarks'), data.get('default_bid'), qid))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/api/smart_quotes/delete', methods=['POST'])
@login_required
def api_smart_quote_delete():
    payload = request.get_json() or {}
    qid = payload.get('id')
    if not qid:
        return jsonify({"success": False, "error": "missing id"}), 400
    conn = get_db()
    conn.execute('DELETE FROM quotes WHERE id=?', (qid,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route('/smart_quote/bulk/import', methods=['POST'])
@login_required
def smart_quote_bulk_import():
    """处理智能报价批量导入的映射配置"""
    try:
        # 获取表单数据
        temp_id = request.form.get('temp_id')
        product_col = request.form.get('product_col')
        price_col = request.form.get('price_col')  # 现在是中标价格
        qty_col = request.form.get('qty_col')     # 现在是预计用量
        
        # 获取手动输入的数据
        company_name = request.form.get('company_name')
        bid_year = request.form.get('bid_year')
        bid_month = request.form.get('bid_month')
        conflict_mode = request.form.get('conflict_mode', 'skip')

        # 参数验证
        if not all([temp_id, product_col, price_col, company_name, bid_year, bid_month]):
            flash('请完整填写必填字段（产品列、中标价格列、公司名称、中标年月）')
            return redirect(url_for('smart_quote_bulk'))
        
        # 查找临时文件
        filepath = _locate_temp_file(temp_id)
        if not filepath:
            flash('临时文件不存在或已过期，请重新上传')
            return redirect(url_for('smart_quote_bulk'))
        
        # 格式化中标日期 - 修复字符串格式化问题
        bid_date = f"{bid_year}-{int(bid_month):02d}-01"  # 统一使用月份第一天
        
        # 处理导入
        result = process_smart_quote_import_new(
            filepath, product_col, price_col, qty_col,
            company_name, bid_date, conflict_mode
        )
        
        # 导入结果反馈
        if result['success']:
            flash(f'导入完成！成功: {result["success_count"]} 条，跳过: {result["skip_count"]} 条，失败: {result["error_count"]} 条')
        else:
            flash(f'导入失败: {result["error"]}')
            
        return redirect(url_for('smart_quote'))
        
    except Exception as e:
        logger.exception("批量导入错误")
        flash(f'导入失败: {str(e)}')
        return redirect(url_for('smart_quote_bulk'))

# ========== 公式（安全执行） ==========
@app.route('/formula', methods=['GET', 'POST'])
@login_required
def formula():
    if request.method == 'POST':
        formula_text = request.form.get('formula', '')
        # 限制字符集（简单防护）
        allowed = set("0123456789+-*/()., _[]abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
        if not set(formula_text) <= allowed:
            flash('公式包含不允许的字符')
        else:
            try:
                if aeval is not None:
                    result = aeval(formula_text)
                else:
                    # 受限 eval（仅提供 sum/avg）
                    result = eval(formula_text, {"__builtins__": {}}, {"sum": sum, "avg": lambda x: sum(x)/len(x) if x else 0})
                flash(f'预览结果: {result}')
            except Exception as e:
                logger.exception("公式解析失败")
                flash('公式解析失败')
        conn = get_db()
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', ('formula', formula_text))
        conn.commit()
        conn.close()
    return render_template('formula.html')

@app.route('/formula/editor', methods=['GET', 'POST'])
@login_required
def formula_editor():
    """
    公式编辑（原位页已移除）。GET 显示编辑器，POST 用于保存/测试表达式（简单回显/测试）。
    """
    result = None
    error = None
    expr = ''
    if request.method == 'POST':
        expr = request.form.get('formula','').strip()
        # 测试计算（如果安装了 asteval 则使用，否则仅回显）
        if expr:
            try:
                if _AEVAL_AVAILABLE:
                    aeval = Interpreter()
                    val = aeval(expr)
                    result = val
                else:
                    result = '（未安装 asteval，仅回显）' + expr
            except Exception as e:
                error = str(e)
    return render_template('formula.html', formula=expr, result=result, error=error)

# ========== 订单模块（含 JSON API） ==========
@app.route('/order')
@login_required
def order():
    conn = get_db()
    type_filter = request.args.get('type', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    customer_filter = request.args.get('customer', '')
    status_filter = request.args.get('status', '')
    query = 'SELECT * FROM orders WHERE 1=1'
    params = []
    if type_filter:
        query += ' AND type = ?'; params.append(type_filter)
    if date_from:
        query += ' AND date >= ?'; params.append(date_from)
    if date_to:
        query += ' AND date <= ?'; params.append(date_to)
    if customer_filter:
        query += ' AND customer LIKE ?'; params.append(f'%{customer_filter}%')
    if status_filter:
        query += ' AND status = ?'; params.append(status_filter)
    orders = conn.execute(query, params).fetchall()
    types = [('销售','销售'), ('采购','采购')]
    statuses = [('待确认','待确认'), ('已确认','已确认'), ('完成','完成')]
    customers = conn.execute('SELECT id, name FROM customers').fetchall()
    conn.close()
    return render_template('order.html', orders=orders, types=types, statuses=statuses, customers=customers, current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/order/data')
@login_required
def order_data():
    try:
        conn = get_db()
        data = conn.execute('SELECT * FROM orders').fetchall()
        conn.close()
        return jsonify([dict(r) for r in data])
    except Exception as e:
        logger.exception("order/data 错误")
        return jsonify({"error": str(e)}), 500

@app.route('/order/add', methods=['POST'])
@login_required
def add_order():
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        details_json = data.get('details_json') or '[]'
        details = json.loads(details_json)
        total_price = sum(float(d.get('price',0))*float(d.get('qty',0)) for d in details)
        conn = get_db()
        conn.execute('INSERT INTO orders (type, customer, date, total_price, status, details_count) VALUES (?, ?, ?, ?, ?, ?)',
                     (data.get('type'), data.get('customer'), data.get('date'), total_price, data.get('status'), len(details)))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("新增订单失败")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/order/update/<int:oid>', methods=['POST'])
@login_required
def update_order(oid):
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        details = json.loads(data.get('details_json','[]'))
        total_price = sum(float(d.get('price',0))*float(d.get('qty',0)) for d in details)
        conn = get_db()
        conn.execute('UPDATE orders SET type=?, customer=?, date=?, total_price=?, status=?, details_count=? WHERE id=?',
                     (data.get('type'), data.get('customer'), data.get('date'), total_price, data.get('status'), len(details), oid))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("更新订单失败")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/order/delete/<int:oid>')
@login_required
def delete_order(oid):
    conn = get_db()
    conn.execute('DELETE FROM order_details WHERE order_id=?', (oid,))
    conn.execute('DELETE FROM orders WHERE id=?', (oid,))
    conn.commit()
    conn.close()
    flash('订单删除成功')
    return redirect(url_for('order'))

@app.route('/order/bulk', methods=['GET','POST'])
@login_required
def order_bulk():
    if request.method == 'POST':
        if pd is None:
            flash('缺少 pandas，无法处理文件')
            return redirect(url_for('order_bulk'))
        file = request.files.get('file')
        if not file:
            flash('未选中文件')
            return redirect(url_for('order_bulk'))
        try:
            if file.filename.lower().endswith('.csv'):
                df = pd.read_csv(file)
            else:
                df = pd.read_excel(file)
            conn = get_db()
            imported = 0
            for _, r in df.iterrows():
                customer_name = r.get('customer') or r.get('客户') or ''
                conn.execute('INSERT OR IGNORE INTO customers (name) VALUES (?)', (customer_name,))
                conn.execute('INSERT INTO orders (type, customer, date, total_price, status) VALUES (?, ?, ?, ?, ?)',
                             (r.get('type'), customer_name, r.get('date'), r.get('total_price') or 0, r.get('status')))
                imported += 1
            conn.commit()
            conn.close()
            flash(f'成功导入 {imported} 订单')
            return redirect(url_for('order'))
        except Exception as e:
            logger.exception("order bulk 错误")
            flash(f'导入失败: {e}')
    return render_template('order_bulk.html')

# ========== 整体导航/错误处理（新增，确保页面不丢） ==========
@app.errorhandler(404)
def page_not_found(e):
    # 简单统一处理：闪现消息并返回仪表盘
    flash('请求的页面未找到，已返回仪表盘')
    return redirect(url_for('dashboard'))

# ========== 库存模块（兼容 JSON） ==========
@app.route('/inventory')
@login_required
def inventory():
    conn = get_db()
    warehouse_filter = request.args.get('warehouse','')
    category_filter = request.args.get('category','')
    product_filter = request.args.get('product','')
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
        query += ' AND w.name LIKE ?'; params.append(f'%{warehouse_filter}%')
    if category_filter:
        query += ' AND c.name LIKE ?'; params.append(f'%{category_filter}%')
    if product_filter:
        query += ' AND p.name LIKE ?'; params.append(f'%{product_filter}%')
    items = conn.execute(query, params).fetchall()
    warehouses = conn.execute('SELECT id, name FROM warehouses').fetchall()
    categories = conn.execute('SELECT id, name FROM categories').fetchall()
    products = conn.execute('SELECT id, name FROM products').fetchall()
    conn.close()
    return render_template('inventory.html', items=items, warehouses=warehouses, categories=categories, products=products)

@app.route('/inventory/data')
@login_required
def inventory_data():
    conn = get_db()
    rows = conn.execute('''
        SELECT i.*, p.name as product_name, w.name as warehouse_name, c.name as category_name
        FROM inventory i
        LEFT JOIN products p ON i.product_id = p.id
        LEFT JOIN warehouses w ON i.warehouse_id = w.id
        LEFT JOIN categories c ON i.category_id = c.id
    ''').fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/inventory/add', methods=['POST'])
@login_required
def add_inventory():
    try:
        if request.is_json:
            data = request.get_json()
            pid = data.get('product_id')
            wid = data.get('warehouse_id')
            cid = data.get('category_id')
            qty = data.get('qty')
        else:
            pid = request.form.get('product_id')
            wid = request.form.get('warehouse_id')
            cid = request.form.get('category_id')
            qty = request.form.get('qty')
        conn = get_db()
        conn.execute('INSERT INTO inventory (product_id, warehouse_id, category_id, qty, last_update) VALUES (?, ?, ?, ?, ?)',
                     (pid, wid, cid, qty, datetime.now().strftime('%Y-%m-%d')))
        conn.commit()
        conn.close()
        if request.is_json:
            return jsonify({"success": True})
        flash('库存新增成功')
        return redirect(url_for('inventory'))
    except Exception as e:
        logger.exception("inventory add 错误")
        if request.is_json:
            return jsonify({"success": False, "error": str(e)}), 500
        flash(f'新增失败: {e}')
        return redirect(url_for('inventory'))

@app.route('/inventory/update/<int:iid>', methods=['POST'])
@login_required
def update_inventory(iid):
    try:
        pid = request.form.get('product_id')
        wid = request.form.get('warehouse_id')
        cid = request.form.get('category_id')
        qty = request.form.get('qty')
        conn = get_db()
        conn.execute('UPDATE inventory SET product_id=?, warehouse_id=?, category_id=?, qty=?, last_update=? WHERE id=?',
                     (pid, wid, cid, qty, datetime.now().strftime('%Y-%m-%d'), iid))
        conn.commit()
        conn.close()
        flash('库存更新成功')
        return redirect(url_for('inventory'))
    except Exception as e:
        logger.exception("inventory update 错误")
        flash(f'更新失败: {e}')
        return redirect(url_for('inventory'))

@app.route('/inventory/delete/<int:iid>')
@login_required
def delete_inventory(iid):
    conn = get_db()
    conn.execute('DELETE FROM inventory WHERE id=?', (iid,))
    conn.commit()
    conn.close()
    flash('库存删除成功')
    return redirect(url_for('inventory'))

@app.route('/pivot')
@login_required
def pivot():
    # 若需从 DB 读取数据，可替换下面的空数组
    try:
        conn = get_db()
        rows = conn.execute('SELECT * FROM quotes LIMIT 100').fetchall()
        conn.close()
        data = [dict(r) for r in rows]
    except Exception:
        data = []
    return render_template('pivot.html', data=data)

@app.route('/settings')
@login_required
def settings():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 获取所有设置
        cur.execute('SELECT * FROM settings')
        settings_dict = {row['key']: row['value'] for row in cur.fetchall()}
        
        conn.close()
        return render_template('settings.html', settings=settings_dict)
    except Exception as e:
        return f"设置页面: {str(e)}", 500
    
    # 添加缺失的import_upload_page路由
@app.route('/import')
@login_required
def import_upload_page():
    return render_template('import_upload.html')

# 启动时确保表存在
def ensure_tables():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS quotes 
                    (id INTEGER PRIMARY KEY, product TEXT, company TEXT, price REAL, qty INTEGER, 
                     bid_date TEXT, remarks TEXT, default_bid REAL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS orders 
                    (id INTEGER PRIMARY KEY, type TEXT, customer TEXT, date TEXT, total_price REAL, 
                     status TEXT, details_count INTEGER)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS customers 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)''')
    # 创建 products 表并保留 normalized_name 列（兼容旧表）
    cur.execute('''CREATE TABLE IF NOT EXISTS products 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, normalized_name TEXT, created_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS order_details 
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER, product_id INTEGER, qty INTEGER, price REAL)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS warehouses (id INTEGER PRIMARY KEY, name TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS categories 
                    (id INTEGER PRIMARY KEY, name TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS inventory 
                    (id INTEGER PRIMARY KEY, product_id INTEGER, warehouse_id INTEGER, category_id INTEGER, 
                     qty INTEGER, last_update TEXT)''')

    # price_meta 与导入任务/错误表（代码中使用到，确保存在）
    cur.execute('''CREATE TABLE IF NOT EXISTS price_meta
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER, bid_month TEXT, company TEXT, price REAL, price_type TEXT, created_at TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS import_tasks
                    (id TEXT PRIMARY KEY, temp_id TEXT, filename TEXT, mapping TEXT, conflict_mode TEXT, status TEXT, created_at TEXT, updated_at TEXT, total INTEGER, success INTEGER, failed INTEGER)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS import_errors
                    (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, row_no INTEGER, raw TEXT, error_msg TEXT)''')

    conn.commit()
    # 兼容：若旧的 products 表缺少 normalized_name 列，尝试添加（SQLite 在重复添加时会抛错，捕获忽略）
    try:
        cur.execute("ALTER TABLE products ADD COLUMN normalized_name TEXT")
        cur.execute("ALTER TABLE products ADD COLUMN created_at TEXT")
        conn.commit()
    except Exception:
        pass

    conn.close()

# 确保在模块加载时初始化表（方便直接用 python app.py 启动）
ensure_tables()

# --- API 路由 ---

@app.route('/api/products', methods=['GET'])
def api_products():
    query = request.args.get('q', '')
    limit = int(request.args.get('limit', 10))
    
    conn = get_db()
    cur = conn.cursor()
    
    if query:
        cur.execute('SELECT id, name FROM products WHERE name LIKE ? ORDER BY name LIMIT ?', 
                    (f'%{query}%', limit))
    else:
        cur.execute('SELECT id, name FROM products ORDER BY name LIMIT ?', (limit,))
        
    products = [{'id': row[0], 'name': row[1]} for row in cur.fetchall()]
    conn.close()
    
    return jsonify(products)

@app.route('/api/product/<int:product_id>', methods=['GET'])
def api_product(product_id):
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT * FROM products WHERE id = ?', (product_id,))
    product = cur.fetchone()
    
    if not product:
        return jsonify({'error': '产品不存在'}), 404
    
    result = dict(product)
    conn.close()
    
    return jsonify(result)

@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
    if 'file' not in request.files:
        return jsonify({'error': '未选择文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '未选择文件'}), 400
    
    try:
        # 保存临时文件
        filename = secure_filename(file.filename)
        temp_id = str(uuid.uuid4())
        temp_path = os.path.join(UPLOAD_FOLDER, f"{temp_id}_{filename}")
        file.save(temp_path)
        
        # 读取文件内容
        if pd is None:
            return jsonify({'error': '系统缺少pandas库，无法处理Excel/CSV文件'}), 500
            
        if filename.lower().endswith('.csv'):
            df = pd.read_csv(temp_path, encoding='utf-8')
        else:
            df = pd.read_excel(temp_path)
            
        # 准备返回数据
        preview_data = df.head(5).to_dict('records')
        columns = df.columns.tolist()
        
        return jsonify({
            'temp_id': temp_id,
            'filename': filename,
            'columns': columns,
            'preview_data': preview_data
        })
                              
    except Exception as e:
        return jsonify({'error': f'处理文件错误: {str(e)}'}), 500

@app.route('/api/import/upload', methods=['POST'])
@login_required
def api_import_upload():
    try:
        if 'file' not in request.files:
            return jsonify({'error': '未选择文件'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': '未选择文件'}), 400
        
        # 检查pandas
        if pd is None:
            return jsonify({'error': '系统缺少pandas库，无法处理Excel/CSV文件'}), 500
        
        # 保存临时文件
        filename = secure_filename(file.filename)
        temp_id = str(uuid.uuid4())
        temp_path = os.path.join(UPLOAD_FOLDER, f"{temp_id}_{filename}")
        file.save(temp_path)
        
        # 读取文件内容
        if filename.lower().endswith('.csv'):
            df = pd.read_csv(temp_path, encoding='utf-8')
        else:
            df = pd.read_excel(temp_path)
            
        # 准备返回数据
        preview_data = df.head(5).to_dict('records')
        columns = df.columns.tolist()
        
        return jsonify({
            'success': True,
            'temp_id': temp_id,
            'filename': filename,
            'columns': columns,
            'preview_data': preview_data
        })
                              
    except Exception as e:
        logger.exception("API上传错误")
        return jsonify({'error': f'处理文件错误: {str(e)}'}), 500

@app.route('/api/import/task', methods=['POST'])
def api_import_task():
    data = request.json
    if not data or 'temp_id' not in data or 'mapping' not in data:
        return jsonify({'error': '缺少必要参数'}), 400
    
    temp_id = data['temp_id']
    mapping = data['mapping']
    conflict_mode = data.get('conflict_mode', 'skip')
    
    # 查找上传的临时文件
    filepath = _locate_temp_file(temp_id)
    if not filepath:
        return jsonify({'error': '临时文件不存在或已过期'}), 404
    
    # 创建导入任务
    task_id = str(uuid.uuid4())
    filename = os.path.basename(filepath).replace(f"{temp_id}_", "", 1)
    
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    
    cur.execute('''
        INSERT INTO import_tasks (id, temp_id, filename, mapping, conflict_mode, 
                                status, created_at, updated_at, total, success, failed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (task_id, temp_id, filename, json.dumps(mapping), conflict_mode, 
         'pending', now, now, 0, 0, 0))
    conn.commit()
    conn.close()
    
    # 在后台执行导入任务
    _IMPORT_EXECUTOR.submit(_process_import_task, task_id, filepath, mapping, conflict_mode)
    
    return jsonify({
        'success': True,
        'task_id': task_id
    })

@app.route('/api/import/status/<task_id>', methods=['GET'])
def api_import_status(task_id):
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute('SELECT * FROM import_tasks WHERE id = ?', (task_id,))
    task = cur.fetchone()
    
    if not task:
        conn.close()
        return jsonify({'error': '任务不存在'}), 404
    
    # 获取错误信息
    cur.execute('SELECT * FROM import_errors WHERE task_id = ? ORDER BY row_no LIMIT 100', (task_id,))
    errors = [dict(row) for row in cur.fetchall()]
    
    result = dict(task)
    result['errors'] = errors
    
    conn.close()
    return jsonify(result)

# 添加新的API路由用于处理映射
@app.route('/api/import/map', methods=['POST'])
@login_required
def api_import_map():
    data = request.json
    if not data or 'temp_id' not in data or 'mapping' not in data:
        return jsonify({'error': '缺少必要参数'}), 400
    
    temp_id = data['temp_id']
    mapping = data['mapping']
    global_month = data.get('global_month', '')
    conflict_mode = data.get('conflict_mode', 'skip')
    
    # 查找临时文件
    filepath = _locate_temp_file(temp_id)
    if not filepath:
        return jsonify({'error': '临时文件不存在或已过期'}), 404
        
    # 读取文件并进行预处理
    try:
        import pandas as pd
        if filepath.endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)
            
        # 获取必要的映射
        product_col = mapping.get('product')
        if not product_col:
            return jsonify({'error': '必须指定产品列'}), 400
            
        price_cols = mapping.get('price_cols', [])
        if not price_cols:
            return jsonify({'error': '必须至少指定一个价格列'}), 400
            
        # 执行预检
        results = []
        conflicts = []
        
        # 最多检查50行，避免处理时间过长
        for idx, row in df.head(50).iterrows():
            product_name = str(row.get(product_col, ''))
            if not product_name:
                continue
                
            # 归一化产品名并查找
            normalized_name = normalize_product_name(product_name)
            matches = fuzzy_match_product(normalized_name)
            
            row_result = {
                'row': idx + 1,
                'product': product_name,
                'normalized': normalized_name,
                'matches': matches,
                'prices': []
            }
            
            # 检查每个价格列
            for price_info in price_cols:
                price_col = price_info.get('column')
                company = price_info.get('company', '')
                
                if not price_col or not company:
                    continue
                    
                price_val = _parse_number(row.get(price_col))
                
                if price_val is not None:
                    # 检查冲突
                    if matches and conflict_mode != 'overwrite':
                        product_id = matches[0][0]
                        date_val = to_bid_month(row.get(mapping.get('date', '')), global_month)
                        
                        # 查询是否已存在该产品+公司+月份的记录
                        conn = get_db()
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT id, price FROM price_meta WHERE product_id=? AND company=? AND bid_month=?",
                            (product_id, company, date_val)
                        )
                        existing = cur.fetchone()
                        conn.close()
                        
                        if existing:
                            conflicts.append({
                                'row': idx + 1,
                                'product': product_name,
                                'company': company,
                                'existing_price': existing[1],
                                'new_price': price_val
                            })
                    
                    row_result['prices'].append({
                        'company': company,
                        'value': price_val
                    })
            
            results.append(row_result)
        
        return jsonify({
            'success': True,
            'preview': results,
            'conflicts': conflicts,
            'total_rows': len(df)
        })
        
    except Exception as e:
        logger.exception("预检查错误")
        return jsonify({'error': str(e)}), 500

@app.route('/api/import/execute', methods=['POST'])
@login_required
def api_import_execute():
    data = request.json
    if not data or 'temp_id' not in data or 'mapping' not in data:
        return jsonify({'error': '缺少必要参数'}), 400
    
    temp_id = data['temp_id']
    mapping = data['mapping']
    global_month = data.get('global_month', '')
    conflict_mode = data.get('conflict_mode', 'skip')
    
    # 创建导入任务
    task_id = str(uuid.uuid4())
    
    # 记录任务信息
    conn = get_db()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    
    try:
        cur.execute(
            "INSERT INTO import_tasks (id, temp_id, filename, mapping, conflict_mode, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, temp_id, os.path.basename(_locate_temp_file(temp_id)), json.dumps(mapping), conflict_mode, 'pending', now, now)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({'error': f'创建导入任务失败: {str(e)}'}), 500
    finally:
        conn.close()
    
    # 将任务提交到后台执行
    _IMPORT_EXECUTOR.submit(
        _process_quote_import,
        task_id, 
        temp_id, 
        mapping, 
        global_month, 
        conflict_mode,
        session.get('user_id', 'unknown')
    )
    
    return jsonify({
        'success': True,
        'task_id': task_id
    })

def _process_quote_import(task_id, temp_id, mapping, global_month, conflict_mode, user_id):
    """后台处理导入任务"""
    import pandas as pd
    
    filepath = _locate_temp_file(temp_id)
    if not filepath:
        logger.error(f"找不到临时文件: {temp_id}")
        return
    
    conn = get_db()
    cur = conn.cursor()
    
    try:  # 将 try { 改为 try:
        # 更新任务状态
        now = datetime.now().isoformat()
        cur.execute(
            "UPDATE import_tasks SET status=?, updated_at=? WHERE id=?",
            ('processing', now, task_id)
        )
        conn.commit()
        
        # 读取文件
        if filepath.lower().endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)
        
        # 获取映射配置
        product_col = mapping.get('product')
        if not product_col:
            raise ValueError("必须指定产品列")
        
        price_cols = mapping.get('price_cols', [])
        if not price_cols:
            raise ValueError("必须至少指定一个价格列")
        
        total_rows = len(df)
        success_count = 0
        error_count = 0
        
        # 更新任务总数
        cur.execute(
            "UPDATE import_tasks SET total=? WHERE id=?",
            (total_rows, task_id)
        )
        conn.commit()
        
        # 处理每行数据
        for idx, row in df.iterrows():
            try:
                product_name = str(row.get(product_col, ''))
                if not product_name:
                    continue
                
                # 归一化并查找/创建产品
                normalized_name = normalize_product_name(product_name)
                
                cur.execute(
                    "SELECT id FROM products WHERE normalized_name=?",
                    (normalized_name,)
                )
                product_row = cur.fetchone()
                
                if product_row:
                    product_id = product_row[0]
                else:
                    # 创建新产品
                    cur.execute(
                        "INSERT INTO products (name, normalized_name, created_at) VALUES (?, ?, ?)",
                        (product_name, normalized_name, now)
                    )
                    product_id = cur.lastrowid
                
                # 创建quote记录
                source = f"导入_{temp_id}"
                cur.execute(
                    "INSERT INTO quotes (product_id, source, created_at) VALUES (?, ?, ?)",
                    (product_id, source, now)
                )
                quote_id = cur.lastrowid
                
                # 处理价格列
                date_col = mapping.get('date')
                bid_month = to_bid_month(row.get(date_col) if date_col else None, global_month)
                if not bid_month:
                    bid_month = datetime.now().strftime('%Y-%m')
                
                at_least_one_price = False
                for price_info in price_cols:
                    price_col = price_info.get('column')
                    company = price_info.get('company')
                    price_type = price_info.get('price_type', '中标价(默认)')
                    
                    if not price_col or not company:
                        continue
                    
                    price_val = _parse_number(row.get(price_col))
                    if price_val is None:
                        continue
                    
                    at_least_one_price = True
                    
                    # 检查冲突
                    cur.execute(
                        "SELECT id FROM price_meta WHERE product_id=? AND company=? AND bid_month=?",
                        (product_id, company, bid_month)
                    )
                    existing = cur.fetchone()
                    
                    if existing:
                        if conflict_mode == 'skip':
                            continue
                        elif conflict_mode == 'overwrite':
                            cur.execute(
                                "UPDATE price_meta SET price=?, price_type=?, created_at=? WHERE id=?",
                                (price_val, price_type, now, existing[0])
                            )
                        # 其他模式默认为 'skip'
                    else:
                        # 插入新记录
                        cur.execute(
                            "INSERT INTO price_meta (product_id, bid_month, company, price, price_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                            (product_id, bid_month, company, price_val, price_type, now)
                        )
                
                if at_least_one_price:
                    success_count += 1
                
                # 定期更新进度
                if (idx + 1) % 100 == 0 or idx + 1 == total_rows:
                    cur.execute(
                        "UPDATE import_tasks SET success=?, failed=?, updated_at=? WHERE id=?",
                        (success_count, error_count, datetime.now().isoformat(), task_id)
                    )
                    conn.commit()
                
            except Exception as e:
                error_count += 1
                logger.exception(f"处理第{idx+1}行时出错")
                try:
                    cur.execute(
                        "INSERT INTO import_errors (task_id, row_no, raw, error_msg) VALUES (?, ?, ?, ?)",
                        (task_id, idx + 1, json.dumps(dict(row)), str(e))
                    )
                except:
                    pass
            
        # 完成导入
        cur.execute(
            "UPDATE import_tasks SET status=?, success=?, failed=?, updated_at=? WHERE id=?",
            ('completed', success_count, error_count, datetime.now().isoformat(), task_id)
        )
        conn.commit()
        
    except Exception as e:
        logger.exception(f"导入任务出错: {str(e)}")
        try:
            cur.execute(
                "UPDATE import_tasks SET status=?, error_msg=?, updated_at=? WHERE id=?",
                ('failed', str(e), datetime.now().isoformat(), task_id)
            )
            conn.commit()
        except:
            pass
    
    finally:
        conn.close()

# 在适当的位置添加此函数，建议放在其他导入任务相关函数附近

def _process_import_task(task_id, filepath, mapping, conflict_mode):
    """处理导入任务的后台函数"""
    import pandas as pd
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 更新任务状态为处理中
        now = datetime.now().isoformat()
        cur.execute(
            "UPDATE import_tasks SET status=?, updated_at=? WHERE id=?",
            ('processing', now, task_id)
        )
        conn.commit()
        
        # 读取文件
        if filepath.lower().endswith('.csv'):
            df = pd.read_csv(filepath)
        else:
            df = pd.read_excel(filepath)
        
        total_rows = len(df)
        success_count = 0
        error_count = 0
        
        # 更新任务总记录数
        cur.execute(
            "UPDATE import_tasks SET total=? WHERE id=?",
            (total_rows, task_id)
        )
        conn.commit()
        
        # 执行导入逻辑（根据mapping参数来处理）
        # 这里实现基本的导入流程，根据您的具体需求可能需要调整
        for idx, row in df.iterrows():
            try:
                # 这里需要根据mapping参数处理每行数据
                # 例如: 根据mapping获取列名，从行中提取数据，插入到相应表中
                
                # 导入成功计数
                success_count += 1
                
                # 定期更新进度
                if (idx + 1) % 100 == 0 or idx + 1 == total_rows:
                    cur.execute(
                        "UPDATE import_tasks SET success=?, failed=?, updated_at=? WHERE id=?",
                        (success_count, error_count, datetime.now().isoformat(), task_id)
                    )
                    conn.commit()
                    
            except Exception as e:
                error_count += 1
                logger.exception(f"处理第{idx+1}行时出错: {str(e)}")
                try:
                    cur.execute(
                        "INSERT INTO import_errors (task_id, row_no, raw, error_msg) VALUES (?, ?, ?, ?)",
                        (task_id, idx + 1, json.dumps(dict(row)), str(e))
                    )
                    conn.commit()
                except:
                    pass
        
        # 完成导入
        cur.execute(
            "UPDATE import_tasks SET status=?, updated_at=? WHERE id=?",
            ('completed', datetime.now().isoformat(), task_id)
        )
        conn.commit()
        
    except Exception as e:
        logger.exception(f"导入任务出错: {str(e)}")
        try:
            cur.execute(
                "UPDATE import_tasks SET status=?, error_msg=?, updated_at=? WHERE id=?",
                ('failed', str(e), datetime.now().isoformat(), task_id)
            )
            conn.commit()
        except:
            pass
    finally:
        conn.close()

def process_smart_quote_import_new(filepath, product_col, price_col, qty_col, 
                                  company_name, bid_date, conflict_mode):
    """新的导入处理逻辑 - 统一公司和日期"""
    try:
        # 读取文件
        if filepath.lower().endswith('.csv'):
            df = pd.read_csv(filepath, encoding='utf-8')
        else:
            df = pd.read_excel(filepath)
        
        conn = get_db()
        cur = conn.cursor()
        
        success_count = 0
        skip_count = 0
        error_count = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                # 从Excel读取的数据
                product_name = str(row.get(product_col, '')).strip()
                price_value = _parse_number(row.get(price_col))
                qty_value = int(_parse_number(row.get(qty_col)) or 1) if qty_col else 1
                
                # 必填字段验证
                if not product_name or price_value is None:
                    error_count += 1
                    errors.append(f'第{idx+2}行: 产品名称或中标价格为空')
                    continue
                
                # 价格合理性验证
                if price_value <= 0:
                    error_count += 1
                    errors.append(f'第{idx+2}行: 中标价格必须大于0')
                    continue
                
                # 冲突检查
                if conflict_mode == 'skip':
                    existing = cur.execute(
                        'SELECT id FROM quotes WHERE product=? AND company=? AND bid_date=?',
                        (product_name, company_name, bid_date)
                    ).fetchone()
                    if existing:
                        skip_count += 1
                        continue
                
                # 插入数据（使用统一的公司和日期）
                cur.execute('''
                    INSERT OR REPLACE INTO quotes (product, company, price, qty, bid_date, remarks)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (product_name, company_name, price_value, qty_value, bid_date, 
                     f'批量导入_{datetime.now().strftime("%Y%m%d")}'))
                
                success_count += 1
                
            except Exception as e:
                error_count += 1
                errors.append(f'第{idx+2}行: {str(e)}')
                logger.exception(f"导入第{idx+1}行时出错")
        
        conn.commit()
        conn.close()
        
        # 清理临时文件
        try:
            os.remove(filepath)
        except:
            pass
        
        return {
            'success': True,
            'success_count': success_count,
            'skip_count': skip_count,
            'error_count': error_count,
            'errors': errors[:10]
        }
        
    except Exception as e:
        return {'success': False, 'error': str(e)}
    
if __name__ == '__main__':
        app.run(debug=True, host='0.0.0.0', port=5000)