"""
GrepTool - 文件内容搜索
=======================

使用 ripgrep 进行高效的文件内容搜索。

支持:
  - 正则表达式搜索
  - 三种输出模式：files_with_matches, content, count
  - 上下文行 (-A, -B, -C)
  - 分页
  - 文件类型过滤

用法:
    # 查找包含 "TODO" 的文件
    result = grep_search("TODO", output_mode="files_with_matches")

    # 查找包含 "def login" 的 Python 文件，显示内容
    result = grep_search("def login", type="py", output_mode="content")

    # 统计每个文件的匹配次数
    result = grep_search("error", output_mode="count")
"""

import os
import re
import subprocess
import asyncio
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum


class GrepMode(Enum):
    """Grep 输出模式"""
    FILES_WITH_MATCHES = "files_with_matches"  # 只返回文件名
    CONTENT = "content"                        # 返回匹配的内容行
    COUNT = "count"                            # 返回每个文件的匹配次数


@dataclass
class GrepResult:
    """Grep 搜索结果"""
    mode: GrepMode                           # 输出模式
    files: List[str]                         # 匹配的文件列表
    content: Optional[str]                   # 内容（content 模式）
    matches: int                             # 总匹配数
    files_with_matches: int                  # 匹配的文件数
    duration_ms: int                         # 搜索耗时
    truncated: bool                          # 是否被截断
    limit: Optional[int]                     # 应用的限制
    offset: int                              # 应用的偏移


# 默认限制
DEFAULT_HEAD_LIMIT = 250

# 要排除的版本控制目录
VCS_DIRECTORIES = ['.git', '.svn', '.hg', '.bzr', '.jj', '.sl']


def _check_rg_available() -> bool:
    """检查 ripgrep 是否可用"""
    try:
        result = subprocess.run(
            ['rg', '--version'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def grep_search(
    pattern: str,
    path: Optional[str] = None,
    output_mode: str = "files_with_matches",
    glob_pattern: Optional[str] = None,
    file_type: Optional[str] = None,
    case_insensitive: bool = False,
    context_before: int = 0,
    context_after: int = 0,
    context: Optional[int] = None,
    head_limit: int = DEFAULT_HEAD_LIMIT,
    offset: int = 0,
    multiline: bool = False,
) -> GrepResult:
    """
    在文件内容中搜索模式。

    Args:
        pattern: 搜索模式（正则表达式）
        path: 搜索路径，默认当前目录
        output_mode: 输出模式 (files_with_matches, content, count)
        glob_pattern: 文件 glob 过滤（如 *.py）
        file_type: 文件类型（如 py, js, rust）
        case_insensitive: 是否忽略大小写
        context_before: 显示匹配前 N 行
        context_after: 显示匹配后 N 行
        context: 显示匹配前后 N 行（优先于 before/after）
        head_limit: 返回结果数量限制，0 表示无限制
        offset: 跳过前 N 个结果
        multiline: 是否启用多行模式

    Returns:
        GrepResult 对象

    示例:
        # 查找所有包含 "TODO" 的文件
        result = grep_search("TODO")

        # 查找 Python 文件中的 "def test"
        result = grep_search("def test", type="py")

        # 显示匹配内容及上下文
        result = grep_search("error", output_mode="content", context=3)

        # 统计匹配次数
        result = grep_search("import", output_mode="count", type="py")
    """
    start_ms = int(time.time() * 1000)
    search_path = path or os.getcwd()

    # 解析输出模式
    mode = GrepMode(output_mode)

    # 检查 ripgrep 是否可用
    if _check_rg_available():
        raw_lines = _grep_with_rg(
            pattern=pattern,
            path=search_path,
            mode=mode,
            glob_pattern=glob_pattern,
            file_type=file_type,
            case_insensitive=case_insensitive,
            context_before=context_before,
            context_after=context_after,
            context=context,
            multiline=multiline,
        )
    else:
        raw_lines = _fallback_grep(
            pattern=pattern,
            path=search_path,
            mode=mode,
            glob_pattern=glob_pattern,
            case_insensitive=case_insensitive,
        )

    # 处理结果
    result = _process_results(
        raw_lines=raw_lines,
        mode=mode,
        head_limit=head_limit,
        offset=offset,
        start_ms=start_ms,
    )

    return result


def _grep_with_rg(
    pattern: str,
    path: str,
    mode: GrepMode,
    glob_pattern: Optional[str],
    file_type: Optional[str],
    case_insensitive: bool,
    context_before: int,
    context_after: int,
    context: Optional[int],
    multiline: bool,
) -> List[str]:
    """
    使用 ripgrep 进行内容搜索。
    """
    args = ['rg', '--hidden']

    # 排除版本控制目录
    for vcs_dir in VCS_DIRECTORIES:
        args.extend(['--glob', f'!{vcs_dir}'])

    # 限制行长度
    args.extend(['--max-columns', '500'])

    # 多行模式
    if multiline:
        args.extend(['-U', '--multiline-dotall'])

    # 大小写
    if case_insensitive:
        args.append('-i')

    # 输出模式
    if mode == GrepMode.FILES_WITH_MATCHES:
        args.append('-l')
    elif mode == GrepMode.COUNT:
        args.append('-c')

    # 行号（content 模式）
    if mode == GrepMode.CONTENT:
        args.append('-n')

    # 上下文
    if mode == GrepMode.CONTENT:
        if context is not None:
            args.extend(['-C', str(context)])
        else:
            if context_before > 0:
                args.extend(['-B', str(context_before)])
            if context_after > 0:
                args.extend(['-A', str(context_after)])

    # 模式（处理以 - 开头的模式）
    if pattern.startswith('-'):
        args.extend(['-e', pattern])
    else:
        args.append(pattern)

    # 文件类型
    if file_type:
        args.extend(['--type', file_type])

    # glob 模式
    if glob_pattern:
        # 处理多个 glob 模式
        patterns = _split_glob_pattern(glob_pattern)
        for gp in patterns:
            args.extend(['--glob', gp])

    try:
        result = subprocess.run(
            args,
            cwd=path,
            capture_output=True,
            text=True,
            timeout=60
        )

        # 返回码 0 = 找到匹配，1 = 没有匹配
        if result.returncode in (0, 1):
            lines = result.stdout.strip().split('\n')
            return [line for line in lines if line]

        # 错误
        return []

    except subprocess.TimeoutExpired:
        return []
    except Exception:
        return []


def _fallback_grep(
    pattern: str,
    path: str,
    mode: GrepMode,
    glob_pattern: Optional[str],
    case_insensitive: bool,
) -> List[str]:
    """
    回退方案：使用 Python 内置搜索。

    当 ripgrep 不可用时使用。
    """
    results = []

    # 编译正则
    flags = re.IGNORECASE if case_insensitive else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        return []

    # 遍历文件
    for root, dirs, files in os.walk(path):
        # 排除版本控制目录
        dirs[:] = [d for d in dirs if d not in VCS_DIRECTORIES]

        for filename in files:
            filepath = os.path.join(root, filename)

            # glob 过滤
            if glob_pattern and not _match_glob(filename, glob_pattern):
                continue

            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                matches = regex.findall(content)

                if not matches:
                    continue

                rel_path = os.path.relpath(filepath, path)

                if mode == GrepMode.FILES_WITH_MATCHES:
                    results.append(rel_path)
                elif mode == GrepMode.COUNT:
                    results.append(f"{rel_path}:{len(matches)}")
                else:  # CONTENT
                    for i, line in enumerate(content.split('\n'), 1):
                        if regex.search(line):
                            results.append(f"{rel_path}:{i}:{line}")

            except Exception:
                continue

    return results


def _split_glob_pattern(glob_pattern: str) -> List[str]:
    """拆分 glob 模式（处理逗号和空格分隔）"""
    patterns = []

    # 按空格分割
    for part in glob_pattern.split():
        # 如果包含大括号，不进一步分割
        if '{' in part and '}' in part:
            patterns.append(part)
        else:
            # 按逗号分割
            patterns.extend([p.strip() for p in part.split(',') if p.strip()])

    return patterns


def _match_glob(filename: str, pattern: str) -> bool:
    """简单的 glob 匹配"""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


def _process_results(
    raw_lines: List[str],
    mode: GrepMode,
    head_limit: int,
    offset: int,
    start_ms: int,
) -> GrepResult:
    """处理搜索结果"""
    total_lines = len(raw_lines)

    # 应用分页
    if head_limit > 0:
        truncated = total_lines > offset + head_limit
        lines = raw_lines[offset:offset + head_limit]
    else:
        truncated = False
        lines = raw_lines[offset:]

    end_ms = int(time.time() * 1000)

    if mode == GrepMode.FILES_WITH_MATCHES:
        return GrepResult(
            mode=mode,
            files=lines,
            content=None,
            matches=len(lines),
            files_with_matches=len(lines),
            duration_ms=end_ms - start_ms,
            truncated=truncated,
            limit=head_limit if head_limit > 0 else None,
            offset=offset,
        )

    elif mode == GrepMode.COUNT:
        # 解析计数
        total_matches = 0
        files_count = 0
        for line in lines:
            try:
                _, count = line.rsplit(':', 1)
                total_matches += int(count)
                files_count += 1
            except (ValueError, IndexError):
                continue

        return GrepResult(
            mode=mode,
            files=[],
            content='\n'.join(lines),
            matches=total_matches,
            files_with_matches=files_count,
            duration_ms=end_ms - start_ms,
            truncated=truncated,
            limit=head_limit if head_limit > 0 else None,
            offset=offset,
        )

    else:  # CONTENT
        # 统计文件数
        files_set = set()
        for line in lines:
            if ':' in line:
                filepath = line.split(':', 1)[0]
                files_set.add(filepath)

        return GrepResult(
            mode=mode,
            files=list(files_set),
            content='\n'.join(lines),
            matches=len(lines),
            files_with_matches=len(files_set),
            duration_ms=end_ms - start_ms,
            truncated=truncated,
            limit=head_limit if head_limit > 0 else None,
            offset=offset,
        )


async def grep_search_async(
    pattern: str,
    path: Optional[str] = None,
    output_mode: str = "files_with_matches",
    **kwargs
) -> GrepResult:
    """
    异步内容搜索。

    使用 asyncio.subprocess 避免阻塞事件循环。
    """
    # 简化实现：在线程池中运行同步版本
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: grep_search(pattern, path=path, output_mode=output_mode, **kwargs)
    )


# ==================== 便捷函数 ====================

def find_files_containing(text: str, path: Optional[str] = None, file_type: Optional[str] = None) -> List[str]:
    """
    查找包含指定文本的文件。

    Args:
        text: 要搜索的文本
        path: 搜索路径
        file_type: 文件类型

    Returns:
        文件路径列表
    """
    result = grep_search(
        pattern=text,
        path=path,
        output_mode="files_with_matches",
        file_type=file_type
    )
    return result.files


def count_matches(pattern: str, path: Optional[str] = None, file_type: Optional[str] = None) -> Dict[str, int]:
    """
    统计每个文件的匹配次数。

    Args:
        pattern: 搜索模式
        path: 搜索路径
        file_type: 文件类型

    Returns:
        {文件路径: 匹配次数} 字典
    """
    result = grep_search(
        pattern=pattern,
        path=path,
        output_mode="count",
        file_type=file_type
    )

    counts = {}
    if result.content:
        for line in result.content.split('\n'):
            if ':' in line:
                filepath, count = line.rsplit(':', 1)
                try:
                    counts[filepath] = int(count)
                except ValueError:
                    continue

    return counts
