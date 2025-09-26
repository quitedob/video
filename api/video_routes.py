#api/video_routes.py
# 视频处理API路由  # 文件功能简介

from flask import Blueprint, request, jsonify, send_from_directory  # Flask组件
import os  # 环境变量
import tempfile  # 临时文件
import uuid  # 唯一ID生成
from pathlib import Path  # 路径处理

from flask_socketio import SocketIO
from werkzeug.utils import secure_filename  # 安全文件名处理

# 导入pkg模块功能
from pkg.video.video_processing import check_command_available, download_video, extract_audio_wav16k, burn_ass_subtitles  # 视频处理
from pkg.audio.audio_processing import create_asr_model, transcribe_audio_segments, AsrConfig  # 音频处理
from pkg.translation.translation import translate_segments  # 翻译功能
from pkg.config.config import global_config  # 全局配置
import subprocess  # 进程管理
import wave  # WAV文件处理
import time  # 时间处理

# 创建蓝图
video_bp = Blueprint('video', __name__)  # 视频API蓝图

# 全局任务状态存储
video_tasks = {}  # 视频任务状态字典

def emit_progress(task_id: str, progress: int, message: str):  # 进度发射函数
    """发送进度更新"""  # 文档
    try:  # 尝试获取SocketIO实例
        from app import socketio  # 从app模块导入socketio实例
        if socketio:  # 如果存在实例
            socketio.emit('progress', {  # 发送进度事件
                'task_id': task_id,  # 任务ID
                'progress': progress,  # 进度百分比
                'message': message  # 进度消息
            })  # 结束

            # 同时发送状态事件
            socketio.emit('status', {  # 发送状态事件
                'task_id': task_id,  # 任务ID
                'status': 'processing',  # 状态
                'progress': progress,  # 进度百分比
                'message': message  # 状态消息
            })  # 结束
    except ImportError:  # 导入失败时使用get_instance回退
        try:  # 尝试使用get_instance
            from flask_socketio import SocketIO  # 导入SocketIO
            socketio = SocketIO.get_instance()  # 获取SocketIO实例
            if socketio:  # 如果存在实例
                socketio.emit('progress', {  # 发送进度事件
                    'task_id': task_id,  # 任务ID
                    'progress': progress,  # 进度百分比
                    'message': message  # 进度消息
                })  # 结束

                # 同时发送状态事件
                socketio.emit('status', {  # 发送状态事件
                    'task_id': task_id,  # 任务ID
                    'status': 'processing',  # 状态
                    'progress': progress,  # 进度百分比
                    'message': message  # 状态消息
                })  # 结束
        except Exception as e:  # 忽略错误
            print(f"进度更新失败: {e}")  # 打印错误
    except Exception as e:  # 忽略其他错误
        print(f"进度更新失败: {e}")  # 打印错误


@video_bp.route('/upload', methods=['POST'])  # 上传路由
def upload_file():  # 上传处理
    """处理文件上传"""  # 文档
    if 'video' not in request.files:  # 无视频文件
        return jsonify({'error': '没有视频文件'}), 400  # 错误响应

    file = request.files['video']  # 获取文件
    if file.filename == '':  # 文件名为空
        return jsonify({'error': '文件名为空'}), 400  # 错误响应

    # 生成任务ID
    task_id = str(uuid.uuid4())  # 唯一任务ID

    # 保存上传的文件
    filename = secure_filename(file.filename)  # 安全文件名
    video_path = os.path.join('uploads', f'{task_id}_{filename}')  # 视频路径
    os.makedirs('uploads', exist_ok=True)  # 确保目录存在
    file.save(video_path)  # 保存文件

    # 初始化任务状态
    video_tasks[task_id] = {  # 任务状态
        'status': 'uploaded',  # 状态
        'video_path': video_path,  # 视频路径
        'progress': 0,  # 进度
        'message': '文件上传完成'  # 消息
    }  # 结束

    return jsonify({  # 返回结果
        'task_id': task_id,  # 任务ID
        'message': '文件上传成功'  # 成功消息
    })  # 结束


@video_bp.route('/process', methods=['POST'])  # 处理路由
def process_video():  # 视频处理
    """处理视频字幕生成"""  # 文档
    data = request.json  # 获取JSON数据
    task_id = data.get('task_id')  # 任务ID
    url = data.get('url')  # 视频URL
    options = data.get('options', {})  # 处理选项

    if not task_id and not url:  # 无任务ID也无URL
        return jsonify({'error': '需要任务ID或URL'}), 400  # 错误响应

    # 如果有URL，下载视频
    if url:  # 有URL
        try:  # 尝试下载
            # 为URL模式生成临时task_id用于进度跟踪
            temp_task_id = str(uuid.uuid4()) if not task_id else task_id
            emit_progress(temp_task_id, 10, '开始下载视频...')  # 进度提示
            video_path = download_video(url, Path('temp_web'),  # 下载视频
                                       lambda p, m: emit_progress(temp_task_id, 10 + int(p * 0.4), m))  # 进度回调
            task_id = str(uuid.uuid4())  # 生成新任务ID
            video_tasks[task_id] = {'status': 'downloaded', 'video_path': video_path}  # 任务状态
        except Exception as e:  # 下载失败
            return jsonify({'error': f'下载失败: {str(e)}'}), 500  # 错误响应
    else:  # 使用上传的文件
        if task_id not in video_tasks:  # 任务不存在
            return jsonify({'error': '任务不存在'}), 404  # 错误响应
        video_path = video_tasks[task_id]['video_path']  # 获取视频路径

    # 提取音频
    try:  # 尝试提取
        emit_progress(task_id, 50, '正在提取音频...')  # 进度提示
        audio_path = os.path.join('temp_web', f'{task_id}_audio.wav')  # 音频路径
        os.makedirs('temp_web', exist_ok=True)  # 确保目录存在
        extract_audio_wav16k(video_path, audio_path,  # 提取音频
                            lambda p, m: emit_progress(task_id, 50 + int(p * 0.2), m),  # 进度回调
                            timeout_seconds=600)  # 超时时间

        video_tasks[task_id].update({  # 更新任务状态
            'status': 'audio_extracted',  # 状态
            'audio_path': audio_path  # 音频路径
        })  # 结束

    except Exception as e:  # 提取失败
        return jsonify({'error': f'音频提取失败: {str(e)}'}), 500  # 错误响应

    # 语音识别
    try:  # 尝试识别
        emit_progress(task_id, 70, '正在进行语音识别...')  # 进度提示

        # 创建ASR模型
        device = options.get('device', 'auto')  # 获取设备参数
        # 简短中文注释：为视频字幕也配置完整的SenseVoice参数
        asr_config = AsrConfig(
            model_dir="iic/SenseVoiceSmall",
            device=device if device in ("auto", "cpu") else "cuda:0",
            trust_remote_code=True,
            remote_code="./model.py",
            vad_kwargs={"max_single_segment_time": 30000},  # 30s VAD切段上限
            batch_size_s=60,        # 动态batch
            merge_vad=True,         # 合并VAD碎片
            merge_length_s=15,      # 合并后目标长度
            use_itn=True,           # 输出标点与ITN
        )
        model = create_asr_model(asr_config)  # 创建模型

        # 执行语音识别（修复：传列表+cfg参数）
        segments = transcribe_audio_segments(model, [audio_path], asr_config)  # 识别音频
        video_tasks[task_id].update({  # 更新任务状态
            'status': 'transcribed',  # 状态
            'segments': segments  # 识别结果
        })  # 结束

        emit_progress(task_id, 90, f'识别完成，共{len(segments)}个片段')  # 进度提示

    except Exception as e:  # 识别失败
        return jsonify({'error': f'语音识别失败: {str(e)}'}), 500  # 错误响应

    # 翻译（如果启用）
    if options.get('translate', False):  # 需要翻译
        try:  # 尝试翻译
            emit_progress(task_id, 90, '正在翻译字幕...')  # 进度提示

            segments = translate_segments(segments,  # 翻译段落
                                        lambda p, m: emit_progress(task_id, 90 + int(p * 0.05), m))  # 进度回调
            video_tasks[task_id].update({  # 更新任务状态
                'status': 'translated',  # 状态
                'segments': segments  # 翻译结果
            })  # 结束

        except Exception as e:  # 翻译失败
            return jsonify({'error': f'翻译失败: {str(e)}'}), 500  # 错误响应

    # 生成字幕文件并渲染视频
    try:  # 尝试渲染
        emit_progress(task_id, 95, '正在渲染字幕视频...')  # 进度提示

        # 生成ASS字幕文件
        ass_path = os.path.join('temp_web', f'{task_id}_subtitles.ass')  # 字幕路径
        with open(ass_path, 'w', encoding='utf-8-sig') as f:  # 写入字幕
            f.write('[Script Info]\nTitle: Video Subtitles\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\nYCbCr Matrix: TV.601\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,48,&H00ffffff,&H000000ff,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')

            for i, segment in enumerate(segments):  # 遍历段落
                start_time = f"{int(segment['start_ms']//3600000):d}:{int(segment['start_ms']//60000)%60:02d}:{int(segment['start_ms']//1000)%60:02d}.{int(segment['start_ms']%1000):03d}"  # 开始时间
                end_time = f"{int(segment['end_ms']//3600000):d}:{int(segment['end_ms']//60000)%60:02d}:{int(segment['end_ms']//1000)%60:02d}.{int(segment['end_ms']%1000):03d}"  # 结束时间
                text = segment.get('translated_text', segment['text']).replace('\n', '\\n')  # 文本
                f.write(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{text}\n")  # 写入对话

        # 渲染最终视频
        output_path = os.path.join('outputs', f'{task_id}_final.mp4')  # 输出路径
        os.makedirs('outputs', exist_ok=True)  # 确保目录存在
        burn_ass_subtitles(video_path, ass_path, output_path,  # 渲染字幕
                          'force_style=\'FontName=Arial,FontSize=48,PrimaryColour=&H00ffffff,SecondaryColour=&H000000ff,OutlineColour=&H00000000,BackColour=&H00000000,Bold=0,Italic=0,Underline=0,StrikeOut=0,ScaleX=100,ScaleY=100,Spacing=0,Angle=0.00,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginL=10,MarginR=10,MarginV=10,Encoding=1\'',  # 样式字符串
                          lambda p, m: emit_progress(task_id, 95 + int(p * 0.05), m))  # 进度回调

        video_tasks[task_id].update({  # 更新任务状态
            'status': 'completed',  # 状态
            'output_path': output_path  # 输出路径
        })  # 结束

        emit_progress(task_id, 100, '处理完成！')  # 完成提示

        # 发送任务完成事件
        try:
            from app import socketio
            socketio.emit('task_completed', {
                'task_id': task_id,
                'status': 'completed',
                'output_url': f'/api/download/{task_id}',
                'message': '视频字幕处理完成'
            })

            # 同时发送状态事件
            socketio.emit('status', {
                'task_id': task_id,
                'status': 'completed',
                'progress': 100,
                'message': '视频字幕处理完成'
            })
        except ImportError:
            try:
                socketio = SocketIO.get_instance()
                if socketio:
                    socketio.emit('task_completed', {
                        'task_id': task_id,
                        'status': 'completed',
                        'output_url': f'/api/download/{task_id}',
                        'message': '视频字幕处理完成'
                    })

                    # 同时发送状态事件
                    socketio.emit('status', {
                        'task_id': task_id,
                        'status': 'completed',
                        'progress': 100,
                        'message': '视频字幕处理完成'
                    })
            except Exception:
                pass

        return jsonify({  # 返回结果
            'task_id': task_id,  # 任务ID
            'status': 'completed',  # 状态
            'output_url': f'/api/download/{task_id}'  # 下载链接
        })  # 结束

    except Exception as e:  # 渲染失败
        error_message = f'视频渲染失败: {str(e)}'

        # 发送任务错误事件
        try:
            from app import socketio
            socketio.emit('task_error', {
                'task_id': task_id,
                'error': error_message,
                'message': '视频字幕处理失败'
            })

            # 同时发送状态事件
            socketio.emit('status', {
                'task_id': task_id,
                'status': 'failed',
                'progress': 0,
                'message': '视频字幕处理失败'
            })
        except ImportError:
            try:
                socketio = SocketIO.get_instance()
                if socketio:
                    socketio.emit('task_error', {
                        'task_id': task_id,
                        'error': error_message,
                        'message': '视频字幕处理失败'
                    })

                    # 同时发送状态事件
                    socketio.emit('status', {
                        'task_id': task_id,
                        'status': 'failed',
                        'progress': 0,
                        'message': '视频字幕处理失败'
                    })
            except Exception:
                pass

        return jsonify({'error': error_message}), 500  # 错误响应


@video_bp.route('/status/<task_id>')  # 状态查询路由
def get_status(task_id):  # 获取状态
    """获取任务状态"""  # 文档
    task = video_tasks.get(task_id)  # 获取任务
    if not task:  # 任务不存在
        return jsonify({'error': '任务不存在'}), 404  # 错误响应

    return jsonify(task)  # 返回任务状态


@video_bp.route('/download/<task_id>')  # 下载路由
def download_file(task_id):  # 文件下载
    """下载处理后的文件"""  # 文档
    task = video_tasks.get(task_id)  # 获取任务
    if not task or task['status'] != 'completed':  # 任务未完成
        return jsonify({'error': '任务未完成或不存在'}), 404  # 错误响应

    output_path = task['output_path']  # 输出路径
    return send_from_directory('outputs', os.path.basename(output_path), as_attachment=True)  # 发送文件


@video_bp.route('/clear-temp', methods=['POST'])  # 清理临时文件路由
def clear_temp_files():  # 清理临时文件
    """清理临时文件"""  # 文档
    try:  # 尝试清理
        import shutil  # 导入清理模块

        # 清理上传目录
        upload_dir = 'uploads'  # 上传目录
        if os.path.exists(upload_dir):  # 目录存在
            for file in os.listdir(upload_dir):  # 遍历文件
                file_path = os.path.join(upload_dir, file)  # 文件路径
                if os.path.isfile(file_path):  # 是文件
                    os.remove(file_path)  # 删除文件

        # 清理临时目录
        temp_dir = 'temp_web'  # 临时目录
        if os.path.exists(temp_dir):  # 目录存在
            shutil.rmtree(temp_dir)  # 删除目录
            os.makedirs(temp_dir, exist_ok=True)  # 重新创建

        # 清理任务状态
        video_tasks.clear()  # 清空任务

        return jsonify({'message': '临时文件清理完成'})  # 成功响应

    except Exception as e:  # 清理失败
        return jsonify({'error': f'清理失败: {str(e)}'}), 500  # 错误响应


def validate_media_file(file) -> dict:  # 验证媒体文件函数
    """验证媒体文件格式和大小"""  # 文档
    max_size = 500 * 1024 * 1024  # 500MB最大限制
    allowed_audio_types = [  # 允许的音频类型
        'audio/mpeg', 'audio/mp3', 'audio/wav', 'audio/x-wav',
        'audio/mp4', 'audio/m4a', 'audio/aac', 'audio/flac'
    ]
    allowed_video_types = [  # 允许的视频类型
        'video/mp4', 'video/avi', 'video/x-msvideo', 'video/quicktime',
        'video/x-matroska', 'video/webm'
    ]
    allowed_extensions = ['.mp3', '.wav', '.m4a', '.mp4', '.avi', '.mov', '.mkv', '.flac']  # 允许的文件扩展名

    # 稳健获取文件大小：优先使用content_length，否则使用stream.seek/tell
    file_size = None  # 文件大小初始化
    try:  # 尝试获取文件大小
        if hasattr(file, 'content_length') and file.content_length is not None:  # 使用content_length
            file_size = file.content_length  # 文件大小
        elif hasattr(file, 'stream') and hasattr(file.stream, 'seek') and hasattr(file.stream, 'tell'):  # 使用stream
            current_pos = file.stream.tell()  # 当前位置
            file.stream.seek(0, 2)  # 移到末尾
            file_size = file.stream.tell()  # 获取大小
            file.stream.seek(current_pos)  # 恢复位置
        else:  # 无法获取大小
            file_size = None  # 大小未知
    except Exception:  # 获取失败
        file_size = None  # 大小未知

    # 检查文件大小
    if file_size is not None and file_size > max_size:  # 文件过大
        return {  # 返回错误
            'valid': False,  # 无效
            'error': f'文件大小超过500MB限制，当前大小: {file_size / (1024*1024):.1f}MB'  # 错误消息
        }

    # 检查文件类型
    if file.mimetype in allowed_audio_types or file.mimetype in allowed_video_types:  # 允许的类型
        return {'valid': True, 'type': 'audio' if file.mimetype in allowed_audio_types else 'video'}  # 返回有效

    # 检查文件扩展名
    file_name = file.filename.lower()  # 文件名小写
    if any(file_name.endswith(ext) for ext in allowed_extensions):  # 允许的扩展名
        return {'valid': True, 'type': 'audio' if file_name.endswith(('.mp3', '.wav', '.m4a', '.flac')) else 'video'}  # 返回有效

    return {  # 返回错误
        'valid': False,  # 无效
        'error': f'不支持的文件格式: {file.mimetype or file.filename}'  # 错误消息
    }  # 结束


def extract_audio_from_media(media_path: str, output_path: str, progress_callback=None) -> bool:  # 提取音频函数
    """从媒体文件中提取音频"""  # 文档
    try:  # 尝试提取
        # 使用FFmpeg提取音频
        cmd = [  # FFmpeg命令
            'ffmpeg', '-i', media_path,  # 输入文件
            '-vn',  # 无视频
            '-acodec', 'pcm_s16le',  # 16位PCM编码
            '-ar', '16000',  # 16kHz采样率
            '-ac', '1',  # 单声道
            '-y',  # 覆盖输出
            output_path  # 输出文件
        ]

        # 执行命令
        process = subprocess.Popen(cmd,  # 创建进程
                                 stdout=subprocess.PIPE,  # 标准输出
                                 stderr=subprocess.PIPE,  # 标准错误
                                 universal_newlines=True)  # 文本模式

        while True:  # 循环处理
            if process.poll() is not None:  # 进程结束
                break  # 跳出

            if progress_callback:  # 有进度回调
                progress_callback(50, '正在提取音频...')  # 进度回调

            time.sleep(0.1)  # 等待

        # 检查结果
        if process.returncode == 0:  # 成功
            return True  # 返回成功
        else:  # 失败
            error_output = process.stderr.read()  # 错误输出
            raise Exception(f'音频提取失败: {error_output}')  # 抛出异常

    except Exception as e:  # 提取失败
        print(f'音频提取出错: {e}')  # 打印错误
        return False  # 返回失败


def segment_audio_file(audio_path: str, segment_duration_minutes: int) -> list:  # 分段音频函数
    """将音频文件分段处理"""  # 文档
    segments = []  # 分段列表

    try:  # 尝试分段
        # 打开WAV文件获取信息
        with wave.open(audio_path, 'rb') as wav_file:  # 打开WAV文件
            sample_rate = wav_file.getframerate()  # 采样率
            channels = wav_file.getnchannels()  # 声道数
            duration_seconds = wav_file.getnframes() / sample_rate  # 时长秒
            duration_minutes = duration_seconds / 60  # 时长分钟

        # 计算分段数量
        segment_duration_seconds = segment_duration_minutes * 60  # 分段时长秒
        total_segments = int(duration_seconds // segment_duration_seconds) + 1  # 总分段数

        # 创建分段
        for i in range(total_segments):  # 遍历分段
            start_time = i * segment_duration_seconds  # 开始时间
            end_time = min((i + 1) * segment_duration_seconds, duration_seconds)  # 结束时间

            if end_time - start_time < 1:  # 分段太小
                break  # 跳出

            segments.append({  # 添加分段
                'index': i,  # 索引
                'start_time': start_time,  # 开始时间
                'end_time': end_time,  # 结束时间
                'duration': end_time - start_time  # 时长
            })

        return segments  # 返回分段列表

    except Exception as e:  # 分段失败
        print(f'音频分段失败: {e}')  # 打印错误
        return segments  # 返回空列表
