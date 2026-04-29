"""
# ==============================================================================
# MEMORY API - 记忆系统 API 端点
# ==============================================================================
# 提供与 server.js 集成的 REST API 端点。
#
# 端点列表：
#   GET  /memory              - 获取记忆索引
#   GET  /memory/list         - 列出所有记忆文件
#   GET  /memory/:filename    - 读取单个记忆
#   POST /memory              - 创建新记忆
#   PUT  /memory/:filename    - 更新记忆
#   DELETE /memory/:filename  - 删除记忆
#   POST /memory/search       - 搜索相关记忆
#   POST /memory/extract      - 从消息提取记忆
#   POST /memory/consolidate  - 触发记忆整理
#
# 在 server.js 中添加：
#   import memoryRoutes from './memory-api.js';
#   app.use('/memory', memoryRoutes);
# ==============================================================================
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

# 导入记忆系统组件
from .types import MemoryType, MemoryConfig
from .manager import MemoryManager


class MemoryAPI:
    """
    记忆系统 API 处理器。

    提供与 Express 兼容的请求处理方法。
    """

    def __init__(
        self,
        memory_dir: Path,
        transcripts_dir: Optional[Path] = None,
        llm_client: Optional[Any] = None,
    ):
        """
        初始化 API 处理器。

        Args:
            memory_dir: memory 目录路径
            transcripts_dir: transcripts 目录路径
            llm_client: LLM 客户端
        """
        self.manager = MemoryManager(
            memory_dir=memory_dir,
            transcripts_dir=transcripts_dir,
            llm_client=llm_client,
        )

    # -------------------------------------------------------------------------
    # GET /memory - 获取记忆索引
    # -------------------------------------------------------------------------

    async def get_index(self) -> Dict[str, Any]:
        """
        获取记忆索引内容。

        Returns:
            { success: bool, content: string, entries: list }
        """
        try:
            content = self.manager.load_index()
            entries = self.manager.get_index_entries()

            return {
                'success': True,
                'content': content,
                'entries': [
                    {'title': t, 'filename': f, 'hook': h}
                    for t, f, h in entries
                ],
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # GET /memory/list - 列出所有记忆
    # -------------------------------------------------------------------------

    async def list_memories(self) -> Dict[str, Any]:
        """
        列出所有记忆文件。

        Returns:
            { success: bool, memories: list }
        """
        try:
            headers = await self.manager.scan_memories()

            return {
                'success': True,
                'memories': [
                    {
                        'filename': h.filename,
                        'type': h.memory_type.value if h.memory_type else None,
                        'description': h.description,
                        'mtime': datetime.fromtimestamp(h.mtime_ms / 1000).isoformat(),
                    }
                    for h in headers
                ],
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # GET /memory/:filename - 读取单个记忆
    # -------------------------------------------------------------------------

    async def get_memory(self, filename: str) -> Dict[str, Any]:
        """
        读取单个记忆文件。

        Args:
            filename: 文件名

        Returns:
            { success: bool, memory: object }
        """
        try:
            topic = self.manager.read_memory(filename)

            if not topic:
                return {
                    'success': False,
                    'error': 'Memory not found',
                }

            return {
                'success': True,
                'memory': {
                    'name': topic.name,
                    'description': topic.description,
                    'type': topic.memory_type.value,
                    'content': topic.content,
                    'created_at': topic.created_at.isoformat() if topic.created_at else None,
                    'updated_at': topic.updated_at.isoformat() if topic.updated_at else None,
                },
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # POST /memory - 创建新记忆
    # -------------------------------------------------------------------------

    async def create_memory(
        self,
        filename: str,
        name: str,
        description: str,
        memory_type: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        创建新记忆。

        Args:
            filename: 文件名
            name: 记忆名称
            description: 描述
            memory_type: 类型字符串
            content: 内容

        Returns:
            { success: bool, path: string }
        """
        try:
            # 解析类型
            mtype = MemoryType.parse(memory_type)
            if not mtype:
                return {
                    'success': False,
                    'error': f'Invalid memory type: {memory_type}',
                }

            # 保存记忆
            file_path = self.manager.save_memory(
                filename=filename,
                name=name,
                description=description,
                memory_type=mtype,
                content=content,
            )

            return {
                'success': True,
                'path': str(file_path),
                'message': f'Memory saved: {filename}',
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # PUT /memory/:filename - 更新记忆
    # -------------------------------------------------------------------------

    async def update_memory(
        self,
        filename: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        memory_type: Optional[str] = None,
        content: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        更新记忆文件。

        Args:
            filename: 文件名
            name: 新名称
            description: 新描述
            memory_type: 新类型
            content: 新内容

        Returns:
            { success: bool }
        """
        try:
            mtype = MemoryType.parse(memory_type) if memory_type else None

            success = self.manager.topic_manager.update_topic(
                filename=filename,
                name=name,
                description=description,
                memory_type=mtype,
                content=content,
            )

            if success:
                # 更新索引
                if name or description:
                    self.manager.index.update_entry(
                        filename=filename + '.md',
                        title=name,
                        hook=description,
                    )

            return {
                'success': success,
                'message': 'Memory updated' if success else 'Update failed',
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # DELETE /memory/:filename - 删除记忆
    # -------------------------------------------------------------------------

    async def delete_memory(self, filename: str) -> Dict[str, Any]:
        """
        删除记忆文件。

        Args:
            filename: 文件名

        Returns:
            { success: bool }
        """
        try:
            success = self.manager.delete_memory(filename)

            return {
                'success': success,
                'message': 'Memory deleted' if success else 'Delete failed',
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # POST /memory/search - 搜索相关记忆
    # -------------------------------------------------------------------------

    async def search_memories(
        self,
        query: str,
        max_results: int = 5,
    ) -> Dict[str, Any]:
        """
        搜索相关记忆。

        Args:
            query: 查询字符串
            max_results: 最大结果数

        Returns:
            { success: bool, memories: list }
        """
        try:
            memories = await self.manager.find_relevant(query, max_results)

            return {
                'success': True,
                'memories': [
                    {
                        'filename': m.filename,
                        'path': str(m.path),
                        'mtime': datetime.fromtimestamp(m.mtime_ms / 1000).isoformat(),
                    }
                    for m in memories
                ],
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # POST /memory/extract - 从消息提取记忆
    # -------------------------------------------------------------------------

    async def extract_memories(
        self,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        从消息中提取记忆。

        Args:
            messages: 消息列表

        Returns:
            { success: bool, files_written: list, memories_saved: int }
        """
        try:
            result = await self.manager.extract_from_messages(messages)

            return {
                'success': result.success,
                'files_written': result.files_written,
                'memories_saved': result.memories_saved,
                'error': result.error,
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # POST /memory/consolidate - 触发记忆整理
    # -------------------------------------------------------------------------

    async def consolidate_memories(
        self,
        session_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        触发记忆整理。

        Args:
            session_ids: 会话 ID 列表

        Returns:
            { success: bool, files_touched: list, sessions_reviewed: int }
        """
        try:
            result = await self.manager.consolidate(session_ids)

            if result:
                return {
                    'success': result.success,
                    'files_touched': result.files_touched,
                    'sessions_reviewed': result.sessions_reviewed,
                    'error': result.error,
                }
            else:
                return {
                    'success': False,
                    'error': 'Dream not configured',
                }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    # -------------------------------------------------------------------------
    # GET /memory/system-prompt - 获取系统提示词部分
    # -------------------------------------------------------------------------

    async def get_system_prompt(self) -> Dict[str, Any]:
        """
        获取记忆系统的系统提示词部分。

        Returns:
            { success: bool, prompt: string }
        """
        try:
            prompt = self.manager.build_system_prompt_section()

            return {
                'success': True,
                'prompt': prompt,
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }


# =============================================================================
# Express Router Factory (for Node.js integration)
# =============================================================================

def create_memory_api_routes(memory_dir: str, transcripts_dir: Optional[str] = None) -> dict:
    """
    创建记忆 API 路由配置。

    这个函数返回一个配置对象，可以在 server.js 中使用。

    Args:
        memory_dir: memory 目录路径
        transcripts_dir: transcripts 目录路径

    Returns:
        路由配置字典
    """
    return {
        'memory_dir': memory_dir,
        'transcripts_dir': transcripts_dir,
        'routes': [
            {'method': 'GET', 'path': '/', 'handler': 'get_index'},
            {'method': 'GET', 'path': '/list', 'handler': 'list_memories'},
            {'method': 'GET', 'path': '/:filename', 'handler': 'get_memory'},
            {'method': 'POST', 'path': '/', 'handler': 'create_memory'},
            {'method': 'PUT', 'path': '/:filename', 'handler': 'update_memory'},
            {'method': 'DELETE', 'path': '/:filename', 'handler': 'delete_memory'},
            {'method': 'POST', 'path': '/search', 'handler': 'search_memories'},
            {'method': 'POST', 'path': '/extract', 'handler': 'extract_memories'},
            {'method': 'POST', 'path': '/consolidate', 'handler': 'consolidate_memories'},
            {'method': 'GET', 'path': '/system-prompt', 'handler': 'get_system_prompt'},
        ],
    }
