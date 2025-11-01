import sys

def check_dependencies():
    """检查必要的依赖库"""
    required_libs = {
        'openpyxl': 'Excel文件读取',
        'pandas': '数据处理',
        'werkzeug': 'Flask文件上传'
    }
    
    print("=" * 80)
    print("📦 检查依赖库")
    print("=" * 80)
    print()
    
    missing = []
    
    for lib, desc in required_libs.items():
        try:
            __import__(lib)
            print(f"✅ {lib:<20} - {desc}")
        except ImportError:
            print(f"❌ {lib:<20} - {desc} (未安装)")
            missing.append(lib)
    
    print()
    print("=" * 80)
    
    if missing:
        print(f"❌ 缺少 {len(missing)} 个依赖库")
        print(f"请运行: pip install {' '.join(missing)}")
    else:
        print("✅ 所有依赖库已安装")
    
    print("=" * 80)
    
    return len(missing) == 0

if __name__ == '__main__':
    if not check_dependencies():
        sys.exit(1)