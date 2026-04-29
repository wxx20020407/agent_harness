"""
FileIndex - 模糊文件搜索
========================

借鉴 Claude Code 的 FileIndex 实现，使用位图预过滤 + 核心评分算法。

核心原理：
1. 预处理阶段：为每个文件路径计算位图（包含哪些字母）
2. 搜索阶段：用位图快速排除不可能匹配的文件
3. 详细匹配：对候选文件进行模糊匹配并评分
4. 排序返回：按分数返回 top N 结果

评分规则：
- 基础分：每匹配一个字符 +16 分
- 连续加分：字符连续出现 +4 分
- 边界加分：在 / . _ - 等边界后 +8 分
- 驼峰加分：小写后大写 +6 分
- 首字符加分：第一个字符匹配 +8 分
- 间隔惩罚：字符间隔 = 起始扣3分 + 每隔1字符扣1分
"""

import os
import re
import time
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Tuple, Set
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import threading


# ============== 评分常量 ==============
SCORE_MATCH = 16           # 每个匹配字符的基础分
BONUS_BOUNDARY = 8         # 边界加分（在 / . _ - 后面）
BONUS_CAMEL = 6            # 驼峰加分（小写后大写）
BONUS_CONSECUTIVE = 4      # 连续匹配加分
BONUS_FIRST_CHAR = 8       # 首字符匹配加分
PENALTY_GAP_START = 3      # 间隔起始惩罚
PENALTY_GAP_EXTENSION = 1  # 间隔延续惩罚（每字符）

# 测试文件惩罚系数（测试文件排在后面）
TEST_FILE_PENALTY = 1.05

# 最大查询长度
MAX_QUERY_LEN = 64


@dataclass
class SearchResult:
    """搜索结果"""
    path: str          # 文件路径
    score: float       # 得分（0-1，越低越好）
    raw_score: int     # 原始得分（越高越好）


class FileIndex:
    """
    模糊文件搜索索引。

    核心思想：
    1. 用位图快速排除不可能匹配的文件（O(1) 操作）
    2. 对候选文件进行详细的模糊匹配评分
    3. 使用 top-k 堆避免全排序

    示例:
        index = FileIndex()
        index.load_from_directory("/path/to/project")

        # 模糊搜索
        results = index.search("srutl", limit=10)
        for r in results:
            print(f"{r.path} (score: {r.score:.3f})")
    """

    def __init__(self):
        """初始化索引"""
        self.paths: List[str] = []                    # 原始路径列表
        self.lower_paths: List[str] = []              # 小写路径列表
        self.char_bits: List[int] = []                # 每个路径的 a-z 位图
        self.path_lens: List[int] = []                # 路径长度
        self._ready_count = 0                         # 已索引的路径数
        self._lock = threading.Lock()                 # 线程锁
        self._is_loaded = False                       # 是否已加载

    # ==================== 核心方法 ====================

    def load_from_file_list(self, file_list: List[str]) -> None:
        """
        从文件列表加载索引。

        Args:
            file_list: 文件路径列表
        """
        with self._lock:
            # 去重
            seen: Set[str] = set()
            paths: List[str] = []
            for path in file_list:
                if path and path not in seen:
                    seen.add(path)
                    paths.append(path)

            self._build_index(paths)

    def load_from_directory(
        self,
        directory: str,
        ignore_patterns: Optional[List[str]] = None,
        use_git: bool = True
    ) -> int:
        """
        从目录加载索引。

        Args:
            directory: 目录路径
            ignore_patterns: 忽略模式列表
            use_git: 是否优先使用 git ls-files

        Returns:
            索引的文件数量
        """
        from .scanner import FileScanner

        scanner = FileScanner(directory)
        result = scanner.scan(use_git=use_git)

        self.load_from_file_list(result.files)
        return len(self.paths)

    async def load_from_directory_async(
        self,
        directory: str,
        use_git: bool = True
    ) -> int:
        """
        异步从目录加载索引。

        Args:
            directory: 目录路径
            use_git: 是否优先使用 git ls-files

        Returns:
            索引的文件数量
        """
        from .scanner import FileScanner

        scanner = FileScanner(directory)
        result = await scanner.scan_async(use_git=use_git)

        self.load_from_file_list(result.files)
        return len(self.paths)

    def search(self, query: str, limit: int = 15) -> List[SearchResult]:
        """
        模糊搜索文件。

        Args:
            query: 查询字符串
            limit: 返回结果数量限制

        Returns:
            SearchResult 列表，按分数排序（越低越好）
        """
        if limit <= 0 or not self.paths:
            return []

        # 空查询返回顶层目录
        if not query:
            return self._get_top_level_paths(limit)

        # 智能大小写：全小写 = 忽略大小写，有大写 = 区分大小写
        case_sensitive = query != query.lower()
        needle = query if case_sensitive else query.lower()
        n_len = min(len(needle), MAX_QUERY_LEN)

        # 计算查询的位图
        needle_chars = list(needle[:n_len])
        needle_bitmap = self._compute_bitmap(needle)

        # 预计算分数上限（用于提前剪枝）
        score_ceiling = n_len * (SCORE_MATCH + BONUS_BOUNDARY) + BONUS_FIRST_CHAR + 32

        # Top-k 堆
        top_k: List[Tuple[str, int]] = []
        threshold = float('-inf')

        ready_count = self._ready_count

        for i in range(ready_count):
            # === 第一步：位图快速排除 ===
            if (self.char_bits[i] & needle_bitmap) != needle_bitmap:
                continue

            # === 第二步：查找字符位置并计算间隔 ===
            haystack = self.paths[i] if case_sensitive else self.lower_paths[i]

            positions, gap_penalty, consec_bonus = self._find_positions(
                haystack, needle_chars, n_len
            )

            if positions is None:
                continue

            # === 第三步：提前剪枝检查 ===
            if len(top_k) == limit:
                best_possible = score_ceiling + consec_bonus - gap_penalty
                if best_possible <= threshold:
                    continue

            # === 第四步：详细评分 ===
            raw_score = self._compute_score(
                self.paths[i],
                positions,
                n_len,
                consec_bonus,
                gap_penalty,
                self.path_lens[i]
            )

            # === 第五步：维护 Top-K 堆 ===
            if len(top_k) < limit:
                top_k.append((self.paths[i], raw_score))
                if len(top_k) == limit:
                    top_k.sort(key=lambda x: x[1], reverse=True)
                    threshold = top_k[-1][1]
            elif raw_score > threshold:
                # 插入到正确位置
                inserted = False
                for j in range(len(top_k)):
                    if raw_score > top_k[j][1]:
                        top_k.insert(j, (self.paths[i], raw_score))
                        top_k.pop()
                        threshold = top_k[-1][1]
                        inserted = True
                        break
                if not inserted and len(top_k) < limit:
                    top_k.append((self.paths[i], raw_score))

        # === 第六步：转换为最终结果 ===
        top_k.sort(key=lambda x: x[1], reverse=True)

        results = []
        denom = max(len(top_k), 1)
        for rank, (path, raw_score) in enumerate(top_k):
            # 归一化分数：位置分数（0-1）
            position_score = rank / denom

            # 测试文件惩罚
            if 'test' in path.lower():
                position_score = min(position_score * TEST_FILE_PENALTY, 1.0)

            results.append(SearchResult(
                path=path,
                score=position_score,
                raw_score=raw_score
            ))

        return results

    # ==================== 内部方法 ====================

    def _build_index(self, paths: List[str]) -> None:
        """构建索引"""
        n = len(paths)
        self.paths = paths
        self.lower_paths = [''] * n
        self.char_bits = [0] * n
        self.path_lens = [0] * n

        for i, path in enumerate(paths):
            self._index_path(i)

        self._ready_count = n
        self._is_loaded = True

    def _index_path(self, i: int) -> None:
        """索引单个路径"""
        path = self.paths[i]
        lower_path = path.lower()

        self.lower_paths[i] = lower_path
        self.path_lens[i] = len(lower_path)
        self.char_bits[i] = self._compute_bitmap(lower_path)

    def _compute_bitmap(self, text: str) -> int:
        """
        计算字符串的 a-z 位图。

        位图的每一位表示一个字母是否存在：
        - 第 0 位 = 'a'
        - 第 1 位 = 'b'
        - ...
        - 第 25 位 = 'z'

        这样可以用一个整数表示字符串包含哪些字母。
        """
        bitmap = 0
        for char in text.lower():
            code = ord(char)
            if 97 <= code <= 122:  # a-z
                bitmap |= 1 << (code - 97)
        return bitmap

    def _find_positions(
        self,
        haystack: str,
        needle_chars: List[str],
        n_len: int
    ) -> Tuple[Optional[List[int]], int, int]:
        """
        查找每个 needle 字符在 haystack 中的位置。

        Returns:
            (positions, gap_penalty, consec_bonus)
            如果找不到所有字符，返回 (None, 0, 0)
        """
        positions = []
        gap_penalty = 0
        consec_bonus = 0
        prev_pos = -1

        for j, char in enumerate(needle_chars):
            # 从上一个匹配位置之后开始查找
            start = prev_pos + 1 if prev_pos >= 0 else 0
            pos = haystack.find(char, start)

            if pos == -1:
                return None, 0, 0

            positions.append(pos)

            if j > 0:
                gap = pos - prev_pos - 1
                if gap == 0:
                    consec_bonus += BONUS_CONSECUTIVE
                else:
                    gap_penalty += PENALTY_GAP_START + gap * PENALTY_GAP_EXTENSION

            prev_pos = pos

        return positions, gap_penalty, consec_bonus

    def _compute_score(
        self,
        path: str,
        positions: List[int],
        n_len: int,
        consec_bonus: int,
        gap_penalty: int,
        path_len: int
    ) -> int:
        """
        计算匹配分数。

        Args:
            path: 原始路径（保留大小写）
            positions: 匹配位置列表
            n_len: 查询长度
            consec_bonus: 连续加分
            gap_penalty: 间隔惩罚
            path_len: 路径长度

        Returns:
            分数（越高越好）
        """
        # 基础分
        score = n_len * SCORE_MATCH

        # 连续加分
        score += consec_bonus

        # 间隔惩罚
        score -= gap_penalty

        # 边界/驼峰加分
        for j, pos in enumerate(positions):
            is_first = (j == 0)
            score += self._boundary_bonus(path, pos, is_first)

        # 路径长度惩罚（越短越好）
        score += max(0, 32 - (path_len >> 2))

        return score

    def _boundary_bonus(self, path: str, pos: int, is_first: bool) -> int:
        """
        计算边界加分。

        边界字符：/ \ - _ . 空格

        Args:
            path: 原始路径
            pos: 匹配位置
            is_first: 是否是第一个匹配字符

        Returns:
            加分值
        """
        if pos == 0:
            return BONUS_FIRST_CHAR if is_first else 0

        prev_char = path[pos - 1]

        # 边界字符
        if prev_char in '/\\-_. ':
            return BONUS_BOUNDARY

        # 驼峰：前一个小写，当前大写
        if prev_char.islower() and path[pos].isupper():
            return BONUS_CAMEL

        return 0

    def _get_top_level_paths(self, limit: int) -> List[SearchResult]:
        """获取顶层路径（空查询时返回）"""
        seen: Set[str] = set()
        top_level: List[str] = []

        for path in self.paths:
            # 取第一级目录
            parts = path.split('/')
            if parts:
                first = parts[0]
                if first and first not in seen:
                    seen.add(first)
                    top_level.append(first)
                    if len(top_level) >= limit:
                        break

        return [SearchResult(path=p, score=0.0, raw_score=0) for p in top_level]

    # ==================== 工具方法 ====================

    def is_loaded(self) -> bool:
        """检查索引是否已加载"""
        return self._is_loaded

    def file_count(self) -> int:
        """返回索引的文件数量"""
        return len(self.paths)

    def clear(self) -> None:
        """清空索引"""
        with self._lock:
            self.paths = []
            self.lower_paths = []
            self.char_bits = []
            self.path_lens = []
            self._ready_count = 0
            self._is_loaded = False


# ==================== 便捷函数 ====================

def create_file_index(directory: str, use_git: bool = True) -> FileIndex:
    """
    创建并加载文件索引的便捷函数。

    Args:
        directory: 目录路径
        use_git: 是否使用 git ls-files

    Returns:
        已加载的 FileIndex 实例
    """
    index = FileIndex()
    index.load_from_directory(directory, use_git=use_git)
    return index
