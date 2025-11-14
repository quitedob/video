from flask import Blueprint, request, jsonify
from typing import Optional
import asyncio
import logging
import os
from pkg.llm.deepseek import DeepSeekLLM
from pkg.llm.ollama import OllamaLLM

logger = logging.getLogger(__name__)

# 创建Flask蓝图
chat_bp = Blueprint('chat', __name__)

# 全局LLM实例
llm_instances = {}


async def get_llm_instance(model_type: str = "deepseek"):
    """获取LLM实例"""
    global llm_instances

    if model_type not in llm_instances:
        if model_type == "deepseek":
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise Exception("DEEPSEEK_API_KEY environment variable is not set")

            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

            llm_instances[model_type] = DeepSeekLLM(
                api_key=api_key,
                base_url=base_url,
                model=model
            )
        elif model_type == "ollama":
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            model = os.getenv("OLLAMA_MODEL", "gemma2:2b")

            llm_instances[model_type] = OllamaLLM(
                api_key="",
                base_url=base_url,
                model=model
            )
        else:
            raise Exception(f"Unknown model type: {model_type}")

    return llm_instances[model_type]


@chat_bp.route("/chat", methods=["POST"])
def chat():
    """
    聊天API

    Request JSON:
        {
            "messages": [{"role": "user", "content": "..."}],
            "model_type": "deepseek" or "ollama",
            "context": "optional context text",
            "temperature": 1.0,
            "max_tokens": 2000
        }

    Returns:
        {
            "response": "AI response text",
            "model": "model name"
        }
    """
    try:
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        messages = data.get("messages", [])
        if not messages:
            return jsonify({"error": "Messages cannot be empty"}), 400

        model_type = data.get("model_type", "deepseek")
        context = data.get("context", "")
        temperature = data.get("temperature", 1.0)
        max_tokens = data.get("max_tokens", None)  # 不限制输出长度，让模型自动决定

        # 如果有上下文，添加到系统消息
        if context:
            system_message = {
                "role": "system",
                "content": f"以下是转写的文本内容作为上下文：\n\n{context}\n\n请基于这个上下文回答用户的问题。"
            }
            # 在用户消息之前插入系统消息
            if messages and messages[0].get("role") != "system":
                messages.insert(0, system_message)

        # 在Flask中运行异步函数
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # 使用事件循环运行异步函数
        result = loop.run_until_complete(
            _chat_async(
                messages=messages,
                model_type=model_type,
                temperature=temperature,
                max_tokens=max_tokens
            )
        )

        return jsonify(result)

    except Exception as e:
        logger.error(f"Chat failed: {str(e)}")
        return jsonify({"error": f"Chat failed: {str(e)}"}), 500


async def _chat_async(messages, model_type, temperature, max_tokens):
    """异步处理聊天的内部函数"""
    # 获取LLM实例
    llm = await get_llm_instance(model_type)

    # 调用聊天API
    response = await llm.chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature
    )

    # 提取响应内容
    content = llm._extract_content_from_response(response)

    return {
        "response": content,
        "model": llm.model
    }


@chat_bp.route("/chat/models", methods=["GET"])
def get_models():
    """获取可用的模型列表"""
    models = [
        {
            "id": "deepseek",
            "name": "DeepSeek Chat",
            "description": "DeepSeek 聊天模型"
        },
        {
            "id": "ollama",
            "name": "Ollama Gemma2",
            "description": "本地 Ollama Gemma2 模型"
        }
    ]
    return jsonify({"models": models})


@chat_bp.route("/chat/clear-cache", methods=["POST"])
def clear_cache():
    """清理缓存和重置LLM实例"""
    try:
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_clear_cache_async())
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)})


async def _clear_cache_async():
    """异步清理缓存"""
    global llm_instances

    for llm in llm_instances.values():
        if llm:
            await llm.close()

    llm_instances = {}

    return {"status": "cache cleared"}
