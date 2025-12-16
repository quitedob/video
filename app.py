#app.py
# Web应用入口：Flask Web服务器启动点  # 文件功能简介

import os  # 环境变量
import ssl  # SSL支持
import logging  # 日志模块
from logging.handlers import RotatingFileHandler  # 日志轮转处理器
from pathlib import Path  # 路径处理
from flask import Flask, render_template  # Flask核心
from flask_socketio import SocketIO, emit  # WebSocket支持
from flask_cors import CORS  # 跨域支持

# 导入API模块
from api import register_api_routes  # API路由注册
from api.utils import check_dependencies  # 依赖检查

# 创建Flask应用
app = Flask(__name__,  # Flask应用实例
            template_folder='templates',  # 模板文件夹
            static_folder='static')  # 静态文件文件夹

# ---- 日志配置函数 ----
def setup_logging():
    """配置日志系统：同时输出到控制台(默认)和文件(新增)"""
    log_dir = 'logs'
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'video_app.log')

    # 定义格式
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 文件处理器: 10MB 切割, 最多保留 10 个备份
    file_handler = RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=10, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # 获取根日志记录器并配置
    root_logger = logging.getLogger()
    # 注意：不要随意重置 level，否则可能覆盖其他模块的设置
    # root_logger.setLevel(logging.INFO) 

    # 避免重复添加 (判断是否已存在 RotatingFileHandler)
    has_file_handler = any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers)
    if not has_file_handler:
        root_logger.addHandler(file_handler)
        print(f"📄 日志系统已就绪，输出文件: {log_file}")

    # 也可以单独为 werkzeug (Flask 请求日志) 添加文件输出
    logging.getLogger('werkzeug').addHandler(file_handler)

# 配置Flask应用
app.config['SECRET_KEY'] = 'video-subtitle-secret-key'  # 会话密钥
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 最大上传1GB
app.config['UPLOAD_FOLDER'] = 'uploads'  # 上传文件夹
app.config['TEMP_FOLDER'] = 'temp_web'  # 临时文件夹

# 启用CORS
CORS(app, resources={r"/*": {"origins": "*"}})  # 允许所有源

# 初始化WebSocket
socketio = SocketIO(app, cors_allowed_origins="*")  # WebSocket服务器

# 确保必要的目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)  # 创建上传目录
os.makedirs(app.config['TEMP_FOLDER'], exist_ok=True)  # 创建临时目录
os.makedirs('outputs', exist_ok=True)  # 创建输出目录
os.makedirs('templates', exist_ok=True)  # 创建模板目录
os.makedirs('static', exist_ok=True)  # 创建静态文件目录
os.makedirs('static/css', exist_ok=True)  # CSS目录
os.makedirs('static/js', exist_ok=True)  # JS目录

# 全局任务状态存储（现在由API模块管理）
# tasks = {}  # 任务状态字典 - 已移动到API模块


@socketio.on('connect')  # 客户端连接事件
def handle_connect():  # 连接处理
    """处理客户端连接"""  # 文档
    print('客户端已连接')  # 连接提示
    emit('status', {'message': '已连接到服务器'})  # 发送状态


@socketio.on('disconnect')  # 客户端断开事件
def handle_disconnect():  # 断开处理
    """处理客户端断开"""  # 文档
    print('客户端已断开')  # 断开提示


# ---------- Web路由定义 ----------

# 注册API路由
register_api_routes(app)  # 注册所有API路由

# 注册Socket事件
try:
    from api.speech_routes import register_socket_events
    register_socket_events(socketio)  # 注册语音处理Socket事件
except ImportError:
    pass

@app.route('/')  # 首页路由
def index():  # 首页函数
    """渲染首页"""  # 文档
    deps = check_dependencies()  # 检查依赖
    return render_template('index.html',  # 渲染模板
                          dependencies_ok=deps['all_good'],  # 依赖状态
                          missing_deps=deps['missing_deps'])  # 缺失依赖


@app.route('/speech')  # 语音转文字页面路由
def speech_to_text_page():  # 语音转文字页面函数
    """渲染语音转文字页面"""  # 文档
    deps = check_dependencies()  # 检查依赖
    return render_template('speech_to_text.html',  # 渲染模板
                          dependencies_ok=deps['all_good'],  # 依赖状态
                          missing_deps=deps['missing_deps'])  # 缺失依赖


def load_env_file():
    """加载.env文件中的环境变量"""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()
        print("已加载 .env 文件配置")
    else:
        print("未找到 .env 文件，使用环境变量或默认配置")


def main():  # 主函数
    """启动Web服务器"""  # 文档
    # 初始化日志
    setup_logging()

    # 加载.env文件
    load_env_file()

    # 规范 CUDA 设备顺序并默认选择第 0 块 GPU（可通过环境变量覆盖）
    os.environ.setdefault("CUDA_DEVICE_ORDER", "PCI_BUS_ID")  # 设备排序
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")  # 默认可见设备

    # 检查依赖
    deps = check_dependencies()  # 检查依赖
    if not deps['all_good']:  # 有缺失依赖
        print(f"警告: 缺失依赖: {', '.join(deps['missing_deps'])}")  # 警告提示
        print("请安装缺失的依赖后重试")  # 提示

    # SSL证书路径
    ssl_cert_path = os.path.join('ssl', 'server.crt')  # 证书文件路径
    ssl_key_path = os.path.join('ssl', 'server.key')  # 私钥文件路径

    # 检查SSL证书文件是否存在
    if not os.path.exists(ssl_cert_path) or not os.path.exists(ssl_key_path):  # 证书不存在
        print(f"❌ SSL证书文件缺失: {ssl_cert_path} 或 {ssl_key_path}")  # 错误提示
        print("请确保SSL证书文件存在")  # 提示
        print("💡 提示：运行以下命令生成自签名证书：")  # 提示
        print("   openssl req -x509 -newkey rsa:4096 -keyout ssl/server.key -out ssl/server.crt -days 365 -nodes")  # 命令
        return  # 退出

    # 创建SSL上下文
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)  # SSL上下文
    ssl_context.load_cert_chain(ssl_cert_path, ssl_key_path)  # 加载证书链

    # 打印启动信息
    print("=" * 50)  # 分隔线
    print("🎬 智能视频字幕处理工作站")  # 标题
    print("=" * 50)  # 分隔线
    print(f"🔒 HTTPS服务器启动中... (SSL已启用)")  # 启动提示
    print(f"📍 访问地址: https://127.0.0.1:443")  # 访问地址
    print(f"📍 本地网络: https://localhost:443")  # 本地网络地址
    print(f"📁 上传目录: {app.config['UPLOAD_FOLDER']}")  # 上传目录
    print(f"📁 临时目录: {app.config['TEMP_FOLDER']}")  # 临时目录
    print(f"📁 输出目录: outputs")  # 输出目录
    print(f"🔒 SSL证书: {ssl_cert_path}")  # SSL证书路径

    if not deps['all_good']:  # 有缺失依赖
        print(f"⚠️  警告: 缺失依赖: {', '.join(deps['missing_deps'])}")  # 警告

    print("=" * 50)  # 分隔线

    # 启动HTTPS服务器
    socketio.run(app,  # 启动SocketIO服务器
                 host='0.0.0.0',  # 监听所有地址
                 port=443,  # HTTPS默认端口
                 ssl_context=ssl_context,  # SSL上下文
                 allow_unsafe_werkzeug=True,
                 debug=True)  # 调试模式


if __name__ == '__main__':  # 脚本直接运行入口
    main()  # 执行主函数


