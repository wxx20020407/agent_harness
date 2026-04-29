"""
# ==============================================================================
# LLM CLIENT - LLM 客户端封装
# ==============================================================================
# 提供统一的 LLM 调用接口，支持主模型和辅助模型配置。
#
# 主模型：用于主对话
# 辅助模型：用于记忆系统等后台任务（使用轻量级模型）
# ==============================================================================
"""

import os
import json
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

# 尝试导入 aiohttp，如果没有则使用内置的 urllib
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False
    import urllib.request
    import urllib.error


class ModelTier(Enum):
    """模型层级"""
    PRIMARY = "primary"  # 主模型（用于主对话）
    HELPER = "helper"    # 辅助模型（用于记忆系统等后台任务）


@dataclass
class LLMConfig:
    """LLM 配置"""
    # 主模型
    primary_base_url: str
    primary_api_key: str
    primary_model: str = "zhipuai/glm-5"

    # 辅助模型（默认使用同 URL 但更轻量的模型）
    helper_base_url: Optional[str] = None
    helper_api_key: Optional[str] = None
    helper_model: str = "zhipuai/glm-4-flash"

    # 超时设置
    timeout: int = 60

    def get_base_url(self, tier: ModelTier) -> str:
        """获取指定层级的 base URL"""
        if tier == ModelTier.PRIMARY:
            return self.primary_base_url
        return self.helper_base_url or self.primary_base_url

    def get_api_key(self, tier: ModelTier) -> str:
        """获取指定层级的 API key"""
        if tier == ModelTier.PRIMARY:
            return self.primary_api_key
        return self.helper_api_key or self.primary_api_key

    def get_model(self, tier: ModelTier) -> str:
        """获取指定层级的模型名"""
        if tier == ModelTier.PRIMARY:
            return self.primary_model
        return self.helper_model


def load_llm_config() -> LLMConfig:
    """
    从环境变量加载 LLM 配置。

    环境变量：
        LLM_BASE_URL - 主模型 base URL
        LLM_API_KEY - 主模型 API key
        LLM_PRIMARY_MODEL - 主模型名称
        LLM_HELPER_BASE_URL - 辅助模型 base URL（可选，默认与主模型相同）
        LLM_HELPER_API_KEY - 辅助模型 API key（可选）
        LLM_HELPER_MODEL - 辅助模型名称（默认更轻量的模型）

    Returns:
        LLMConfig 实例
    """
    base_url = os.environ.get('LLM_BASE_URL', 'http://model.mify.ai.srv/v1')
    api_key = os.environ.get('LLM_API_KEY', '')

    return LLMConfig(
        primary_base_url=base_url,
        primary_api_key=api_key,
        primary_model=os.environ.get('LLM_PRIMARY_MODEL', 'zhipuai/glm-5'),
        helper_base_url=os.environ.get('LLM_HELPER_BASE_URL'),
        helper_api_key=os.environ.get('LLM_HELPER_API_KEY'),
        helper_model=os.environ.get('LLM_HELPER_MODEL', 'zhipuai/glm-4-flash'),
    )


class LLMClient:
    """
    LLM 客户端。

    支持主模型和辅助模型的统一调用。

    Example:
        config = load_llm_config()
        client = LLMClient(config)

        # 使用辅助模型进行记忆选择
        response = await client.chat(
            tier=ModelTier.HELPER,
            messages=[{"role": "user", "content": "..."}],
            system="You are selecting relevant memories...",
        )
    """

    def __init__(self, config: Optional[LLMConfig] = None):
        """
        初始化客户端。

        Args:
            config: LLM 配置，None 时自动从环境变量加载
        """
        self.config = config or load_llm_config()
        self._session: Optional[Any] = None

    async def __aenter__(self):
        if HAS_AIOHTTP:
            self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session and HAS_AIOHTTP:
            await self._session.close()

    def _get_session(self) -> Any:
        """获取或创建 session"""
        if self._session is None and HAS_AIOHTTP:
            self._session = aiohttp.ClientSession()
        return self._session

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        tier: ModelTier = ModelTier.HELPER,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        发送聊天请求。

        Args:
            messages: 消息列表
            system: 系统提示词
            tier: 模型层级
            max_tokens: 最大 token 数
            temperature: 温度参数
            response_format: 响应格式（如 JSON 模式）

        Returns:
            模型响应文本
        """
        base_url = self.config.get_base_url(tier)
        api_key = self.config.get_api_key(tier)
        model = self.config.get_model(tier)

        # 构建请求体
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        # 提取模型名（去掉 provider 前缀）
        model_name = model.split('/')[-1] if '/' in model else model

        request_body = {
            "model": model_name,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if response_format:
            request_body["response_format"] = response_format

        # 发送请求
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        if HAS_AIOHTTP:
            return await self._chat_aiohttp(url, request_body, headers)
        else:
            return await self._chat_urllib(url, request_body, headers)

    async def _chat_aiohttp(self, url: str, body: dict, headers: dict) -> str:
        """使用 aiohttp 发送请求"""
        session = self._get_session()
        timeout = aiohttp.ClientTimeout(total=self.config.timeout)

        async with session.post(url, json=body, headers=headers, timeout=timeout) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"LLM API error: {response.status} - {error_text}")

            data = await response.json()
            return data["choices"][0]["message"]["content"]

    async def _chat_urllib(self, url: str, body: dict, headers: dict) -> str:
        """使用 urllib 发送请求（兼容模式）"""
        import ssl

        loop = asyncio.get_event_loop()

        def sync_request():
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode('utf-8'),
                headers=headers,
                method='POST',
            )
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=self.config.timeout, context=ctx) as response:
                return json.loads(response.read().decode('utf-8'))

        data = await loop.run_in_executor(None, sync_request)
        return data["choices"][0]["message"]["content"]

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        system: Optional[str] = None,
        tier: ModelTier = ModelTier.HELPER,
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        """
        发送聊天请求并解析 JSON 响应。

        Args:
            messages: 消息列表
            system: 系统提示词
            tier: 模型层级
            max_tokens: 最大 token 数

        Returns:
            解析后的 JSON 对象
        """
        # 尝试使用 JSON 模式
        try:
            response = await self.chat(
                messages=messages,
                system=system,
                tier=tier,
                max_tokens=max_tokens,
                temperature=0.3,
                response_format={"type": "json_object"},
            )
        except Exception:
            # 如果 JSON 模式不支持，回退到普通模式
            response = await self.chat(
                messages=messages,
                system=system,
                tier=tier,
                max_tokens=max_tokens,
                temperature=0.3,
            )

        # 解析 JSON
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取 JSON 块
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError(f"Failed to parse JSON from response: {response[:200]}")


# =============================================================================
# 便捷函数
# =============================================================================

_default_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取默认 LLM 客户端"""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


async def call_llm(
    messages: List[Dict[str, str]],
    system: Optional[str] = None,
    tier: ModelTier = ModelTier.HELPER,
    max_tokens: int = 1024,
) -> str:
    """
    便捷的 LLM 调用函数。

    Args:
        messages: 消息列表
        system: 系统提示词
        tier: 模型层级
        max_tokens: 最大 token 数

    Returns:
        模型响应文本
    """
    client = get_llm_client()
    return await client.chat(messages, system, tier, max_tokens)


async def call_llm_json(
    messages: List[Dict[str, str]],
    system: Optional[str] = None,
    tier: ModelTier = ModelTier.HELPER,
    max_tokens: int = 1024,
) -> Dict[str, Any]:
    """
    便捷的 LLM JSON 调用函数。

    Args:
        messages: 消息列表
        system: 系统提示词
        tier: 模型层级
        max_tokens: 最大 token 数

    Returns:
        解析后的 JSON 对象
    """
    client = get_llm_client()
    return await client.chat_json(messages, system, tier, max_tokens)
