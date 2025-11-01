import requests
import json

BASE_URL = 'http://localhost:5000'

def test_create_config():
    """测试创建配置"""
    print("=" * 80)
    print("测试1: 创建智能报价导入配置")
    print("=" * 80)
    
    data = {
        'module_code': 'quotation',
        'module_name': '智能报价导入',
        'target_table': 'quotes',
        'unique_fields': ['product_name', 'company', 'quotation_date'],
        'status': 'enabled',
        'fields': [
            {
                'field_name': 'product_name',
                'display_name': '产品名称',
                'field_type': 'string',
                'is_required': True,
                'max_length': 255,
                'sort_order': 0,
                'remark': '用于识别产品'
            },
            {
                'field_name': 'company',
                'display_name': '公司名称',
                'field_type': 'string',
                'is_required': True,
                'max_length': 100,
                'sort_order': 1,
                'remark': '报价所属公司'
            },
            {
                'field_name': 'quotation_price',
                'display_name': '报价',
                'field_type': 'number',
                'is_required': True,
                'sort_order': 2,
                'remark': '单位：元'
            },
            {
                'field_name': 'quotation_date',
                'display_name': '报价日期',
                'field_type': 'date',
                'is_required': True,
                'sort_order': 3,
                'remark': '格式：YYYY-MM-DD'
            },
            {
                'field_name': 'note',
                'display_name': '备注',
                'field_type': 'string',
                'is_required': False,
                'max_length': 500,
                'sort_order': 4,
                'remark': '可选填写'
            }
        ]
    }
    
    response = requests.post(f'{BASE_URL}/api/import_config', json=data)
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()
    
    return response.json().get('data', {}).get('id')


def test_get_configs():
    """测试获取配置列表"""
    print("=" * 80)
    print("测试2: 获取配置列表")
    print("=" * 80)
    
    response = requests.get(f'{BASE_URL}/api/import_config')
    print(f"状态码: {response.status_code}")
    result = response.json()
    
    if result['success']:
        print(f"共 {len(result['data'])} 条配置:")
        for config in result['data']:
            print(f"  - {config['module_name']} ({config['module_code']}) - {config['status']}")
    else:
        print(f"错误: {result['message']}")
    print()


def test_get_config_detail(config_id):
    """测试获取配置详情"""
    print("=" * 80)
    print(f"测试3: 获取配置详情 (ID: {config_id})")
    print("=" * 80)
    
    response = requests.get(f'{BASE_URL}/api/import_config/{config_id}')
    print(f"状态码: {response.status_code}")
    result = response.json()
    
    if result['success']:
        config = result['data']
        print(f"模块: {config['module_name']}")
        print(f"目标表: {config['target_table']}")
        print(f"唯一字段: {config['unique_fields']}")
        print(f"字段数量: {len(config['fields'])}")
        print("字段列表:")
        for field in config['fields']:
            required = "必填" if field['is_required'] else "可选"
            print(f"  - {field['display_name']} ({field['field_name']}) [{field['field_type']}] {required}")
    else:
        print(f"错误: {result['message']}")
    print()


def test_toggle_config(config_id):
    """测试切换配置状态"""
    print("=" * 80)
    print(f"测试4: 切换配置状态 (ID: {config_id})")
    print("=" * 80)
    
    response = requests.post(f'{BASE_URL}/api/import_config/{config_id}/toggle')
    print(f"状态码: {response.status_code}")
    print(f"响应: {json.dumps(response.json(), ensure_ascii=False, indent=2)}")
    print()


if __name__ == '__main__':
    print("\n🚀 开始测试导入配置管理API\n")
    
    try:
        # 测试创建配置
        config_id = test_create_config()
        
        if config_id:
            # 测试获取列表
            test_get_configs()
            
            # 测试获取详情
            test_get_config_detail(config_id)
            
            # 测试切换状态
            test_toggle_config(config_id)
            
            # 再次获取列表确认状态变化
            test_get_configs()
        
        print("=" * 80)
        print("✅ 所有测试完成！")
        print("=" * 80)
        
    except requests.exceptions.ConnectionError:
        print("❌ 无法连接到服务器，请确保Flask应用正在运行 (python app.py)")
    except Exception as e:
        print(f"❌ 测试失败: {str(e)}")