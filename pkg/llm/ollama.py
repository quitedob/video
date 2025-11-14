import requests
import json
from typing import Dict, Any, Optional
import logging
import asyncio
from .base import BaseLLM

logger = logging.getLogger(__name__)


class OllamaLLM(BaseLLM):
    """
    Ollama LLM实现类
    基于Ollama API的LLM功能实现
    """

    def __init__(
        self,
        api_key: str = "",  # Ollama通常不需要API key
        base_url: str = "http://localhost:11434",
        model: str = None
    ):
        """
        初始化Ollama LLM

        Args:
            api_key: API密钥（Ollama通常不需要）
            base_url: API基础URL，默认为http://localhost:11434
            model: 模型名称，默认为gemma2:2b
        """
        super().__init__(api_key, base_url, model)
        self.headers = {
            "Content-Type": "application/json"
        }

    def get_default_model(self) -> str:
        """获取默认模型名称"""
        return "gemma2:2b"

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
                logger.error(f"Ollama API error: {response.status_code} - {error_text}")
                raise Exception(f"Ollama API error: {response.status_code} - {error_text}")

            return response.json()

        except requests.RequestException as e:
            logger.error(f"Ollama API request failed: {e}")
            raise Exception(f"Ollama API request failed: {e}")

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
        Ollama聊天补全API调用

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
            "options": {
                "temperature": temperature
            }
        }

        # 添加可选参数
        if max_tokens is not None:
            request_data["options"]["num_predict"] = max_tokens

        # 添加其他参数
        for key, value in kwargs.items():
            if key not in request_data:
                request_data[key] = value

        try:
            # 在异步函数中运行同步请求
            def sync_request():
                return self._make_request("/api/chat", request_data)

            # 使用线程池运行同步请求
            loop = asyncio.get_event_loop()
            response_data = await loop.run_in_executor(None, sync_request)

            logger.debug(f"Ollama API response: {response_data}")
            return response_data

        except Exception as e:
            logger.error(f"Ollama API request failed: {e}")
            raise Exception(f"Ollama API request failed: {e}")

    def _extract_content_from_response(self, response: Dict[str, Any]) -> str:
        """
        从Ollama API响应中提取内容

        Args:
            response: API响应

        Returns:
            提取的文本内容
        """
        try:
            return response["message"]["content"]
        except (KeyError, IndexError) as e:
            logger.error(f"Failed to extract content from response: {e}")
            raise ValueError("Invalid response format: cannot extract content")

    def __del__(self):
        """析构函数"""
        pass
