# 🎬 智能视频字幕处理工作站

一个基于 AI 的智能视频字幕处理工作站，提供视频字幕生成、语音转文字等功能。

## 📋 项目状态

### ✅ 已完成功能

- **语音转文字**: 支持音频和视频文件的语音识别和转文字功能
  - 支持多种音频格式（MP3, WAV, M4A, FLAC等）
  - 支持多种视频格式（MP4, AVI, MOV, MKV等）
  - 基于 FunASR + Fun-ASR-Nano 的高精度语音识别
  - 支持31种语言，包括中文7大方言和26个地方口音
  - 自动音频分段处理，避免显存溢出

### 🚧 开发中功能

- **URL 下载**: 支持从网络URL下载视频和音频文件
- **视频字幕**: 为视频文件自动生成和嵌入字幕
- **会议总结**: 接入 AI API 进行会议内容智能总结

## 🚀 快速开始

### 环境要求

- Python 3.8+
- FFmpeg
- CUDA (可选，用于GPU加速，建议8GB+显存)

### 安装步骤

#### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

#### 2. 准备 SSL 证书

```bash
# 生成自签名SSL证书
openssl req -x509 -newkey rsa:4096 -keyout ssl/server.key -out ssl/server.crt -days 365 -nodes
```

#### 3. ⚠️ 重要：配置 Fun-ASR-Nano 模型

Fun-ASR-Nano 模型需要额外的 `model.py` 文件才能正常运行。

**步骤：**

1. 首次启动时，模型会自动下载到 `/model_cache/FunAudioLLM/Fun-ASR-Nano-2512/` 目录

2. 将项目根目录的 `model.py` 文件复制到模型缓存目录：

   **Windows (PowerShell):**
   ```powershell
   Copy-Item "model.py" "/model_cache/FunAudioLLM/Fun-ASR-Nano-2512/model.py" -Force
   ```

   **Windows (CMD):**
   ```cmd
   copy model.py \model_cache\FunAudioLLM\Fun-ASR-Nano-2512\model.py
   ```

   **Linux/Mac:**
   ```bash
   cp model.py /model_cache/FunAudioLLM/Fun-ASR-Nano-2512/model.py
   ```

3. 如果 `model.py` 不存在，请从 ModelScope 下载：
   - 访问 https://github.com/FunAudioLLM/Fun-ASR/blob/main/model.py
   - 下载 `model.py` 文件
   - 放置到上述模型缓存目录

#### 4. 启动服务

```bash
python app.py
```

服务将在 `https://127.0.0.1:443` 启动。

## 📖 使用指南

### 语音转文字功能

1. 访问 `https://127.0.0.1:443/speech`
2. 点击或拖拽上传音频/视频文件
3. 选择处理选项（设备、语言等）
4. 点击"开始转换"进行语音识别
5. 查看转写结果

## 🔧 配置说明

### 模型配置

项目使用 **Fun-ASR-Nano-2512** 模型：

| 特性 | 说明 |
|------|------|
| 模型ID | `FunAudioLLM/Fun-ASR-Nano-2512` |
| 参数量 | ~800M |
| 支持语言 | 31种语言 |
| 中文方言 | 7大方言 + 26个地方口音 |
| 显存需求 | 约 3-4GB |

### 音频切割配置

系统会自动将长音频切割成小段处理，避免显存溢出：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `segment_duration` | 30秒 | 每段音频的时长 |

**显存建议：**
- 16GB 显存：可设置 60-120 秒
- 8GB 显存：建议 30-60 秒  
- 4GB 显存：建议 15-30 秒
- CPU 模式：建议 30 秒

### 环境变量

```bash
# CUDA 设备设置
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export CUDA_VISIBLE_DEVICES=0

# 模型缓存目录（可选）
export MODELSCOPE_CACHE=/model_cache
```

## 🏗️ 项目结构

```
video/
├── app.py                      # Flask 主应用入口
├── model.py                    # ⚠️ Fun-ASR-Nano 模型文件（需复制到模型缓存目录）
├── requirements.txt            # Python 依赖
├── api/                        # API 路由层
│   ├── speech_routes.py       # 语音转文字 API
│   ├── video_routes.py        # 视频处理 API
│   └── ...
├── pkg/                        # 核心处理模块
│   ├── audio/
│   │   └── audio_processing.py # ASR 推理核心
│   ├── config/
│   │   └── config.py          # 配置管理
│   └── llm/                   # LLM 集成
├── templates/                  # HTML 模板
├── static/                     # 静态资源
├── model_cache/               # 模型缓存目录（自动创建）
├── temp_web/                   # 临时文件目录
├── uploads/                    # 上传文件目录
├── outputs/                    # 输出文件目录
├── logs/                       # 日志目录
└── ssl/                        # SSL 证书目录
```

## 🐛 故障排除

### 常见问题

#### 1. `No module named 'model'` 或 `Loading remote code failed`

**原因**: `model.py` 文件未放置到正确位置

**解决方案**:
```powershell
# Windows
Copy-Item "model.py" "/model_cache/FunAudioLLM/Fun-ASR-Nano-2512/model.py" -Force
```

#### 2. `ModuleNotFoundError: No module named 'datasets'`

**解决方案**:
```bash
pip install datasets transformers
```

#### 3. `CUDA out of memory`

**解决方案**: 减小音频分段时长
```bash
# 在 API 请求中设置较小的分段时长
curl -X POST https://127.0.0.1:443/api/speech-to-text \
  -F "media_file=@audio.mp3" \
  -F "segment_duration=15"
```

#### 4. `attention_mask` 警告

这是 transformers 库的正常警告，不影响识别结果，可以忽略。

### 日志查看

```bash
# Windows (PowerShell)
Get-Content logs/video_app.log -Wait

# Linux/Mac
tail -f logs/video_app.log
```

## 🔄 API 接口

### 语音转文字

```
POST /api/speech-to-text
Content-Type: multipart/form-data

参数:
- media_file: 音频/视频文件（必需）
- device: 处理设备 (auto/cuda:0/cpu)，默认 auto
- segment_duration: 分段时长（秒），默认 30
- task_id: 任务ID（可选）
```

## 📄 许可证

本项目采用 MIT 许可证

## 📞 联系方式

项目维护者: quitedob    
项目链接: https://github.com/quitedob/video

---

**注意**: 本项目仍在积极开发中。如有问题或建议，请提交 Issue。
