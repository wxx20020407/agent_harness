"""
# ==============================================================================
# CONSOLIDATION LOCK - 整理锁机制
# ==============================================================================
# 来源: claude-code-source-code/src/services/autoDream/consolidationLock.ts
#
# 锁文件用于防止多个进程同时进行记忆整理。
#
# 锁文件特性：
#   - 位置：memory 目录下的 .consolidate-lock
#   - 内容：持有锁的进程 PID
#   - mtime：表示上次整理时间
#
# 锁获取策略：
#   1. 检查锁文件是否存在
#   2. 检查持有者进程是否还在运行
#   3. 如果进程已死或锁过期（> 1小时），重 claim
#   4. 写入自己的 PID，验证竞态条件
# ==============================================================================
"""

import os
import time
from pathlib import Path
from datetime import datetime
from typing import Optional


class ConsolidationLock:
    """
    整理锁管理器。

    使用文件锁防止多个进程同时进行记忆整理。

    Example:
        lock = ConsolidationLock(Path("~/.claude/projects/my-project/memory"))
        prior_mtime = await lock.try_acquire()
        if prior_mtime is not None:
            # 获取锁成功，执行整理
            ...
            # 完成后记录
            lock.record_consolidation()
    """

    LOCK_FILE = ".consolidate-lock"
    HOLDER_STALE_MS = 60 * 60 * 1000  # 1 小时过期

    def __init__(self, memory_dir: Path):
        """
        初始化锁管理器。

        Args:
            memory_dir: memory 目录路径
        """
        self.memory_dir = Path(memory_dir)
        self.lock_path = self.memory_dir / self.LOCK_FILE

    def _ensure_dir(self):
        """确保 memory 目录存在"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    async def read_last_consolidated(self) -> float:
        """
        读取上次整理时间。

        Returns:
            时间戳（毫秒），如果锁文件不存在返回 0
        """
        if not self.lock_path.exists():
            return 0.0

        try:
            mtime = self.lock_path.stat().st_mtime
            return mtime * 1000
        except Exception:
            return 0.0

    async def is_locked(self) -> bool:
        """
        检查锁是否被持有。

        Returns:
            是否被锁定
        """
        if not self.lock_path.exists():
            return False

        try:
            # 读取持有者 PID
            with open(self.lock_path, 'r') as f:
                content = f.read().strip()
                holder_pid = int(content) if content else None

            # 检查 mtime
            mtime = self.lock_path.stat().st_mtime
            age_ms = (time.time() - mtime) * 1000

            # 如果锁已过期，不算锁定
            if age_ms > self.HOLDER_STALE_MS:
                return False

            # 检查进程是否还在运行
            if holder_pid and self._is_process_running(holder_pid):
                return True

            return False
        except Exception:
            return False

    async def try_acquire(self) -> Optional[float]:
        """
        尝试获取锁。

        Returns:
            获取锁之前的时间戳，如果被其他进程持有返回 None
        """
        self._ensure_dir()

        prior_mtime_ms = None

        # 检查现有锁
        if self.lock_path.exists():
            try:
                stat = self.lock_path.stat()
                mtime_ms = stat.st_mtime * 1000

                with open(self.lock_path, 'r') as f:
                    content = f.read().strip()
                    holder_pid = int(content) if content else None

                # 检查是否过期或进程已死
                age_ms = (time.time() * 1000) - mtime_ms

                if age_ms < self.HOLDER_STALE_MS:
                    if holder_pid and self._is_process_running(holder_pid):
                        # 被活跃进程持有
                        return None

                prior_mtime_ms = mtime_ms
            except Exception:
                pass

        # 写入自己的 PID
        try:
            self._ensure_dir()
            with open(self.lock_path, 'w') as f:
                f.write(str(os.getpid()))

            # 验证竞态条件
            with open(self.lock_path, 'r') as f:
                content = f.read().strip()
                verify_pid = int(content) if content else None

            if verify_pid != os.getpid():
                # 输给了竞态条件
                return None

            return prior_mtime_ms if prior_mtime_ms is not None else 0.0
        except Exception:
            return None

    async def rollback(self, prior_mtime: Optional[float] = None):
        """
        回滚锁到之前的状态。

        用于整理失败时恢复锁的时间戳。

        Args:
            prior_mtime: 之前的时间戳
        """
        try:
            if prior_mtime is None or prior_mtime == 0:
                # 删除锁文件
                if self.lock_path.exists():
                    os.remove(self.lock_path)
            else:
                # 恢复 mtime
                with open(self.lock_path, 'w') as f:
                    f.write('')
                # 设置 mtime
                mtime_sec = prior_mtime / 1000
                os.utime(self.lock_path, (mtime_sec, mtime_sec))
        except Exception:
            pass

    async def record_consolidation(self):
        """
        记录整理完成。

        更新锁文件的 mtime 为当前时间。
        """
        try:
            self._ensure_dir()
            with open(self.lock_path, 'w') as f:
                f.write(str(os.getpid()))
        except Exception:
            pass

    def _is_process_running(self, pid: int) -> bool:
        """
        检查进程是否在运行。

        Args:
            pid: 进程 ID

        Returns:
            是否在运行
        """
        try:
            # 发送信号 0 检查进程是否存在
            os.kill(pid, 0)
            return True
        except OSError:
            return False


async def list_sessions_touched_since(
    sessions_dir: Path,
    since_ms: float,
) -> list:
    """
    列出自指定时间以来被修改的会话。

    Args:
        sessions_dir: 会话目录
        since_ms: 时间戳（毫秒）

    Returns:
        会话 ID 列表
    """
    if not sessions_dir.exists():
        return []

    sessions = []
    since_sec = since_ms / 1000

    for f in sessions_dir.iterdir():
        if f.is_file() and f.suffix == '.jsonl':
            try:
                mtime = f.stat().st_mtime
                if mtime > since_sec:
                    sessions.append(f.stem)
            except Exception:
                continue

    return sessions
