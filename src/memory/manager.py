"""
# ==============================================================================
# MEMORY MANAGER - 统一记忆管理接口
# ==============================================================================
# 提供三层记忆系统的统一访问入口，简化使用复杂度。
#
# 使用示例：
#   from memory import MemoryManager
#
#   manager = MemoryManager(Path("~/.claude/projects/my-project/memory"))
#
#   # 加载索引层
#   index_content = manager.load_index()
#
#   # 保存记忆
#   manager.save_memory("user_role", "User Role", "user is senior engineer", MemoryType.USER, content)
#
#   # 查找相关记忆
#   memories = await manager.find_relevant("how to fix auth bug")
#
#   # 触发整理
#   result = await manager.consolidate()
# ==============================================================================
"""

import os
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from datetime import datetime

from .types import MemoryType, MemoryConfig, MemoryHeader, MemoryEntry
from .scanner import MemoryScanner
from .index_layer import MemoryIndex
from .topic_layer import TopicManager, TopicFile
from .transcript_layer import TranscriptStore, TranscriptSearch
from .relevance import RelevanceFinder, RelevantMemory
from .extract import MemoryExtractor, ExtractResult
from .dream import MemoryDream, DreamResult


class MemoryManager:
    """
    统一记忆管理器。

    提供三层记忆系统的完整操作接口。

    Example:
        manager = MemoryManager(
            memory_dir=Path("~/.claude/projects/my-project/memory"),
            transcripts_dir=Path("~/.claude/projects/my-project/sessions"),
        )

        # 检查是否启用
        if manager.is_enabled():
            # 加载系统提示词部分
            prompt = manager.build_system_prompt_section()

            # 保存记忆
            manager.save_memory(...)
    """

    DIR_EXISTS_GUIDANCE = "This directory already exists — write to it directly with the Write tool (do not run mkdir or check for its existence)."

    def __init__(
        self,
        memory_dir: Path,
        transcripts_dir: Optional[Path] = None,
        config: Optional[MemoryConfig] = None,
        llm_client: Optional[Any] = None,
    ):
        """
        初始化记忆管理器。

        Args:
            memory_dir: memory 目录路径
            transcripts_dir: transcripts 目录路径
            config: 配置对象
            llm_client: LLM 客户端
        """
        self.memory_dir = Path(memory_dir)
        self.transcripts_dir = transcripts_dir
        self.config = config or MemoryConfig()
        self.llm_client = llm_client

        # 初始化各层组件
        self.scanner = MemoryScanner(self.memory_dir, self.config)
        self.index = MemoryIndex(self.memory_dir, self.config)
        self.topic_manager = TopicManager(self.memory_dir, self.config)
        self.relevance_finder = RelevanceFinder(self.scanner, self.config, llm_client)
        self.extractor = MemoryExtractor(self.memory_dir, self.config, llm_client)

        # 第三层（可选）
        if transcripts_dir:
            self.transcript_store = TranscriptStore(transcripts_dir)
            self.transcript_search = TranscriptSearch(self.transcript_store)
            self.dream = MemoryDream(self.memory_dir, transcripts_dir, self.config, llm_client)
        else:
            self.transcript_store = None
            self.transcript_search = None
            self.dream = None

    def is_enabled(self) -> bool:
        """
        检查记忆系统是否启用。

        Returns:
            是否启用
        """
        # 检查环境变量或设置
        return os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY', '').lower() not in ('1', 'true')

    def ensure_memory_dir(self) -> None:
        """
        确保 memory 目录存在。

        在构建系统提示词时调用，保证模型可以直接写入。
        """
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Layer 1: Index Operations
    # =========================================================================

    def load_index(self) -> str:
        """
        加载索引层内容。

        Returns:
            MEMORY.md 内容
        """
        self.ensure_memory_dir()
        content = self.index.read()

        if content.strip():
            truncated = self.index.truncate(content)
            return truncated.content
        else:
            return self.index.build_empty_index()

    def get_index_entries(self) -> List[tuple]:
        """
        获取索引条目列表。

        Returns:
            List of (title, filename, hook) tuples
        """
        return self.index.parse_entries()

    # =========================================================================
    # Layer 2: Topic File Operations
    # =========================================================================

    def save_memory(
        self,
        filename: str,
        name: str,
        description: str,
        memory_type: MemoryType,
        content: str,
        update_index: bool = True,
    ) -> Path:
        """
        保存记忆到主题文件。

        实现严格的写入纪律：
        1. 先写入主题文件
        2. 写入成功后才更新索引

        Args:
            filename: 文件名（不含扩展名）
            name: 记忆名称
            description: 一行描述
            memory_type: 记忆类型
            content: 正文内容
            update_index: 是否更新索引

        Returns:
            写入的文件路径
        """
        # Step 1: 写入主题文件
        file_path = self.topic_manager.write_topic(
            filename=filename,
            name=name,
            description=description,
            memory_type=memory_type,
            content=content,
        )

        # Step 2: 更新索引（只有写入成功才执行）
        if update_index:
            self.index.add_entry(
                title=name,
                filename=filename + '.md',
                hook=description,
            )

        return file_path

    def read_memory(self, filename: str) -> Optional[TopicFile]:
        """
        读取记忆文件。

        Args:
            filename: 文件名

        Returns:
            TopicFile 或 None
        """
        return self.topic_manager.read_topic(filename)

    def delete_memory(self, filename: str) -> bool:
        """
        删除记忆文件。

        同时从索引中移除。

        Args:
            filename: 文件名

        Returns:
            是否删除成功
        """
        # 先从索引移除
        self.index.remove_entry(filename + '.md' if not filename.endswith('.md') else filename)

        # 删除文件
        return self.topic_manager.delete_topic(filename)

    def list_memories(self) -> List[str]:
        """
        列出所有记忆文件。

        Returns:
            文件名列表
        """
        return self.topic_manager.list_topics()

    async def scan_memories(self) -> List[MemoryHeader]:
        """
        扫描所有记忆文件。

        Returns:
            MemoryHeader 列表
        """
        return await self.scanner.scan()

    # =========================================================================
    # Layer 3: Transcript Operations
    # =========================================================================

    def search_transcripts(
        self,
        pattern: str,
        session_ids: Optional[List[str]] = None,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        在 transcript 中搜索。

        第三层记忆的唯一读取方式：精确关键词搜索。

        Args:
            pattern: 搜索模式
            session_ids: 会话 ID 列表
            max_results: 最大结果数

        Returns:
            匹配结果列表
        """
        if not self.transcript_search:
            return []

        return self.transcript_search.grep(pattern, session_ids, max_results)

    # =========================================================================
    # Relevance Search
    # =========================================================================

    async def find_relevant(
        self,
        query: str,
        max_results: int = 5,
        recent_tools: Optional[List[str]] = None,
    ) -> List[RelevantMemory]:
        """
        查找与查询相关的记忆。

        Args:
            query: 查询字符串
            max_results: 最大结果数
            recent_tools: 最近使用的工具列表

        Returns:
            RelevantMemory 列表
        """
        headers = await self.scanner.scan()

        if not headers:
            return []

        # 如果没有 LLM 客户端，使用关键词匹配
        if not self.llm_client:
            return self.relevance_finder.find_by_keywords(query, headers, max_results)

        return await self.relevance_finder.find(query, recent_tools)

    # =========================================================================
    # Self-Healing: Extract & Dream
    # =========================================================================

    async def extract_from_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> ExtractResult:
        """
        从消息中提取记忆。

        Self-Healing 机制的第一部分：实时提取。

        Args:
            messages: 消息列表

        Returns:
            ExtractResult
        """
        return await self.extractor.extract(messages)

    async def should_consolidate(self) -> bool:
        """
        检查是否应该进行整理。

        Returns:
            是否满足整理条件
        """
        if not self.dream:
            return False
        return await self.dream.should_run()

    async def consolidate(
        self,
        session_ids: Optional[List[str]] = None,
    ) -> Optional[DreamResult]:
        """
        执行记忆整理。

        Self-Healing 机制的第二部分：后台整理。

        Args:
            session_ids: 要审查的会话 ID 列表

        Returns:
            DreamResult 或 None
        """
        if not self.dream:
            return None
        return await self.dream.run(session_ids)

    # =========================================================================
    # System Prompt Generation
    # =========================================================================

    def build_system_prompt_section(self) -> str:
        """
        构建记忆系统的系统提示词部分。

        用于注入到主 agent 的系统提示词中。

        Returns:
            系统提示词部分
        """
        self.ensure_memory_dir()

        lines = [
            f"# auto memory",
            "",
            f"You have a persistent, file-based memory system at `{self.memory_dir}`. {self.DIR_EXISTS_GUIDANCE}",
            "",
            "You should build up this memory system over time so that future conversations can have a complete picture of who the user is, how they'd like to collaborate with you, what behaviors to avoid or repeat, and the context behind the work the user gives you.",
            "",
            "If the user explicitly asks you to remember something, save it immediately as whichever type fits best. If they ask you to forget something, find and remove the relevant entry.",
            "",
        ]

        # 添加类型说明
        from .types import MEMORY_TYPES_DESCRIPTION, WHAT_NOT_TO_SAVE, WHEN_TO_ACCESS, TRUSTING_RECALL
        lines.append(MEMORY_TYPES_DESCRIPTION)
        lines.append(WHAT_NOT_TO_SAVE)
        lines.append(WHEN_TO_ACCESS)
        lines.append(TRUSTING_RECALL)

        # 添加如何保存
        lines.extend([
            "## How to save memories",
            "",
            "Saving a memory is a two-step process:",
            "",
            "**Step 1** — write the memory to its own file (e.g., `user_role.md`) using this frontmatter format:",
            "",
            "```markdown",
            "---",
            "name: {{memory name}}",
            "description: {{one-line description}}",
            "type: {{user, feedback, project, reference}}",
            "---",
            "",
            "{{memory content}}",
            "```",
            "",
            "**Step 2** — add a pointer to that file in `MEMORY.md`. Each entry should be one line, under ~150 characters: `- [Title](file.md) — one-line hook`.",
            "",
            f"- `MEMORY.md` is always loaded into your conversation context — lines after {self.config.max_index_lines} will be truncated, so keep the index concise",
            "- Organize memory semantically by topic, not chronologically",
            "- Update or remove memories that turn out to be wrong or outdated",
            "- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one.",
            "",
        ])

        # 添加 MEMORY.md 内容
        index_content = self.index.read()
        if index_content.strip():
            truncated = self.index.truncate(index_content)
            lines.extend([
                "## MEMORY.md",
                "",
                truncated.content,
            ])
        else:
            lines.extend([
                "## MEMORY.md",
                "",
                "Your MEMORY.md is currently empty. When you save new memories, they will appear here.",
            ])

        return '\n'.join(lines)


# =============================================================================
# Factory Function
# =============================================================================

def create_memory_manager(
    project_root: Path,
    team_id: Optional[str] = None,
) -> MemoryManager:
    """
    创建记忆管理器的工厂函数。

    Args:
        project_root: 项目根目录
        team_id: 团队 ID（可选）

    Returns:
        MemoryManager 实例
    """
    # 确定记忆目录
    if team_id:
        memory_dir = project_root / "teams" / team_id / "memory"
        transcripts_dir = project_root / "data" / "sessions"
    else:
        # 使用项目级目录
        memory_dir = project_root / ".claude" / "memory"
        transcripts_dir = project_root / ".claude" / "sessions"

    return MemoryManager(
        memory_dir=memory_dir,
        transcripts_dir=transcripts_dir,
    )
