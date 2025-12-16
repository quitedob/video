from __future__ import annotations
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Callable, Optional
import ollama
import requests
import json

class Translator(ABC):
    """翻译器抽象基类"""
    @abstractmethod
    def translate(self, text: str) -> str:
        pass

class OllamaTranslator(Translator):
    """Ollama 翻译器实现"""
    def __init__(self, host: str, model: str):
        self.host = host
        self.model = model
        self.client = ollama.Client(host=host)
        self._validate_model()

    def _validate_model(self):
        try:
            self.client.show(self.model)
        except ollama.ResponseError as e:
            raise RuntimeError(f"Ollama 模型不可用: {getattr(e, 'error', str(e))}")

    def translate(self, text: str) -> str:
        system_prompt = (
            "你是个专业的字幕翻译中文专家，专门把所有语言翻译成中文。"
            "将以下文本自然简洁地翻译成简体中文，以制作视频字幕。"
            "仅返回翻译成中文的文本，无需额外注释。"
        )
        try:
            resp = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text}
                ]
            )
            return resp.get('message', {}).get('content', '').strip()
        except Exception as e:
            print(f"翻译出错: {e}")
            return text  # 出错返回原文

class OpenAILikeTranslator(Translator):
    """OpenAI 兼容接口翻译器 (用于 DeepSeek 等)"""
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def translate(self, text: str) -> str:
        system_prompt = (
            "你是个专业的字幕翻译中文专家，专门把所有语言翻译成中文。"
            "将以下文本自然简洁地翻译成简体中文，以制作视频字幕。"
            "仅返回翻译成中文的文本，无需额外注释。"
        )
        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            "stream": False
        }
        try:
            # 兼容 /chat/completions
            endpoint = f"{self.base_url}/chat/completions" if "chat/completions" not in self.base_url else self.base_url
            resp = requests.post(endpoint, headers=self.headers, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()
            return result['choices'][0]['message']['content'].strip()
        except Exception as e:
            print(f"DeepSeek/OpenAI 翻译出错: {e}")
            return text

def translate_segments(subtitles: List[Dict], host: str = "http://127.0.0.1:11434", model: str = "gemma3:12b", progress_callback: Optional[Callable[[float, str], None]] = None, **kwargs) -> List[Dict]:
    """
    批量翻译字幕段
    kwargs 支持: provider, api_key, base_url (会覆盖 host)
    """
    provider = kwargs.get('provider', 'ollama')
    
    if provider == 'deepseek' or provider == 'openai':
        api_key = kwargs.get('api_key')
        base_url = kwargs.get('base_url') or host
        if not api_key:
            raise ValueError(f"{provider} 翻译需要提供 API Key")
        translator = OpenAILikeTranslator(base_url=base_url, api_key=api_key, model=model)
    else:
        # Default to Ollama
        translator = OllamaTranslator(host=host, model=model)

    results = [None] * len(subtitles)

    total_segments = len(subtitles)
    completed_count = 0

    # 使用线程池并发翻译
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_index = {
            executor.submit(translator.translate, seg.get('text', '')): i 
            for i, seg in enumerate(subtitles)
        }

        for future in as_completed(future_to_index):
            i = future_to_index[future]
            original_seg = subtitles[i]
            try:
                translated_text = future.result()
            except Exception:
                translated_text = original_seg.get('text', '')
            
            new_seg = dict(original_seg)
            new_seg['translated_text'] = translated_text or None
            results[i] = new_seg

            completed_count += 1
            if progress_callback:
                progress = (completed_count / total_segments) * 100
                progress_callback(progress, f'翻译进度: {completed_count}/{total_segments}')

    return results



