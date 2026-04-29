"""
# ==============================================================================
# MEMORY MANAGEMENT - Claude Code 三层自愈记忆架构
# ==============================================================================
# 本模块实现了 Claude Code 的三层记忆系统：
#
#   Layer 1: MEMORY.md 索引层 - 轻量级索引，常驻上下文窗口
#   Layer 2: Topic Files 知识层 - 按主题分散存储，按需加载
#   Layer 3: Transcript Grep 日志层 - JSONL 原始对话，仅 grep 检索
#
# Self-Healing 机制：
#   - extract_memories: 实时从对话中提取记忆
#   - auto_dream: 后台整理记忆（需要 agent runtime 支持）
#
# 来源: Claude Code v2.1.88 源码分析
#
# 当前状态说明：
#   - agent_harness 目前依赖外部 opencode runtime，不是真正的 agent runtime
#   - 自动触发功能（auto_dream）暂时无法完全实现
#   - 提供手动调用接口，后续可向 agent runtime 对齐
# ==============================================================================
"""

from .types import (
    MemoryType,
    MemoryHeader,
    MemoryConfig,
    MemoryEntry,
    MEMORY_TYPES_DESCRIPTION,
    WHAT_NOT_TO_SAVE,
    WHEN_TO_ACCESS,
    TRUSTING_RECALL,
)
from .config import (
    MemorySystemConfig,
    load_config,
    is_auto_memory_enabled,
    is_auto_dream_enabled,
    get_default_memory_dir,
    get_default_transcripts_dir,
)
from .index_layer import MemoryIndex, EntrypointTruncation
from .topic_layer import TopicFile, TopicManager
from .transcript_layer import TranscriptStore, TranscriptSearch, TranscriptEntry
from .scanner import MemoryScanner, format_memory_manifest
from .relevance import RelevanceFinder, RelevantMemory
from .extract import MemoryExtractor, ExtractResult
from .dream import MemoryDream, DreamResult
from .lock import ConsolidationLock
from .manager import MemoryManager, create_memory_manager
from .api import MemoryAPI, create_memory_api_routes
from .llm_client import (
    LLMClient,
    LLMConfig,
    ModelTier,
    load_llm_config,
    get_llm_client,
    call_llm,
    call_llm_json,
)

__all__ = [
    # Types
    'MemoryType',
    'MemoryHeader',
    'MemoryConfig',
    'MemoryEntry',

    # Config
    'MemorySystemConfig',
    'load_config',
    'is_auto_memory_enabled',
    'is_auto_dream_enabled',
    'get_default_memory_dir',
    'get_default_transcripts_dir',

    # Layers
    'MemoryIndex',
    'EntrypointTruncation',
    'TopicFile',
    'TopicManager',
    'TranscriptStore',
    'TranscriptSearch',
    'TranscriptEntry',

    # Operations
    'MemoryScanner',
    'format_memory_manifest',
    'RelevanceFinder',
    'RelevantMemory',
    'MemoryExtractor',
    'ExtractResult',
    'MemoryDream',
    'DreamResult',
    'ConsolidationLock',

    # High-level API
    'MemoryManager',
    'create_memory_manager',

    # REST API
    'MemoryAPI',
    'create_memory_api_routes',

    # LLM Client
    'LLMClient',
    'LLMConfig',
    'ModelTier',
    'load_llm_config',
    'get_llm_client',
    'call_llm',
    'call_llm_json',

    # Prompt sections
    'MEMORY_TYPES_DESCRIPTION',
    'WHAT_NOT_TO_SAVE',
    'WHEN_TO_ACCESS',
    'TRUSTING_RECALL',
]

__version__ = '1.0.0'
