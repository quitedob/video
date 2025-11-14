from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class BaseLLM(ABC):
    """
    LLM基础抽象类
    定义了所有LLM实现必须遵循的接口
    """

    def __init__(self, api_key: str, base_url: str, model: str = None):
        """
        初始化LLM实例

        Args:
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model or self.get_default_model()

    @abstractmethod
    def get_default_model(self) -> str:
        """
        获取默认模型名称

        Returns:
            默认模型名称
        """
        pass

    @abstractmethod
    async def chat_completion(
        self,
        messages: list,
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        聊天补全API

        Args:
            messages: 对话消息列表
            max_tokens: 最大输出token数
            temperature: 温度参数
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            API响应结果
        """
        pass

    async def summarize_text(
        self,
        text: str,
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
        **kwargs
    ) -> str:
        """
        文本总结

        Args:
            text: 要总结的文本
            max_tokens: 最大输出token数
            temperature: 温度参数
            **kwargs: 其他参数

        Returns:
            总结结果
        """
        messages = [
            {
                "role": "system",
                "content": "你是一个专业的文本总结助手。请对给定的文本进行简洁、准确的总结，突出核心内容和关键信息。"
            },
            {
                "role": "user",
                "content": f"请总结以下文本内容：\n\n{text}"
            }
        ]

        response = await self.chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )

        return self._extract_content_from_response(response)

    @abstractmethod
    def _extract_content_from_response(self, response: Dict[str, Any]) -> str:
        """
        从响应中提取内容

        Args:
            response: API响应

        Returns:
            提取的文本内容
        """
        pass

    def estimate_tokens(self, text: str) -> int:
        """
        估算文本的token数量
        使用简单的启发式方法：中文字符*0.6 + 英文字符*0.3

        Args:
            text: 输入文本

        Returns:
            估算的token数量
        """
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fa5'])
        english_chars = len([c for c in text if c.isalpha()])
        other_chars = len(text) - chinese_chars - english_chars

        # 简单估算：中文0.6，英文0.3，其他0.5
        estimated_tokens = int(chinese_chars * 0.6 + english_chars * 0.3 + other_chars * 0.5)

        return max(1, estimated_tokens)  # 至少1个token

    def split_text_by_tokens(
        self,
        text: str,
        max_tokens: int = 128000,
        overlap_tokens: int = 2000
    ) -> list[str]:
        """
        按token数量分割文本

        Args:
            text: 输入文本
            max_tokens: 每段最大token数
            overlap_tokens: 重叠token数

        Returns:
            分割后的文本段落列表
        """
        if self.estimate_tokens(text) <= max_tokens:
            return [text]

        # 简单实现：按字符比例分割
        total_chars = len(text)
        chars_per_token = total_chars / self.estimate_tokens(text)
        max_chars = int(max_tokens * chars_per_token)
        overlap_chars = int(overlap_tokens * chars_per_token)

        segments = []
        start = 0

        while start < total_chars:
            end = min(start + max_chars, total_chars)
            segment = text[start:end]
            segments.append(segment)

            if end >= total_chars:
                break

            start = end - overlap_chars

        return segments