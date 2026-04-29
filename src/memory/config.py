"""
# ==============================================================================
# MEMORY CONFIG - 记忆系统配置
# ==============================================================================
# 从环境变量和配置文件加载记忆系统配置。
#
# 环境变量：
#   CLAUDE_CODE_DISABLE_AUTO_MEMORY - 禁用自动记忆功能
#   CLAUDE_MEMORY_DIR              - 自定义记忆目录路径
#   CLAUDE_TRANSCRIPTS_DIR         - 自定义 transcripts 目录路径
# ==============================================================================
"""

import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from .types import MemoryConfig


@dataclass
class MemorySystemConfig:
    """
    记忆系统完整配置。

    包含路径配置、功能开关、性能参数等。
    """
    # 路径配置
    memory_dir: Path
    transcripts_dir: Optional[Path] = None

    # 功能开关
    auto_memory_enabled: bool = True
    auto_dream_enabled: bool = False  # 默认关闭，需要 agent runtime

    # 记忆配置
    memory_config: MemoryConfig = field(default_factory=MemoryConfig)

    # LLM 配置
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: str = "sonnet"  # 使用轻量级模型进行记忆选择


def get_default_memory_dir(project_root: Optional[Path] = None) -> Path:
    """
    获取默认的记忆目录路径。

    优先级：
    1. CLAUDE_MEMORY_DIR 环境变量
    2. 项目根目录下的 .claude/memory
    3. 用户主目录下的 ~/.claude/projects/<project-slug>/memory

    Args:
        project_root: 项目根目录

    Returns:
        记忆目录路径
    """
    # 检查环境变量
    env_dir = os.environ.get('CLAUDE_MEMORY_DIR')
    if env_dir:
        return Path(env_dir)

    # 使用项目根目录
    if project_root:
        return project_root / ".claude" / "memory"

    # 默认使用当前工作目录
    return Path.cwd() / ".claude" / "memory"


def get_default_transcripts_dir(project_root: Optional[Path] = None) -> Path:
    """
    获取默认的 transcripts 目录路径。

    Args:
        project_root: 项目根目录

    Returns:
        transcripts 目录路径
    """
    env_dir = os.environ.get('CLAUDE_TRANSCRIPTS_DIR')
    if env_dir:
        return Path(env_dir)

    if project_root:
        return project_root / ".claude" / "sessions"

    return Path.cwd() / ".claude" / "sessions"


def load_config(
    project_root: Optional[Path] = None,
    team_id: Optional[str] = None,
) -> MemorySystemConfig:
    """
    加载记忆系统配置。

    Args:
        project_root: 项目根目录
        team_id: 团队 ID（用于多团队场景）

    Returns:
        MemorySystemConfig 实例
    """
    # 确定路径
    if team_id and project_root:
        memory_dir = project_root / "teams" / team_id / ".claude" / "memory"
        transcripts_dir = project_root / "teams" / team_id / ".claude" / "sessions"
    else:
        memory_dir = get_default_memory_dir(project_root)
        transcripts_dir = get_default_transcripts_dir(project_root)

    # 检查功能开关
    disable_auto_memory = os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY', '').lower() in ('1', 'true')

    # 加载 LLM 配置
    llm_base_url = os.environ.get('LLM_BASE_URL')
    llm_api_key = os.environ.get('LLM_API_KEY')

    return MemorySystemConfig(
        memory_dir=memory_dir,
        transcripts_dir=transcripts_dir,
        auto_memory_enabled=not disable_auto_memory,
        auto_dream_enabled=False,  # 当前 agent_harness 不支持自动触发
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
    )


def is_auto_memory_enabled() -> bool:
    """
    检查自动记忆功能是否启用。

    Returns:
        是否启用
    """
    return os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY', '').lower() not in ('1', 'true')


def is_auto_dream_enabled() -> bool:
    """
    检查自动整理功能是否启用。

    注意：在当前 agent_harness 架构中，此功能返回 False。

    Returns:
        是否启用
    """
    # 当前不支持自动触发
    return False


# =============================================================================
# 配置验证
# =============================================================================

def validate_config(config: MemorySystemConfig) -> list:
    """
    验证配置是否有效。

    Args:
        config: 配置对象

    Returns:
        错误消息列表（空列表表示验证通过）
    """
    errors = []

    # 检查目录路径
    if not config.memory_dir:
        errors.append("memory_dir is required")

    # 检查路径安全性
    memory_dir_str = str(config.memory_dir)
    if '..' in memory_dir_str:
        errors.append("memory_dir contains '..' which may be unsafe")

    # 检查 LLM 配置（如果启用自动记忆）
    if config.auto_memory_enabled:
        if not config.llm_base_url:
            errors.append("llm_base_url is required when auto_memory is enabled")
        if not config.llm_api_key:
            errors.append("llm_api_key is required when auto_memory is enabled")

    return errors
