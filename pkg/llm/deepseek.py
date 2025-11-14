import requests
import json
from typing import Dict, Any, Optional
import logging
import asyncio
import time
from .base import BaseLLM

logger = logging.getLogger(__name__)


class DeepSeekLLM(BaseLLM):
    """
    DeepSeek LLM实现类
    基于DeepSeek API的LLM功能实现
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com",
        model: str = None
    ):
        """
        初始化DeepSeek LLM

        Args:
            api_key: DeepSeek API密钥
            base_url: API基础URL，默认为https://api.deepseek.com
            model: 模型名称，默认为deepseek-chat
        """
        super().__init__(api_key, base_url, model)
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def get_default_model(self) -> str:
        """获取默认模型名称"""
        return "deepseek-chat"

    def _make_request(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        发送HTTP请求

        Args:
            endpoint: API端点
            data: 请求数据

        Returns:
            响应数据
        """
        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.post(
                url,
                headers=self.headers,
                json=data,
                timeout=300  # 5分钟超时
            )

            if response.status_code != 200:
                error_text = response.text
                logger.error(f"DeepSeek API error: {response.status_code} - {error_text}")
                raise Exception(f"DeepSeek API error: {response.status_code} - {error_text}")

            return response.json()

        except requests.RequestException as e:
            logger.error(f"DeepSeek API request failed: {e}")
            raise Exception(f"DeepSeek API request failed: {e}")

    async def close(self):
        """清理资源"""
        # 使用requests不需要关闭会话
        pass

    async def chat_completion(
        self,
        messages: list,
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        DeepSeek聊天补全API调用

        Args:
            messages: 对话消息列表
            max_tokens: 最大输出token数
            temperature: 温度参数
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            API响应结果
        """
        # 构建请求参数
        request_data = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature
        }

        # 添加可选参数
        if max_tokens is not None:
            request_data["max_tokens"] = max_tokens

        # 添加其他参数
        for key, value in kwargs.items():
            if key not in request_data:
                request_data[key] = value

        try:
            # 在异步函数中运行同步请求
            def sync_request():
                return self._make_request("/chat/completions", request_data)

            # 使用线程池运行同步请求
            loop = asyncio.get_event_loop()
            response_data = await loop.run_in_executor(None, sync_request)

            logger.debug(f"DeepSeek API response: {response_data}")
            return response_data

        except Exception as e:
            logger.error(f"DeepSeek API request failed: {e}")
            raise Exception(f"DeepSeek API request failed: {e}")

    # 流式响应暂时不支持，使用requests库实现较为复杂
    def _handle_stream_response(self, response):
        """处理流式响应 - 暂未实现"""
        raise NotImplementedError("Stream response is not implemented with requests library")

    def _extract_content_from_response(self, response: Dict[str, Any]) -> str:
        """
        从DeepSeek API响应中提取内容

        Args:
            response: API响应

        Returns:
            提取的文本内容
        """
        if "stream" in response:
            raise ValueError("Stream responses should be handled separately")

        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to extract content from response: {e}")
            raise ValueError("Invalid response format: cannot extract content")

    async def summarize_text(
        self,
        text: str,
        max_tokens: Optional[int] = None,
        temperature: float = 1.3,  # 总结使用较高的温度值
        **kwargs
    ) -> str:
        """
        文本总结 - 重写以使用适合的参数

        Args:
            text: 要总结的文本
            max_tokens: 最大输出token数
            temperature: 温度参数，默认1.3适合总结任务
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

    async def reason_completion(
        self,
        messages: list,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """
        使用推理模式进行聊天补全

        Args:
            messages: 对话消息列表
            max_tokens: 最大输出token数
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            包含推理内容和最终答案的响应
        """
        # 临时切换到推理模型
        original_model = self.model
        self.model = "deepseek-reasoner"

        try:
            response = await self.chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=1.0,  # 推理模式使用固定温度
                stream=stream,
                **kwargs
            )
            return response
        finally:
            # 恢复原模型
            self.model = original_model

    def extract_reasoning_and_content(self, response: Dict[str, Any]) -> tuple[str, str]:
        """
        从推理模式响应中提取推理过程和最终答案

        Args:
            response: 推理模式API响应

        Returns:
            (reasoning_content, final_content) 元组
        """
        if "stream" in response:
            raise ValueError("Stream responses should be handled separately")

        try:
            choice = response["choices"][0]
            message = choice["message"]

            reasoning_content = message.get("reasoning_content", "")
            final_content = message.get("content", "")

            return reasoning_content, final_content
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to extract reasoning from response: {e}")
            raise ValueError("Invalid response format: cannot extract reasoning")

    def __del__(self):
        """析构函数"""
        pass