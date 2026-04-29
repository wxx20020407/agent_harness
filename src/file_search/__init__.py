"""
File Search Module - 文件搜索工具模块
=====================================

借鉴 Claude Code 的文件搜索系统，为 Agent 提供高效的文件搜索能力。

包含:
  - FileIndex: 模糊文件搜索（位图加速 + 核心评分）
  - GlobTool: 文件模式匹配（ripgrep 封装）
  - GrepTool: 文件内容搜索（ripgrep 封装）
  - FileScanner: 文件扫描器（git ls-files 优先）

用法:
    from file_search import FileIndex, GlobTool, GrepTool

    # 模糊搜索
    index = FileIndex()
    index.load_from_directory("/path/to/project")
    results = index.search("srutl", limit=10)

    # Glob 搜索
    files = glob_search("*.py", path="/project/src")

    # Grep 搜索
    matches = grep_search("TODO", path="/project", output_mode="content")
"""

from .file_index import FileIndex, SearchResult
from .glob_tool import glob_search, GlobResult
from .grep_tool import grep_search, GrepResult, GrepMode
from .scanner import FileScanner, ScanResult

__all__ = [
    # FileIndex
    'FileIndex',
    'SearchResult',

    # Glob
    'glob_search',
    'GlobResult',

    # Grep
    'grep_search',
    'GrepResult',
    'GrepMode',

    # Scanner
    'FileScanner',
    'ScanResult',
]

__version__ = '1.0.0'
