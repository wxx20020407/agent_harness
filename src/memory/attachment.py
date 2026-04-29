"""
# ==============================================================================
# MEMORY ATTACHMENT - 记忆附件注入
# ==============================================================================
# 来源: claude-code-source-code/src/utils/attachments.ts
#
# 实现三层记忆架构的注入机制：
#   1. 系统提示词注入 - MEMORY.md 索引层
#   2. 相关记忆预取 - 后台查找相关记忆
#   3. 记忆内容注入 - 按需加载主题文件
#
# 三层记忆架构：
#   Layer 1: MEMORY.md Index (索引层) - 常驻上下文，最多200行
#   Layer 2: Topic Files (知识层) - 按需加载
#   Layer 3: Transcript Grep (日志层) - 仅grep检索
# ==============================================================================
"""

import os
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import re

from .types import MemoryType, MemoryHeader
from .scanner import MemoryScanner
from .index_layer import IndexLayer
from .relevance import RelevanceFinder, RelevantMemory
from .llm_client import get_llm_client, ModelTier


class MemoryLayer(Enum):
    """记忆层级"""
    INDEX = "index"           # Layer 1: 索引层 (MEMORY.md)
    TOPIC = "topic"           # Layer 2: 主题文件层
    TRANSCRIPT = "transcript" # Layer 3: 日志层


@dataclass
class MemoryAttachment:
    """
    记忆附件 - 用于注入到对话上下文。

    对应 Claude Code 的 attachment message:
    {
      type: 'attachment',
      attachment: {
        type: 'memory',
        path: string,
        content: string,
        mtime_ms: number,
      }
    }
    """
    path: Path
    content: str
    mtime_ms: float
    layer: MemoryLayer
    memory_type: Optional[MemoryType] = None
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "type": "memory",
            "path": str(self.path),
            "content": self.content,
            "mtime_ms": self.mtime_ms,
            "layer": self.layer.value,
            "memory_type": self.memory_type.value if self.memory_type else None,
            "description": self.description,
        }

    def to_system_prompt_section(self) -> str:
        """
        转换为系统提示词格式。

        用于 Layer 1 (MEMORY.md) 的注入。
        """
        if self.layer != MemoryLayer.INDEX:
            return ""

        lines = [
            f"# Memory Index ({self.path.name})",
            "",
            "You have access to persistent memory files. The index below shows what memories exist.",
            "Read specific memory files when you need their full content.",
            "",
            self.content,
        ]
        return "\n".join(lines)


@dataclass
class MemoryPrefetchResult:
    """记忆预取结果"""
    attachments: List[MemoryAttachment] = field(default_factory=list)
    settled_at: Optional[float] = None  # 预取完成时间戳

    @classmethod
    def empty(cls) -> 'MemoryPrefetchResult':
        return cls(attachments=[], settled_at=datetime.now().timestamp())


class MemoryAttachmentManager:
    """
    记忆附件管理器。

    实现三层记忆架构的注入机制。

    Example:
        manager = MemoryAttachmentManager(memory_dir)

        # 1. 获取系统提示词部分 (Layer 1)
        system_prompt = manager.build_system_prompt_section()

        # 2. 启动相关记忆预取 (后台)
        prefetch = manager.start_prefetch(query, recent_tools)

        # 3. 获取预取结果 (Layer 2)
        attachments = await prefetch.attachments
    """

    # 系统提示词头部
    MEMORY_SYSTEM_PROMPT_HEADER = """# Memory System

You have a persistent, file-based memory system. The memories are organized in three layers:

1. **Index Layer (MEMORY.md)** - Always loaded, shows available memories
2. **Topic Files** - Loaded on-demand when relevant to the current query
3. **Transcript Logs** - Searched via grep when needed

## When to access memories

- **When the user explicitly asks you to remember something** → Save immediately
- **When the user asks you to forget something** → Find and remove the relevant entry
- **When starting a new task** → Check if relevant memories exist
- **When the user mentions past work** → Search for related context

## How to save memories

Write to files in the memory directory using the Write tool:
- Each memory is a separate file with frontmatter
- Update MEMORY.md index after writing

## What NOT to save

- Code patterns, conventions, architecture → Derivable from codebase
- Git history, recent changes → Use git commands
- Debugging solutions → Already in the code/commits
- Ephemeral task details → Use tasks instead
"""

    def __init__(
        self,
        memory_dir: Path,
        scanner: Optional[MemoryScanner] = None,
        index_layer: Optional[IndexLayer] = None,
        relevance_finder: Optional[RelevanceFinder] = None,
    ):
        """
        初始化管理器。

        Args:
            memory_dir: 记忆目录路径
            scanner: 记忆扫描器
            index_layer: 索引层管理器
            relevance_finder: 相关记忆查找器
        """
        self.memory_dir = memory_dir
        self.scanner = scanner or MemoryScanner(memory_dir)
        self.index_layer = index_layer or IndexLayer(memory_dir, self.scanner)
        self.relevance_finder = relevance_finder or RelevanceFinder(self.scanner)

        # 缓存已加载的记忆路径
        self._loaded_paths: Set[str] = set()

        # 预取任务
        self._pending_prefetch: Optional[asyncio.Task] = None

    # =========================================================================
    # Layer 1: 系统提示词注入 (MEMORY.md 索引层)
    # =========================================================================

    def build_system_prompt_section(self) -> str:
        """
        构建系统提示词的记忆部分。

        这是 Layer 1 的注入点 - MEMORY.md 索引层。

        对应 Claude Code:
          QueryEngine.ts:316-319 → loadMemoryPrompt()
          memdir/memdir.ts:buildMemoryLines()

        Returns:
            系统提示词字符串，如果 MEMORY.md 不存在则返回空
        """
        # 读取 MEMORY.md
        memory_md_path = self.memory_dir / "MEMORY.md"

        if not memory_md_path.exists():
            # 返回基础说明（没有记忆时）
            return self._build_empty_memory_prompt()

        try:
            content = memory_md_path.read_text(encoding='utf-8')
            mtime_ms = memory_md_path.stat().st_mtime * 1000

            # 截断到 200 行 / 25KB
            content = self._truncate_content(content)

            lines = [
                self.MEMORY_SYSTEM_PROMPT_HEADER,
                "",
                "## MEMORY.md (Index Layer)",
                "",
                "```",
                content,
                "```",
            ]

            return "\n".join(lines)

        except Exception as e:
            return f"# Memory System\n\nError loading MEMORY.md: {e}"

    def _build_empty_memory_prompt(self) -> str:
        """构建空的记忆提示词"""
        lines = [
            self.MEMORY_SYSTEM_PROMPT_HEADER,
            "",
            "## MEMORY.md",
            "",
            "Your MEMORY.md is currently empty. When you save new memories, they will appear here.",
        ]
        return "\n".join(lines)

    def _truncate_content(self, content: str, max_lines: int = 200, max_bytes: int = 25000) -> str:
        """
        截断内容到限制内。

        对应 Claude Code: memdir/memdir.ts:truncateEntrypointContent()
        """
        lines = content.split('\n')

        # 行数截断
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True
        else:
            truncated = False

        content = '\n'.join(lines)

        # 字节截断
        if len(content.encode('utf-8')) > max_bytes:
            # 找到最后一个换行符
            cut_at = content.rfind('\n', 0, max_bytes)
            if cut_at > 0:
                content = content[:cut_at]
            else:
                content = content[:max_bytes]
            truncated = True

        if truncated:
            content += "\n\n> WARNING: MEMORY.md was truncated. Keep index entries concise."

        return content

    # =========================================================================
    # Layer 2: 相关记忆预取 (主题文件层)
    # =========================================================================

    def start_prefetch(
        self,
        query: str,
        recent_tools: Optional[List[str]] = None,
        already_surfaced: Optional[Set[str]] = None,
    ) -> 'MemoryPrefetch':
        """
        启动相关记忆预取。

        这是 Layer 2 的入口 - 后台查找相关记忆。

        对应 Claude Code:
          query.ts:301-304 → startRelevantMemoryPrefetch()
          utils/attachments.ts:startRelevantMemoryPrefetch()

        Args:
            query: 用户查询
            recent_tools: 最近使用的工具列表
            already_surfaced: 已经展示过的文件路径

        Returns:
            MemoryPrefetch 对象，可 await 获取结果
        """
        return MemoryPrefetch(
            manager=self,
            query=query,
            recent_tools=recent_tools,
            already_surfaced=already_surfaced,
        )

    async def find_relevant_memories(
        self,
        query: str,
        recent_tools: Optional[List[str]] = None,
        already_surfaced: Optional[Set[str]] = None,
        max_results: int = 5,
    ) -> List[MemoryAttachment]:
        """
        查找相关记忆并返回附件。

        Args:
            query: 用户查询
            recent_tools: 最近使用的工具
            already_surfaced: 已展示的路径
            max_results: 最大结果数

        Returns:
            MemoryAttachment 列表
        """
        # 使用 relevance finder 查找
        relevant = await self.relevance_finder.find(
            query=query,
            recent_tools=recent_tools,
            already_surfaced=already_surfaced,
        )

        # 转换为附件
        attachments = []
        for mem in relevant[:max_results]:
            try:
                content = mem.path.read_text(encoding='utf-8')
                attachment = MemoryAttachment(
                    path=mem.path,
                    content=content,
                    mtime_ms=mem.mtime_ms,
                    layer=MemoryLayer.TOPIC,
                )
                attachments.append(attachment)
                self._loaded_paths.add(str(mem.path))
            except Exception:
                continue

        return attachments

    # =========================================================================
    # Layer 3: Transcript Grep (日志层)
    # =========================================================================

    def build_transcript_search_instruction(self, transcript_dir: Optional[Path] = None) -> str:
        """
        构建 Transcript 搜索指令。

        这是 Layer 3 的入口 - 仅通过 grep 检索。

        对应 Claude Code:
          memdir/memdir.ts:buildSearchingPastContextSection()

        Args:
            transcript_dir: 日志目录路径

        Returns:
            搜索指令字符串
        """
        if transcript_dir is None:
            transcript_dir = self.memory_dir.parent / "sessions"

        return f"""## Searching Past Context (Layer 3)

When you need to search past conversations:

1. **Search memory files:**
   ```
   grep -rn "<search term>" {self.memory_dir} --include="*.md"
   ```

2. **Search session transcripts (last resort):**
   ```
   grep -rn "<search term>" {transcript_dir}/ --include="*.jsonl"
   ```

Use narrow search terms (error messages, file paths, function names) rather than broad keywords.
"""

    # =========================================================================
    # 记忆写入辅助
    # =========================================================================

    def build_memory_write_instruction(self) -> str:
        """
        构建记忆写入指令。

        对应 Claude Code: memdir/memdir.ts 中的 "How to save memories" 部分
        """
        return """## How to Save Memories

Saving a memory is a two-step process:

**Step 1** - Write the memory to its own file using this frontmatter format:

```markdown
---
name: {{memory name}}
description: {{one-line description}}
type: {{user|feedback|project|reference}}
---

{{memory content}}
```

**Step 2** - Add a pointer to MEMORY.md:
```
- [Title](file.md) — one-line hook
```

**Rules:**
- Keep MEMORY.md entries to one line under ~150 characters
- Keep the name, description, and type fields up-to-date
- Organize memory semantically by topic, not chronologically
- Update or remove outdated memories
- Do not write duplicate memories
"""


class MemoryPrefetch:
    """
    记忆预取任务。

    对应 Claude Code 的 pendingMemoryPrefetch 对象。

    Example:
        prefetch = manager.start_prefetch(query)

        # 非阻塞，可以继续其他工作
        await some_other_work()

        # 获取结果（如果已完成则立即返回）
        attachments = await prefetch.attachments
    """

    def __init__(
        self,
        manager: MemoryAttachmentManager,
        query: str,
        recent_tools: Optional[List[str]] = None,
        already_surfaced: Optional[Set[str]] = None,
    ):
        self.manager = manager
        self.query = query
        self.recent_tools = recent_tools
        self.already_surfaced = already_surfaced or set()

        self._task: Optional[asyncio.Task] = None
        self._result: Optional[MemoryPrefetchResult] = None
        self._started_at = datetime.now().timestamp()

    @property
    def settled_at(self) -> Optional[float]:
        """预取完成时间戳"""
        return self._result.settled_at if self._result else None

    @property
    def attachments(self) -> 'asyncio.Task[List[MemoryAttachment]]':
        """
        获取附件的 awaitable。

        Returns:
            asyncio.Task，可 await 获取 List[MemoryAttachment]
        """
        if self._task is None:
            self._task = asyncio.create_task(self._run())
        return self._task

    async def _run(self) -> List[MemoryAttachment]:
        """执行预取"""
        try:
            attachments = await self.manager.find_relevant_memories(
                query=self.query,
                recent_tools=self.recent_tools,
                already_surfaced=self.already_surfaced,
            )

            self._result = MemoryPrefetchResult(
                attachments=attachments,
                settled_at=datetime.now().timestamp(),
            )

            return attachments

        except Exception:
            self._result = MemoryPrefetchResult.empty()
            return []


# =============================================================================
# 便捷函数
# =============================================================================

def get_memory_attachment_manager(memory_dir: Optional[Path] = None) -> MemoryAttachmentManager:
    """
    获取记忆附件管理器。

    Args:
        memory_dir: 记忆目录，默认使用环境变量 MEMORY_DIR 或 ~/.claude/memory

    Returns:
        MemoryAttachmentManager 实例
    """
    if memory_dir is None:
        memory_dir = Path(os.environ.get(
            'MEMORY_DIR',
            Path.home() / '.claude' / 'memory'
        ))

    return MemoryAttachmentManager(memory_dir)


def build_memory_system_prompt(memory_dir: Optional[Path] = None) -> str:
    """
    构建记忆系统提示词。

    便捷函数，用于直接获取 Layer 1 的系统提示词部分。

    Args:
        memory_dir: 记忆目录

    Returns:
        系统提示词字符串
    """
    manager = get_memory_attachment_manager(memory_dir)
    return manager.build_system_prompt_section()