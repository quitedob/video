#api/utils.py
# API工具函数  # 文件功能简介

import os  # 环境变量
import ssl  # SSL支持
from flask import Flask  # Flask应用
from flask_socketio import SocketIO  # WebSocket支持

# 导入pkg模块功能
from pkg.video.video_processing import check_command_available  # 依赖检查

def check_dependencies() -> dict:  # 检查依赖函数
    """检查系统依赖"""  # 文档
    missing_deps = []  # 缺失依赖列表

    # 检查 FFmpeg
    if not check_command_available('ffmpeg'):  # 检测 ffmpeg 命令
        missing_deps.append("FFmpeg")  # 添加到列表

    return {  # 返回结果
        'all_good': len(missing_deps) == 0,  # 是否都正常
        'missing_deps': missing_deps  # 缺失依赖
    }  # 结束
