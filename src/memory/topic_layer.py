"""
# ==============================================================================
# TOPIC LAYER - 主题文件层
# ==============================================================================
# 来源: claude-code-source-code/src/memdir/memdir.ts
#
# 第二层记忆：按主题分散存储的知识文件。
#
# 特点：
#   - 只有被索引层引用时才读入上下文（按需加载）
#   - 实际的项目知识、代码约定、架构决策存在这里
#   - 四种类型: user, feedback, project, reference
#   - 格式：frontmatter + content
#
# 文件格式：
#   ---
#   name: memory name
#   description: one-line description
#   type: user | feedback | project | reference
#   ---
#
#   content here...
# ==============================================================================
"""

import os
import re
from pathlib import Path
from typing import Optional, List
from datetime import datetime
from dataclasses import dataclass

from .types import MemoryType, MemoryConfig


@dataclass
class TopicFile:
    """
    主题文件数据结构。

    Attributes:
        name: 记忆名称
        description: 一行描述
        memory_type: 记忆类型
        content: 正文内容
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

    def to_markdown(self) -> str:
        """转换为 Markdown 格式（带 frontmatter）"""
        return f"""---
name: {self.name}
description: {self.description}
type: {self.memory_type.value}
---

{self.content}"""


class TopicManager:
    """
    主题文件管理器。

    管理主题文件的创建、读取、更新和删除。

    Example:
        manager = TopicManager(Path("~/.claude/projects/my-project/memory"))
        manager.write_topic("user_role", "User Role", "user is a senior engineer", MemoryType.USER)
        topic = manager.read_topic("user_role.md")
    """

    # Frontmatter 模板
    FRONTMATTER_TEMPLATE = """---
name: {name}
description: {description}
type: {memory_type}
---

{content}"""

    # Frontmatter 正则
    FRONTMATTER_PATTERN = re.compile(
        r'^---\s*\n(.*?)\n---\s*\n(.*)$',
        re.DOTALL
    )
    YAML_KEY_VALUE = re.compile(r'^(\w+):\s*(.*)$', re.MULTILINE)

    def __init__(self, memory_dir: Path, config: Optional[MemoryConfig] = None):
        """
        初始化主题管理器。

        Args:
            memory_dir: memory 目录路径
            config: 配置对象
        """
        self.memory_dir = Path(memory_dir)
        self.config = config or MemoryConfig()

    def _ensure_dir(self):
        """确保 memory 目录存在"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def write_topic(
        self,
        filename: str,
        name: str,
        description: str,
        memory_type: MemoryType,
        content: str,
    ) -> Path:
        """
        写入主题文件。

        Args:
            filename: 文件名（不含扩展名）
            name: 记忆名称
            description: 一行描述
            memory_type: 记忆类型
            content: 正文内容

        Returns:
            写入的文件路径
        """
        self._ensure_dir()

        # 确保文件名以 .md 结尾
        if not filename.endswith('.md'):
            filename = f"{filename}.md"

        file_path = self.memory_dir / filename

        # 构建内容
        markdown = self.FRONTMATTER_TEMPLATE.format(
            name=name,
            description=description,
            memory_type=memory_type.value,
            content=content,
        )

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(markdown)

        return file_path

    def read_topic(self, filename: str) -> Optional[TopicFile]:
        """
        读取主题文件。

        Args:
            filename: 文件名

        Returns:
            TopicFile 或 None（如果文件不存在或解析失败）
        """
        if not filename.endswith('.md'):
            filename = f"{filename}.md"

        file_path = self.memory_dir / filename

        if not file_path.exists():
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 解析 frontmatter
            match = self.FRONTMATTER_PATTERN.match(content)
            if not match:
                return None

            frontmatter = match.group(1)
            body = match.group(2)

            # 解析 YAML
            name = None
            description = None
            memory_type = None

            for line in frontmatter.split('\n'):
                kv_match = self.YAML_KEY_VALUE.match(line)
                if kv_match:
                    key = kv_match.group(1)
                    value = kv_match.group(2).strip()

                    if key == 'name':
                        name = value
                    elif key == 'description':
                        description = value
                    elif key == 'type':
                        memory_type = MemoryType.parse(value)

            if not name or not memory_type:
                return None

            # 获取文件信息
            stat = file_path.stat()
            created_at = datetime.fromtimestamp(stat.st_ctime)
            updated_at = datetime.fromtimestamp(stat.st_mtime)

            return TopicFile(
                name=name,
                description=description or '',
                memory_type=memory_type,
                content=body,
                file_path=file_path,
                created_at=created_at,
                updated_at=updated_at,
            )
        except Exception:
            return None

    def delete_topic(self, filename: str) -> bool:
        """
        删除主题文件。

        Args:
            filename: 文件名

        Returns:
            是否删除成功
        """
        if not filename.endswith('.md'):
            filename = f"{filename}.md"

        file_path = self.memory_dir / filename

        if not file_path.exists():
            return False

        try:
            os.remove(file_path)
            return True
        except Exception:
            return False

    def update_topic(
        self,
        filename: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        content: Optional[str] = None,
    ) -> bool:
        """
        更新主题文件。

        Args:
            filename: 文件名
            name: 新名称（可选）
            description: 新描述（可选）
            memory_type: 新类型（可选）
            content: 新内容（可选）

        Returns:
            是否更新成功
        """
        topic = self.read_topic(filename)
        if not topic:
            return False

        # 更新字段
        if name:
            topic.name = name
        if description:
            topic.description = description
        if memory_type:
            topic.memory_type = memory_type
        if content:
            topic.content = content

        # 重新写入
        if topic.file_path:
            try:
                with open(topic.file_path, 'w', encoding='utf-8') as f:
                    f.write(topic.to_markdown())
                return True
            except Exception:
                return False

        return False

    def list_topics(self) -> List[str]:
        """
        列出所有主题文件名。

        Returns:
            文件名列表（不含 MEMORY.md）
        """
        if not self.memory_dir.exists():
            return []

        topics = []
        for f in self.memory_dir.iterdir():
            if f.is_file() and f.suffix == '.md' and f.name != 'MEMORY.md':
                topics.append(f.name)

        return sorted(topics)

    @staticmethod
    def format_feedback_content(rule: str, why: str, how_to_apply: str) -> str:
        """
        格式化 feedback 类型的记忆内容。

        Args:
            rule: 规则本身
            why: 原因说明
            how_to_apply: 应用场景

        Returns:
            格式化的内容
        """
        return f"""{rule}

**Why:** {why}

**How to apply:** {how_to_apply}"""

    @staticmethod
    def format_project_content(fact: str, why: str, how_to_apply: str) -> str:
        """
        格式化 project 类型的记忆内容。

        Args:
            fact: 事实或决策
            why: 动机
            how_to_apply: 如何应用

        Returns:
            格式化的内容
        """
        return f"""{fact}

**Why:** {why}

**How to apply:** {how_to_apply}"""
