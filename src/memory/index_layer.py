"""
# ==============================================================================
# INDEX LAYER - MEMORY.md 索引层
# ==============================================================================
# 来源: claude-code-source-code/src/memdir/memdir.ts
#
# 第一层记忆：轻量级索引文件，常驻上下文窗口。
#
# 特点：
#   - 最多 200 行, 25KB
#   - 只存指针（标题 + 文件名 + 一行 hook），不存数据
#   - 格式: `- [Title](file.md) — one-line hook`
#
# 写入纪律：
#   只有文件写入成功后才更新索引。如果写入 Topic File 失败，
#   索引层不会被更新——防止失败操作污染上下文。
# ==============================================================================
"""

import os
import re
from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass

from .types import MemoryConfig


@dataclass
class EntrypointTruncation:
    """索引截断结果"""
    content: str
    line_count: int
    byte_count: int
    was_line_truncated: bool
    was_byte_truncated: bool


class MemoryIndex:
    """
    MEMORY.md 索引层管理器。

    管理索引文件的读取、写入、截断和更新。

    索引格式示例：
        ```markdown
        # MEMORY.md

        - [User Role](user_role.md) — user is a senior engineer
        - [Testing Policy](feedback_testing.md) — integration tests must hit real DB
        - [Project Deadline](project_deadline.md) — merge freeze 2026-03-05
        ```
    """

    ENTRYPOINT_NAME = "MEMORY.md"
    INDEX_LINE_PATTERN = re.compile(r'^-\s+\[([^\]]+)\]\(([^)]+)\)\s*[—-]\s*(.+)$')

    def __init__(self, memory_dir: Path, config: Optional[MemoryConfig] = None):
        """
        初始化索引管理器。

        Args:
            memory_dir: memory 目录路径
            config: 配置对象
        """
        self.memory_dir = Path(memory_dir)
        self.config = config or MemoryConfig()
        self.entrypoint_path = self.memory_dir / self.ENTRYPOINT_NAME

    def exists(self) -> bool:
        """检查索引文件是否存在"""
        return self.entrypoint_path.exists()

    def read(self) -> str:
        """
        读取索引文件内容。

        Returns:
            索引文件内容，如果不存在返回空字符串
        """
        if not self.exists():
            return ""
        try:
            with open(self.entrypoint_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception:
            return ""

    def truncate(self, content: str) -> EntrypointTruncation:
        """
        截断索引内容以满足行数和字节数限制。

        先按行截断，再按字节截断，确保不切在行中间。

        Args:
            content: 原始内容

        Returns:
            EntrypointTruncation 包含截断结果
        """
        trimmed = content.strip()
        lines = trimmed.split('\n')
        line_count = len(lines)
        byte_count = len(trimmed.encode('utf-8'))

        was_line_truncated = line_count > self.config.max_index_lines
        was_byte_truncated = byte_count > self.config.max_index_bytes

        if not was_line_truncated and not was_byte_truncated:
            return EntrypointTruncation(
                content=trimmed,
                line_count=line_count,
                byte_count=byte_count,
                was_line_truncated=False,
                was_byte_truncated=False,
            )

        # 先按行截断
        if was_line_truncated:
            lines = lines[:self.config.max_index_lines]
            truncated = '\n'.join(lines)
        else:
            truncated = trimmed

        # 再按字节截断
        if len(truncated.encode('utf-8')) > self.config.max_index_bytes:
            encoded = truncated.encode('utf-8')
            # 找到最后一个换行符（在截断点之前）
            cut_at = truncated.rfind('\n', 0, self.config.max_index_bytes)
            if cut_at > 0:
                truncated = truncated[:cut_at]
            else:
                truncated = encoded[:self.config.max_index_bytes].decode('utf-8', errors='ignore')

        final_lines = truncated.split('\n')
        final_line_count = len(final_lines)
        final_byte_count = len(truncated.encode('utf-8'))

        # 添加截断警告
        if was_byte_truncated and not was_line_truncated:
            reason = f"{final_byte_count} bytes (limit: {self.config.max_index_bytes}) — index entries are too long"
        elif was_line_truncated and not was_byte_truncated:
            reason = f"{final_line_count} lines (limit: {self.config.max_index_lines})"
        else:
            reason = f"{final_line_count} lines and {final_byte_count} bytes"

        truncated += f"\n\n> WARNING: {self.ENTRYPOINT_NAME} is {reason}. Only part of it was loaded."

        return EntrypointTruncation(
            content=truncated,
            line_count=final_line_count,
            byte_count=final_byte_count,
            was_line_truncated=was_line_truncated,
            was_byte_truncated=was_byte_truncated,
        )

    def write(self, content: str) -> bool:
        """
        写入索引文件。

        自动进行截断以满足限制。

        Args:
            content: 要写入的内容

        Returns:
            是否写入成功
        """
        try:
            # 确保目录存在
            self.memory_dir.mkdir(parents=True, exist_ok=True)

            # 截断内容
            truncated = self.truncate(content)

            with open(self.entrypoint_path, 'w', encoding='utf-8') as f:
                f.write(truncated.content)

            return True
        except Exception:
            return False

    def parse_entries(self) -> List[Tuple[str, str, str]]:
        """
        解析索引文件中的条目。

        Returns:
            List of (title, filename, hook) tuples
        """
        content = self.read()
        entries = []

        for line in content.split('\n'):
            match = self.INDEX_LINE_PATTERN.match(line.strip())
            if match:
                title = match.group(1)
                filename = match.group(2)
                hook = match.group(3)
                entries.append((title, filename, hook))

        return entries

    def add_entry(self, title: str, filename: str, hook: str) -> bool:
        """
        添加一个条目到索引。

        Args:
            title: 条目标题
            filename: 文件名
            hook: 一行描述

        Returns:
            是否添加成功
        """
        content = self.read()

        # 检查是否已存在
        for line in content.split('\n'):
            if filename in line:
                return False  # 已存在

        # 添加新条目
        new_line = f"- [{title}]({filename}) — {hook}"

        # 找到插入位置（在现有条目之后）
        lines = content.split('\n')
        insert_idx = len(lines)

        # 查找最后一个条目的位置
        for i in range(len(lines) - 1, -1, -1):
            if self.INDEX_LINE_PATTERN.match(lines[i].strip()):
                insert_idx = i + 1
                break

        # 插入新条目
        lines.insert(insert_idx, new_line)
        new_content = '\n'.join(lines)

        return self.write(new_content)

    def remove_entry(self, filename: str) -> bool:
        """
        从索引中移除条目。

        Args:
            filename: 要移除的文件名

        Returns:
            是否移除成功
        """
        content = self.read()
        lines = content.split('\n')
        new_lines = []

        for line in lines:
            if filename not in line:
                new_lines.append(line)

        new_content = '\n'.join(new_lines)
        return self.write(new_content)

    def update_entry(self, filename: str, title: Optional[str] = None, hook: Optional[str] = None) -> bool:
        """
        更新索引中的条目。

        Args:
            filename: 文件名
            title: 新标题（可选）
            hook: 新描述（可选）

        Returns:
            是否更新成功
        """
        content = self.read()
        lines = content.split('\n')
        updated = False

        for i, line in enumerate(lines):
            match = self.INDEX_LINE_PATTERN.match(line.strip())
            if match and match.group(2) == filename:
                old_title = match.group(1)
                old_hook = match.group(3)
                new_title = title if title else old_title
                new_hook = hook if hook else old_hook
                lines[i] = f"- [{new_title}]({filename}) — {new_hook}"
                updated = True
                break

        if updated:
            new_content = '\n'.join(lines)
            return self.write(new_content)

        return False

    def build_empty_index(self) -> str:
        """
        构建空的索引文件内容。

        Returns:
            空索引文件的默认内容
        """
        return f"""# {self.ENTRYPOINT_NAME}

Your {self.ENTRYPOINT_NAME} is currently empty. When you save new memories, they will appear here.

## What to save

- **user**: User preferences, role, knowledge background
- **feedback**: Corrections, confirmed approaches
- **project**: Ongoing work, decisions, deadlines
- **reference**: External system pointers (Linear, Slack, etc.)

## What NOT to save

- Code patterns or architecture (read from code)
- Git history (use git log)
- Temporary task details
"""
