from flask import Blueprint, request, jsonify
from typing import Optional
import asyncio
import logging
import os
from pkg.llm.deepseek import DeepSeekLLM
from pkg.llm.ollama import OllamaLLM

logger = logging.getLogger(__name__)

# 创建Flask蓝图
summary_bp = Blueprint('summary', __name__)


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
            model = os.getenv("OLLAMA_MODEL", "gemma3:2b")

            llm_instances[model_type] = OllamaLLM(
                api_key="",
                base_url=base_url,
                model=model
            )
        else:
            raise Exception(f"Unknown model type: {model_type}")

    return llm_instances[model_type]


async def process_large_text_recursive(
    text: str,
    llm: DeepSeekLLM,
    max_tokens: int = 32000,  # 输入上下文最大token数（DeepSeek支持128K上下文）
    temperature: float = 1.3,
    use_reasoning: bool = False
) -> str:
    """
    递归处理大文本分段总结

    Args:
        text: 输入文本
        llm: LLM实例
        max_tokens: 单段最大输入token数（上下文长度）
        temperature: 温度参数
        use_reasoning: 是否使用推理模式

    Returns:
        最终总结结果
    """
    # 估算token数量
    estimated_tokens = llm.estimate_tokens(text)

    if estimated_tokens <= max_tokens:
        # 直接总结（不限制输出长度，让模型自动决定）
        logger.info(f"Text tokens ({estimated_tokens}) <= max_tokens ({max_tokens}), summarizing directly")
        return await llm.summarize_text(
            text=text,
            max_tokens=None,  # 不限制输出token数
            temperature=temperature
        )

    # 计算需要分段的数量
    segment_count = (estimated_tokens + max_tokens - 1) // max_tokens
    logger.info(f"Text too large ({estimated_tokens} tokens), splitting into {segment_count} segments")

    previous_summary = ""
    full_text = text

    for i in range(segment_count):
        logger.info(f"Processing segment {i + 1}/{segment_count}")

        # 构建当前段的文本
        if i == 0:
            # 第一段：取完整的最大max_tokens内容
            segment_text = llm.split_text_by_tokens(full_text, max_tokens, 0)[0]
        else:
            # 后续段：上次总结(最大20k tokens) + 上次前20k tokens内容 + 后面64k tokens内容
            segments = llm.split_text_by_tokens(full_text, max_tokens, 20000)

            # 获取上次总结的最后部分（最多20k tokens）
            summary_part = previous_summary[-20000:] if len(previous_summary) > 20000 else previous_summary

            # 获取原文开头部分（最多20k tokens）
            start_segments = llm.split_text_by_tokens(full_text, 20000, 0)
            previous_start = start_segments[0] if start_segments else ""

            # 获取当前处理的部分（最多64k tokens）
            current_start_pos = i * max_tokens - 20000
            current_segments = llm.split_text_by_tokens(full_text, 64000, 0)
            current_segment = ""
            for seg in current_segments:
                if full_text.find(seg) >= current_start_pos:
                    current_segment = seg
                    break

            segment_text = f"{summary_part}\n\n{previous_start}\n\n{current_segment}"

        logger.info(f"Segment {i + 1} text length: {len(segment_text)} characters")

        # 总结当前段
        if use_reasoning:
            response = await llm.reason_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的文本总结助手。请对给定的文本进行简洁、准确的总结，突出核心内容和关键信息。"
                    },
                    {
                        "role": "user",
                        "content": f"请总结以下文本内容：\n\n{segment_text}"
                    }
                ],
                max_tokens=None
            )
            reasoning, current_summary = llm.extract_reasoning_and_content(response)
            previous_summary = current_summary
        else:
            current_summary = await llm.summarize_text(
                text=segment_text,
                max_tokens=None,
                temperature=temperature
            )
            previous_summary = current_summary

        # 添加延迟避免API限速
        if i < segment_count - 1:
            await asyncio.sleep(1)

    return previous_summary


@summary_bp.route("/summarize", methods=["POST"])
def summarize_text():
    """
    文本总结API

    Returns:
        总结结果 (JSON)
    """
    try:
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        text = data.get("text", "")
        if not text or not text.strip():
            return jsonify({"error": "Text cannot be empty"}), 400

        max_tokens = data.get("max_tokens", 4096)  # DeepSeek默认4K，最大8K
        temperature = data.get("temperature", 1.3)
        use_reasoning = data.get("use_reasoning", False)
        model_type = data.get("model_type", "deepseek")

        import time
        start_time = time.time()

        # 在Flask中运行异步函数
        loop = None
        try:
            # 尝试获取事件循环
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # 如果没有事件循环，创建一个新的
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # 使用事件循环运行异步函数
        result = loop.run_until_complete(
            _summarize_text_async(
                text=text,
                max_tokens=max_tokens,
                temperature=temperature,
                use_reasoning=use_reasoning,
                model_type=model_type
            )
        )

        processing_time = time.time() - start_time

        response_data = {
            "summary": result["summary"],
            "reasoning_content": result.get("reasoning_content"),
            "tokens_used": result.get("tokens_used"),
            "processing_time": processing_time
        }

        return jsonify(response_data)

    except Exception as e:
        logger.error(f"Summarization failed: {str(e)}")
        return jsonify({"error": f"Summarization failed: {str(e)}"}), 500


async def _summarize_text_async(text, max_tokens, temperature, use_reasoning, model_type="deepseek"):
    """异步处理文本总结的内部函数"""
    # 获取LLM实例
    llm = await get_llm_instance(model_type)

    # 估算token数量
    estimated_tokens = llm.estimate_tokens(text)
    logger.info(f"Received text with {estimated_tokens} estimated tokens")

    result = {
        "summary": "",
        "reasoning_content": None,
        "tokens_used": estimated_tokens
    }

    # 根据模型类型设置合适的上下文长度
    if model_type == "deepseek":
        context_limit = 32000  # DeepSeek支持128K，但我们保守使用32K作为单次处理上限
    elif model_type == "ollama":
        context_limit = 4000   # Ollama本地模型通常上下文较小
    else:
        context_limit = 4000

    if estimated_tokens > context_limit:
        # 大文本分段处理
        summary = await process_large_text_recursive(
            text=text,
            llm=llm,
            max_tokens=context_limit,
            temperature=temperature,
            use_reasoning=use_reasoning
        )
        result["summary"] = summary
    else:
        # 小文本直接处理
        if use_reasoning and model_type == "deepseek":
            # 只有DeepSeek支持推理模式
            response = await llm.reason_completion(
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个专业的文本总结助手。请对给定的文本进行简洁、准确的总结，突出核心内容和关键信息。"
                    },
                    {
                        "role": "user",
                        "content": f"请总结以下文本内容：\n\n{text}"
                    }
                ],
                max_tokens=None  # 不限制输出长度
            )
            reasoning_content, summary = llm.extract_reasoning_and_content(response)
            result["summary"] = summary
            result["reasoning_content"] = reasoning_content
        else:
            summary = await llm.summarize_text(
                text=text,
                max_tokens=None,  # 不限制输出长度，让模型自动决定
                temperature=temperature
            )
            result["summary"] = summary

    return result


@summary_bp.route("/summary/health", methods=["GET"])
def health_check():
    """健康检查API"""
    try:
        # 在Flask中运行异步函数
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        result = loop.run_until_complete(_health_check_async())
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)})


async def _health_check_async():
    """异步健康检查"""
    try:
        llm = await get_llm_instance()
        return {"status": "healthy", "model": llm.model}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


@summary_bp.route("/summary/clear-cache", methods=["POST"])
def clear_cache():
    """清理缓存和重置LLM实例"""
    try:
        # 在Flask中运行异步函数
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