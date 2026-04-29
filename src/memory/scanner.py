"""
# ==============================================================================
# MEMORY SCANNER - 记忆文件扫描器
# ==============================================================================
# 来源: claude-code-source-code/src/memdir/memoryScan.ts
#
# 扫描 memory 目录中的 .md 文件，读取 frontmatter，返回按修改时间排序的头部列表。
# 用于：
#   - findRelevantMemories: 查询时召回
#   - extractMemories: 预注入清单，避免额外 ls 开销
# ==============================================================================
"""

import os
import re
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime

from .types import MemoryHeader, MemoryType, MemoryConfig


class MemoryScanner:
    """
    记忆文件扫描器。

    扫描 memory 目录中的 .md 文件，读取 frontmatter 元数据，
    返回按修改时间排序的 MemoryHeader 列表。

    Example:
        scanner = MemoryScanner(Path("~/.claude/projects/my-project/memory"))
        headers = await scanner.scan()
        manifest = scanner.format_manifest(headers)
    """

    # Frontmatter 正则模式
    FRONTMATTER_PATTERN = re.compile(
        r'^---\s*\n(.*?)\n---\s*\n',
        re.DOTALL
    )
    # YAML 键值对正则
    YAML_KEY_VALUE = re.compile(r'^(\w+):\s*(.*)$', re.MULTILINE)

    def __init__(self, memory_dir: Path, config: Optional[MemoryConfig] = None):
        """
        初始化扫描器。

        Args:
            memory_dir: memory 目录路径
            config: 配置对象
        """
        self.memory_dir = Path(memory_dir)
        self.config = config or MemoryConfig()

    async def scan(self) -> List[MemoryHeader]:
        """
        扫描 memory 目录，返回按修改时间排序的记忆头部列表。

        Returns:
            MemoryHeader 列表，最多 max_topic_files 个
        """
        if not self.memory_dir.exists():
            return []

        headers: List[MemoryHeader] = []

        # 递归遍历目录
        for root, _, files in os.walk(self.memory_dir):
            for filename in files:
                if not filename.endswith('.md'):
                    continue
                # 跳过 MEMORY.md（索引文件）
                if filename == 'MEMORY.md':
                    continue

                file_path = Path(root) / filename
                relative_path = file_path.relative_to(self.memory_dir)

                try:
                    header = self._read_header(file_path, str(relative_path))
                    if header:
                        headers.append(header)
                except Exception:
                    # 读取失败时跳过
                    continue

        # 按修改时间降序排序
        headers.sort(key=lambda h: h.mtime_ms, reverse=True)

        # 限制数量
        return headers[:self.config.max_topic_files]

    def _read_header(self, file_path: Path, relative_path: str) -> Optional[MemoryHeader]:
        """
        读取单个文件的头部信息。

        Args:
            file_path: 文件绝对路径
            relative_path: 相对于 memory 目录的路径

        Returns:
            MemoryHeader 或 None（如果读取失败）
        """
        # 获取修改时间
        mtime = os.path.getmtime(file_path)
        mtime_ms = mtime * 1000

        # 读取文件开头部分
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 只读取前 N 行
                lines = []
                for i, line in enumerate(f):
                    if i >= self.config.frontmatter_max_lines:
                        break
                    lines.append(line)
                content = ''.join(lines)
        except Exception:
            return None

        # 解析 frontmatter
        description, memory_type = self._parse_frontmatter(content)

        return MemoryHeader(
            filename=relative_path,
            file_path=file_path,
            mtime_ms=mtime_ms,
            description=description,
            memory_type=memory_type,
        )

    def _parse_frontmatter(self, content: str) -> Tuple[Optional[str], Optional[MemoryType]]:
        """
        解析 frontmatter 提取 description 和 type。

        Args:
            content: 文件开头内容

        Returns:
            (description, memory_type) 元组
        """
        match = self.FRONTMATTER_PATTERN.match(content)
        if not match:
            return None, None

        frontmatter = match.group(1)
        description = None
        memory_type = None

        # 解析 YAML 键值对
        for line in frontmatter.split('\n'):
            kv_match = self.YAML_KEY_VALUE.match(line)
            if kv_match:
                key = kv_match.group(1)
                value = kv_match.group(2).strip()

                if key == 'description':
                    description = value
                elif key == 'type':
                    memory_type = MemoryType.parse(value)

        return description, memory_type

    def format_manifest(self, headers: List[MemoryHeader]) -> str:
        """
        将记忆头部列表格式化为清单文本。

        格式: [type] filename (timestamp): description

        Args:
            headers: MemoryHeader 列表

        Returns:
            格式化的清单字符串
        """
        lines = []
        for h in headers:
            tag = f"[{h.memory_type.value}] " if h.memory_type else ""
            ts = datetime.fromtimestamp(h.mtime_ms / 1000).isoformat()
            if h.description:
                lines.append(f"- {tag}{h.filename} ({ts}): {h.description}")
            else:
                lines.append(f"- {tag}{h.filename} ({ts})")
        return '\n'.join(lines)


def format_memory_manifest(headers: List[MemoryHeader]) -> str:
    """
    格式化记忆清单的便捷函数。

    Args:
        headers: MemoryHeader 列表

    Returns:
        格式化的清单字符串
    """
    scanner = MemoryScanner(Path('.'))
    return scanner.format_manifest(headers)
