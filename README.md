# 🎬 智能视频字幕处理工作站

一个基于 AI 的智能视频字幕处理工作站，提供视频字幕生成、语音转文字等功能。

## 📋 项目状态

### ✅ 已完成功能

- **语音转文字**: 支持音频和视频文件的语音识别和转文字功能
  - 支持多种音频格式（MP3, WAV, M4A, FLAC等）
  - 支持多种视频格式（MP4, AVI, MOV, MKV等）
  - 基于 FunASR 的高精度语音识别
  - 实时转写和批量处理两种模式
  - 流式处理支持大文件分段识别

### 🚧 开发中功能

- **URL 下载**: 支持从网络URL下载视频和音频文件
- **视频字幕**: 为视频文件自动生成和嵌入字幕
- **会议总结**: 接入 AI API 进行会议内容智能总结

### 🔮 计划功能

- 多语言字幕翻译
- 字幕样式自定义
- 批量处理队列
- 云端存储集成

## 🏗️ 项目架构

```
video-subtitle-workstation/
├── app.py                      # Flask 主应用
├── api/                        # API 路由层
│   ├── __init__.py            # API 包初始化
│   ├── chat_routes.py         # 聊天对话 API
│   ├── routes.py              # 基础路由
│   ├── speech_routes.py       # 语音转文字 API
│   ├── summary_routes.py      # 智能总结 API
│   ├── utils.py               # 工具函数
│   └── video_routes.py        # 视频处理 API
├── pkg/                        # 核心处理模块
│   ├── audio/                 # 音频处理模块
│   │   └── audio_processing.py # ASR 推理和音频处理
│   ├── config/                # 配置管理
│   │   └── config.py          # 配置文件管理
│   ├── llm/                   # 大语言模型模块
│   │   ├── __init__.py       # LLM 包初始化
│   │   ├── base.py           # LLM 基础类
│   │   ├── deepseek.py       # DeepSeek API 集成
│   │   └── ollama.py         # Ollama 本地模型集成
│   ├── translation/           # 翻译模块
│   │   └── translation.py    # 翻译功能实现
│   └── video/                 # 视频处理模块
│       └── video_processing.py # 视频处理逻辑
├── templates/                  # HTML 模板
│   ├── index.html             # 主页面 - 视频字幕处理
│   └── speech_to_text.html    # 语音转文字页面
├── static/                     # 静态资源
│   ├── js/                    # JavaScript 文件
│   │   └── speech_to_text.js  # 语音转文字前端逻辑
│   └── css/                   # 样式文件 (如需要)
├── temp_web/                   # 临时文件目录
├── uploads/                    # 上传文件目录
├── outputs/                    # 输出文件目录
├── ssl/                        # SSL 证书目录
```

## 🛠️ 技术栈

### 后端

- **Flask**: Web 框架
- **Flask-SocketIO**: WebSocket 实时通信
- **FunASR**: 语音识别引擎
- **ModelScope**: 模型管理平台
- **MoviePy**: 视频处理
- **FFmpeg**: 多媒体处理

### 前端

- **HTML5/CSS3**: 用户界面
- **JavaScript**: 交互逻辑
- **Socket.IO**: 实时通信

### AI/模型

- **FunASR**: 语音识别
- **SenseVoice**: 通用的语音理解模型
- **Ollama**: 本地 AI 模型运行时

## 🚀 快速开始

### 环境要求

- Python 3.8+
- FFmpeg
- CUDA (可选，用于GPU加速)

### 安装依赖

```bash
pip install -r requirements.txt
```

### 准备 SSL 证书

```bash
# 生成自签名SSL证书
openssl req -x509 -newkey rsa:4096 -keyout ssl/server.key -out ssl/server.crt -days 365 -nodes
```

### 启动服务

```bash
python app.py
```

服务将在 `https://127.0.0.1:443` 启动。

## 📖 使用指南

### 语音转文字功能

1. 访问 `https://127.0.0.1:443/speech`
2. 点击或拖拽上传音频/视频文件
3. 选择处理选项（设备、语言、分段大小等）
4. 点击"开始转换"进行语音识别
5. 实时查看转写结果并下载

### 视频字幕处理（开发中）

1. 访问 `https://127.0.0.1:443/`
2. 上传视频文件
3. 选择字幕生成选项
4. 自动生成并嵌入字幕

## 🔧 配置说明

### 环境变量

```bash
# CUDA 设备设置
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=0

# Flask 配置
export FLASK_ENV=development
```

### 模型配置

项目默认使用以下 AI 模型：

- **FunASR MLT Nano**: `FunAudioLLM/Fun-ASR-MLT-Nano-2512` (多语言/多任务语音识别)

模型会自动从 ModelScope 下载并缓存到 `model_cache` 目录。

### 🌟 特性

- **智能资源管理**: 
  - 自动检测系统显存 (VRAM) 和内存 (RAM)。
  - 若显存不足 (低于 1.5GB)，自动从 GPU 降级到 CPU 推理，防止崩溃。
- **实时日志**: 同时输出到控制台和 `logs/video_app.log`，支持自动轮转。
- **SSL 安全**: 默认启用 HTTPS，保护数据传输安全。

## 📁 文件说明

### 核心文件

- `app.py`: Flask 应用入口，包含路由定义和服务器配置
- `api/speech_routes.py`: 语音转文字 API 实现
- `api/video_routes.py`: 视频处理 API 实现
- `api/chat_routes.py`: 聊天对话 API 实现
- `api/summary_routes.py`: 智能总结 API 实现
- `pkg/audio/audio_processing.py`: ASR 推理和音频处理核心逻辑
- `pkg/llm/deepseek.py`: DeepSeek AI 模型集成
- `pkg/llm/ollama.py`: Ollama 本地模型集成
- `pkg/translation/translation.py`: 翻译功能实现
- `pkg/video/video_processing.py`: 视频处理核心逻辑

### 模板文件

- `templates/index.html`: 视频字幕处理页面
- `templates/speech_to_text.html`: 语音转文字页面

### 静态资源

- `static/js/speech_to_text.js`: 前端交互逻辑

## 🔄 API 接口

### 语音转文字

```
POST /api/speech-to-text
Content-Type: multipart/form-data

参数:
- media_file: 音频/视频文件
- device: 处理设备 (auto/cuda:0/cpu)
- task_id: 任务ID
```

### 视频处理

```
POST /api/video/process
Content-Type: multipart/form-data

参数:
- video_file: 视频文件
- subtitle_options: 字幕选项
```

### 聊天对话

```
POST /api/chat
Content-Type: application/json

参数:
- message: 用户消息
- model: AI模型选择 (deepseek/ollama)
- context: 对话上下文
```

### 智能总结

```
POST /api/summary
Content-Type: application/json

参数:
- content: 待总结内容
- summary_type: 总结类型 (brief/detailed)
- language: 输出语言
```

## 🐛 故障排除

### 常见问题

1. **SSL 证书错误**: 确保 `ssl/server.crt` 和 `ssl/server.key` 文件存在
2. **依赖缺失**: 运行 `pip install -r requirements.txt`
3. **CUDA 错误**: 检查 CUDA 安装和环境变量设置
4. **端口占用**: 确保 443 端口未被其他服务占用

### 日志查看

系统日志（含 Flask Web 和 ASR 推理日志）统一输出到：

```bash
# Windows (PowerShell)
Get-Content logs/video_app.log -Wait

# Linux/Mac
tail -f logs/video_app.log
```

## 🤝 贡献指南

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push https://github.com/quitedob/video feature/AmazingFeature`)
5. 创建 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 📞 联系方式

项目维护者: quitedob    

项目链接: https://github.com/quitedob/video

---

**注意**: 本项目仍在积极开发中，功能可能会发生变化。如有问题或建议，请提交 Issue。
