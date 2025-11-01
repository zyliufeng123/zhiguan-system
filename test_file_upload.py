import requests
import os

BASE_URL = 'http://localhost:5000'

def create_test_excel():
    """创建一个测试Excel文件"""
    import pandas as pd
    
    data = {
        '产品名称': ['笔记本电脑', '台式机', '显示器', '键盘', '鼠标'],
        '公司名称': ['华为', '联想', '戴尔', '罗技', '雷蛇'],
        '报价': [5999, 4500, 1200, 299, 199],
        '报价日期': ['2024-10-29', '2024-10-28', '2024-10-27', '2024-10-26', '2024-10-25'],
        '备注': ['包含配件', '高性能', '27寸', '机械键盘', '无线']
    }
    
    df = pd.DataFrame(data)
    test_file = 'test_quotation.xlsx'
    df.to_excel(test_file, index=False)
    
    print(f"✅ 创建测试文件: {test_file}")
    return test_file


def test_upload_file(file_path):
    """测试上传文件"""
    print("=" * 80)
    print("测试1: 上传Excel文件")
    print("=" * 80)
    
    with open(file_path, 'rb') as f:
        files = {'file': (os.path.basename(file_path), f)}
        response = requests.post(f'{BASE_URL}/api/bulk_import/upload', files=files)
    
    print(f"状态码: {response.status_code}")
    result = response.json()
    
    if result['success']:
        data = result['data']
        print(f"✅ 文件上传成功")
        print(f"文件ID: {data['file_id']}")
        print(f"原始文件名: {data['original_filename']}")
        print(f"总行数: {data['total_rows']}")
        print(f"列名: {', '.join(data['columns'])}")
        print(f"预览数据行数: {len(data['preview_data'])}")
        print("\n预览数据 (前3行):")
        for i, row in enumerate(data['preview_data'][:3], 1):
            print(f"  第{i}行: {row}")
        print()
        return data['file_id']
    else:
        print(f"❌ 上传失败: {result['message']}")
        return None


def test_delete_file(file_id):
    """测试删除文件"""
    print("=" * 80)
    print(f"测试2: 删除文件 (ID: {file_id})")
    print("=" * 80)
    
    response = requests.delete(f'{BASE_URL}/api/bulk_import/file/{file_id}')
    print(f"状态码: {response.status_code}")
    result = response.json()
    
    if result['success']:
        print(f"✅ {result['message']}")
    else:
        print(f"❌ {result['message']}")
    print()


def test_upload_invalid_file():
    """测试上传无效文件"""
    print("=" * 80)
    print("测试3: 上传不支持的文件格式")
    print("=" * 80)
    
    # 创建一个文本文件
    test_file = 'test_invalid.txt'
    with open(test_file, 'w') as f:
        f.write('This is not an Excel file')
    
    try:
        with open(test_file, 'rb') as f:
            files = {'file': (test_file, f)}
            response = requests.post(f'{BASE_URL}/api/bulk_import/upload', files=files)
        
        print(f"状态码: {response.status_code}")
        result = response.json()
        
        if not result['success']:
            print(f"✅ 正确拒绝: {result['message']}")
        else:
            print(f"❌ 应该拒绝但没有拒绝")
    finally:
        if os.path.exists(test_file):
            os.remove(test_file)
    
    print()


if __name__ == '__main__':
    print("\n🚀 开始测试文件上传功能\n")
    
    try:
        # 创建测试文件
        test_file = create_test_excel()
        
        # 测试上传文件
        file_id = test_upload_file(test_file)
        
        if file_id:
            # 测试删除文件
            test_delete_file(file_id)
        
        # 测试上传无效文件
        test_upload_invalid_file()
        
        # 清理测试文件
        if os.path.exists(test_file):
            os.remove(test_file)
            print(f"🧹 清理测试文件: {test_file}\n")
        
        print("=" * 80)
        print("✅ 所有测试完成！")
        print("=" * 80)
        
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到服务器，请确保Flask应用正在运行 (python app.py)")
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()