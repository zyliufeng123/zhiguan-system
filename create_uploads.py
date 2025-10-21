import os

# 创建上传文件夹
uploads_dir = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(uploads_dir, exist_ok=True)
print(f"已创建上传文件夹: {uploads_dir}")