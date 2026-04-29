"""
# ==============================================================================
# MEMORY DREAM - 后台记忆整理
# ==============================================================================
# 来源: claude-code-source-code/src/services/autoDream/autoDream.ts
#
# 用户空闲时，系统会 fork 一个子 agent 做"记忆整理"：
#   - 合并分散的观察
#   - 消除矛盾的记录
#   - 把模糊推断转为确定事实
#
# 触发条件：
#   - 时间门控：距离上次整理 >= min_hours（默认 24 小时）
#   - 会话门控：积累 >= min_sessions 个新会话（默认 5 个）
#   - 锁机制：无其他进程正在整理
#
# 重要：当前 agent_harness 不是真正的 agent runtime，
#       此模块提供手动调用接口，自动触发功能暂时无法实现。
# ==============================================================================
"""

import os
from pathlib import Path
from typing import Optional, List, Any
from datetime import datetime
from dataclasses import dataclass

from .types import MemoryConfig
from .scanner import MemoryScanner
from .index_layer import MemoryIndex
from .topic_layer import TopicManager
from .lock import ConsolidationLock


@dataclass
class DreamResult:
    """整理结果"""
    success: bool
    files_touched: List[str]
    sessions_reviewed: int
    error: Optional[str] = None


class MemoryDream:
    """
    后台记忆整理器。

    实现 Claude Code 的 autoDream 功能。

    Example:
        dream = MemoryDream(memory_dir, transcript_dir)
        result = await dream.run()
    """

    CONSOLIDATION_PROMPT_TEMPLATE = """# Dream: Memory Consolidation

You are performing a dream — a reflective pass over your memory files. Synthesize what you've learned recently into durable, well-organized memories so that future sessions can orient quickly.

Memory directory: `{memory_dir}`

---

## Phase 1 — Orient

- `ls` the memory directory to see what already exists
- Read `MEMORY.md` to understand the current index
- Skim existing topic files so you improve them rather than creating duplicates

## Phase 2 — Gather recent signal

Look for new information worth persisting. Sources in rough priority order:

1. **Daily logs** (`logs/YYYY/MM/YYYY-MM-DD.md`) if present — these are the append-only stream
2. **Existing memories that drifted** — facts that contradict something you see in the codebase now
3. **Transcript search** — if you need specific context, grep the JSONL transcripts for narrow terms

Don't exhaustively read transcripts. Look only for things you already suspect matter.

## Phase 3 — Consolidate

For each thing worth remembering, write or update a memory file at the top level of the memory directory.

Focus on:
- Merging new signal into existing topic files rather than creating near-duplicates
- Converting relative dates ("yesterday", "last week") to absolute dates so they remain interpretable after time passes
- Deleting contradicted facts — if today's investigation disproves an old memory, fix it at the source

## Phase 4 — Prune and index

Update `MEMORY.md` so it stays under 200 lines AND under ~25KB. It's an **index**, not a dump — each entry should be one line under ~150 characters: `- [Title](file.md) — one-line hook`.

- Remove pointers to memories that are now stale, wrong, or superseded
- Demote verbose entries: if an index line is over ~200 chars, shorten the line, move the detail
- Add pointers to newly important memories
- Resolve contradictions — if two files disagree, fix the wrong one

---

Return a brief summary of what you consolidated, updated, or pruned. If nothing changed (memories are already tight), say so.
"""

    def __init__(
        self,
        memory_dir: Path,
        transcript_dir: Optional[Path] = None,
        config: Optional[MemoryConfig] = None,
        llm_client: Optional[Any] = None,
    ):
        """
        初始化整理器。

        Args:
            memory_dir: memory 目录路径
            transcript_dir: transcript 目录路径
            config: 配置对象
            llm_client: LLM 客户端
        """
        self.memory_dir = Path(memory_dir)
        self.transcript_dir = transcript_dir
        self.config = config or MemoryConfig()
        self.llm_client = llm_client

        self.lock = ConsolidationLock(self.memory_dir)
        self.scanner = MemoryScanner(self.memory_dir, self.config)
        self.index = MemoryIndex(self.memory_dir, self.config)
        self.topic_manager = TopicManager(self.memory_dir, self.config)

        # 上次扫描时间（用于节流）
        self._last_session_scan = 0

    async def should_run(self) -> bool:
        """
        检查是否应该运行整理。

        Returns:
            是否满足触发条件
        """
        # 检查时间门控
        last_consolidated = await self.lock.read_last_consolidated()
        hours_since = (datetime.now().timestamp() - last_consolidated) / 3600

        if hours_since < self.config.dream_min_hours:
            return False

        # 检查会话门控（需要 transcript 目录）
        if self.transcript_dir:
            sessions = self._list_sessions_touched_since(last_consolidated)
            if len(sessions) < self.config.dream_min_sessions:
                return False

        # 检查锁
        if await self.lock.is_locked():
            return False

        return True

    async def run(
        self,
        session_ids: Optional[List[str]] = None,
        extra_context: Optional[str] = None,
    ) -> DreamResult:
        """
        运行记忆整理。

        Args:
            session_ids: 要审查的会话 ID 列表
            extra_context: 额外的上下文信息

        Returns:
            DreamResult
        """
        files_touched = []

        try:
            # 尝试获取锁
            prior_mtime = await self.lock.try_acquire()
            if prior_mtime is None:
                return DreamResult(
                    success=False,
                    files_touched=[],
                    sessions_reviewed=0,
                    error="Another consolidation is in progress",
                )

            # 构建 prompt
            prompt = self._build_prompt(session_ids or [], extra_context)

            # 调用 LLM 进行整理
            result = await self._call_llm_for_consolidation(prompt)

            # 记录成功
            await self.lock.record_consolidation()

            return DreamResult(
                success=True,
                files_touched=files_touched,
                sessions_reviewed=len(session_ids) if session_ids else 0,
            )
        except Exception as e:
            # 回滚锁
            await self.lock.rollback()
            return DreamResult(
                success=False,
                files_touched=files_touched,
                sessions_reviewed=0,
                error=str(e),
            )

    def _build_prompt(
        self,
        session_ids: List[str],
        extra_context: Optional[str] = None,
    ) -> str:
        """
        构建整理 prompt。

        Args:
            session_ids: 会话 ID 列表
            extra_context: 额外上下文

        Returns:
            prompt 字符串
        """
        prompt = self.CONSOLIDATION_PROMPT_TEMPLATE.format(
            memory_dir=self.memory_dir,
        )

        # 添加工具约束说明
        tool_constraints = """

**Tool constraints for this run:** Bash is restricted to read-only commands (`ls`, `find`, `grep`, `cat`, `stat`, `wc`, `head`, `tail`, and similar). Anything that writes, redirects to a file, or modifies state will be denied."""

        # 添加会话列表
        if session_ids:
            tool_constraints += f"\n\nSessions since last consolidation ({len(session_ids)}):\n"
            for sid in session_ids:
                tool_constraints += f"- {sid}\n"

        if extra_context:
            tool_constraints += f"\n\n## Additional context\n\n{extra_context}"

        return prompt + tool_constraints

    async def _call_llm_for_consolidation(self, prompt: str) -> str:
        """
        调用 LLM 进行记忆整理。

        Args:
            prompt: 系统 prompt

        Returns:
            LLM 响应
        """
        from .llm_client import get_llm_client, ModelTier

        client = self.llm_client or get_llm_client()

        try:
            # 调用 LLM（使用辅助模型）
            response = await client.chat(
                messages=[{"role": "user", "content": "Please perform the memory consolidation as described above."}],
                system=prompt,
                tier=ModelTier.HELPER,
                max_tokens=4096,  # 整理任务可能需要更多输出
            )

            return response
        except Exception as e:
            import sys
            print(f"[memory] Consolidation error: {e}", file=sys.stderr)
            return ""

    def _list_sessions_touched_since(self, since_timestamp: float) -> List[str]:
        """
        列出自指定时间以来被修改的会话。

        Args:
            since_timestamp: 时间戳

        Returns:
            会话 ID 列表
        """
        if not self.transcript_dir or not self.transcript_dir.exists():
            return []

        sessions = []
        for f in self.transcript_dir.iterdir():
            if f.is_file() and f.suffix == '.jsonl':
                mtime = f.stat().st_mtime
                if mtime > since_timestamp:
                    sessions.append(f.stem)

        return sessions


class AutoDreamScheduler:
    """
    自动整理调度器。

    注意：在当前 agent_harness 架构中，这需要外部触发。
    未来向 agent runtime 对齐后，可以实现自动触发。
    """

    def __init__(
        self,
        dream: MemoryDream,
        config: Optional[MemoryConfig] = None,
    ):
        """
        初始化调度器。

        Args:
            dream: MemoryDream 实例
            config: 配置对象
        """
        self.dream = dream
        self.config = config or MemoryConfig()
        self._last_scan_time = 0

    async def check_and_run(self) -> Optional[DreamResult]:
        """
        检查条件并运行整理（如果满足）。

        Returns:
            DreamResult 或 None（如果未触发）
        """
        # 时间门控
        last = await self.dream.lock.read_last_consolidated()
        hours_since = (datetime.now().timestamp() - last) / 3600

        if hours_since < self.config.dream_min_hours:
            return None

        # 会话门控
        sessions = self.dream._list_sessions_touched_since(last)
        if len(sessions) < self.config.dream_min_sessions:
            return None

        # 运行整理
        return await self.dream.run(sessions)


def build_consolidation_prompt(
    memory_root: str,
    transcript_dir: str,
    extra: str = "",
) -> str:
    """
    构建整理 prompt 的便捷函数。

    Args:
        memory_root: memory 目录路径
        transcript_dir: transcript 目录路径
        extra: 额外内容

    Returns:
        prompt 字符串
    """
    return MemoryDream.CONSOLIDATION_PROMPT_TEMPLATE.format(
        memory_dir=memory_root,
    ) + (f"\n\n## Additional context\n\n{extra}" if extra else "")
