#!/usr/bin/env python3
"""
文件搜索模块测试脚本
====================

测试 FileIndex、GlobTool、GrepTool 的功能。
"""

import os
import sys
import time

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from src.file_search import FileIndex, glob_search, grep_search, GrepMode, FileScanner


def test_file_scanner():
    """测试文件扫描器"""
    print("\n" + "=" * 60)
    print("测试 FileScanner")
    print("=" * 60)

    # 使用当前项目目录测试
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    scanner = FileScanner(project_root)
    result = scanner.scan(use_git=True)

    print(f"扫描方法: {result.method}")
    print(f"文件数量: {result.total}")
    print(f"耗时: {result.duration_ms}ms")

    if result.files:
        print(f"\n前 10 个文件:")
        for f in result.files[:10]:
            print(f"  - {f}")

    if result.directories:
        print(f"\n目录数量: {len(result.directories)}")
        print(f"前 5 个目录:")
        for d in result.directories[:5]:
            print(f"  - {d}/")


def test_file_index():
    """测试模糊文件搜索"""
    print("\n" + "=" * 60)
    print("测试 FileIndex")
    print("=" * 60)

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 创建索引
    print("构建索引...")
    start = time.time()
    index = FileIndex()
    count = index.load_from_directory(project_root, use_git=True)
    elapsed = time.time() - start

    print(f"索引文件数: {count}")
    print(f"构建耗时: {elapsed:.3f}s")

    # 测试搜索
    test_queries = [
        "srutl",      # 应该匹配 src/utils/...
        "test",       # 应该匹配测试文件
        "docling",    # 应该匹配 docling 相关文件
        "docker",     # 应该匹配 Docker 相关文件
        "api",        # 应该匹配 API 相关文件
    ]

    for query in test_queries:
        print(f"\n搜索 '{query}':")
        results = index.search(query, limit=5)
        for r in results:
            print(f"  [{r.score:.3f}] {r.path}")


def test_glob_search():
    """测试 Glob 搜索"""
    print("\n" + "=" * 60)
    print("测试 GlobTool")
    print("=" * 60)

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 测试不同的 glob 模式
    patterns = [
        "*.py",
        "*.md",
        "deploy/*",
        "src/**/*.py",
    ]

    for pattern in patterns:
        result = glob_search(pattern, path=project_root, limit=10)
        print(f"\n模式 '{pattern}':")
        print(f"  匹配数: {result.total}")
        print(f"  耗时: {result.duration_ms}ms")
        if result.files:
            for f in result.files[:5]:
                print(f"    - {f}")


def test_grep_search():
    """测试内容搜索"""
    print("\n" + "=" * 60)
    print("测试 GrepTool")
    print("=" * 60)

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 测试不同的搜索模式
    test_cases = [
        {
            "pattern": "def test",
            "type": "py",
            "mode": "files_with_matches",
            "desc": "查找包含 'def test' 的 Python 文件"
        },
        {
            "pattern": "TODO",
            "mode": "count",
            "desc": "统计 TODO 出现次数"
        },
        {
            "pattern": "import",
            "type": "py",
            "mode": "content",
            "limit": 5,
            "desc": "查看 import 语句"
        },
    ]

    for case in test_cases:
        print(f"\n{case['desc']}:")

        result = grep_search(
            pattern=case["pattern"],
            path=project_root,
            output_mode=case["mode"],
            file_type=case.get("type"),
            head_limit=case.get("limit", 10)
        )

        print(f"  耗时: {result.duration_ms}ms")
        print(f"  匹配文件数: {result.files_with_matches}")
        print(f"  总匹配数: {result.matches}")

        if case["mode"] == "files_with_matches" and result.files:
            print(f"  文件:")
            for f in result.files[:5]:
                print(f"    - {f}")

        if case["mode"] == "content" and result.content:
            print(f"  内容:")
            for line in result.content.split('\n')[:5]:
                print(f"    {line}")


def main():
    """主测试函数"""
    print("=" * 60)
    print("文件搜索模块测试")
    print("=" * 60)

    try:
        test_file_scanner()
        test_file_index()
        test_glob_search()
        test_grep_search()

        print("\n" + "=" * 60)
        print("所有测试完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
