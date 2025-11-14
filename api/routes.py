#api/routes.py
# API路由注册模块  # 文件功能简介

from flask import Flask, Blueprint  # Flask组件
import os  # 环境变量
import ssl  # SSL支持

# 创建蓝图
api_bp = Blueprint('api', __name__)  # API蓝图

# 导入路由模块
from . import video_routes, speech_routes, summary_routes, chat_routes  # 导入路由模块
from .video_routes import video_bp  # 导入视频蓝图
from .speech_routes import speech_bp  # 导入语音蓝图
from .summary_routes import summary_bp  # 导入总结蓝图
from .chat_routes import chat_bp  # 导入聊天蓝图
from .utils import check_dependencies  # 导入工具函数

# 注册子蓝图
api_bp.register_blueprint(video_bp)  # 注册视频蓝图
api_bp.register_blueprint(speech_bp)  # 注册语音蓝图
api_bp.register_blueprint(summary_bp)  # 注册总结蓝图
api_bp.register_blueprint(chat_bp)  # 注册聊天蓝图

def register_api_routes(app: Flask) -> None:  # 注册API路由函数
    """注册所有API路由到Flask应用"""  # 文档
    app.register_blueprint(api_bp, url_prefix='/api')  # 注册蓝图
    print("API路由已注册")  # 提示
