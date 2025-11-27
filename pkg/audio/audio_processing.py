# 文件路径: pkg/audio/audio_processing.py
# 文件作用: 音频提取与 ASR 推理封装（包含模型下载目录调整、设备强制使用、健壮的结果解析）
from __future__ import annotations

# === 基本说明（每个代码块上方添加短中文注释） ===
# 导入与类型注解
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import List, Dict, Optional, Any, Callable
import os
import json
import traceback
import wave
import subprocess
import logging
import threading
import queue
import time
import numpy as np

# 设置日志格式
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---- 实用函数：获取音频时长 ----
def get_audio_duration(audio_path: str) -> float:
    """获取音频文件时长（秒），优先使用 wave，失败回退到 ffprobe"""
    audio_path = Path(audio_path)
    if audio_path.suffix.lower() == '.wav':
        try:
            with wave.open(str(audio_path), 'rb') as wav_file:
                frames = wav_file.getnframes()
                rate = wav_file.getframerate()
                return frames / float(rate)
        except Exception:
            pass
    try:
        cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', str(audio_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        return float(data['format']['duration'])
    except Exception as e:
        logger.warning(f"无法获取音频时长 {audio_path}: {e}")
        return 0.0




# ---- GPU 可用性检测函数 ----
def check_gpu_availability_and_memory(min_memory_gb: float = 4.0) -> tuple[str, bool, dict]:
    """
    检测GPU可用性和内存，基于FunASR官方最佳实践

    参数:
        min_memory_gb: 最小GPU内存要求（GB），默认4GB

    返回:
        tuple: (设备字符串, 是否可用, 详细信息字典)
    """
    gpu_info = {
        'gpu_available': False,
        'gpu_count': 0,
        'gpu_memory_total': 0,
        'gpu_memory_free': 0,
        'gpu_name': '',
        'cuda_version': '',
        'torch_version': '',
        'fallback_reason': '',
        'recommended_device': 'cpu'
    }

    try:
        import torch

        # 记录版本信息
        gpu_info['torch_version'] = torch.__version__
        gpu_info['cuda_version'] = torch.version.cuda or "N/A"

        # 基础GPU可用性检查
        if not torch.cuda.is_available():
            gpu_info['fallback_reason'] = 'torch.cuda.is_available() 返回 False'
            logger.info("🔍 GPU检测结果: CUDA不可用")
            return "cpu", False, gpu_info

        # GPU数量检查
        gpu_info['gpu_count'] = torch.cuda.device_count()
        if gpu_info['gpu_count'] == 0:
            gpu_info['fallback_reason'] = '未检测到GPU设备'
            logger.info("🔍 GPU检测结果: 无GPU设备")
            return "cpu", False, gpu_info

        # 尝试使用第一个GPU设备
        try:
            device_id = 0
            device = f"cuda:{device_id}"

            # 获取GPU属性和内存信息
            gpu_props = torch.cuda.get_device_properties(device_id)
            gpu_info['gpu_name'] = gpu_props.name
            gpu_info['gpu_memory_total'] = gpu_props.total_memory / (1024**3)  # GB

            # 测试GPU是否真的可以工作（分配少量内存）
            test_tensor = torch.randn(1000, device=device)
            del test_tensor
            torch.cuda.empty_cache()

            # 获取当前可用内存
            gpu_info['gpu_memory_free'] = (torch.cuda.get_device_properties(device_id).total_memory -
                                         torch.cuda.memory_allocated(device_id)) / (1024**3)

            # 检查内存是否满足最小要求
            if gpu_info['gpu_memory_free'] < min_memory_gb:
                gpu_info['fallback_reason'] = f'GPU内存不足，当前可用 {gpu_info["gpu_memory_free"]:.2f}GB，要求至少 {min_memory_gb}GB'
                logger.warning(f"⚠️ GPU内存不足: {gpu_info['fallback_reason']}")
                return "cpu", False, gpu_info

            # 所有检查通过
            gpu_info['gpu_available'] = True
            gpu_info['recommended_device'] = device
            logger.info(f"✅ GPU检测成功: {gpu_info['gpu_name']}, 可用内存 {gpu_info['gpu_memory_free']:.2f}GB")
            return device, True, gpu_info

        except RuntimeError as e:
            gpu_info['fallback_reason'] = f'GPU运行时错误: {str(e)}'
            logger.warning(f"⚠️ GPU运行时错误: {e}")
            return "cpu", False, gpu_info

    except ImportError:
        gpu_info['fallback_reason'] = 'PyTorch未安装'
        logger.error("❌ PyTorch未安装")
        return "cpu", False, gpu_info
    except Exception as e:
        gpu_info['fallback_reason'] = f'检测过程异常: {str(e)}'
        logger.error(f"❌ GPU检测异常: {e}")
        return "cpu", False, gpu_info

# ---- ASR 配置数据类 ----
@dataclass
class AsrConfig:
    """ASR 参数配置"""
    model_dir: str = "iic/SenseVoiceSmall"    # modelscope 模型 id 或本地路径
    device: str = "auto"                      # 设备 'auto', 'cuda:0', 'cpu' 等
    trust_remote_code: bool = True
    remote_code: Optional[str] = "./model.py"
    vad_kwargs: Optional[dict] = None
    batch_size_s: int = 30
    merge_length_s: int = 5
    merge_vad: bool = True
    use_itn: bool = True
    min_gpu_memory_gb: float = 4.0           # 最小GPU内存要求（GB）

# ---- 内部：解析 AutoModel / Pipeline 返回结果 ----
def _parse_asr_result(raw_res: Any) -> str:
    """
    解析 FunASR / ModelScope 返回结果，支持多种结构：
    - 列表形式： [ { 'text': '...' , ... }, ... ]
    - 字典形式： { 'text': '...', 'segments': [...], 'sentence_info': [...] }
    返回拼接后的文本（经过简单后处理调用 rich_transcription_postprocess 如果可用）
    """
    text_parts: List[str] = []

    try:
        # 若是列表并且第一个元素为 dict 且含 text 字段
        if isinstance(raw_res, list):
            for item in raw_res:
                if isinstance(item, dict):
                    t = item.get('text') or item.get('output') or item.get('sentence', '')
                    if isinstance(t, str) and t.strip():
                        text_parts.append(t.strip())
                elif isinstance(item, str):
                    text_parts.append(item.strip())

        # 若是 dict，尝试多路径解析
        elif isinstance(raw_res, dict):
            # 常见字段
            if 'text' in raw_res and isinstance(raw_res['text'], str):
                text_parts.append(raw_res['text'].strip())
            # 有 segments / sentence_info
            if 'segments' in raw_res and isinstance(raw_res['segments'], list):
                for seg in raw_res['segments']:
                    if isinstance(seg, dict):
                        t = seg.get('text') or seg.get('content') or ''
                        if isinstance(t, str) and t.strip():
                            text_parts.append(t.strip())
            if 'sentence_info' in raw_res and isinstance(raw_res['sentence_info'], list):
                for s in raw_res['sentence_info']:
                    if isinstance(s, dict):
                        t = s.get('text') or s.get('sentence')
                        if isinstance(t, str) and t.strip():
                            text_parts.append(t.strip())
        else:
            # 兜底：字符串
            if isinstance(raw_res, str) and raw_res.strip():
                text_parts.append(raw_res.strip())

    except Exception:
        logger.warning("解析 ASR 原始结果时报错，尝试直接转换为字符串。")
        try:
            text_parts.append(str(raw_res))
        except Exception:
            pass

    # 合并并返回
    joined = " ".join([p for p in text_parts if p])
    # 额外后处理（若可用）
    try:
        # 延迟导入，避免未安装 funasr 时抛错
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
        if joined:
            return rich_transcription_postprocess(joined)
    except Exception:
        pass

    return joined

# ---- 创建/加载 ASR 模型（含模型下载目录重定向与设备检查） ----
def create_asr_model(cfg: AsrConfig):
    """
    创建并返回 FunASR AutoModel（优先）或回退 ModelScope pipeline。
    变化点：
    - 将 ModelScope 下载缓存目录默认设置到项目根下 model_cache（可通过环境变量 MODELSCOPE_CACHE 覆盖）
    - 调用 snapshot_download 时使用 cache_dir 参数，避免下载到系统用户目录
    - 在创建模型前检查并提示 GPU 可用性
    """
    # --- 1) 确保 MODELSCOPE_CACHE 在导入 modelscope 前设置（优先使用用户设置） ---
    try:
        project_root = Path(__file__).resolve().parents[2]  # d:\python\video\pkg -> project root 为上两级
        default_cache = project_root / "model_cache"
        # 只有当用户没有自己设置 MODELSCOPE_CACHE 时才设置默认
        if not os.environ.get("MODELSCOPE_CACHE"):
            os.environ["MODELSCOPE_CACHE"] = str(default_cache)
            logger.info(f"MODELSCOPE_CACHE 未设置，已将 modelscope 缓存目录设置为: {os.environ['MODELSCOPE_CACHE']}")
        else:
            logger.info(f"MODELSCOPE_CACHE 已存在: {os.environ.get('MODELSCOPE_CACHE')}")
    except Exception:
        logger.warning("设置 MODELSCOPE_CACHE 时出错，继续使用系统默认缓存路径。")

    # --- 2) 增强的GPU可用性检测与设备选择 ---
    logger.info("🔍 开始进行GPU可用性检测...")

    # 使用新的GPU检测函数
    if cfg.device == "auto":
        # 自动模式：使用新的检测函数
        recommended_device, gpu_available, gpu_info = check_gpu_availability_and_memory(cfg.min_gpu_memory_gb)
        cfg.device = recommended_device

        if gpu_available:
            logger.info(f"🔥 自动选择并成功配置GPU: {gpu_info['gpu_name']}")
            logger.info(f"📊 GPU信息 - 总内存: {gpu_info['gpu_memory_total']:.2f}GB, "
                       f"可用内存: {gpu_info['gpu_memory_free']:.2f}GB")
        else:
            logger.info(f"💻 GPU不可用，自动使用CPU处理")
            logger.info(f"📝 回退原因: {gpu_info['fallback_reason']}")
    else:
        # 手动指定设备模式：验证指定设备是否可用
        if cfg.device.startswith("cuda"):
            logger.info(f"🔍 验证用户指定的设备: {cfg.device}")
            recommended_device, gpu_available, gpu_info = check_gpu_availability_and_memory(cfg.min_gpu_memory_gb)

            if not gpu_available:
                logger.warning(f"⚠️ 用户指定的设备 {cfg.device} 不可用")
                logger.warning(f"📝 原因: {gpu_info['fallback_reason']}")
                logger.info(f"🔄 自动回退到CPU设备")
                cfg.device = "cpu"
            else:
                logger.info(f"✅ 用户指定的设备 {cfg.device} 可用")
                logger.info(f"📊 GPU信息: {gpu_info['gpu_name']}, "
                           f"可用内存: {gpu_info['gpu_memory_free']:.2f}GB")
        elif cfg.device != "cpu":
            logger.warning(f"⚠️ 未知设备类型: {cfg.device}，回退到CPU")
            cfg.device = "cpu"

    logger.info(f"📱 最终使用的设备: {cfg.device}")

    # 显示详细的系统信息（仅在GPU可用时）
    if cfg.device.startswith("cuda"):
        try:
            import torch
            logger.info(f"🔧 系统信息 - PyTorch: {torch.__version__}, CUDA: {torch.version.cuda}")
        except Exception:
            pass

    # --- 3) 如果 model_dir 看起来不是本地路径，则使用 modelscope.snapshot_download 下载到本地 cache_dir ---
    local_model_dir = cfg.model_dir
    try:
        from pathlib import Path as _P
        from modelscope import snapshot_download
        path_candidate = _P(local_model_dir)
        if not path_candidate.exists():
            logger.info(f"模型目录 '{local_model_dir}' 未在本地找到，尝试使用 modelscope.snapshot_download 下载（cache_dir 已指向 MODELSCOPE_CACHE）...")
            try:
                # 使用 cache_dir 明确控制下载位置（modelscope 支持 cache_dir 参数）
                cache_dir = os.environ.get("MODELSCOPE_CACHE")
                local_model_dir = snapshot_download(local_model_dir, cache_dir=cache_dir)
                logger.info(f"模型已下载到: {local_model_dir}")
            except TypeError:
                # 兼容旧版 snapshot_download 可能不支持 cache_dir 参数
                local_model_dir = snapshot_download(local_model_dir)
                logger.info(f"模型已下载到 (fallback): {local_model_dir}")
            except Exception as e:
                logger.warning(f"modelscope.snapshot_download 失败: {e}; 将继续使用原始路径（可能 AutoModel 可直接处理远程 id）")
                local_model_dir = cfg.model_dir
        else:
            local_model_dir = str(path_candidate)
    except Exception as e:
        logger.warning(f"无法使用 modelscope 下载模型（继续使用原路径），错误: {e}")
        local_model_dir = cfg.model_dir

    # --- 4) 如果本地目录中存在 model.py，则把 remote_code 指向该文件 ---
    remote_code_path = None
    try:
        cand = Path(local_model_dir)
        if cand.is_dir():
            model_py = cand / "model.py"
            if model_py.exists():
                remote_code_path = str(model_py)
                logger.info(f"找到本地 model.py，remote_code 指向：{remote_code_path}")
    except Exception:
        remote_code_path = cfg.remote_code

    # --- 5) 尝试构造 FunASR AutoModel（首选） ---
    try:
        from funasr import AutoModel
        am = AutoModel(
            model=local_model_dir,
            trust_remote_code=cfg.trust_remote_code,
            remote_code=remote_code_path or cfg.remote_code,
            vad_model="fsmn-vad",
            vad_kwargs=cfg.vad_kwargs or {"max_single_segment_time": 6000000},
            device=cfg.device,
            disable_update=True,
        )
        logger.info("✅ AutoModel 初始化成功")
        return am
    except Exception as e:
        logger.error("❌ AutoModel 初始化失败，开始回退流程（ModelScope pipeline）:")
        traceback.print_exc()

    # --- 6) 回退到 ModelScope pipeline（更可靠但功能受限） ---
    try:
        from modelscope.pipelines import pipeline
        from modelscope.utils.constant import Tasks
        logger.info("尝试使用 ModelScope pipeline 回退启动模型...")
        pipeline_model = pipeline(task=Tasks.auto_speech_recognition, model=cfg.model_dir, device=cfg.device)
        logger.info("✅ ModelScope pipeline 初始化成功")
        return pipeline_model
    except Exception:
        logger.error("❌ ModelScope pipeline 回退也失败，请检查网络/依赖/模型 id")
        traceback.print_exc()
        raise RuntimeError("无法初始化 ASR 模型（AutoModel 与 pipeline 均失败）")

# ---- 音频分段（支持长音频分片） ----
def split_audio_to_segments(audio_path: str, segment_duration_minutes: int) -> list:
    """将音频切分为若干段（用于长音频）"""
    segments = []
    try:
        with wave.open(audio_path, 'rb') as wav_file:
            sample_rate = wav_file.getframerate()
            duration_seconds = wav_file.getnframes() / sample_rate
        segment_duration_seconds = segment_duration_minutes * 60
        total_segments = int(duration_seconds // segment_duration_seconds) + 1
        for i in range(total_segments):
            start_time = i * segment_duration_seconds
            end_time = min((i + 1) * segment_duration_seconds, duration_seconds)
            if end_time - start_time < 1:
                break
            segments.append({
                'index': i,
                'start_time': start_time,
                'end_time': end_time,
                'duration': end_time - start_time
            })
        return segments
    except Exception as e:
        logger.error(f"音频分段失败: {e}")
        return segments

# ---- 对单个分段或文件进行 ASR 推理并返回文本 ----
def transcribe_audio_segment(model: Any, audio_path: str, cfg: AsrConfig) -> str:
    """
    对单个音频文件或分割片段做推理（兼容 AutoModel 和 ModelScope pipeline）。
    返回：识别到的文本（字符串）
    """
    logger.info(f"开始处理音频文件: {audio_path}")
    try:
        # AutoModel 有 generate 方法； pipeline 对象可直接调用
        if hasattr(model, "generate"):
            # AutoModel.generate 的返回可能是 list/dict/自定义结构，取名 raw_res
            raw_res = model.generate(
                input=str(audio_path),
                cache={},
                language="auto",
                use_itn=cfg.use_itn,
                batch_size_s=cfg.batch_size_s,
                merge_vad=cfg.merge_vad,
                merge_length_s=cfg.merge_length_s,
            )
            # FunASR 返回可能为 [ { 'key':'...', 'text':'...' } , ... ]
            # 解析为字符串
            parsed = _parse_asr_result(raw_res)
            logger.info(f"分段识别结果（截断显示）: {parsed[:200]}")
            return parsed
        else:
            # pipeline 情况：直接传路径
            raw_res = model(str(audio_path))
            parsed = _parse_asr_result(raw_res)
            logger.info(f"pipeline 返回结果（截断显示）: {parsed[:200]}")
            return parsed
    except Exception as e:
        logger.error(f"音频推理失败: {e}")
        traceback.print_exc()
        return ""

# ---- 批量分段推理（对文件目录或已经切好的片段逐段识别） ----
def transcribe_audio_segments(model: Any, audio_files: List[str], cfg: AsrConfig) -> Dict[str, Any]:
    """
    批量识别多个音频片段（audio_files 为片段路径列表）
    返回结构: { 'total_segments': n, 'texts': [ ... ], 'joined_text': '...' }
    """
    texts = []
    total_speech_seconds = 0.0
    for fp in audio_files:
        text = transcribe_audio_segment(model, fp, cfg)
        texts.append({'file': fp, 'text': text})
        # 统计处理时长（尝试获取片段时长）
        try:
            dur = get_audio_duration(fp)
            total_speech_seconds += dur
        except Exception:
            pass

    joined = " ".join([t['text'] for t in texts if t['text']])
    return {
        'total_segments': len(audio_files),
        'texts': texts,
        'joined_text': joined,
        'time_speech': total_speech_seconds
    }

# ---- 额外工具：命令行/脚本启动时强制 GPU 的建议 ----
# 提示：如果你想在脚本外部强制哪个 GPU 可见，请在启动程序前设置：
# 在 Windows cmd: set CUDA_VISIBLE_DEVICES=0 && python app.py
# 在 Linux/mac:   CUDA_VISIBLE_DEVICES=0 python app.py
# 注意：必须在 import torch 之前设置本环境变量，否则可能无效。


# =====================================================
# 新的流式ASR架构实现（基于生产者-消费者模式）
# =====================================================

class FfmpegProducer(threading.Thread):
    """FFmpeg生产者线程：从媒体文件流式读取音频数据并放入队列"""

    def __init__(self, media_path: str, audio_queue: queue.Queue, chunk_size: int = 3840000,
                 progress_callback: Optional[Callable] = None):
        """
        初始化FFmpeg生产者

        参数:
            media_path: 媒体文件路径
            audio_queue: 线程安全队列用于数据传输
            chunk_size: 音频数据块大小（字节），默认2分钟16kHz单声道数据
            progress_callback: 进度回调函数
        """
        super().__init__(daemon=True)
        self.media_path = media_path
        self.audio_queue = audio_queue
        self.chunk_size = chunk_size
        self.progress_callback = progress_callback
        self.stop_event = threading.Event()
        self.process = None
        self.logger = logging.getLogger(__name__)

    def run(self):
        """运行生产者线程"""
        try:
            print(f"[FFmpeg] 生产者线程启动，媒体文件: {self.media_path}")
            # 构建FFmpeg命令：流式输出到stdout
            cmd = [
                'ffmpeg', '-i', self.media_path,
                '-vn',  # 无视频流
                '-acodec', 'pcm_s16le',  # 16位PCM编码
                '-ar', '16000',  # 16kHz采样率
                '-ac', '1',  # 单声道
                '-f', 's16le',  # 原始PCM格式
                'pipe:1'  # 输出到stdout管道
            ]

            self.logger.info(f"启动FFmpeg进程: {' '.join(cmd)}")

            # 启动FFmpeg进程
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.chunk_size
            )

            # 读取流数据并放入队列
            while not self.stop_event.is_set():
                if self.process.poll() is not None:
                    # 进程已结束
                    break

                # 从FFmpeg stdout读取数据块
                data = self.process.stdout.read(self.chunk_size)
                if not data:
                    break

                # 将数据块放入队列
                try:
                    self.audio_queue.put(data, timeout=1.0)
                    if self.progress_callback:
                        self.progress_callback(0, "音频数据流传输中...")
                except queue.Full:
                    self.logger.warning("队列已满，跳过数据块")
                    continue

            # 发送结束信号
            try:
                self.audio_queue.put(None, timeout=1.0)  # None作为结束标记
            except queue.Full:
                pass

            print(f"[FFmpeg] 生产者线程结束")
            self.logger.info("FFmpeg生产者线程结束")

        except Exception as e:
            self.logger.error(f"FFmpeg生产者错误: {e}")
            try:
                self.audio_queue.put(None, timeout=1.0)  # 发送错误结束信号
            except queue.Full:
                pass
        finally:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                self.process.wait()

    def stop(self):
        """停止生产者线程"""
        self.stop_event.set()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait()


class AsrConsumer(threading.Thread):
    """ASR消费者线程：从队列获取音频数据并进行实时转写"""

    def __init__(self, task_id: str, audio_queue: queue.Queue, model: Any,
                 asr_config: AsrConfig, socketio: Any, result_callback: Optional[Callable] = None):
        """
        初始化ASR消费者

        参数:
            task_id: 任务ID
            audio_queue: 线程安全队列
            model: ASR模型实例
            asr_config: ASR配置
            socketio: SocketIO实例用于实时通信
            result_callback: 结果回调函数
        """
        super().__init__(daemon=True)
        self.task_id = task_id
        self.audio_queue = audio_queue
        self.model = model
        self.asr_config = asr_config
        self.socketio = socketio
        self.result_callback = result_callback
        self.stop_event = threading.Event()
        self.logger = logging.getLogger(__name__)
        self.chunk_count = 0

    def run(self):
        """运行消费者线程"""
        try:
            print(f"[ASR] 消费者线程启动，任务ID: {self.task_id}, socketio类型: {type(self.socketio)}")
            self.logger.info(f"ASR消费者线程启动，任务ID: {self.task_id}")

            while not self.stop_event.is_set():
                try:
                    # 从队列获取数据块（阻塞等待）
                    data = self.audio_queue.get(timeout=1.0)
                    if data is None:  # 结束信号
                        break

                    self.chunk_count += 1

                    # 将bytes转换为numpy数组
                    audio_array = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

                    # 执行ASR推理
                    try:
                        print(f"[ASR] 开始处理音频块 {self.chunk_count}，数据长度: {len(audio_array)}")
                        if hasattr(self.model, "generate"):
                            # FunASR AutoModel
                            print(f"[ASR] 使用FunASR AutoModel，参数: use_itn={self.asr_config.use_itn}, batch_size_s={self.asr_config.batch_size_s}")
                            raw_result = self.model.generate(
                                input=audio_array,
                                cache={},
                                language="auto",
                                use_itn=self.asr_config.use_itn,
                                batch_size_s=self.asr_config.batch_size_s,
                                merge_vad=self.asr_config.merge_vad,
                                merge_length_s=self.asr_config.merge_length_s,
                            )
                        else:
                            # ModelScope pipeline
                            print(f"[ASR] 使用ModelScope pipeline")
                            raw_result = self.model(audio_array)

                        print(f"[ASR] 推理完成，结果类型: {type(raw_result)}")

                        # 解析结果
                        text = self._parse_asr_result(raw_result)
                        print(f"[ASR] 文本解析完成，文本长度: {len(text)}")

                        if text.strip():  # 只有非空文本才发送
                            print(f"[ASR] 识别到文本: '{text[:100]}...' (长度: {len(text)})")
                            # 实时发送转写结果
                            self._emit_transcript_chunk(text)

                            # 保存到结果文件
                            if self.result_callback:
                                self.result_callback(text)
                        else:
                            print(f"[ASR] 文本为空，跳过发送")

                    except Exception as e:
                        self.logger.error(f"ASR推理失败: {e}")
                        continue

                except queue.Empty:
                    continue
                except Exception as e:
                    self.logger.error(f"消费者处理错误: {e}")
                    continue

            print(f"[ASR] 消费者线程结束，任务ID: {self.task_id}")
            self.logger.info(f"ASR消费者线程结束，任务ID: {self.task_id}")

        except Exception as e:
            self.logger.error(f"ASR消费者线程异常: {e}")
        finally:
            # 发送流结束事件
            try:
                print(f"[ASR] 发送流结束事件: task_id={self.task_id}, socketio={type(self.socketio)}")

                if self.socketio is None:
                    print(f"[ASR] ❌ socketio为None，无法发送结束事件")
                else:
                    self.socketio.emit('asr_stream_end', {
                        'task_id': self.task_id,
                        'message': '处理完成'
                    })
                    print(f"[ASR] ✅ 流结束事件已发送")
            except Exception as e:
                self.logger.error(f"发送结束事件失败: {e}")
                print(f"[ASR] ❌ 发送结束事件异常: {e}")

    def _parse_asr_result(self, raw_result: Any) -> str:
        """解析ASR结果"""
        text_parts = []

        try:
            if isinstance(raw_result, list):
                for item in raw_result:
                    if isinstance(item, dict):
                        text = item.get('text', '')
                        if text.strip():
                            text_parts.append(text.strip())
            elif isinstance(raw_result, dict):
                if 'text' in raw_result:
                    text_parts.append(raw_result['text'].strip())
            else:
                text_parts.append(str(raw_result).strip())
        except Exception as e:
            self.logger.warning(f"解析ASR结果失败: {e}")

        return ' '.join(text_parts)

    def _emit_transcript_chunk(self, text: str, is_final: bool = False):
        """
        在后台线程中向前端发送识别到的文本块。
        - 显式指定 namespace="/"，避免后台线程默认命名空间不一致导致客户端收不到事件
        - 发送前先清理 SenseVoice 的富文本标记（如 <|zh|>、<|withitn|> 等）
        - 继续携带 task_id，前端可校验是否当前任务
        """
        import re  # 简短中文注释：用于正则清理特殊标记

        try:
            # 简短中文注释：健壮性检查，确保 socketio 存在
            if self.socketio is None:
                print("[ASR] ❌ socketio 为 None，无法发送转写块")
                return

            # 简短中文注释：清理 <|...|> 形式的富文本标签，并折叠多余空白
            # 例：<|zh|><|NEUTRAL|><|Speech|><|withitn|> → ""
            cleaned = re.sub(r"<\|[^|>]+?\|>", "", text or "")
            cleaned = re.sub(r"\s+", " ", cleaned).strip()

            # 添加调试日志
            print(f"[ASR] 发送转写块: task_id={self.task_id}, 原始长度={len(text)}, 清洗后长度={len(cleaned)}, socketio={type(self.socketio)}")

            payload = {
                "task_id": self.task_id,   # 简短中文注释：用于前端任务匹配
                "text": cleaned,           # 简短中文注释：已清洗文本
                "is_final": bool(is_final)
            }

            # 简短中文注释：显式指定 namespace="/"; 后台线程 emit 在某些模式下不指定会被客户端收不到
            self.socketio.emit('asr_transcript_chunk', payload, namespace="/")
            print(f"[ASR] ✅ 转写块已发送: {len(cleaned)} 字符 (已清洗)")
        except Exception as e:
            self.logger.error(f"发送转写结果失败: {e}")
            print(f"[ASR] ❌ 发送转写结果异常: {e}")

    def stop(self):
        """停止消费者线程"""
        self.stop_event.set()


class StreamingAsrProcessor:
    """流式ASR处理器：协调生产者和消费者的主控制器"""

    def __init__(self, socketio: Any):
        """
        初始化流式ASR处理器

        参数:
            socketio: SocketIO实例用于通信
        """
        self.socketio = socketio
        self.active_tasks = {}  # 任务状态存储
        self.logger = logging.getLogger(__name__)

    def start_streaming_asr(self, task_id: str, media_path: str,
                           asr_config: AsrConfig, device: str = 'auto') -> bool:
        """
        启动流式ASR处理

        参数:
            task_id: 任务ID
            media_path: 媒体文件路径
            asr_config: ASR配置
            device: 计算设备

        返回:
            bool: 是否成功启动
        """
        try:
            # 创建ASR模型
            model = create_asr_model(asr_config)
            if not model:
                raise Exception("ASR模型创建失败")

            # 创建线程安全队列
            audio_queue = queue.Queue(maxsize=5)  # 有界队列防止内存溢出

            # 创建生产者和消费者线程
            producer = FfmpegProducer(
                media_path=media_path,
                audio_queue=audio_queue,
                progress_callback=lambda p, m: self._emit_progress(task_id, p, m)
            )

            consumer = AsrConsumer(
                task_id=task_id,
                audio_queue=audio_queue,
                model=model,
                asr_config=asr_config,
                socketio=self.socketio,
                result_callback=lambda text: self._save_result_chunk(task_id, text)
            )

            # 存储任务信息
            self.active_tasks[task_id] = {
                'status': 'processing',
                'media_path': media_path,
                'producer': producer,
                'consumer': consumer,
                'audio_queue': audio_queue,
                'result_text': [],
                'start_time': time.time()
            }

            # 启动线程
            print(f"[ASR] 启动生产者线程: {producer}")
            producer.start()
            print(f"[ASR] 生产者线程状态: {producer.is_alive()}")

            print(f"[ASR] 启动消费者线程: {consumer}")
            consumer.start()
            print(f"[ASR] 消费者线程状态: {consumer.is_alive()}")

            # 发送任务创建事件（修复：添加namespace="/"）
            print(f"[ASR] 发送asr_task_created事件，task_id: {task_id}")
            self.socketio.emit('asr_task_created', {
                'task_id': task_id,
                'message': '流式ASR任务已创建，开始处理...'
            }, namespace="/")
            print(f"[ASR] asr_task_created事件已发送")

            self.logger.info(f"流式ASR任务启动成功: {task_id}")
            print(f"[ASR] 流式ASR任务启动完成，task_id: {task_id}")
            return True

        except Exception as e:
            self.logger.error(f"启动流式ASR失败: {e}")
            self._emit_error(task_id, str(e))
            return False

    def stop_task(self, task_id: str):
        """停止指定任务"""
        if task_id in self.active_tasks:
            task_info = self.active_tasks[task_id]

            # 停止线程
            if task_info['producer'].is_alive():
                task_info['producer'].stop()

            if task_info['consumer'].is_alive():
                task_info['consumer'].stop()

            # 更新任务状态
            task_info['status'] = 'stopped'
            self._emit_progress(task_id, 100, '任务已停止')

    def get_task_status(self, task_id: str) -> dict:
        """获取任务状态"""
        if task_id not in self.active_tasks:
            return {'status': 'not_found'}

        task_info = self.active_tasks[task_id]
        return {
            'status': task_info['status'],
            'chunks_processed': len(task_info['result_text']),
            'duration': time.time() - task_info['start_time']
        }

    def _emit_progress(self, task_id: str, progress: int, message: str):
        """发送进度事件"""
        try:
            self.socketio.emit('asr_progress', {
                'task_id': task_id,
                'progress': progress,
                'message': message
            })
        except Exception as e:
            self.logger.error(f"发送进度事件失败: {e}")

    def _emit_error(self, task_id: str, error: str):
        """发送错误事件"""
        try:
            self.socketio.emit('asr_error', {
                'task_id': task_id,
                'error': error
            })
        except Exception as e:
            self.logger.error(f"发送错误事件失败: {e}")

    def _save_result_chunk(self, task_id: str, text: str):
        """保存结果块到任务信息"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id]['result_text'].append(text)

    def get_full_result(self, task_id: str) -> str:
        """获取完整结果"""
        if task_id in self.active_tasks:
            return ' '.join(self.active_tasks[task_id]['result_text'])
        return ""