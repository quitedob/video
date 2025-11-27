# api/speech_routes.py
# 语音转文字API路由
# 说明（中文注释）：提供两种模式——(1) 异步+Socket仅做进度；(2) 简洁同步HTTP一次性返回文本
from flask import Blueprint, request, jsonify, send_from_directory
import os
import tempfile
import uuid
from flask_socketio import SocketIO  # 仅用于进度推送
import subprocess
import time
from werkzeug.utils import secure_filename

# 说明：引入单段与多段识别函数 + 配置 + 新流式架构
from pkg.audio.audio_processing import (
    create_asr_model,
    transcribe_audio_segment,     # 新增：单段识别
    transcribe_audio_segments,    # 批量识别
    AsrConfig,
    StreamingAsrProcessor,        # 新增：流式ASR处理器
    FfmpegProducer,              # 新增：FFmpeg生产者
    AsrConsumer                  # 新增：ASR消费者
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
                               device: str, language: str, segment_duration: int) -> str:
    """
    同步处理语音转文字：抽音→分片→批量识别→返回完整文本
    移除Socket.IO，改为直接返回结果
    """
    try:
        print(f"[处理] 开始语音转文字同步处理，task_id={task_id}")

        # 1) 抽取WAV(16k, mono)
        audio_path = os.path.join(temp_dir, 'extracted_audio.wav')
        if not extract_audio_from_media(media_path, audio_path):
            raise Exception('音频提取失败')

        print(f"[处理] 音频提取完成，开始分段...")

        # 2) 计算时间段（单位：分钟→秒），默认2min/段
        segments = segment_audio_file(audio_path, segment_duration)
        if not segments:
            segments = [{'index': 0, 'start_time': 0, 'end_time': 0, 'duration': 0}]

        print(f"[处理] 共{len(segments)}段，开始识别...")

        # 3) 构建ASR模型（AutoModel，SenseVoiceSmall + VAD参数）
        asr_config = AsrConfig(
            model_dir="iic/SenseVoiceSmall",
            device=device if device in ("auto", "cpu") else "cuda:0",
            trust_remote_code=True,
            remote_code="./model.py",
            vad_kwargs={"max_single_segment_time": 30000},  # 每个VAD子段最长30秒（毫秒）
            batch_size_s=60,        # 动态batch：累计音频时长（秒）
            merge_vad=True,         # 合并VAD碎片
            merge_length_s=15,      # 合并后目标长度（秒）
            use_itn=True,           # 输出包含标点与ITN
        )
        model = create_asr_model(asr_config)

        # 4) 批量识别：先切出所有片段 → 批量送入 ASR
        segment_paths = []
        for i, seg in enumerate(segments):
            print(f"[处理] 切片第{i+1}/{len(segments)}段...")

            # 精确切片
            segment_audio_path = os.path.join(temp_dir, f'segment_{i:04d}.wav')
            start_time = seg['start_time']
            duration = max(0.1, seg['end_time'] - seg['start_time'])
            cmd = [
                'ffmpeg', '-i', audio_path,
                '-ss', str(start_time),
                '-t', str(duration),
                '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
                '-y', segment_audio_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            segment_paths.append(segment_audio_path)

        print(f"[处理] 开始批量识别，共{len(segment_paths)}个片段...")

        # 批量识别
        try:
            batch_result = transcribe_audio_segments(model, segment_paths, asr_config)
            final_text = batch_result.get('joined_text', '')
            if not final_text:
                # 降级：手动拼接texts列表
                texts = batch_result.get('texts', [])
                final_text = '\n'.join([item.get('text', '') for item in texts if item.get('text')])
        except Exception as e:
            print(f"[处理] 批量识别失败: {e}")
            final_text = "识别过程中发生错误"

        # 清理分段文件
        for segment_path in segment_paths:
            try:
                os.remove(segment_path)
            except Exception:
                pass

        # 清理提取的音频文件
        try:
            os.remove(audio_path)
        except Exception:
            pass

        print(f"[处理] 语音转文字处理完成，文本长度: {len(final_text)}")
        return final_text

    except Exception as e:
        import traceback
        print(f"[处理] 语音转文字同步处理异常: {str(e)}")
        print(traceback.format_exc())
        raise


def process_speech_to_text(task_id: str, media_path: str, temp_dir: str,
                           device: str, language: str, segment_duration: int,
                           notify: str):
    """后台处理语音转文字：抽音→分片→队列识别→汇总"""
    try:
        if notify != 'none':
            emit_speech_progress(task_id, 10, '开始处理文件...')

        # 1) 抽取WAV(16k, mono) —— 更利于后续精确切片与ASR稳定性
        audio_path = os.path.join(temp_dir, 'extracted_audio.wav')
        if not extract_audio_from_media(
            media_path, audio_path,
            (lambda p, m: emit_speech_progress(task_id, 10 + p * 0.3, m)) if notify != 'none' else (lambda *_: None)
        ):
            raise Exception('音频提取失败')

        if notify != 'none':
            emit_speech_progress(task_id, 40, '音频提取完成，开始分段...')

        # 2) 计算时间段（单位：分钟→秒），默认2min/段
        segments = segment_audio_file(audio_path, segment_duration)
        if not segments:
            segments = [{'index': 0, 'start_time': 0, 'end_time': 0, 'duration': 0}]

        if notify != 'none':
            emit_speech_progress(task_id, 50, f'共{len(segments)}段，开始识别...', {
                'total_segments': len(segments),
                'current_segment': 0
            })

        # 3) 构建ASR模型（AutoModel，SenseVoiceSmall + VAD参数）
        # 简短中文注释：SenseVoice 推荐开启VAD并设置合并参数；use_itn 打开标点/逆文本正则化
        asr_config = AsrConfig(
            model_dir="iic/SenseVoiceSmall",
            device=device if device in ("auto", "cpu") else "cuda:0",
            trust_remote_code=True,
            remote_code="./model.py",
            vad_kwargs={"max_single_segment_time": 30000},  # 每个VAD子段最长30秒（毫秒）
            batch_size_s=60,        # 动态batch：累计音频时长（秒）
            merge_vad=True,         # 合并VAD碎片
            merge_length_s=15,      # 合并后目标长度（秒）
            use_itn=True,           # 输出包含标点与ITN
        )
        model = create_asr_model(asr_config)

        # 4) 批量识别：先切出所有片段 → 批量送入 ASR（效率更高，避免逐段GPU调用）
        segment_paths = []
        for i, seg in enumerate(segments):
            if notify != 'none':
                emit_speech_progress(task_id, 50 + (i / max(1, len(segments))) * 20,
                                     f'切片第{i+1}/{len(segments)}段...', {
                                         'total_segments': len(segments),
                                         'current_segment': i + 1
                                     })

            # 精确切片（Windows下强制pcm_s16le编码，避免header/truncation问题）
            segment_audio_path = os.path.join(temp_dir, f'segment_{i:04d}.wav')
            start_time = seg['start_time']
            duration = max(0.1, seg['end_time'] - seg['start_time'])
            cmd = [
                'ffmpeg', '-i', audio_path,  # 先输入再 -ss/-t，精确切片
                '-ss', str(start_time),
                '-t', str(duration),
                '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le',
                '-y', segment_audio_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            segment_paths.append(segment_audio_path)

        # —— 关键修复：批量调用 transcribe_audio_segments(model, segment_paths, asr_config) ——
        # 简短中文注释：transcribe_audio_segments 要求 (model, List[str], cfg)，返回带joined_text的字典
        if notify != 'none':
            emit_speech_progress(task_id, 70, '开始批量识别...')

        try:
            batch_result = transcribe_audio_segments(model, segment_paths, asr_config)
            # 返回结构类似：{'total_segments': n, 'texts': [{'file':path,'text':txt},...], 'joined_text': '...'}
            final_text = batch_result.get('joined_text', '')
            if not final_text:
                # 降级：如果没有joined_text，手动拼接texts列表
                texts = batch_result.get('texts', [])
                final_text = '\n'.join([item.get('text', '') for item in texts if item.get('text')])
        except Exception as e:
            logger.exception(f"批量识别失败: {e}")
            final_text = "识别过程中发生错误"

        # 清理所有分段文件
        for segment_path in segment_paths:
            try:
                os.remove(segment_path)
            except Exception:
                pass

        # 5) 保存结果文件（供下载/留存）
        result_path = os.path.join(temp_dir, 'speech_result.txt')
        with open(result_path, 'w', encoding='utf-8') as f:
            f.write(final_text)

        speech_tasks[task_id].update({
            'status': 'completed',
            'result_path': result_path,
            'text': final_text
        })

        if notify != 'none':
            emit_speech_progress(task_id, 100, '语音转文字完成！')
            # 同时推送最终结果
            try:
                from app import socketio
                socketio.emit('speech_result', {'task_id': task_id, 'text': final_text})
            except ImportError:
                socketio = SocketIO.get_instance()
                if socketio:
                    socketio.emit('speech_result', {'task_id': task_id, 'text': final_text})

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

            # 抽音
            audio_path = os.path.join(td, 'extracted_audio.wav')
            if not extract_audio_from_media(media_path, audio_path, lambda *_: None):
                return jsonify({'error': '音频提取失败'}), 500

            # 2min切片
            segments = segment_audio_file(audio_path, int(request.form.get('segment_duration', 120)))
            if not segments:
                segments = [{'index': 0, 'start_time': 0, 'end_time': 0, 'duration': 0}]

            # 构模
            asr_config = AsrConfig(
                device=request.form.get('device', 'auto'),
                vad_kwargs={"max_single_segment_time": 30000},
                merge_vad=True, merge_length_s=15, batch_size_s=60, use_itn=True
            )
            model = create_asr_model(asr_config)

            # 队列识别
            out = []
            for i, seg in enumerate(segments):
                seg_path = os.path.join(td, f'segment_{i}.wav')
                cmd = [
                    'ffmpeg', '-i', audio_path,
                    '-ss', str(seg['start_time']), '-t', str(max(0.1, seg['end_time'] - seg['start_time'])),
                    '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', '-y', seg_path
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                out.append(transcribe_audio_segment(model, seg_path, asr_config))
            return jsonify({'text': '\n'.join([t for t in out if t])})
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
            result_text = process_speech_to_text_sync(
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
            speech_tasks[task_id]['result'] = result_text

            return jsonify({
                'task_id': task_id,
                'text': result_text,
                'message': '语音转文字处理完成',
                'status': 'completed'
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
