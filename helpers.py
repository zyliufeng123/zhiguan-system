import re
import os
import json
import uuid
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 创建线程池执行器
_IMPORT_EXECUTOR = ThreadPoolExecutor(max_workers=2)

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def normalize_product_name(name: str) -> str:
    """对产品名称进行归一化处理"""
    if not name:
        return ""
    s = str(name).strip().lower()
    # 去掉括号及其内容
    s = re.sub(r'[\(\（].*?[\)\）]', '', s)
    # 去掉单位/常见词
    s = re.sub(r'(kg|g|斤|箱|袋|包|克|千克|公斤)', '', s)
    # 去掉标点
    s = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def fuzzy_match_product(normalized_name: str, threshold=85):
    """模糊匹配产品名称
    返回格式: [(id, name, normalized_name, similarity), ...]
    """
    from difflib import SequenceMatcher
    
    if not normalized_name:
        return []
    
    from app import get_db
    conn = get_db()
    cursor = conn.cursor()
    
    # 先尝试精确匹配
    cursor.execute("SELECT id, name, normalized_name FROM products WHERE normalized_name = ?", (normalized_name,))
    exact_match = cursor.fetchone()
    if exact_match:
        conn.close()
        return [(exact_match[0], exact_match[1], exact_match[2], 100)]
    
    # 获取所有产品进行模糊匹配
    cursor.execute("SELECT id, name, normalized_name FROM products")
    all_products = cursor.fetchall()
    conn.close()
    
    matches = []
    for product in all_products:
        ratio = SequenceMatcher(None, normalized_name, product[2]).ratio() * 100
        if ratio >= threshold:
            matches.append((product[0], product[1], product[2], round(ratio, 1)))
    
    # 按相似度降序排序
    matches.sort(key=lambda x: x[3], reverse=True)
    return matches[:5]  # 返回最多5个匹配结果

def to_bid_month(date_value, global_month=None):
    """将日期值转换为中标月份格式(YYYY-MM)"""
    if not date_value and not global_month:
        return None
        
    if not date_value and global_month:
        if re.match(r'^\d{4}-\d{2}$', global_month):
            return global_month
        elif re.match(r'^\d{4}-\d{2}-\d{2}$', global_month):
            return global_month[:7]  # 截取YYYY-MM部分
        return None
    
    # 尝试解析日期值
    date_str = str(date_value).strip()
    
    # 尝试不同的日期格式
    date_formats = [
        '%Y-%m-%d',
        '%Y/%m/%d',
        '%Y.%m.%d',
        '%Y年%m月%d日',
        '%Y年%m月',
        '%Y-%m',
        '%Y/%m',
    ]
    
    for fmt in date_formats:
        try:
            date_obj = datetime.strptime(date_str, fmt)
            return date_obj.strftime('%Y-%m')  # 转为YYYY-MM格式
        except ValueError:
            continue
    
    # 如果都失败了，返回全局月份或None
    return global_month if re.match(r'^\d{4}-\d{2}$', str(global_month)) else None

def _parse_number(value):
    """解析数字，处理各种可能的格式"""
    if value is None:
        return None
        
    # 如果是数字类型，直接返回
    if isinstance(value, (int, float)):
        return float(value)
    
    # 如果是字符串，尝试解析
    try:
        # 去除所有空格和货币符号
        value_str = str(value).strip()
        value_str = re.sub(r'[,，\s¥$€£]', '', value_str)
        
        # 如果是空字符串，返回None
        if not value_str:
            return None
            
        # 尝试直接转换
        return float(value_str)
    except (ValueError, TypeError):
        return None

def _locate_temp_file(temp_id):
    """定位临时文件"""
    from app import app
    upload_folder = app.config['UPLOAD_FOLDER']
    for filename in os.listdir(upload_folder):
        if filename.startswith(temp_id + "_"):
            return os.path.join(upload_folder, filename)
    return None