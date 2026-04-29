# Memory System - 三层自愈记忆架构

> **来源**: Claude Code v2.1.88 源码分析

本模块实现了 Claude Code 的三层自愈记忆系统。

## 重要说明：Agent Runtime 与当前架构

### 什么是 Agent Runtime？

**Agent Runtime** 是指能够持续运行、响应事件、自动触发任务的后台程序。它的核心特点是：

1. **事件驱动循环** - 持续运行，响应事件（用户消息、定时器、webhook）
2. **状态持久化** - 会话状态、记忆、上下文自动保存
3. **自动触发机制** - 可以在特定条件下自动执行任务

### 当前 agent_harness 的状态

**当前 agent_harness 不是真正的 Agent Runtime**，原因：

```
当前架构：
浏览器 → Nginx → Node.js API → 转发 → Openencode 容器
                                    ↑
                              请求结束后进程空闲
                              
问题：没有后台循环，无法自动触发记忆整理
```

### 如何变成 Agent Runtime？

**方案 1：在 Node.js API 层添加后台调度**

```javascript
import cron from 'node-cron';

// 每天凌晨 3 点整理记忆
cron.schedule('0 3 * * *', async () => {
  await triggerMemoryConsolidation();
});
```

**方案 2：使用 Openencode 的后台 Agent 功能（如果支持）**

**方案 3：重构为独立的 agent runtime 服务**

### 当前可用的功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 记忆读写 | ✅ 完全可用 | 模型可以调用工具读写记忆 |
| 相关记忆查找 | ✅ 完全可用 | 需要 LLM API |
| 记忆提取 | ⚠️ 需手动调用 | 会话结束后手动触发 |
| 记忆整理 | ⚠️ 需手动调用 | 定时或手动触发 |

## 与原有架构的对接

### 当前问题：记忆系统是孤立的

Openencode 容器目前**无法感知** Python 实现的记忆系统。

### 解决方案：集成到系统提示词

**关键步骤：让模型知道记忆系统的存在**

1. **修改 AGENTS.md**，添加记忆系统使用说明
2. **动态注入 MEMORY.md 内容**到系统提示词
3. **模型通过工具读写记忆**

### 什么时候与记忆系统互动？

| 时机 | 动作 | 触发者 |
|------|------|--------|
| 会话开始 | 加载 MEMORY.md 到上下文 | 系统提示词 |
| 用户提问 | 搜索相关记忆 | 模型主动 |
| 用户说"记住" | 写入记忆文件 | 模型调用 Write 工具 |
| 会话结束 | 提取记忆 | 后台任务（需 runtime） |
| 定时 | 整理记忆 | 定时任务（需 runtime） |

## 架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Three-Layer Self-Healing Memory                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Layer 1: MEMORY.md Index (索引层)                                   │    │
│  │  - 常驻上下文窗口                                                    │    │
│  │  - 最多 200 行, 25KB                                                │    │
│  │  - 只存指针，不存数据                                                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                   ↓ 按需加载                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Layer 2: Topic Files (知识层)                                       │    │
│  │  - 按主题分散存储                                                    │    │
│  │  - 四种类型: user, feedback, project, reference                     │    │
│  │  - 只有被索引引用时才读入上下文                                       │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                   ↓ 仅 grep 检索                             │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Layer 3: Transcript Grep (日志层)                                   │    │
│  │  - JSONL 格式的原始对话记录                                          │    │
│  │  - 从不完整回读到上下文                                              │    │
│  │  - 只通过 grep 精确检索                                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Self-Healing: autoDream + extractMemories                          │    │
│  │  - 后台记忆整理 (dream)                                              │    │
│  │  - 实时记忆提取 (extractMemories)                                    │    │
│  │  - Strict Write Discipline (写入纪律)                                │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 当前状态说明

**重要**: agent_harness 目前依赖外部 opencode runtime，不是真正的 agent runtime。因此：

1. **自动触发功能**（auto_dream）暂时无法完全实现
2. **提供了手动调用接口**，后续可向 agent runtime 对齐
3. **每个功能模块都有特殊注释**，标明来源和用途

## 快速开始

```python
from pathlib import Path
from src.memory import MemoryManager, MemoryType

# 创建管理器
manager = MemoryManager(
    memory_dir=Path("~/.claude/projects/my-project/memory"),
)

# 保存记忆
manager.save_memory(
    filename="user_role",
    name="User Role",
    description="user is a senior engineer",
    memory_type=MemoryType.USER,
    content="The user is a senior software engineer with 10 years of experience...",
)

# 读取记忆
topic = manager.read_memory("user_role.md")

# 搜索相关记忆
memories = await manager.find_relevant("how to fix auth bug")

# 获取系统提示词部分
prompt = manager.build_system_prompt_section()
```

## 文件结构

```
src/memory/
├── __init__.py          # 模块入口
├── types.py             # 记忆类型定义
├── config.py            # 配置管理
├── scanner.py           # 记忆文件扫描器
├── index_layer.py       # Layer 1: 索引层
├── topic_layer.py       # Layer 2: 主题文件层
├── transcript_layer.py  # Layer 3: 日志层
├── relevance.py         # 相关记忆查找
├── extract.py           # 实时记忆提取
├── dream.py             # 后台记忆整理
├── lock.py              # 整理锁机制
├── manager.py           # 统一管理接口
├── api.py               # REST API 端点
└── test_memory.py       # 测试文件
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /memory | 获取记忆索引 |
| GET | /memory/list | 列出所有记忆文件 |
| GET | /memory/:filename | 读取单个记忆 |
| POST | /memory | 创建新记忆 |
| PUT | /memory/:filename | 更新记忆 |
| DELETE | /memory/:filename | 删除记忆 |
| POST | /memory/search | 搜索相关记忆 |
| POST | /memory/extract | 从消息提取记忆 |
| POST | /memory/consolidate | 触发记忆整理 |

## 四种记忆类型

| 类型 | 用途 | 示例 |
|------|------|------|
| **user** | 用户信息、角色、偏好 | "user is a senior engineer" |
| **feedback** | 行为指导、纠正 | "don't summarize diffs" |
| **project** | 项目状态、决策 | "merge freeze starts 2026-04-15" |
| **reference** | 外部系统指针 | "bugs tracked in Linear INGEST" |

## 写入纪律

**核心原则**: 只有文件写入成功后才更新索引。

这防止失败操作污染上下文，避免"记忆"指向不存在的内容。

## 与 server.js 集成

```javascript
// 在 server.js 中添加记忆 API 端点
// 注意: 需要使用 Python 子进程或 HTTP 调用

import { spawn } from 'child_process';

// 调用 Python 记忆 API
async function callMemoryAPI(endpoint, method, data) {
  const python = spawn('python3', [
    '-c',
    `from src.memory import MemoryAPI; import asyncio; import json;
     api = MemoryAPI(Path("${MEMORY_DIR}"));
     result = asyncio.run(api.${endpoint}(${JSON.stringify(data)}));
     print(json.dumps(result))`
  ]);
  // ...
}
```

## 测试

```bash
cd /data/agent_harness
python3 -m src.memory.test_memory
```

## 参考来源

本模块基于以下 Claude Code v2.1.88 源码文件实现：

- `src/memdir/memdir.ts` - 索引层构建
- `src/memdir/memoryTypes.ts` - 类型定义
- `src/memdir/memoryScan.ts` - 文件扫描
- `src/memdir/findRelevantMemories.ts` - 相关记忆查找
- `src/services/extractMemories/extractMemories.ts` - 实时提取
- `src/services/autoDream/autoDream.ts` - 后台整理
- `src/utils/sessionStorage.ts` - Transcript 存储
- `src/utils/transcriptSearch.ts` - Grep 检索

## 许可

本模块仅供学术研究和教育目的使用。
