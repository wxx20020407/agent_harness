"""
GlobTool - 文件模式匹配搜索
===========================

使用 ripgrep 进行高效的文件模式匹配搜索。

支持:
  - glob 模式匹配（如 *.py, src/**/*.js）
  - 按修改时间排序
  - 结果分页

用法:
    # 查找所有 Python 文件
    result = glob_search("*.py", path="/project")

    # 查找 src 目录下的所有 TypeScript 文件
    result = glob_search("src/**/*.ts", path="/project")

    # 分页
    result = glob_search("*.py", limit=50, offset=100)
"""

import os
import subprocess
import asyncio
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class GlobResult:
    """Glob 搜索结果"""
    files: List[str]          # 匹配的文件列表
    total: int                # 总匹配数
    duration_ms: int          # 搜索耗时（毫秒）
    truncated: bool           # 是否被截断
    limit: Optional[int]      # 应用的限制
    offset: int               # 应用的偏移


# 默认限制
DEFAULT_LIMIT = 100


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


def _fallback_glob(pattern: str, path: str) -> List[str]:
    """
    回退方案：使用 Python 内置的 glob 模块。

    当 ripgrep 不可用时使用。
    """
    import glob as glob_module

    full_pattern = os.path.join(path, pattern)
    return glob_module.glob(full_pattern, recursive=True)


def glob_search(
    pattern: str,
    path: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    respect_gitignore: bool = True,
    hidden: bool = False,
) -> GlobResult:
    """
    使用 glob 模式搜索文件。

    Args:
        pattern: glob 模式（如 *.py, src/**/*.ts）
        path: 搜索路径，默认当前目录
        limit: 返回结果数量限制，0 表示无限制
        offset: 跳过前 N 个结果
        respect_gitignore: 是否遵循 .gitignore
        hidden: 是否包含隐藏文件

    Returns:
        GlobResult 对象

    示例:
        # 查找所有 Python 文件
        result = glob_search("*.py")

        # 查找 src 下的所有 JS/TS 文件
        result = glob_search("src/**/*.{js,ts}")

        # 包含隐藏文件
        result = glob_search(".*", hidden=True)
    """
    start_time = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
    import time
    start_ms = int(time.time() * 1000)

    search_path = path or os.getcwd()

    # 检查 ripgrep 是否可用
    if _check_rg_available():
        files = _glob_with_rg(pattern, search_path, respect_gitignore, hidden)
    else:
        files = _fallback_glob(pattern, search_path)

    # 按修改时间排序
    files = _sort_by_mtime(files)

    total = len(files)
    truncated = False

    # 应用分页
    if limit > 0:
        if offset + limit < total:
            truncated = True
        files = files[offset:offset + limit]
    else:
        files = files[offset:]

    end_ms = int(time.time() * 1000)

    return GlobResult(
        files=files,
        total=total,
        duration_ms=end_ms - start_ms,
        truncated=truncated,
        limit=limit if limit > 0 else None,
        offset=offset
    )


def _glob_with_rg(
    pattern: str,
    path: str,
    respect_gitignore: bool,
    hidden: bool
) -> List[str]:
    """
    使用 ripgrep 进行 glob 搜索。

    ripgrep 的 --files --glob 组合可以高效地列出匹配模式的文件。
    """
    args = ['rg', '--files']

    # 添加 glob 模式
    args.extend(['--glob', pattern])

    # 隐藏文件
    if hidden:
        args.append('--hidden')

    # gitignore
    if not respect_gitignore:
        args.append('--no-ignore-vcs')

    # 排除版本控制目录
    for vcs_dir in ['.git', '.svn', '.hg', '.bzr', '.jj', '.sl']:
        args.extend(['--glob', f'!{vcs_dir}'])

    try:
        result = subprocess.run(
            args,
            cwd=path,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            files = result.stdout.strip().split('\n')
            return [f for f in files if f]

        # ripgrep 返回 1 表示没有匹配
        if result.returncode == 1:
            return []

        # 其他错误
        return _fallback_glob(pattern, path)

    except subprocess.TimeoutExpired:
        return _fallback_glob(pattern, path)
    except Exception:
        return _fallback_glob(pattern, path)


def _sort_by_mtime(files: List[str]) -> List[str]:
    """按修改时间排序（最新的在前）"""
    def get_mtime(f: str) -> float:
        try:
            return os.path.getmtime(f)
        except OSError:
            return 0

    # 获取修改时间并排序
    files_with_mtime = [(f, get_mtime(f)) for f in files]
    files_with_mtime.sort(key=lambda x: x[1], reverse=True)

    return [f for f, _ in files_with_mtime]


async def glob_search_async(
    pattern: str,
    path: Optional[str] = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    respect_gitignore: bool = True,
    hidden: bool = False,
) -> GlobResult:
    """
    异步 glob 搜索。

    使用 asyncio.subprocess 避免阻塞事件循环。
    """
    import time
    start_ms = int(time.time() * 1000)

    search_path = path or os.getcwd()

    # 检查 ripgrep 是否可用
    if _check_rg_available():
        files = await _glob_with_rg_async(pattern, search_path, respect_gitignore, hidden)
    else:
        files = _fallback_glob(pattern, search_path)

    # 按修改时间排序
    files = _sort_by_mtime(files)

    total = len(files)
    truncated = False

    # 应用分页
    if limit > 0:
        if offset + limit < total:
            truncated = True
        files = files[offset:offset + limit]
    else:
        files = files[offset:]

    end_ms = int(time.time() * 1000)

    return GlobResult(
        files=files,
        total=total,
        duration_ms=end_ms - start_ms,
        truncated=truncated,
        limit=limit if limit > 0 else None,
        offset=offset
    )


async def _glob_with_rg_async(
    pattern: str,
    path: str,
    respect_gitignore: bool,
    hidden: bool
) -> List[str]:
    """异步使用 ripgrep 进行 glob 搜索"""
    args = ['rg', '--files']

    args.extend(['--glob', pattern])

    if hidden:
        args.append('--hidden')

    if not respect_gitignore:
        args.append('--no-ignore-vcs')

    for vcs_dir in ['.git', '.svn', '.hg', '.bzr', '.jj', '.sl']:
        args.extend(['--glob', f'!{vcs_dir}'])

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=30
        )

        if proc.returncode == 0:
            files = stdout.decode().strip().split('\n')
            return [f for f in files if f]

        if proc.returncode == 1:
            return []

        return _fallback_glob(pattern, path)

    except asyncio.TimeoutError:
        return _fallback_glob(pattern, path)
    except Exception:
        return _fallback_glob(pattern, path)


# ==================== 便捷函数 ====================

def find_files_by_extension(extension: str, path: Optional[str] = None) -> List[str]:
    """
    按扩展名查找文件。

    Args:
        extension: 文件扩展名（如 py, js, ts）
        path: 搜索路径

    Returns:
        文件路径列表
    """
    if not extension.startswith('.'):
        extension = '.' + extension

    pattern = f'**/*{extension}'
    result = glob_search(pattern, path=path, limit=0)  # 无限制
    return result.files


def find_all_files(path: Optional[str] = None) -> List[str]:
    """
    列出所有文件。

    Args:
        path: 搜索路径

    Returns:
        文件路径列表
    """
    result = glob_search('**/*', path=path, limit=0)
    return result.files
