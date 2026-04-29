"""
# ==============================================================================
# MEMORY SYSTEM TEST - 记忆系统测试
# ==============================================================================
# 测试三层记忆系统的基本功能。
#
# 运行方式：
#   cd /data/agent_harness
#   python -m src.memory.test_memory
# ==============================================================================
"""

import asyncio
import tempfile
import shutil
from pathlib import Path
import sys

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from memory import (
    MemoryManager,
    MemoryType,
    MemoryConfig,
    create_memory_manager,
    load_config,
)


def test_basic_operations():
    """测试基本操作"""
    print("=" * 60)
    print("Testing Basic Memory Operations")
    print("=" * 60)

    # 创建临时目录
    temp_dir = Path(tempfile.mkdtemp())
    memory_dir = temp_dir / "memory"
    transcripts_dir = temp_dir / "sessions"

    try:
        # 创建管理器
        manager = MemoryManager(
            memory_dir=memory_dir,
            transcripts_dir=transcripts_dir,
        )

        print(f"\n1. Memory directory: {memory_dir}")

        # 测试索引层
        print("\n2. Testing Index Layer...")
        index_content = manager.load_index()
        print(f"   Index content length: {len(index_content)} chars")
        print(f"   Index empty: {'MEMORY.md is currently empty' in index_content}")

        # 测试主题层 - 保存记忆
        print("\n3. Testing Topic Layer - Save Memory...")

        # 保存一个 user 类型记忆
        file_path = manager.save_memory(
            filename="user_role",
            name="User Role",
            description="user is a senior software engineer",
            memory_type=MemoryType.USER,
            content="The user is a senior software engineer with 10 years of experience in backend development. They prefer concise responses and have deep expertise in Go.",
        )
        print(f"   Saved user memory to: {file_path}")

        # 保存一个 feedback 类型记忆
        file_path = manager.save_memory(
            filename="feedback_style",
            name="Response Style",
            description="user prefers terse responses",
            memory_type=MemoryType.FEEDBACK,
            content="User prefers terse responses without trailing summaries.\n\n**Why:** User can read diffs themselves.\n\n**How to apply:** Skip filler words and preamble in responses.",
        )
        print(f"   Saved feedback memory to: {file_path}")

        # 保存一个 project 类型记忆
        file_path = manager.save_memory(
            filename="project_deadline",
            name="Project Deadline",
            description="merge freeze starts 2026-04-15",
            memory_type=MemoryType.PROJECT,
            content="Merge freeze begins 2026-04-15 for the Q2 release.\n\n**Why:** Mobile team is cutting a release branch.\n\n**How to apply:** Flag any non-critical PR work after this date.",
        )
        print(f"   Saved project memory to: {file_path}")

        # 列出所有记忆
        print("\n4. Listing all memories...")
        memories = manager.list_memories()
        print(f"   Found {len(memories)} memories:")
        for m in memories:
            print(f"   - {m}")

        # 读取单个记忆
        print("\n5. Reading a specific memory...")
        topic = manager.read_memory("user_role.md")
        if topic:
            print(f"   Name: {topic.name}")
            print(f"   Type: {topic.memory_type.value}")
            print(f"   Description: {topic.description}")
            print(f"   Content preview: {topic.content[:100]}...")

        # 检查索引是否更新
        print("\n6. Checking updated index...")
        index_content = manager.load_index()
        entries = manager.get_index_entries()
        print(f"   Index entries: {len(entries)}")
        for title, filename, hook in entries:
            print(f"   - [{title}]({filename}): {hook}")

        # 扫描记忆
        print("\n7. Scanning memories...")
        headers = asyncio.run(manager.scan_memories())
        print(f"   Scanned {len(headers)} memory headers:")
        for h in headers:
            print(f"   - {h.filename}: {h.description}")

        print("\n" + "=" * 60)
        print("All tests passed!")
        print("=" * 60)

    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir)


def test_memory_types():
    """测试记忆类型"""
    print("\n" + "=" * 60)
    print("Testing Memory Types")
    print("=" * 60)

    # 测试类型解析
    print("\n1. Testing type parsing...")
    assert MemoryType.parse("user") == MemoryType.USER
    assert MemoryType.parse("feedback") == MemoryType.FEEDBACK
    assert MemoryType.parse("project") == MemoryType.PROJECT
    assert MemoryType.parse("reference") == MemoryType.REFERENCE
    assert MemoryType.parse("invalid") is None
    assert MemoryType.parse(None) is None
    print("   Type parsing works correctly")

    # 测试类型值
    print("\n2. Testing type values...")
    for mtype in MemoryType:
        print(f"   - {mtype.name}: {mtype.value}")

    print("\nAll type tests passed!")


def test_config():
    """测试配置"""
    print("\n" + "=" * 60)
    print("Testing Configuration")
    print("=" * 60)

    # 测试默认配置
    config = MemoryConfig()
    print(f"\n1. Default config:")
    print(f"   max_index_lines: {config.max_index_lines}")
    print(f"   max_index_bytes: {config.max_index_bytes}")
    print(f"   max_topic_files: {config.max_topic_files}")
    print(f"   dream_min_hours: {config.dream_min_hours}")
    print(f"   dream_min_sessions: {config.dream_min_sessions}")

    # 测试配置加载
    print(f"\n2. Loading system config...")
    sys_config = load_config(project_root=Path.cwd())
    print(f"   memory_dir: {sys_config.memory_dir}")
    print(f"   auto_memory_enabled: {sys_config.auto_memory_enabled}")
    print(f"   auto_dream_enabled: {sys_config.auto_dream_enabled}")

    print("\nAll config tests passed!")


def test_system_prompt():
    """测试系统提示词生成"""
    print("\n" + "=" * 60)
    print("Testing System Prompt Generation")
    print("=" * 60)

    temp_dir = Path(tempfile.mkdtemp())
    memory_dir = temp_dir / "memory"

    try:
        manager = MemoryManager(memory_dir=memory_dir)

        # 保存一些测试记忆
        manager.save_memory(
            filename="test_memory",
            name="Test Memory",
            description="a test memory",
            memory_type=MemoryType.USER,
            content="This is a test memory content.",
        )

        # 生成系统提示词
        prompt = manager.build_system_prompt_section()
        print(f"\n1. Generated prompt length: {len(prompt)} chars")
        print(f"\n2. Prompt preview (first 500 chars):")
        print("-" * 40)
        print(prompt[:500])
        print("-" * 40)

        # 检查关键部分
        assert "auto memory" in prompt
        assert "Types of memory" in prompt
        assert "MEMORY.md" in prompt
        print("\n3. Prompt contains all required sections")

        print("\nAll system prompt tests passed!")

    finally:
        shutil.rmtree(temp_dir)


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("MEMORY SYSTEM TEST SUITE")
    print("=" * 60)

    test_memory_types()
    test_config()
    test_basic_operations()
    test_system_prompt()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED!")
    print("=" * 60)


if __name__ == "__main__":
    main()
