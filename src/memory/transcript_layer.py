"""
# ==============================================================================
# TRANSCRIPT LAYER - 日志层
# ==============================================================================
# 来源: claude-code-source-code/src/utils/sessionStorage.ts
#       claude-code-source-code/src/utils/transcriptSearch.ts
#
# 第三层记忆：JSONL 格式的原始对话记录。
#
# 特点：
#   - 从不完整回读到上下文，只通过 grep 精确检索
#   - 相当于只写不读的日志归档
#   - 仅在需要精确回溯时查询（如查找错误信息、特定标识符）
#
# 查询方式：
#   grep -rn "<narrow term>" /path/to/transcripts/ --include="*.jsonl"
# ==============================================================================
"""

import os
import json
import re
from pathlib import Path
from typing import List, Optional, Dict, Any, Iterator
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class TranscriptEntry:
    """
    单条对话记录。

    Attributes:
        uuid: 消息唯一标识
        role: 角色 (user/assistant/system)
        content: 消息内容
        timestamp: 时间戳
        session_id: 会话 ID
        tool_uses: 工具调用列表
        tool_results: 工具结果列表
    """
    uuid: str
    role: str
    content: str
    timestamp: Optional[datetime] = None
    session_id: Optional[str] = None
    tool_uses: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_jsonl(self) -> str:
        """转换为 JSONL 格式"""
        data = {
            'uuid': self.uuid,
            'role': self.role,
            'content': self.content,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'session_id': self.session_id,
            'tool_uses': self.tool_uses,
            'tool_results': self.tool_results,
        }
        return json.dumps(data, ensure_ascii=False)

    @classmethod
    def from_jsonl(cls, line: str) -> Optional['TranscriptEntry']:
        """从 JSONL 行解析"""
        try:
            data = json.loads(line)
            return cls(
                uuid=data.get('uuid', ''),
                role=data.get('role', ''),
                content=data.get('content', ''),
                timestamp=datetime.fromisoformat(data['timestamp']) if data.get('timestamp') else None,
                session_id=data.get('session_id'),
                tool_uses=data.get('tool_uses', []),
                tool_results=data.get('tool_results', []),
            )
        except Exception:
            return None


class TranscriptStore:
    """
    对话记录存储。

    以 JSONL 格式持久化对话记录，支持追加写入和 grep 检索。

    Example:
        store = TranscriptStore(Path("~/.claude/projects/my-project/sessions"))
        store.append("session-123", entry)
        entries = store.search("session-123", "error message")
    """

    def __init__(self, transcripts_dir: Path):
        """
        初始化存储。

        Args:
            transcripts_dir: transcript 文件目录
        """
        self.transcripts_dir = Path(transcripts_dir)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)

    def _get_transcript_path(self, session_id: str) -> Path:
        """获取会话的 transcript 文件路径"""
        return self.transcripts_dir / f"{session_id}.jsonl"

    def append(self, session_id: str, entry: TranscriptEntry) -> bool:
        """
        追加一条记录到 transcript 文件。

        Args:
            session_id: 会话 ID
            entry: 要追加的记录

        Returns:
            是否追加成功
        """
        try:
            file_path = self._get_transcript_path(session_id)
            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(entry.to_jsonl() + '\n')
            return True
        except Exception:
            return False

    def read_all(self, session_id: str) -> List[TranscriptEntry]:
        """
        读取会话的所有记录。

        Args:
            session_id: 会话 ID

        Returns:
            TranscriptEntry 列表
        """
        file_path = self._get_transcript_path(session_id)
        if not file_path.exists():
            return []

        entries = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = TranscriptEntry.from_jsonl(line)
                        if entry:
                            entries.append(entry)
        except Exception:
            pass

        return entries

    def read_tail(self, session_id: str, n: int = 100) -> List[TranscriptEntry]:
        """
        读取会话最近 N 条记录。

        Args:
            session_id: 会话 ID
            n: 要读取的条数

        Returns:
            TranscriptEntry 列表
        """
        all_entries = self.read_all(session_id)
        return all_entries[-n:]

    def get_mtime(self, session_id: str) -> Optional[datetime]:
        """
        获取 transcript 文件的最后修改时间。

        Args:
            session_id: 会话 ID

        Returns:
            最后修改时间
        """
        file_path = self._get_transcript_path(session_id)
        if not file_path.exists():
            return None
        try:
            mtime = os.path.getmtime(file_path)
            return datetime.fromtimestamp(mtime)
        except Exception:
            return None

    def list_sessions(self) -> List[str]:
        """
        列出所有会话 ID。

        Returns:
            会话 ID 列表
        """
        sessions = []
        for f in self.transcripts_dir.iterdir():
            if f.is_file() and f.suffix == '.jsonl':
                sessions.append(f.stem)
        return sorted(sessions)


class TranscriptSearch:
    """
    对话记录搜索器。

    提供 grep 风格的精确搜索功能。

    注意：不做语义匹配，只做精确字符串匹配。
    这是第三层记忆的核心设计：从不完整回读，只通过精确关键词检索。

    Example:
        searcher = TranscriptSearch(store)
        results = searcher.grep("error", max_results=50)
    """

    def __init__(self, store: TranscriptStore):
        """
        初始化搜索器。

        Args:
            store: TranscriptStore 实例
        """
        self.store = store

    def grep(
        self,
        pattern: str,
        session_ids: Optional[List[str]] = None,
        max_results: int = 50,
        case_sensitive: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        在 transcript 中搜索模式。

        模拟 grep -rn 的行为，返回匹配的记录片段。

        Args:
            pattern: 搜索模式（精确字符串）
            session_ids: 要搜索的会话 ID 列表，None 表示搜索所有
            max_results: 最大结果数
            case_sensitive: 是否区分大小写

        Returns:
            匹配结果列表，每项包含 {session_id, uuid, role, content, match_start, match_end}
        """
        if not pattern:
            return []

        results = []
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            regex = re.compile(re.escape(pattern), flags)
        except re.error:
            return []

        sessions = session_ids or self.store.list_sessions()

        for session_id in sessions:
            entries = self.store.read_all(session_id)

            for entry in entries:
                if len(results) >= max_results:
                    break

                # 在内容中搜索
                for match in regex.finditer(entry.content):
                    results.append({
                        'session_id': session_id,
                        'uuid': entry.uuid,
                        'role': entry.role,
                        'content': entry.content,
                        'match_start': match.start(),
                        'match_end': match.end(),
                        'matched_text': match.group(),
                    })

                    if len(results) >= max_results:
                        break

        return results

    def grep_in_session(
        self,
        session_id: str,
        pattern: str,
        max_results: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        在单个会话中搜索模式。

        Args:
            session_id: 会话 ID
            pattern: 搜索模式
            max_results: 最大结果数

        Returns:
            匹配结果列表
        """
        return self.grep(pattern, [session_id], max_results)

    def search_context_around(
        self,
        session_id: str,
        pattern: str,
        context_lines: int = 2,
    ) -> List[Dict[str, Any]]:
        """
        搜索并返回上下文。

        类似 grep -C 参数，返回匹配位置前后的消息。

        Args:
            session_id: 会话 ID
            pattern: 搜索模式
            context_lines: 前后消息数

        Returns:
            带上下文的结果列表
        """
        entries = self.store.read_all(session_id)
        results = []

        try:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        except re.error:
            return []

        for i, entry in enumerate(entries):
            if regex.search(entry.content):
                # 提取上下文
                start = max(0, i - context_lines)
                end = min(len(entries), i + context_lines + 1)

                context = []
                for j in range(start, end):
                    context.append({
                        'uuid': entries[j].uuid,
                        'role': entries[j].role,
                        'content': entries[j].content[:500],  # 截断内容
                        'is_match': j == i,
                    })

                results.append({
                    'session_id': session_id,
                    'match_index': i,
                    'context': context,
                })

        return results


def render_search_command(transcript_dir: Path, pattern: str) -> str:
    """
    生成 grep 命令供外部执行。

    这是第三层记忆推荐的使用方式：直接执行 shell grep，
    而不是在 Python 中加载和解析所有文件。

    Args:
        transcript_dir: transcript 目录路径
        pattern: 搜索模式

    Returns:
        grep 命令字符串
    """
    return f'grep -rn "{pattern}" {transcript_dir} --include="*.jsonl" | tail -50'
