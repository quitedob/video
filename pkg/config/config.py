#config.py
# 统一配置文件：管理模型、路径、参数等配置  # 文件功能简介

from __future__ import annotations  # 前向注解

from dataclasses import dataclass, asdict  # 数据类和转换
from pathlib import Path  # 路径处理
from typing import Dict, Any, Optional  # 类型注解
import json  # JSON 处理
import os  # 环境变量


@dataclass  # ASR 配置
class ASRConfig:  # ASR 配置类
    model_dir: str = "FunAudioLLM/Fun-ASR-Nano-2512"  # 模型目录
    device: str = "cuda:0"  # 设备
    trust_remote_code: bool = True  # 信任远程代码
    remote_code: Optional[str] = "./model.py"  # 远程代码路径
    vad_kwargs: Optional[dict] = None  # VAD 参数
    segment_duration_seconds: int = 30  # 音频切割时长（秒），Fun-ASR-Nano建议30秒以内

    @classmethod  # 从字典创建
    def from_dict(cls, data: Dict[str, Any]) -> 'ASRConfig':  # 类方法
        return cls(**data)  # 展开字典

    def to_dict(self) -> Dict[str, Any]:  # 转字典
        return asdict(self)  # 转换


@dataclass  # 翻译配置
class TranslationConfig:  # 翻译配置类
    provider: str = "ollama"  # 翻译服务提供商: ollama, deepseek, openai
    host: str = "http://127.0.0.1:11434"  # Ollama 主机 / API Base URL
    base_url: Optional[str] = None  # 兼容 OpenAI 格式 API 的 Base URL (若不设置则使用 host)
    api_key: Optional[str] = None  # API Key
    model: str = "gemma3:12b"  # 模型名称
    system_prompt: str = (  # 系统提示词
        "你是个专业的字幕翻译中文专家，专门把所有语言翻译成中文。"
        "将以下文本自然简洁地翻译成简体中文，以制作视频字幕。"
        "仅返回翻译成中文的文本，无需额外注释。"
    )  # 提示词

    @classmethod  # 从字典创建
    def from_dict(cls, data: Dict[str, Any]) -> 'TranslationConfig':  # 类方法
        # 过滤掉不存在的字段，防止报错
        valid_keys = cls.__annotations__.keys()
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)

    def to_dict(self) -> Dict[str, Any]:  # 转字典
        return asdict(self)  # 转换


@dataclass  # 视频处理配置
class VideoConfig:  # 视频处理配置类
    temp_dir: str = "./temp_video_processing"  # 临时目录
    crf: int = 22  # 视频质量（CRF值）
    preset: str = "fast"  # 编码预设
    audio_bitrate: str = "160k"  # 音频比特率

    @classmethod  # 从字典创建
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoConfig':  # 类方法
        return cls(**data)  # 展开字典

    def to_dict(self) -> Dict[str, Any]:  # 转字典
        return asdict(self)  # 转换


@dataclass  # 主配置
class Config:  # 主配置类
    asr: ASRConfig = None  # ASR配置
    translation: TranslationConfig = None  # 翻译配置
    video: VideoConfig = None  # 视频配置

    def __post_init__(self):  # 后初始化
        if self.asr is None:  # 无ASR配置
            self.asr = ASRConfig()  # 设置默认
        if self.translation is None:  # 无翻译配置
            self.translation = TranslationConfig()  # 设置默认
        if self.video is None:  # 无视频配置
            self.video = VideoConfig()  # 设置默认

    @classmethod  # 从文件加载
    def load_from_file(cls, config_path: str = "config.json") -> 'Config':  # 类方法
        """从JSON文件加载配置"""  # 文档
        config_path = Path(config_path)  # 路径对象

        if not config_path.exists():  # 文件不存在
            print(f"配置文件不存在: {config_path}，使用默认配置")  # 提示
            return cls()  # 返回默认

        try:  # 尝试加载
            with open(config_path, 'r', encoding='utf-8') as f:  # 打开文件
                data = json.load(f)  # 加载JSON

            # 分别加载各部分配置
            asr_data = data.get('asr', {})  # ASR数据
            translation_data = data.get('translation', {})  # 翻译数据
            video_data = data.get('video', {})  # 视频数据

            return cls(  # 返回配置
                asr=ASRConfig.from_dict(asr_data),  # ASR配置
                translation=TranslationConfig.from_dict(translation_data),  # 翻译配置
                video=VideoConfig.from_dict(video_data),  # 视频配置
            )  # 结束

        except Exception as e:  # 加载失败
            print(f"加载配置文件失败: {e}，使用默认配置")  # 错误提示
            return cls()  # 返回默认

    def save_to_file(self, config_path: str = "config.json") -> None:  # 保存到文件
        """保存配置到JSON文件"""  # 文档
        config_path = Path(config_path)  # 路径对象
        config_path.parent.mkdir(parents=True, exist_ok=True)  # 确保目录

        try:  # 尝试保存
            with open(config_path, 'w', encoding='utf-8') as f:  # 打开文件
                json.dump({  # 写入JSON
                    'asr': self.asr.to_dict(),  # ASR配置
                    'translation': self.translation.to_dict(),  # 翻译配置
                    'video': self.video.to_dict(),  # 视频配置
                }, f, ensure_ascii=False, indent=2)  # 格式化

            print(f"配置已保存到: {config_path}")  # 成功提示

        except Exception as e:  # 保存失败
            print(f"保存配置文件失败: {e}")  # 错误提示

    def update_from_env(self) -> None:  # 从环境变量更新
        """从环境变量更新配置"""  # 文档
        # ASR配置
        if 'ASR_MODEL_DIR' in os.environ:  # 模型目录
            self.asr.model_dir = os.environ['ASR_MODEL_DIR']  # 更新
        if 'ASR_DEVICE' in os.environ:  # 设备
            self.asr.device = os.environ['ASR_DEVICE']  # 更新

        # 翻译配置
        if 'OLLAMA_HOST' in os.environ:  # Ollama主机
            self.translation.host = os.environ['OLLAMA_HOST']  # 更新
        if 'OLLAMA_MODEL' in os.environ:  # Ollama模型
            self.translation.model = os.environ['OLLAMA_MODEL']  # 更新

        # 视频配置
        if 'TEMP_DIR' in os.environ:  # 临时目录
            self.video.temp_dir = os.environ['TEMP_DIR']  # 更新


# 全局配置实例
global_config = Config()  # 全局配置

# 尝试从文件和环境变量加载配置
try:  # 尝试加载
    global_config = Config.load_from_file()  # 从文件加载
    global_config.update_from_env()  # 从环境变量更新
    print("配置加载完成")  # 提示
except Exception as e:  # 加载失败
    print(f"配置加载失败，使用默认配置: {e}")  # 提示
