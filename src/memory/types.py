"""
# ==============================================================================
# MEMORY TYPES - 记忆类型定义
# ==============================================================================
# 来源: claude-code-source-code/src/memdir/memoryTypes.ts
#
# 记忆被约束为四种类型，捕获不能从当前项目状态推导的上下文。
# 代码模式、架构、git 历史和文件结构是可推导的（通过 grep/git/CLAUDE.md），
# 不应保存为记忆。
# ==============================================================================
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List
from pathlib import Path
from datetime import datetime


class MemoryType(Enum):
    """
    记忆类型枚举。

    四种类型捕获不能从项目状态推导的上下文：

    - USER: 用户信息 - 角色、偏好、知识背景
    - FEEDBACK: 反馈 - 用户指导、行为纠正
    - PROJECT: 项目 - 正在进行的工作、目标、决策
    - REFERENCE: 引用 - 外部系统指针（Linear项目、Slack频道等）
    """
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"

    @classmethod
    def parse(cls, raw: Optional[str]) -> Optional['MemoryType']:
        """解析原始值为 MemoryType，无效值返回 None"""
        if raw is None:
            return None
        try:
            return cls(raw.lower())
        except ValueError:
            return None


@dataclass
class MemoryHeader:
    """
    记忆文件头部信息。

    用于扫描和索引记忆文件，不包含完整内容。

    Attributes:
        filename: 相对于 memory 目录的文件名
        file_path: 绝对文件路径
        mtime_ms: 最后修改时间（毫秒时间戳）
        description: 记忆描述（来自 frontmatter）
        memory_type: 记忆类型
    """
    filename: str
    file_path: Path
    mtime_ms: float
    description: Optional[str] = None
    memory_type: Optional[MemoryType] = None

    def to_dict(self) -> dict:
        return {
            'filename': self.filename,
            'file_path': str(self.file_path),
            'mtime_ms': self.mtime_ms,
            'description': self.description,
            'memory_type': self.memory_type.value if self.memory_type else None,
        }


@dataclass
class MemoryConfig:
    """
    记忆系统配置。

    用于控制索引层大小、文件扫描数量、整理频率等。

    Attributes:
        max_index_lines: MEMORY.md 最大行数（默认 200）
        max_index_bytes: MEMORY.md 最大字节数（默认 25KB）
        max_topic_files: 最大主题文件数量（默认 200）
        frontmatter_max_lines: frontmatter 最大行数（默认 30）
        dream_min_hours: 自动整理最小间隔小时数（默认 24）
        dream_min_sessions: 触发整理的最小会话数（默认 5）
        relevant_memories_max: 相关记忆最大返回数（默认 5）
    """
    max_index_lines: int = 200
    max_index_bytes: int = 25_000
    max_topic_files: int = 200
    frontmatter_max_lines: int = 30
    dream_min_hours: int = 24
    dream_min_sessions: int = 5
    relevant_memories_max: int = 5


@dataclass
class MemoryEntry:
    """
    完整的记忆条目。

    包含 frontmatter 元数据和正文内容。

    Attributes:
        name: 记忆名称
        description: 一行描述
        memory_type: 记忆类型
        content: 记忆正文
        file_path: 文件路径
        created_at: 创建时间
        updated_at: 更新时间
    """
    name: str
    description: str
    memory_type: MemoryType
    content: str
    file_path: Optional[Path] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def render_frontmatter(self) -> str:
        """渲染 frontmatter 格式"""
        return f"""---
name: {self.name}
description: {self.description}
type: {self.memory_type.value}
---

{self.content}"""


# ==============================================================================
# 记忆类型说明文本 - 用于构建系统提示词
# ==============================================================================

MEMORY_TYPES_DESCRIPTION = """
## Types of memory

There are several discrete types of memory that you can store in your memory system:

<types>
<type>
    <name>user</name>
    <description>Contain information about the user's role, goals, responsibilities, and knowledge. Great user memories help you tailor your future behavior to the user's preferences and perspective.</description>
    <when_to_save>When you learn any details about the user's role, preferences, responsibilities, or knowledge</when_to_save>
    <how_to_use>When your work should be informed by the user's profile or perspective.</how_to_use>
    <examples>
    user: I'm a data scientist investigating what logging we have in place
    assistant: [saves user memory: user is a data scientist, currently focused on observability/logging]
    </examples>
</type>
<type>
    <name>feedback</name>
    <description>Guidance the user has given you about how to approach work — both what to avoid and what to keep doing. Record from failure AND success.</description>
    <when_to_save>Any time the user corrects your approach OR confirms a non-obvious approach worked.</when_to_save>
    <how_to_use>Let these memories guide your behavior so that the user does not need to offer the same guidance twice.</how_to_use>
    <body_structure>Lead with the rule itself, then a **Why:** line and a **How to apply:** line.</body_structure>
    <examples>
    user: don't mock the database in these tests — we got burned last quarter
    assistant: [saves feedback memory: integration tests must hit a real database. Reason: prior incident where mock/prod divergence masked a broken migration]
    </examples>
</type>
<type>
    <name>project</name>
    <description>Information that you learn about ongoing work, goals, initiatives, bugs, or incidents within the project that is not otherwise derivable from the code or git history.</description>
    <when_to_save>When you learn who is doing what, why, or by when.</when_to_save>
    <how_to_use>Use these memories to more fully understand the details and nuance behind the user's request.</how_to_use>
    <body_structure>Lead with the fact or decision, then a **Why:** line and a **How to apply:** line.</body_structure>
    <examples>
    user: we're freezing all non-critical merges after Thursday — mobile team is cutting a release branch
    assistant: [saves project memory: merge freeze begins 2026-03-05 for mobile release cut]
    </examples>
</type>
<type>
    <name>reference</name>
    <description>Stores pointers to where information can be found in external systems.</description>
    <when_to_save>When you learn about resources in external systems and their purpose.</when_to_save>
    <how_to_use>When the user references an external system or information that may be in an external system.</how_to_use>
    <examples>
    user: check the Linear project "INGEST" if you want context on these tickets
    assistant: [saves reference memory: pipeline bugs are tracked in Linear project "INGEST"]
    </examples>
</type>
</types>
"""

WHAT_NOT_TO_SAVE = """
## What NOT to save in memory

- Code patterns, conventions, architecture, file paths, or project structure — these can be derived by reading the current project state.
- Git history, recent changes, or who-changed-what — `git log` / `git blame` are authoritative.
- Debugging solutions or fix recipes — the fix is in the code; the commit message has the context.
- Anything already documented in CLAUDE.md files.
- Ephemeral task details: in-progress work, temporary state, current conversation context.
"""

WHEN_TO_ACCESS = """
## When to access memories

- When memories seem relevant, or the user references prior-conversation work.
- You MUST access memory when the user explicitly asks you to check, recall, or remember.
- If the user says to *ignore* or *not use* memory: proceed as if MEMORY.md were empty.
- Memory records can become stale over time. Before answering, verify that the memory is still correct by reading the current state of the files or resources.
"""

TRUSTING_RECALL = """
## Before recommending from memory

A memory that names a specific function, file, or flag is a claim that it existed *when the memory was written*. It may have been renamed, removed, or never merged. Before recommending it:

- If the memory names a file path: check the file exists.
- If the memory names a function or flag: grep for it.
- If the user is about to act on your recommendation (not just asking about history), verify first.

"The memory says X exists" is not the same as "X exists now."
"""
