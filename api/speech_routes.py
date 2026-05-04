# api/speech_routes.py
# 语音转文字API路由
# 说明（中文注释）：提供两种模式——(1) 异步+Socket仅做进度；(2) 简洁同步HTTP一次性返回文本
from flask import Blueprint, request, jsonify, send_from_directory
import json
import os
import tempfile
import uuid
import threading
import shutil
import datetime
from flask_socketio import SocketIO  # 仅用于进度推送
import subprocess
import time
from werkzeug.utils import secure_filename

# 说明：引入单段与多段识别函数 + 配置 + 新流式架构
from pkg.audio.audio_processing import (
    get_asr_model,                # 单例缓存模型
    extract_audio_to_memory,      # 零I/O音频提取到内存
    transcribe_memory_chunks,     # 内存切片推理
    transcribe_audio_segment,     # 单段识别（simple接口备用）
    AsrConfig,
    StreamingAsrProcessor,        # 流式ASR处理器
    FfmpegProducer,              # FFmpeg生产者
    AsrConsumer                  # ASR消费者
)

# 说明：媒体校验/抽音/计算分段
from .video_routes import (
    validate_media_file,
    extract_audio_from_media,
    segment_audio_file
)

speech_bp = Blueprint('speech', __name__)
speech_tasks = {}  # 简单的内存任务表

# 全局流式ASR处理器实例
streaming_processor = None

def get_streaming_processor():
    """获取或创建流式ASR处理器实例"""
    global streaming_processor
    if streaming_processor is None:
        # 直接从全局导入socketio
        from app import socketio
        streaming_processor = StreamingAsrProcessor(socketio)
    return streaming_processor

# 说明：统一的进度推送（可被关闭）
def emit_speech_progress(task_id: str, progress: int, message: str, segment_info=None):
    """发送语音转文字进度更新（若无socket则忽略）"""
    try:
        from app import socketio
        if socketio:
            data = {'task_id': task_id, 'progress': progress, 'message': message}
            if segment_info:
                data.update(segment_info)
            socketio.emit('progress', data)
            if segment_info:
                socketio.emit('segment_progress', segment_info)
    except ImportError:
        try:
            socketio = SocketIO.get_instance()
            if socketio:
                data = {'task_id': task_id, 'progress': progress, 'message': message}
                if segment_info:
                    data.update(segment_info)
                socketio.emit('progress', data)
                if segment_info:
                    socketio.emit('segment_progress', segment_info)
        except Exception:
            pass
    except Exception:
        pass

# ========================
# 模式A：异步 + 仅用Socket做进度提示（原有接口）
# ========================
def process_speech_to_text_sync(task_id: str, media_path: str, temp_dir: str,
                               device: str, language: str, segment_duration: int) -> dict:
    """
    同步处理语音转文字：FFmpeg pipe→内存numpy→单次推理→返回文本+计时
    零磁盘中间文件，1次FFmpeg子进程，1次model.generate()调用
    返回: {'text': str, 'audio_duration': float, 'total_time': float,
           'extract_time': float, 'infer_time': float}
    """
    try:
        print(f"[处理] 开始语音转文字同步处理（零I/O管道），task_id={task_id}")
        total_t0 = time.time()

        # 1) FFmpeg pipe → 内存numpy（零磁盘I/O，仅1次子进程）
        extract_t0 = time.time()
        audio = extract_audio_to_memory(media_path)
        extract_time = time.time() - extract_t0
        audio_duration = len(audio) / 16000
        print(f"[处理] 音频提取完成，时长 {audio_duration:.1f}s，提取耗时 {extract_time:.1f}s，内存 {len(audio)*4/1024/1024:.1f}MB")

        # 2) 获取缓存的ASR模型
        asr_config = AsrConfig(
            model_dir="iic/SenseVoiceSmall",
            device=device if device in ("auto", "cpu") else "cuda:0",
            trust_remote_code=True,
            remote_code="./model.py",
            vad_kwargs={"max_single_segment_time": 30000},
            batch_size_s=300,
            merge_vad=True,
            merge_length_s=15,
            use_itn=True,
        )
        model = get_asr_model(asr_config)

        # 3) 一次性传入完整音频，模型内部 VAD + batch_size_s 自动分段批处理
        print(f"[处理] 开始推理（单次调用，内部自动批处理）...")
        infer_t0 = time.time()
        if hasattr(model, "generate"):
            raw_res = model.generate(
                input=audio,
                cache={},
                language="auto",
                use_itn=asr_config.use_itn,
                batch_size_s=asr_config.batch_size_s,
                merge_vad=asr_config.merge_vad,
                merge_length_s=asr_config.merge_length_s,
            )
        else:
            raw_res = model(audio)

        from pkg.audio.audio_processing import _parse_asr_result
        final_text = _parse_asr_result(raw_res)
        infer_time = time.time() - infer_t0
        total_time = time.time() - total_t0
        rtf = audio_duration / infer_time if infer_time > 0 else 0

        print(f"[处理] 完成！音频 {audio_duration:.1f}s | 提取 {extract_time:.1f}s | "
              f"推理 {infer_time:.1f}s | 总计 {total_time:.1f}s | RTF {rtf:.2f}x | 文本 {len(final_text)}字")

        return {
            'text': final_text,
            'audio_duration': round(audio_duration, 1),
            'extract_time': round(extract_time, 2),
            'infer_time': round(infer_time, 2),
            'total_time': round(total_time, 2),
            'rtf': round(rtf, 2),
        }

    except Exception as e:
        import traceback
        print(f"[处理] 语音转文字同步处理异常: {str(e)}")
        print(traceback.format_exc())
        raise


def process_speech_to_text(task_id: str, media_path: str, temp_dir: str,
                           device: str, language: str, segment_duration: int,
                           notify: str):
    """后台处理语音转文字：FFmpeg pipe→内存numpy→单次推理→汇总（零磁盘中间文件）"""
    try:
        total_t0 = time.time()

        if notify != 'none':
            emit_speech_progress(task_id, 10, '开始处理文件...')

        # 1) FFmpeg pipe → 内存numpy
        if notify != 'none':
            emit_speech_progress(task_id, 20, '正在提取音频到内存...')
        extract_t0 = time.time()
        audio = extract_audio_to_memory(media_path)
        extract_time = time.time() - extract_t0
        duration = len(audio) / 16000

        if notify != 'none':
            emit_speech_progress(task_id, 40, f'音频提取完成({duration:.1f}s)，开始识别...')

        # 2) 获取缓存的ASR模型
        asr_config = AsrConfig(
            model_dir="iic/SenseVoiceSmall",
            device=device if device in ("auto", "cpu") else "cuda:0",
            trust_remote_code=True,
            remote_code="./model.py",
            vad_kwargs={"max_single_segment_time": 30000},
            batch_size_s=300,       # CPU推理加大批次
            merge_vad=True,
            merge_length_s=15,
            use_itn=True,
        )
        model = get_asr_model(asr_config)

        # 3) 一次性传入完整音频推理
        if notify != 'none':
            emit_speech_progress(task_id, 50, '正在进行语音识别...')

        infer_t0 = time.time()
        try:
            from pkg.audio.audio_processing import _parse_asr_result
            if hasattr(model, "generate"):
                raw_res = model.generate(
                    input=audio,
                    cache={},
                    language="auto",
                    use_itn=asr_config.use_itn,
                    batch_size_s=asr_config.batch_size_s,
                    merge_vad=asr_config.merge_vad,
                    merge_length_s=asr_config.merge_length_s,
                )
            else:
                raw_res = model(audio)
            final_text = _parse_asr_result(raw_res)
        except Exception as e:
            print(f"[处理] 识别失败: {e}")
            final_text = "识别过程中发生错误"
        infer_time = time.time() - infer_t0
        total_time = time.time() - total_t0
        rtf = duration / infer_time if infer_time > 0 else 0

        print(f"[处理] 异步完成！音频 {duration:.1f}s | 提取 {extract_time:.1f}s | "
              f"推理 {infer_time:.1f}s | 总计 {total_time:.1f}s | RTF {rtf:.2f}x")

        # 5) 保存结果文件（供下载/留存）
        result_path = os.path.join(temp_dir, 'speech_result.txt')
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(final_text)

        speech_tasks[task_id].update({
            'status': 'completed',
            'result_path': result_path,
            'text': final_text,
            'timing': {
                'audio_duration': round(duration, 1),
                'extract_time': round(extract_time, 2),
                'infer_time': round(infer_time, 2),
                'total_time': round(total_time, 2),
                'rtf': round(rtf, 2),
            }
        })

        if notify != 'none':
            emit_speech_progress(task_id, 100, '语音转文字完成！')
            # 同时推送最终结果（含计时）
            result_data = {
                'task_id': task_id,
                'text': final_text,
                'timing': {
                    'audio_duration': round(duration, 1),
                    'extract_time': round(extract_time, 2),
                    'infer_time': round(infer_time, 2),
                    'total_time': round(total_time, 2),
                    'rtf': round(rtf, 2),
                }
            }
            try:
                from app import socketio
                socketio.emit('speech_result', result_data)
            except ImportError:
                socketio = SocketIO.get_instance()
                if socketio:
                    socketio.emit('speech_result', result_data)

    except Exception as e:
        speech_tasks[task_id]['status'] = 'failed'
        if notify != 'none':
            try:
                from app import socketio
                socketio.emit('speech_error', {'task_id': task_id, 'error': str(e)})
            except ImportError:
                socketio = SocketIO.get_instance()
                if socketio:
                    socketio.emit('speech_error', {'task_id': task_id, 'error': str(e)})


# ========================
# 模式B：HTTP简洁同步（无需Socket，返回最终文本）
# ========================
@speech_bp.route('/speech-to-text/simple', methods=['POST'])
def speech_to_text_simple():
    """同步接口：上传文件→等待完成→直接返回最终文本"""
    try:
        if 'media_file' not in request.files:
            return jsonify({'error': '没有上传文件'}), 400
        file = request.files['media_file']
        if file.filename == '':
            return jsonify({'error': '文件名为空'}), 400

        validation = validate_media_file(file)
        if not validation['valid']:
            return jsonify({'error': validation['error']}), 400

        # 临时场景保存
        with tempfile.TemporaryDirectory(dir='temp_web') as td:
            filename = secure_filename(file.filename)
            media_path = os.path.join(td, filename)
            file.save(media_path)

            # 调用同步处理函数（含计时）
            device = request.form.get('device', 'auto')
            result = process_speech_to_text_sync(
                'simple', media_path, td, device, 'auto', 120
            )
            return jsonify({
                'text': result['text'],
                'timing': {
                    'audio_duration': result['audio_duration'],
                    'extract_time': result['extract_time'],
                    'infer_time': result['infer_time'],
                    'total_time': result['total_time'],
                    'rtf': result['rtf'],
                }
            })
    except Exception as e:
        return jsonify({'error': f'处理失败: {e}'}), 500


@speech_bp.route('/speech-download/<task_id>')
def download_speech_result(task_id):
    """下载语音转文字结果"""
    task = speech_tasks.get(task_id)
    if not task or task['status'] != 'completed':
        return jsonify({'error': '任务未完成或不存在'}), 404
    result_path = task['result_path']
    if not os.path.exists(result_path):
        return jsonify({'error': '结果文件不存在'}), 404
    return send_from_directory(os.path.dirname(result_path), os.path.basename(result_path), as_attachment=True)


# =====================================================
# 新的流式ASR API端点（基于生产者-消费者架构）
# =====================================================

@speech_bp.route('/speech-to-text', methods=['POST'])
def speech_to_text():
    """
    语音转文字端点 - 直接处理并返回完整文本
    移除Socket.IO，改为同步HTTP请求-响应
    """
    try:
        if 'media_file' not in request.files:
            return jsonify({'error': '没有上传文件'}), 400

        file = request.files['media_file']
        if file.filename == '':
            return jsonify({'error': '文件名为空'}), 400

        validation = validate_media_file(file)
        if not validation['valid']:
            return jsonify({'error': validation['error']}), 400

        # 生成任务ID
        task_id = request.form.get('task_id', str(uuid.uuid4()))
        temp_dir = os.path.join('temp_web', task_id)
        os.makedirs(temp_dir, exist_ok=True)

        filename = secure_filename(file.filename)
        media_path = os.path.join(temp_dir, filename)
        file.save(media_path)

        # 存储任务信息
        speech_tasks[task_id] = {
            'status': 'processing',
            'media_path': media_path,
            'temp_dir': temp_dir,
            'progress': 10,
            'message': '正在处理语音转文字...',
            'processor': 'direct'
        }

        device = request.form.get('device', 'auto')
        language = request.form.get('language', 'auto')
        segment_duration = int(request.form.get('segment_duration', 120))  # 默认2分钟

        try:
            # 直接调用语音转文字处理（同步方式）
            print(f"[API] 开始语音转文字处理，task_id={task_id}")
            result = process_speech_to_text_sync(
                task_id, media_path, temp_dir, device, language, segment_duration
            )

            # 清理临时文件
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                print(f"[API] 清理临时目录失败: {e}")

            # 返回完整结果
            speech_tasks[task_id]['status'] = 'completed'
            speech_tasks[task_id]['progress'] = 100
            speech_tasks[task_id]['result'] = result['text']

            return jsonify({
                'task_id': task_id,
                'text': result['text'],
                'message': '语音转文字处理完成',
                'status': 'completed',
                'timing': {
                    'audio_duration': result['audio_duration'],
                    'extract_time': result['extract_time'],
                    'infer_time': result['infer_time'],
                    'total_time': result['total_time'],
                    'rtf': result['rtf'],
                }
            })

        except Exception as e:
            speech_tasks[task_id]['status'] = 'failed'
            speech_tasks[task_id]['error'] = str(e)

            # 清理临时文件
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_e:
                print(f"[API] 清理临时目录失败: {cleanup_e}")

            print(f"[API] 语音转文字处理失败: {str(e)}")
            return jsonify({'error': f'处理失败: {str(e)}'}), 500

    except Exception as e:
        import traceback
        print(f"[API] 语音转文字请求异常: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': f'请求处理失败: {str(e)}'}), 500


@speech_bp.route('/streaming-speech-status/<task_id>')
def get_streaming_speech_status(task_id):
    """获取流式语音转文字任务状态"""
    processor = get_streaming_processor()
    status = processor.get_task_status(task_id)

    if status['status'] == 'not_found':
        task = speech_tasks.get(task_id)
        if not task:
            return jsonify({'error': '任务不存在'}), 404
        return jsonify(task)

    return jsonify(status)


@speech_bp.route('/streaming-speech-stop/<task_id>', methods=['POST'])
def stop_streaming_speech(task_id):
    """停止流式语音转文字任务"""
    processor = get_streaming_processor()
    processor.stop_task(task_id)

    if task_id in speech_tasks:
        speech_tasks[task_id]['status'] = 'stopped'

    return jsonify({'message': '任务已停止'})


@speech_bp.route('/streaming-speech-result/<task_id>')
def get_streaming_speech_result(task_id):
    """获取流式语音转文字完整结果"""
    processor = get_streaming_processor()
    result = processor.get_full_result(task_id)

    if not result:
        task = speech_tasks.get(task_id)
        if not task:
            return jsonify({'error': '任务不存在'}), 404
        return jsonify({'result': ''})

    return jsonify({'result': result})


# =====================================================
# WebSocket事件处理（新的流式协议）
# =====================================================

def register_socket_events(socketio):
    """注册WebSocket事件处理函数"""

    @socketio.on('start_asr_stream')
    def handle_start_asr_stream(data):
        """处理客户端启动ASR流请求"""
        print(f"[Socket] 收到start_asr_stream事件: {data}")
        task_id = data.get('task_id')
        if not task_id:
            print(f"[Socket] 缺少任务ID")
            socketio.emit('asr_error', {'error': '缺少任务ID'})
            return

        task = speech_tasks.get(task_id)
        print(f"[Socket] 查找任务: {task_id}, 结果: {task}")
        if not task or task.get('processor') != 'streaming':
            print(f"[Socket] 任务未找到或不是流式任务")
            socketio.emit('asr_error', {'task_id': task_id, 'error': '任务未找到或不是流式任务'})
            return

        print(f"[Socket] 任务验证通过，状态: {task.get('status')}")
        # 发送确认事件（Socket事件处理器发送）
        socketio.emit('asr_task_created', {
            'task_id': task_id,
            'message': 'ASR流已启动，等待数据...'
        }, namespace="/")
        print(f"[Socket] 已发送asr_task_created事件")

    @socketio.on('stop_asr_stream')
    def handle_stop_asr_stream(data):
        """处理客户端停止ASR流请求"""
        task_id = data.get('task_id')
        if not task_id:
            return

        processor = get_streaming_processor()
        processor.stop_task(task_id)

        if task_id in speech_tasks:
            speech_tasks[task_id]['status'] = 'stopped'

    @socketio.on('get_asr_status')
    def handle_get_asr_status(data):
        """处理客户端查询ASR状态请求"""
        task_id = data.get('task_id')
        if not task_id:
            return

        processor = get_streaming_processor()
        status = processor.get_task_status(task_id)

        socketio.emit('asr_status', {
            'task_id': task_id,
            'status': status
        })

# =====================================================
# 批量处理功能
# =====================================================

@speech_bp.route('/select-folder', methods=['GET'])
def select_folder():
    """打开系统文件夹选择对话框"""
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)

        folder_path = filedialog.askdirectory(title="选择文件夹")

        if folder_path:
            return jsonify({'path': folder_path.replace('/', os.sep)})
        else:
            return jsonify({'path': ''})
    except Exception as e:
        print(f"选择文件夹失败: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if root is not None:
            try:
                root.quit()
                root.destroy()
            except Exception:
                pass


@speech_bp.route('/batch-process', methods=['POST'])
def batch_process():
    """批量处理语音转文字"""
    try:
        data = request.json
        input_folder = data.get('input_folder')
        output_folder = data.get('output_folder')
        
        if not input_folder or not os.path.exists(input_folder):
            return jsonify({'error': '输入文件夹不存在'}), 400
            
        # 默认输出到桌面的同名文件夹
        if not output_folder:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            folder_name = os.path.basename(input_folder)
            output_folder = os.path.join(desktop, folder_name)
            
        # 创建任务ID
        task_id = str(uuid.uuid4())
        
        # 启动后台线程处理
        thread = threading.Thread(
            target=batch_process_thread,
            args=(task_id, input_folder, output_folder, data)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'task_id': task_id,
            'message': '批量处理已启动',
            'output_folder': output_folder
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =====================================================
# 识别缓存（跳过已识别文件）
# =====================================================

RECOGNITION_CACHE_PATH = os.path.join('outputs', 'recognition_cache.json')


def load_recognition_cache():
    """加载识别缓存"""
    if os.path.exists(RECOGNITION_CACHE_PATH):
        try:
            with open(RECOGNITION_CACHE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_recognition_cache(cache):
    """保存识别缓存"""
    os.makedirs(os.path.dirname(RECOGNITION_CACHE_PATH), exist_ok=True)
    with open(RECOGNITION_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def is_file_recognized(file_path):
    """检查文件是否已识别过（文件路径+大小+mtime均匹配才视为相同文件）"""
    cache = load_recognition_cache()
    abs_path = os.path.abspath(file_path)
    if abs_path not in cache:
        return False
    try:
        stat = os.stat(abs_path)
        entry = cache[abs_path]
        if entry.get('file_size') == stat.st_size and entry.get('file_mtime') == stat.st_mtime:
            return True
    except OSError:
        pass
    return False


def mark_file_recognized(file_path, output_path=''):
    """标记文件为已识别"""
    cache = load_recognition_cache()
    abs_path = os.path.abspath(file_path)
    try:
        stat = os.stat(abs_path)
        cache[abs_path] = {
            'file_size': stat.st_size,
            'file_mtime': stat.st_mtime,
            'recognized_at': datetime.datetime.now().isoformat(),
            'output_path': output_path
        }
        save_recognition_cache(cache)
    except OSError:
        pass


def batch_process_thread(task_id, input_folder, output_folder, options):
    """批量处理后台线程"""
    from app import socketio

    device = options.get('device', 'auto')
    language = options.get('language', 'auto')
    segment_duration = int(options.get('segment_duration', 120))
    skip_existing = options.get('skip_existing', False)
    skip_recognized = options.get('skip_recognized', False)

    processed_count = 0
    skipped_count = 0
    total_files = 0
    files_to_process = []

    # 加载识别缓存（用于跳过已识别文件）
    recognition_cache = load_recognition_cache() if skip_recognized else {}

    try:
        # 1. 扫描文件
        socketio.emit('batch_log', {'task_id': task_id, 'level': 'info', 'message': f'开始扫描文件夹: {input_folder}'})

        supported_exts = ('.mp4', '.mp3', '.m4a')

        for root, dirs, files in os.walk(input_folder):
            for file in files:
                if file.lower().endswith(supported_exts):
                    files_to_process.append(os.path.join(root, file))

        total_files = len(files_to_process)
        socketio.emit('batch_log', {'task_id': task_id, 'level': 'info', 'message': f'找到 {total_files} 个待处理文件'})

        if skip_recognized and recognition_cache:
            cached_count = sum(1 for fp in files_to_process if is_file_recognized(fp))
            socketio.emit('batch_log', {'task_id': task_id, 'level': 'info', 'message': f'其中 {cached_count} 个文件已识别过（将跳过）'})

        # 2. 逐个处理
        for file_path in files_to_process:
            try:
                processed_count += 1
                rel_path = os.path.relpath(file_path, input_folder)
                file_name = os.path.basename(file_path)

                # 确定输出路径
                rel_dir = os.path.dirname(rel_path)
                target_dir = os.path.join(output_folder, rel_dir)
                os.makedirs(target_dir, exist_ok=True)

                base_name = os.path.splitext(file_name)[0]
                target_txt_name = f"{base_name}.txt"
                target_txt_path = os.path.join(target_dir, target_txt_name)

                # 检查：跳过已识别的文件
                if skip_recognized and is_file_recognized(file_path):
                    skipped_count += 1
                    socketio.emit('batch_log', {'task_id': task_id, 'level': 'success', 'message': f'⏭ 跳过已识别: {file_name} [{processed_count}/{total_files}]'})
                    socketio.emit('batch_progress', {
                        'task_id': task_id,
                        'current': processed_count,
                        'total': total_files,
                        'current_file': f'{file_name} (跳过)',
                        'percent': int((processed_count / total_files) * 100)
                    })
                    continue

                socketio.emit('batch_progress', {
                    'task_id': task_id,
                    'current': processed_count,
                    'total': total_files,
                    'current_file': file_name,
                    'percent': int((processed_count / total_files) * 100)
                })

                socketio.emit('batch_log', {'task_id': task_id, 'level': 'info', 'message': f'正在处理 [{processed_count}/{total_files}]: {file_name}'})

                # 如果输出文件已存在
                if os.path.exists(target_txt_path):
                    if skip_existing:
                        socketio.emit('batch_log', {'task_id': task_id, 'level': 'success', 'message': f'跳过已存在文件: {target_txt_name}'})
                        continue
                    else:
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        target_txt_name = f"{base_name}_{timestamp}.txt"
                        target_txt_path = os.path.join(target_dir, target_txt_name)
                        socketio.emit('batch_log', {'task_id': task_id, 'level': 'warning', 'message': f'文件已存在，重命名为: {target_txt_name}'})

                # 创建临时目录用于处理单个文件
                with tempfile.TemporaryDirectory() as temp_dir:
                    result = process_speech_to_text_sync(
                        f"{task_id}_{processed_count}",
                        file_path,
                        temp_dir,
                        device,
                        language,
                        segment_duration
                    )

                    with open(target_txt_path, 'w', encoding='utf-8') as f:
                        f.write(result['text'])

                # 标记为已识别
                if skip_recognized:
                    mark_file_recognized(file_path, target_txt_path)

                socketio.emit('batch_log', {'task_id': task_id, 'level': 'success', 'message': f'完成: {file_name}'})

            except Exception as e:
                socketio.emit('batch_log', {'task_id': task_id, 'level': 'error', 'message': f'处理 {file_name} 失败: {str(e)}'})
                import traceback
                traceback.print_exc()

        summary_msg = f'所有文件处理完成！处理 {processed_count - skipped_count} 个'
        if skipped_count > 0:
            summary_msg += f'，跳过 {skipped_count} 个已识别文件'
        socketio.emit('batch_complete', {'task_id': task_id, 'output_folder': output_folder})
        socketio.emit('batch_log', {'task_id': task_id, 'level': 'success', 'message': summary_msg})

    except Exception as e:
        socketio.emit('batch_log', {'task_id': task_id, 'level': 'error', 'message': f'批量处理发生严重错误: {str(e)}'})
