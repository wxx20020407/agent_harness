"""
# ==============================================================================
# RELEVANCE FINDER - 相关记忆查找
# ==============================================================================
# 来源: claude-code-source-code/src/memdir/findRelevantMemories.ts
#
# 使用 LLM 选择与当前查询最相关的记忆文件。
#
# 流程：
#   1. 扫描 memory 目录获取所有文件头
#   2. 将文件清单和查询发送给 LLM
#   3. LLM 返回最相关的文件名列表（最多 5 个）
#
# 注意：这里使用轻量级模型（如 Sonnet）进行选择，避免使用主模型。
# ==============================================================================
"""

import json
import re
from pathlib import Path
from typing import List, Optional, Set, Any
from dataclasses import dataclass

from .types import MemoryHeader, MemoryConfig
from .scanner import MemoryScanner


@dataclass
class RelevantMemory:
    """相关记忆结果"""
    path: Path
    mtime_ms: float
    filename: str


class RelevanceFinder:
    """
    相关记忆查找器。

    使用 LLM 从记忆文件中选择与查询最相关的文件。

    Example:
        finder = RelevanceFinder(scanner, llm_client)
        memories = await finder.find("how to fix the auth bug")
    """

    SELECT_MEMORIES_SYSTEM_PROMPT = """You are selecting memories that will be useful to Claude Code as it processes a user's query. You will be given the user's query and a list of available memory files with their filenames and descriptions.

Return a list of filenames for the memories that will clearly be useful to Claude Code as it processes the user's query (up to 5). Only include memories that you are certain will be helpful based on their name and description.
- If you are unsure if a memory will be useful in processing the user's query, then do not include it in your list. Be selective and discerning.
- If there are no memories in the list that would clearly be useful, feel free to return an empty list.
- If a list of recently-used tools is provided, do not select memories that are usage reference or API documentation for those tools (Claude Code is already exercising them). DO still select memories containing warnings, gotchas, or known issues about those tools — active use is exactly when those matter.

Respond with ONLY the JSON object, no markdown formatting:
{"selected_memories": ["file1.md", "file2.md"]}"""

    def __init__(
        self,
        scanner: MemoryScanner,
        config: Optional[MemoryConfig] = None,
        llm_client: Optional[Any] = None,
    ):
        """
        初始化查找器。

        Args:
            scanner: MemoryScanner 实例
            config: 配置对象
            llm_client: LLM 客户端（用于选择相关记忆）
        """
        self.scanner = scanner
        self.config = config or MemoryConfig()
        self.llm_client = llm_client

    async def find(
        self,
        query: str,
        recent_tools: Optional[List[str]] = None,
        already_surfaced: Optional[Set[str]] = None,
    ) -> List[RelevantMemory]:
        """
        查找与查询相关的记忆。

        Args:
            query: 用户查询
            recent_tools: 最近使用的工具列表
            already_surfaced: 已经展示过的文件路径集合

        Returns:
            RelevantMemory 列表
        """
        # 扫描记忆文件
        headers = await self.scanner.scan()

        # 过滤已展示的文件
        if already_surfaced:
            headers = [h for h in headers if str(h.file_path) not in already_surfaced]

        if not headers:
            return []

        # 使用 LLM 选择相关记忆
        selected_filenames = await self._select_with_llm(
            query,
            headers,
            recent_tools or [],
        )

        # 构建结果
        by_filename = {h.filename: h for h in headers}
        results = []

        for filename in selected_filenames:
            header = by_filename.get(filename)
            if header:
                results.append(RelevantMemory(
                    path=header.file_path,
                    mtime_ms=header.mtime_ms,
                    filename=header.filename,
                ))

        return results

    async def _select_with_llm(
        self,
        query: str,
        headers: List[MemoryHeader],
        recent_tools: List[str],
    ) -> List[str]:
        """
        使用 LLM 选择相关记忆文件。

        Args:
            query: 用户查询
            headers: 记忆头部列表
            recent_tools: 最近使用的工具

        Returns:
            选中的文件名列表
        """
        if not self.llm_client:
            # 没有 LLM 客户端，返回空列表
            # 在 agent_harness 中，这可能需要外部调用
            return []

        # 构建清单
        manifest = self.scanner.format_manifest(headers)

        # 添加最近使用的工具信息
        tools_section = ""
        if recent_tools:
            tools_section = f"\n\nRecently used tools: {', '.join(recent_tools)}"

        # 构建 prompt
        user_message = f"""Query: {query}

Available memories:
{manifest}{tools_section}"""

        try:
            # 调用 LLM
            response = await self._call_llm(user_message)

            # 解析响应
            return self._parse_response(response, headers)
        except Exception:
            return []

    async def _call_llm(self, user_message: str) -> str:
        """
        调用 LLM。

        Args:
            user_message: 用户消息

        Returns:
            LLM 响应文本
        """
        # 使用内置的 LLM 客户端
        from .llm_client import get_llm_client, ModelTier

        client = self.llm_client or get_llm_client()

        # 如果传入的是自定义客户端，使用其 chat 方法
        if hasattr(client, 'chat') and callable(getattr(client, 'chat')):
            if hasattr(client, 'chat_json'):
                # 使用我们的 LLMClient
                result = await client.chat_json(
                    messages=[{"role": "user", "content": user_message}],
                    system=self.SELECT_MEMORIES_SYSTEM_PROMPT,
                    tier=ModelTier.HELPER,
                    max_tokens=256,
                )
                return json.dumps(result)
            else:
                # 其他客户端实现
                return await client.chat(
                    system=self.SELECT_MEMORIES_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}],
                    max_tokens=256,
                )

        raise NotImplementedError("LLM client must implement 'chat' method")

    def _parse_response(
        self,
        response: str,
        headers: List[MemoryHeader],
    ) -> List[str]:
        """
        解析 LLM 响应。

        Args:
            response: LLM 响应文本
            headers: 记忆头部列表（用于验证文件名）

        Returns:
            有效的文件名列表
        """
        valid_filenames = {h.filename for h in headers}

        try:
            # 尝试解析 JSON
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group())
                selected = data.get('selected_memories', [])
                # 过滤有效文件名
                return [f for f in selected if f in valid_filenames]
        except json.JSONDecodeError:
            pass

        return []

    def find_by_keywords(
        self,
        query: str,
        headers: List[MemoryHeader],
        max_results: int = 5,
    ) -> List[RelevantMemory]:
        """
        基于关键词的简单匹配（不使用 LLM）。

        当没有 LLM 客户端时使用此方法。

        Args:
            query: 查询字符串
            headers: 记忆头部列表
            max_results: 最大结果数

        Returns:
            RelevantMemory 列表
        """
        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored = []
        for header in headers:
            score = 0

            # 检查文件名
            filename_lower = header.filename.lower()
            for word in query_words:
                if word in filename_lower:
                    score += 2

            # 检查描述
            if header.description:
                desc_lower = header.description.lower()
                for word in query_words:
                    if word in desc_lower:
                        score += 1

            # 检查类型
            if header.memory_type:
                type_lower = header.memory_type.value.lower()
                if type_lower in query_lower:
                    score += 1

            if score > 0:
                scored.append((score, header))

        # 按分数排序
        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            RelevantMemory(path=h.file_path, mtime_ms=h.mtime_ms, filename=h.filename)
            for _, h in scored[:max_results]
        ]