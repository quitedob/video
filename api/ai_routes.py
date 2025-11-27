#api/ai_routes.py
# AI功能路由模块  # 文件功能简介

import os  # 环境变量
import json  # JSON处理
import requests  # HTTP请求
from flask import Blueprint, request, jsonify  # Flask组件
from dotenv import load_dotenv  # 环境变量加载

# 加载环境变量
load_dotenv()  # 加载.env文件

# 创建蓝图
ai_bp = Blueprint('ai', __name__)  # AI功能蓝图

# 获取API配置
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')  # OpenAI API密钥
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')  # OpenAI API基础URL

DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')  # DeepSeek API密钥
DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com/v1')  # DeepSeek API基础URL

OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')  # Ollama API基础URL
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'llama2')  # Ollama默认模型

AI_PROVIDER = os.getenv('AI_PROVIDER', 'openai')  # 默认AI服务提供商


def get_provider_config(provider=None):  # 获取AI服务提供商配置
    """根据提供商获取API配置"""  # 文档
    provider = provider or AI_PROVIDER  # 使用指定提供商或默认提供商

    if provider == 'deepseek':  # DeepSeek配置
        if not DEEPSEEK_API_KEY:
            return None, 'DeepSeek API密钥未配置'
        return {
            'base_url': DEEPSEEK_BASE_URL,
            'headers': {
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
                'Content-Type': 'application/json'
            },
            'model': 'deepseek-chat'
        }, None
    elif provider == 'ollama':  # Ollama配置
        return {
            'base_url': OLLAMA_BASE_URL,
            'headers': {
                'Content-Type': 'application/json'
            },
            'model': OLLAMA_MODEL
        }, None
    else:  # OpenAI配置 (默认)
        if not OPENAI_API_KEY:
            return None, 'OpenAI API密钥未配置'
        return {
            'base_url': OPENAI_BASE_URL,
            'headers': {
                'Authorization': f'Bearer {OPENAI_API_KEY}',
                'Content-Type': 'application/json'
            },
            'model': 'gpt-3.5-turbo'
        }, None


def get_openai_headers():  # 获取OpenAI请求头 (保持向后兼容)
    """获取OpenAI API请求头"""  # 文档
    config, error = get_provider_config('openai')  # 获取OpenAI配置
    if error:
        return None  # 配置错误
    return config['headers']  # 返回请求头


@ai_bp.route('/summarize', methods=['POST'])  # AI总结路由
def summarize_text():  # 文本总结函数
    """文本总结API接口"""  # 文档
    try:  # 异常处理
        data = request.get_json()  # 获取请求数据
        text = data.get('text', '')  # 获取文本内容
        provider = data.get('provider', AI_PROVIDER)  # 获取指定提供商或默认提供商

        if not text:  # 检查文本内容
            return jsonify({'error': '文本内容不能为空'}), 400  # 返回错误

        # 获取AI服务配置
        config, error = get_provider_config(provider)  # 获取配置
        if error:  # 配置错误
            return jsonify({'error': error}), 500  # 返回错误

        # 调用AI API进行总结
        response = requests.post(  # 发送请求
            f'{config["base_url"]}/chat/completions',  # API地址
            headers=config['headers'],  # 请求头
            json={  # 请求数据
                'model': config['model'],  # 模型
                'messages': [  # 消息列表
                    {
                        'role': 'system',  # 系统角色
                        'content': '你是一个专业的文本总结助手，请将用户提供的文本内容总结成简洁明了的要点。'  # 系统提示
                    },
                    {
                        'role': 'user',  # 用户角色
                        'content': f'请总结以下内容：\n\n{text}'  # 用户文本
                    }
                ],
                'max_tokens': 500,  # 最大令牌数
                'temperature': 0.7  # 温度参数
            }
        )

        if response.status_code == 200:  # 请求成功
            result = response.json()  # 解析响应
            summary = result['choices'][0]['message']['content']  # 获取总结内容
            return jsonify({  # 返回结果
                'summary': summary,  # 总结内容
                'provider': provider,  # 使用的提供商
                'success': True  # 成功标志
            })
        else:  # 请求失败
            return jsonify({  # 返回错误
                'error': f'AI总结失败: {response.status_code}',  # 错误信息
                'provider': provider,  # 使用的提供商
                'details': response.text  # 详细信息
            }), response.status_code  # 状态码

    except Exception as e:  # 异常捕获
        return jsonify({'error': f'服务器错误: {str(e)}'}), 500  # 返回错误


@ai_bp.route('/chat', methods=['POST'])  # AI聊天路由
def chat_with_ai():  # AI聊天函数
    """AI聊天API接口"""  # 文档
    try:  # 异常处理
        data = request.get_json()  # 获取请求数据
        message = data.get('message', '')  # 获取用户消息
        conversation_history = data.get('history', [])  # 获取对话历史
        provider = data.get('provider', AI_PROVIDER)  # 获取指定提供商或默认提供商

        if not message:  # 检查消息内容
            return jsonify({'error': '消息内容不能为空'}), 400  # 返回错误

        # 获取AI服务配置
        config, error = get_provider_config(provider)  # 获取配置
        if error:  # 配置错误
            return jsonify({'error': error}), 500  # 返回错误

        # 构建消息列表
        messages = [  # 消息列表
            {
                'role': 'system',  # 系统角色
                'content': '你是一个智能助手，可以帮助用户解答问题和进行对话。请用简洁、友好的语调回复。'  # 系统提示
            }
        ]

        # 添加对话历史
        messages.extend(conversation_history)  # 历史消息

        # 添加当前用户消息
        messages.append({  # 用户消息
            'role': 'user',  # 用户角色
            'content': message  # 消息内容
        })

        # 调用AI API
        response = requests.post(  # 发送请求
            f'{config["base_url"]}/chat/completions',  # API地址
            headers=config['headers'],  # 请求头
            json={  # 请求数据
                'model': config['model'],  # 模型
                'messages': messages,  # 消息列表
                'max_tokens': 1000,  # 最大令牌数
                'temperature': 0.7  # 温度参数
            }
        )

        if response.status_code == 200:  # 请求成功
            result = response.json()  # 解析响应
            ai_reply = result['choices'][0]['message']['content']  # 获取AI回复

            # 更新对话历史
            conversation_history.append({  # 添加用户消息
                'role': 'user',  # 用户角色
                'content': message  # 消息内容
            })
            conversation_history.append({  # 添加AI回复
                'role': 'assistant',  # 助手角色
                'content': ai_reply  # 回复内容
            })

            return jsonify({  # 返回结果
                'reply': ai_reply,  # AI回复
                'history': conversation_history,  # 对话历史
                'provider': provider,  # 使用的提供商
                'success': True  # 成功标志
            })
        else:  # 请求失败
            return jsonify({  # 返回错误
                'error': f'AI聊天失败: {response.status_code}',  # 错误信息
                'provider': provider,  # 使用的提供商
                'details': response.text  # 详细信息
            }), response.status_code  # 状态码

    except Exception as e:  # 异常捕获
        return jsonify({'error': f'服务器错误: {str(e)}'}), 500  # 返回错误


@ai_bp.route('/web-search', methods=['POST'])  # 网络搜索路由
def web_search():  # 网络搜索函数
    """使用MCP进行网络搜索"""  # 文档
    try:  # 异常处理
        data = request.get_json()  # 获取请求数据
        query = data.get('query', '')  # 获取搜索查询
        provider = data.get('provider', 'deepseek')  # 获取指定提供商或默认提供商

        if not query:  # 检查查询内容
            return jsonify({'error': '搜索查询不能为空'}), 400  # 返回错误

        # 获取AI服务配置
        config, error = get_provider_config(provider)  # 获取配置
        if error:  # 配置错误
            return jsonify({'error': error}), 500  # 返回错误

        # 构建搜索消息
        messages = [  # 消息列表
            {
                'role': 'system',  # 系统角色
                'content': '你是一个智能搜索助手。用户会提供搜索查询，请基于你的知识库回答问题。如果需要最新信息，请告知用户你需要联网搜索功能。'  # 系统提示
            },
            {
                'role': 'user',  # 用户角色
                'content': f'请搜索并回答：{query}'  # 用户查询
            }
        ]

        # 调用AI API进行搜索
        response = requests.post(  # 发送请求
            f'{config["base_url"]}/chat/completions',  # API地址
            headers=config['headers'],  # 请求头
            json={  # 请求数据
                'model': config['model'],  # 模型
                'messages': messages,  # 消息列表
                'max_tokens': 1500,  # 最大令牌数
                'temperature': 0.5  # 温度参数
            }
        )

        if response.status_code == 200:  # 请求成功
            result = response.json()  # 解析响应
            search_result = result['choices'][0]['message']['content']  # 获取搜索结果

            return jsonify({  # 返回结果
                'query': query,  # 搜索查询
                'result': search_result,  # 搜索结果
                'provider': provider,  # 使用的提供商
                'success': True  # 成功标志
            })
        else:  # 请求失败
            return jsonify({  # 返回错误
                'error': f'网络搜索失败: {response.status_code}',  # 错误信息
                'provider': provider,  # 使用的提供商
                'details': response.text  # 详细信息
            }), response.status_code  # 状态码

    except Exception as e:  # 异常捕获
        return jsonify({'error': f'服务器错误: {str(e)}'}), 500  # 返回错误


@ai_bp.route('/providers', methods=['GET'])  # 服务提供商列表路由
def get_providers():  # 获取提供商列表函数
    """获取可用的AI服务提供商列表"""  # 文档
    try:  # 异常处理
        providers = {  # 提供商列表
            'openai': {  # OpenAI
                'name': 'OpenAI',  # 名称
                'available': bool(OPENAI_API_KEY),  # 是否可用
                'model': 'gpt-3.5-turbo'  # 模型
            },
            'deepseek': {  # DeepSeek
                'name': 'DeepSeek',  # 名称
                'available': bool(DEEPSEEK_API_KEY),  # 是否可用
                'model': 'deepseek-chat'  # 模型
            },
            'ollama': {  # Ollama
                'name': 'Ollama (本地)',  # 名称
                'available': True,  # 本地服务总是可用
                'model': OLLAMA_MODEL  # 模型
            }
        }

        return jsonify({  # 返回结果
            'providers': providers,  # 提供商列表
            'default': AI_PROVIDER,  # 默认提供商
            'success': True  # 成功标志
        })

    except Exception as e:  # 异常捕获
        return jsonify({'error': f'服务器错误: {str(e)}'}), 500  # 返回错误