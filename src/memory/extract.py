"""
# ==============================================================================
# MEMORY EXTRACTOR - 实时记忆提取
# ==============================================================================
# 来源: claude-code-source-code/src/services/extractMemories/extractMemories.ts
#
# 在每个完整查询循环结束时，从对话中提取持久化记忆。
#
# 触发时机：
#   当模型产生无工具调用的最终响应时
#
# 使用 forked agent 模式：
#   - 共享主对话的 prompt cache
#   - 工具权限受限（只能写 memory 目录）
#
# 重要：当前 agent_harness 不是真正的 agent runtime，
#       此模块提供手动调用接口，后续可向 agent 对齐。
# ==============================================================================
"""

import os
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from dataclasses import dataclass, field
from datetime import datetime

from .types import MemoryType, MemoryConfig, MEMORY_TYPES_DESCRIPTION, WHAT_NOT_TO_SAVE
from .scanner import MemoryScanner, format_memory_manifest
from .index_layer import MemoryIndex
from .topic_layer import TopicManager


@dataclass
class ExtractResult:
    """提取结果"""
    success: bool
    files_written: List[str] = field(default_factory=list)
    memories_saved: int = 0
    error: Optional[str] = None


class MemoryExtractor:
    """
    记忆提取器。

    从对话消息中提取持久化记忆。

    Example:
        extractor = MemoryExtractor(memory_dir)
        result = await extractor.extract(messages)
    """

    EXTRACT_SYSTEM_PROMPT = """You are now acting as the memory extraction subagent. Analyze the most recent messages and use them to update your persistent memory systems.

You have a limited turn budget. The efficient strategy is:
- Turn 1: issue all Read calls in parallel for every file you might update
- Turn 2: issue all Write/Edit calls in parallel

You MUST only use content from the messages to update your persistent memories. Do not waste any turns attempting to investigate or verify that content further.

If the user explicitly asks you to remember something, save it immediately as whichever type fits best. If they ask you to forget something, find and remove the relevant entry.
"""

    def __init__(
        self,
        memory_dir: Path,
        config: Optional[MemoryConfig] = None,
        llm_client: Optional[Any] = None,
    ):
        """
        初始化提取器。

        Args:
            memory_dir: memory 目录路径
            config: 配置对象
            llm_client: LLM 客户端
        """
        self.memory_dir = Path(memory_dir)
        self.config = config or MemoryConfig()
        self.llm_client = llm_client

        self.scanner = MemoryScanner(self.memory_dir, self.config)
        self.index = MemoryIndex(self.memory_dir, self.config)
        self.topic_manager = TopicManager(self.memory_dir, self.config)

        # 游标：记录上次处理的消息位置
        self._last_message_uuid: Optional[str] = None

    async def extract(
        self,
        messages: List[Dict[str, Any]],
        force: bool = False,
    ) -> ExtractResult:
        """
        从消息中提取记忆。

        Args:
            messages: 消息列表
            force: 是否强制提取（忽略游标）

        Returns:
            ExtractResult
        """
        if not messages:
            return ExtractResult(success=True)

        # 确定要处理的消息范围
        if force or not self._last_message_uuid:
            new_messages = messages
        else:
            # 找到游标位置之后的消息
            new_messages = []
            found_cursor = False
            for msg in messages:
                if not found_cursor:
                    if msg.get('uuid') == self._last_message_uuid:
                        found_cursor = True
                    continue
                new_messages.append(msg)

        if not new_messages:
            return ExtractResult(success=True)

        # 检查主对话是否已经写了记忆
        if self._has_memory_writes(new_messages):
            # 推进游标，跳过提取
            self._last_message_uuid = messages[-1].get('uuid')
            return ExtractResult(success=True)

        try:
            # 扫描现有记忆
            existing_headers = await self.scanner.scan()
            existing_manifest = format_memory_manifest(existing_headers)

            # 构建 prompt
            prompt = self._build_extract_prompt(
                len(new_messages),
                existing_manifest,
            )

            # 调用 LLM 提取记忆
            extracted = await self._call_llm_for_extraction(prompt, new_messages)

            # 保存提取的记忆
            files_written = []
            for memory in extracted:
                file_path = self.topic_manager.write_topic(
                    filename=memory['filename'],
                    name=memory['name'],
                    description=memory['description'],
                    memory_type=MemoryType.parse(memory['type']),
                    content=memory['content'],
                )
                files_written.append(str(file_path))

                # 更新索引
                self.index.add_entry(
                    title=memory['name'],
                    filename=memory['filename'] + '.md',
                    hook=memory['description'],
                )

            # 更新游标
            self._last_message_uuid = messages[-1].get('uuid')

            return ExtractResult(
                success=True,
                files_written=files_written,
                memories_saved=len(files_written),
            )
        except Exception as e:
            return ExtractResult(success=False, error=str(e))

    def _has_memory_writes(self, messages: List[Dict[str, Any]]) -> bool:
        """
        检查消息中是否有记忆写入操作。

        如果主对话已经写了记忆，跳过提取以避免重复。

        Args:
            messages: 消息列表

        Returns:
            是否有记忆写入
        """
        memory_dir_str = str(self.memory_dir)

        for msg in messages:
            if msg.get('role') != 'assistant':
                continue

            tool_uses = msg.get('tool_uses', [])
            for tool in tool_uses:
                if tool.get('name') in ('Write', 'Edit'):
                    file_path = tool.get('input', {}).get('file_path', '')
                    if memory_dir_str in file_path:
                        return True

        return False

    def _build_extract_prompt(
        self,
        message_count: int,
        existing_manifest: str,
    ) -> str:
        """
        构建提取 prompt。

        Args:
            message_count: 新消息数量
            existing_manifest: 现有记忆清单

        Returns:
            prompt 字符串
        """
        manifest_section = ""
        if existing_manifest:
            manifest_section = f"""
## Existing memory files

{existing_manifest}

Check this list before writing — update an existing file rather than creating a duplicate.
"""

        return f"""{self.EXTRACT_SYSTEM_PROMPT}

Analyze the most recent ~{message_count} messages above and use them to update your persistent memory systems.
{manifest_section}

{MEMORY_TYPES_DESCRIPTION}

{WHAT_NOT_TO_SAVE}

## How to save memories

Saving a memory is a two-step process:

**Step 1** — write the memory to its own file (e.g., `user_role.md`) using this frontmatter format:

```markdown
---
name: {{memory name}}
description: {{one-line description}}
type: {{user, feedback, project, reference}}
---

{{memory content}}
```

**Step 2** — add a pointer to that file in `MEMORY.md`. Each entry should be one line, under ~150 characters: `- [Title](file.md) — one-line hook`.

- `MEMORY.md` is always loaded into your conversation context — lines after 200 will be truncated, so keep the index concise
- Organize memory semantically by topic, not chronologically
- Update or remove memories that turn out to be wrong or outdated
- Do not write duplicate memories. First check if there is an existing memory you can update before writing a new one.
"""

    async def _call_llm_for_extraction(
        self,
        prompt: str,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        调用 LLM 进行记忆提取。

        Args:
            prompt: 系统 prompt
            messages: 消息列表

        Returns:
            提取的记忆列表
        """
        from .llm_client import get_llm_client, ModelTier

        client = self.llm_client or get_llm_client()

        # 格式化消息
        formatted_messages = []
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            if isinstance(content, list):
                # 处理多部分内容
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get('type') == 'text':
                        text_parts.append(part.get('text', ''))
                    elif isinstance(part, str):
                        text_parts.append(part)
                content = '\n'.join(text_parts)
            formatted_messages.append({"role": role, "content": content})

        try:
            # 调用 LLM
            response = await client.chat(
                messages=formatted_messages,
                system=prompt,
                tier=ModelTier.HELPER,
                max_tokens=2048,
            )

            # 解析响应，提取记忆
            return self._parse_extraction_response(response)
        except Exception as e:
            # 记录错误但不抛出，返回空列表
            import sys
            print(f"[memory] Extraction error: {e}", file=sys.stderr)
            return []

    def _parse_extraction_response(self, response: str) -> List[Dict[str, Any]]:
        """
        解析 LLM 的提取响应。

        Args:
            response: LLM 响应文本

        Returns:
            记忆列表
        """
        memories = []

        # 尝试解析 JSON
        import re
        import json

        # 查找 JSON 块
        json_pattern = r'\{[\s\S]*?"memories"[\s\S]*?\}'
        matches = re.findall(json_pattern, response)

        for match in matches:
            try:
                data = json.loads(match)
                if 'memories' in data:
                    for m in data['memories']:
                        memories.append({
                            'filename': m.get('filename', f"memory_{len(memories)}"),
                            'name': m.get('name', 'Unnamed'),
                            'description': m.get('description', ''),
                            'type': m.get('type', 'user'),
                            'content': m.get('content', ''),
                        })
            except json.JSONDecodeError:
                continue

        # 如果没找到 JSON，尝试解析纯文本格式
        if not memories:
            # 简单的格式：---\nname: xxx\n---\ncontent
            sections = response.split('---')
            for i in range(1, len(sections), 2):
                if i + 1 < len(sections):
                    header = sections[i]
                    content = sections[i + 1]

                    # 解析 header
                    name = ''
                    desc = ''
                    mtype = 'user'

                    for line in header.split('\n'):
                        line = line.strip()
                        if line.startswith('name:'):
                            name = line[5:].strip()
                        elif line.startswith('description:'):
                            desc = line[12:].strip()
                        elif line.startswith('type:'):
                            mtype = line[5:].strip()

                    if name:
                        memories.append({
                            'filename': name.lower().replace(' ', '_'),
                            'name': name,
                            'description': desc,
                            'type': mtype,
                            'content': content.strip(),
                        })

        return memories

    def extract_from_text(
        self,
        text: str,
        memory_type: Optional[MemoryType] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        从文本中手动提取记忆。

        这是一个简化的接口，用于手动触发记忆提取。

        Args:
            text: 文本内容
            memory_type: 记忆类型（可选）

        Returns:
            提取的记忆字典或 None
        """
        # 简单的关键词检测
        type_keywords = {
            MemoryType.USER: ['我是', '我是做', '我是做', '我的角色', '我负责'],
            MemoryType.FEEDBACK: ['不要', '别', '停止', '正确', '错误', '应该是'],
            MemoryType.PROJECT: ['项目', '截止', '发布', 'merge', 'freeze'],
            MemoryType.REFERENCE: ['linear', 'jira', 'slack', 'grafana', '文档'],
        }

        detected_type = memory_type
        if not detected_type:
            text_lower = text.lower()
            for mtype, keywords in type_keywords.items():
                for kw in keywords:
                    if kw.lower() in text_lower:
                        detected_type = mtype
                        break
                if detected_type:
                    break

        if not detected_type:
            detected_type = MemoryType.USER  # 默认类型

        # 生成文件名
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"memory_{timestamp}"

        return {
            'filename': filename,
            'name': f'Memory {timestamp}',
            'description': text[:100] + ('...' if len(text) > 100 else ''),
            'type': detected_type.value,
            'content': text,
        }


class ExtractMemoriesConfig:
    """记忆提取配置"""

    def __init__(self):
        self.enabled = True
        self.throttle_turns = 1  # 每 N 个 turn 执行一次提取
        self.max_turns = 5  # 最大 turn 数限制
        self.skip_transcript = True  # 是否跳过 transcript 写入


# 全局状态管理
class ExtractMemoriesState:
    """记忆提取状态管理"""

    def __init__(self):
        self._in_progress = False
        self._pending_context = None
        self._turns_since_extraction = 0
        self._last_message_uuid: Optional[str] = None

    def is_in_progress(self) -> bool:
        return self._in_progress

    def set_in_progress(self, value: bool):
        self._in_progress = value

    def get_last_uuid(self) -> Optional[str]:
        return self._last_message_uuid

    def set_last_uuid(self, uuid: str):
        self._last_message_uuid = uuid
