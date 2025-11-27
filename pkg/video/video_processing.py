#video_processing.py
# 视频下载、转换、字幕烧录与通用工具  # 文件功能简介

from __future__ import annotations  # 前向注解

import os  # 路径处理
import re  # 正则解析
import subprocess  # 子进程（ffmpeg）
import time  # 超时控制
from pathlib import Path  # 跨平台路径
from typing import Callable, Optional  # 类型注解
import platform  # 系统平台

import yt_dlp  # 视频下载


# ---------------- 公共工具函数 ----------------  # 工具分节

def check_command_available(command: str) -> bool:  # 检查命令是否存在
    """检测命令是否可运行（例如 ffmpeg）。"""  # 文档说明
    try:  # 捕获异常
        subprocess.run([command, '-version'], capture_output=True, check=True)  # 试运行
        return True  # 可用
    except Exception:  # 任意失败
        return False  # 不可用


def run_ffmpeg(command: list[str], on_progress: Optional[Callable[[int, str], None]] = None, timeout_seconds: Optional[int] = None) -> None:  # 运行 ffmpeg 并回调进度
    """以管道模式执行 ffmpeg 命令，解析进度并通过回调报告；可设置总时长超时。"""  # 文档
    process = subprocess.Popen(  # 启动进程
        command, stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True, encoding='utf-8', errors='replace'
    )  # 进程创建
    duration_seconds = 0.0  # 总时长
    duration_re = re.compile(r"Duration: (\d{2}):(\d{2}):(\d{2})\.(\d{2})")  # 时长正则
    progress_re = re.compile(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})")  # 进度正则
    if on_progress is None:  # 默认进度函数
        on_progress = lambda p, t: None  # 空函数
    start_time = time.monotonic()  # 起始时间
    for line in process.stderr:  # 逐行读取
        if timeout_seconds is not None and (time.monotonic() - start_time) > timeout_seconds:  # 超时判断
            try:
                process.kill()  # 杀进程
            finally:
                raise TimeoutError(f"FFmpeg 处理超时（>{timeout_seconds}s），已中断。")  # 抛出超时
        if (m := duration_re.search(line)):  # 匹配时长
            h, mnt, s, cs = map(int, m.groups())  # 解析
            duration_seconds = h * 3600 + mnt * 60 + s + cs / 100.0  # 计算
        if (p := progress_re.search(line)):  # 匹配进度
            h, mnt, s, cs = map(int, p.groups())  # 解析
            current_seconds = h * 3600 + mnt * 60 + s + cs / 100.0  # 计算
            if duration_seconds > 0:  # 防除零
                percent = int(current_seconds / duration_seconds * 100)  # 百分比
                on_progress(percent, f"FFmpeg 处理中... {percent}%")  # 回调
    process.wait()  # 等待
    if process.returncode != 0:  # 非零退出
        stdout, stderr = process.communicate()  # 取输出
        raise subprocess.CalledProcessError(process.returncode, command, output=stdout, stderr=stderr)  # 抛错


# ---------------- 下载与转换 ----------------  # 下载分节

def download_video(url: str, output_dir: Path, on_progress: Optional[Callable[[int, str], None]] = None) -> str:  # 下载视频
    """使用 yt-dlp 下载视频为 mp4，返回文件路径。"""  # 文档
    output_dir = Path(output_dir)  # 规范路径
    output_dir.mkdir(parents=True, exist_ok=True)  # 确保目录
    def _hook(d: dict):  # 进度钩子
        if on_progress is None:  # 无回调
            return  # 直接返回
        if d.get('status') == 'downloading':  # 下载中
            total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')  # 总大小
            if total_bytes:  # 有总大小
                downloaded = d.get('downloaded_bytes', 0)  # 已下载
                percent = int(downloaded / total_bytes * 100)  # 百分比
                on_progress(percent, f"下载中... {percent}%")  # 回调
        elif d.get('status') == 'finished':  # 完成
            on_progress(100, "下载完成，准备合并...")  # 完成回调
    ydl_opts = {  # 配置
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',  # mp4 优先
        'outtmpl': str(output_dir / '%(title)s.%(ext)s'),  # 输出模板
        'merge_output_format': 'mp4',  # 合并为 mp4
        'progress_hooks': [_hook],  # 进度钩子
        'noprogress': True,  # 不显示自带进度
    }  # 结束
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # 创建下载器
        info = ydl.extract_info(url, download=True)  # 下载
        filename = ydl.prepare_filename(info)  # 文件名
        if not filename.lower().endswith('.mp4'):  # 统一扩展
            filename = os.path.splitext(filename)[0] + '.mp4'  # 改后缀
    return filename  # 返回路径


def _build_cmd_convert(input_path: str, output_path: str, crf: int, preset: str, hwaccel: str) -> list[str]:  # 内部：构建转码命令
    base = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'info', '-y']  # 基础参数
    if hwaccel and hwaccel != 'none':  # 仅在需要时添加
        base += ['-hwaccel', hwaccel]  # 硬件加速
    base += ['-i', str(input_path), '-c:v', 'libx264', '-preset', preset, '-crf', str(crf), '-c:a', 'aac', '-b:a', '160k', str(output_path)]  # 余下参数
    return base  # 返回


def _build_cmd_extract(input_video: str, output_wav: str, hwaccel: str) -> list[str]:  # 内部：构建提取命令
    base = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'info', '-y']  # 基础参数
    if hwaccel and hwaccel != 'none':  # 条件添加
        base += ['-hwaccel', hwaccel]  # 硬件加速
    base += ['-i', str(input_video), '-vn', '-acodec', 'pcm_s16le', '-ar', '16000', '-ac', '1', str(output_wav)]  # 参数
    return base  # 返回


def _build_cmd_burn(video_path: str, ass_path: str, output_path: str, style_string: str, hwaccel: str) -> list[str]:  # 内部：构建烧录命令
    ass_path_escaped = str(Path(ass_path)).replace('\\', '/').replace(':', '\\:')  # 路径转义
    vf = f"subtitles='{ass_path_escaped}':force_style='{style_string}'"  # 滤镜
    base = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'info', '-y']  # 基础
    if hwaccel and hwaccel != 'none':  # 硬件
        base += ['-hwaccel', hwaccel]  # 添加
    base += ['-i', str(video_path), '-vf', vf, '-c:v', 'libx264', '-preset', 'fast', '-crf', '22', '-c:a', 'copy', str(output_path)]  # 参数
    return base  # 返回


def _ffmpeg_hw_candidates(prefer_hw: bool = True) -> list[str]:  # 内部：硬件加速候选
    if not prefer_hw:  # 不偏好硬件
        return ['none']  # 仅 CPU
    candidates = []  # 候选
    system = platform.system().lower()  # 平台
    # 优先尝试 auto，其次按平台常见方案  # 说明
    candidates.append('auto')  # 自动
    if system == 'windows':  # Windows
        candidates += ['dxva2']  # DXVA2
    candidates += ['cuda']  # CUDA（如可用）
    candidates.append('none')  # 最后 CPU
    # 去重保持顺序  # 处理
    seen = set()  # 集
    ordered = []  # 列表
    for h in candidates:  # 遍历
        if h not in seen:  # 未见
            seen.add(h)  # 标记
            ordered.append(h)  # 追加
    return ordered  # 返回


def _run_with_hw_fallback(cmd_builder: Callable[[str], list[str]], on_progress: Optional[Callable[[int, str], None]], timeout_seconds: Optional[int], prefer_hw: bool = True) -> None:  # 内部：硬件回退
    last_err: Optional[Exception] = None  # 最后错误
    for hw in _ffmpeg_hw_candidates(prefer_hw=prefer_hw):  # 遍历候选
        try:  # 尝试
            run_ffmpeg(cmd_builder(hw), on_progress, timeout_seconds=timeout_seconds)  # 运行
            return  # 成功返回
        except (subprocess.CalledProcessError, TimeoutError) as e:  # 失败
            last_err = e  # 记录
            if on_progress:  # 回调
                on_progress(0, f"FFmpeg 使用硬件加速 {hw} 失败，尝试回退...")  # 提示
            continue  # 继续
    if last_err:  # 若有错误
        raise last_err  # 抛出


def convert_video_to_mp4(input_path: str, output_path: str, crf: int = 22, preset: str = 'fast', on_progress: Optional[Callable[[int, str], None]] = None, timeout_seconds: Optional[int] = None, hwaccel: str = 'none', prefer_hw: bool = True) -> None:  # 转码为 mp4
    """利用 FFmpeg 将任意格式转码为 H.264/AAC 的 MP4。"""  # 文档
    def _builder(h: str) -> list[str]:  # 构建器
        return _build_cmd_convert(input_path, output_path, crf, preset, h)  # 构建
    _run_with_hw_fallback(_builder, on_progress, timeout_seconds, prefer_hw=prefer_hw)  # 执行


def extract_audio_wav16k(input_video: str, output_wav: str, on_progress: Optional[Callable[[int, str], None]] = None, timeout_seconds: Optional[int] = 600, hwaccel: str = 'none', prefer_hw: bool = True) -> None:  # 提取 16k WAV
    """从视频提取 16kHz 单声道 16-bit PCM WAV 音频。"""  # 文档
    def _builder(h: str) -> list[str]:  # 构建器
        return _build_cmd_extract(input_video, output_wav, h)  # 构建
    _run_with_hw_fallback(_builder, on_progress, timeout_seconds, prefer_hw=prefer_hw)  # 执行


def burn_ass_subtitles(video_path: str, ass_path: str, output_path: str, style_string: str, on_progress: Optional[Callable[[int, str], None]] = None, timeout_seconds: Optional[int] = None, hwaccel: str = 'none', prefer_hw: bool = True) -> None:  # 烧录字幕
    """通过 FFmpeg subtitles 滤镜与 force_style 将 ASS 烧录到视频。"""  # 文档
    def _builder(h: str) -> list[str]:  # 构建器
        return _build_cmd_burn(video_path, ass_path, output_path, style_string, h)  # 构建
    _run_with_hw_fallback(_builder, on_progress, timeout_seconds, prefer_hw=prefer_hw)  # 执行



