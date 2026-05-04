#translation.py
# 使用 Ollama 本地服务进行字幕翻译与润色  # 文件功能简介

from __future__ import annotations  # 前向注解

from typing import List, Dict  # 类型注解
import ollama  # Ollama 客户端


def translate_segments(subtitles: List[Dict], host: str = "http://127.0.0.1:11434", model: str = "gemma3:12b") -> List[Dict]:  # 批量翻译
    """遍历字幕段，逐条调用 Ollama 进行翻译，返回新列表。"""  # 文档
    client = ollama.Client(host=host)  # 创建客户端
    try:  # 校验模型
        client.show(model)  # 查看模型
    except ollama.ResponseError as e:  # 处理不存在
        raise RuntimeError(f"Ollama 模型不可用: {getattr(e, 'error', str(e))}")  # 抛出错误
    results: List[Dict] = []  # 结果集
    system_prompt = (
        "你是个专业的字幕翻译中文专家，专门把所有语言翻译成中文。"
        "将以下文本自然简洁地翻译成简体中文，以制作视频字幕。"
        "仅返回翻译成中文的文本，无需额外注释。"
    )  # 提示词
    for seg in subtitles:  # 遍历片段
        user_text = seg.get('text', '')  # 原文
        resp = client.chat(  # 调用对话
            model=model,  # 模型
            messages=[  # 消息列表
                {"role": "system", "content": system_prompt},  # 系统提示
                {"role": "user", "content": user_text}  # 用户内容
            ]  # 结束
        )  # 请求结束
        translated_text = resp.get('message', {}).get('content', '').strip()  # 提取译文
        new_seg = dict(seg)  # 拷贝片段
        new_seg['translated_text'] = translated_text or None  # 写入译文
        results.append(new_seg)  # 追加
    return results  # 返回结果



