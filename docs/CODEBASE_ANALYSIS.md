# Agent Harness 代码库深度分析报告

## 一、项目概述

Agent Harness 是一个多团队 Agent 运行平台，基于 OpenCode Runtime 和 Claude Code 架构，支持：

- 多团队独立部署
- Skills 和 Knowledge Base 管理
- 三层记忆系统
- Docker 容器化部署
- 离线环境支持

## 二、目录结构

```
/data/agent_harness/
├── src/
│   ├── api/                    # API Server (Node.js/Express)
│   │   └── server.js           # 主文件，约 2900 行
│   ├── ui/                     # 前端 (Vite + React)
│   ├── ui_vite/                # 备选前端
│   ├── frontend_new/           # 新前端 (开发中)
│   ├── frontend_new_build/     # 新前端构建版
│   ├── frontend_new_2/         # 新前端 v2
│   ├── memory/                 # 记忆系统 (Python)
│   │   ├── manager.py          # 统一管理接口
│   │   ├── types.py            # 类型定义
│   │   ├── scanner.py          # 文件扫描
│   │   ├── index_layer.py      # Layer 1: 索引层
│   │   ├── topic_layer.py      # Layer 2: 主题层
│   │   ├── transcript_layer.py # Layer 3: 历史层
│   │   ├── relevance.py        # 相关性搜索
│   │   ├── extract.py          # 记忆提取
│   │   └── dream.py            # 记忆整理
│   └── file_search/            # 文件搜索工具
│
├── teams/
│   └── team-a/                 # 团队 A 配置
│       ├── AGENTS.md           # Agent 系统提示词
│       ├── opencode.json       # OpenCode 配置
│       ├── kb/                 # 知识库
│       ├── skills/             # 技能目录
│       ├── .claude/            # Claude 配置和记忆
│       └── attachments/        # 附件存储
│
├── data/
│   ├── sessions.json           # 会话索引
│   ├── messages/               # 消息存储
│   ├── tasks/                  # 任务存储
│   ├── memory_state.json       # 记忆状态
│   └── memory_cursors.json     # 记忆游标
│
├── deploy/
│   ├── Dockerfile.api          # API 镜像
│   ├── Dockerfile.ui           # UI 镜像
│   ├── Dockerfile.opencode     # OpenCode 镜像
│   ├── docling-server*.py      # 文档转换服务
│   └── start-docling-host.sh   # Docling 启动脚本
│
├── tools/
│   ├── auto_convert_all.py     # 自动文档转换
│   └── sync_transcripts.py     # 同步 transcripts
│
├── dist/                       # 前端构建产物
│   ├── team-a/                 # Team A UI
│   └── team-a-new/             # Team A 新 UI
│
├── docker-compose.yml          # Docker 编排
├── .env                        # 环境变量 (不提交)
├── .env.example                # 环境变量示例
└── .gitignore
```

## 三、核心组件分析

### 3.1 API Server (`src/api/server.js`)

**技术栈**：Node.js + Express + 原生 fetch

**主要功能模块**：

#### 3.1.1 配置管理 (Line 30-50)

```javascript
const TEAM_ID = process.env.TEAM_ID || 'unknown';
const TEAM_NAME = process.env.TEAM_NAME || 'Agent';
const TEAM_DIR = process.env.TEAM_DIR || '/teams/' + TEAM_ID;
const OPENCODE_URL = process.env.OPENCODE_URL || 'http://localhost:4096';
const OPENCODE_PASSWORD = process.env.OPENCODE_PASSWORD || '';
const DATA_DIR = '/data/agent_harness/data';  // ⚠️ 硬编码路径
```

**发现**：`DATA_DIR` 等路径为硬编码，需要改为环境变量以支持新服务器部署。

#### 3.1.2 会话管理 (Line 1046-1264)

```javascript
// GET /sessions - 获取会话列表
// GET /sessions/:id - 获取会话详情 + 消息历史
// POST /sessions - 创建新会话
// PATCH /sessions/:id - 更新会话
// DELETE /sessions/:id - 删除会话
```

**关键逻辑**：
- 会话切换时触发记忆整理 (`checkAndExtractMemories`)
- 支持 OpenCode session 自动重建
- 会话状态持久化到 `data/sessions.json`

#### 3.1.3 对话流程 (Line 1709-1953)

**核心流程**：

```
POST /chat
    │
    ├── 1. 验证 session，获取或创建 OpenCode session
    │
    ├── 2. 建立 SSE 连接 (GET /event)
    │
    ├── 3. 排空旧事件，等待 session.idle
    │
    ├── 4. 发送用户消息 (POST /session/:id/message)
    │
    ├── 5. 转发 SSE 事件到前端
    │       ├── message.part.delta → 文本流
    │       ├── message.part.updated → 工具调用
    │       ├── session.idle → 完成
    │       └── session.error → 错误
    │
    └── 6. 对话完成，安排延迟记忆整理
```

**事件转换** (`translateEvent` 函数)：

- `message.part.delta` → `{ type: 'text', content: '...' }`
- `message.part.updated (tool)` → `{ type: 'tool', name: '...', status: '...' }`
- `session.idle` → `{ type: 'done' }`
- 支持 thinking 模式 (`reasoning` 部分)

#### 3.1.4 记忆系统集成 (Line 227-991)

**三层架构实现**：

| 层级 | 存储 | 访问方式 |
|------|------|---------|
| Layer 1 | `MEMORY.md` | 自动注入系统提示词 |
| Layer 2 | `*.md` 文件 | `read` 工具按需读取 |
| Layer 3 | `sessions/*.jsonl` | `grep` 搜索 |

**记忆提取流程** (`extractMemoriesFromSession`)：

1. 检查 cursor，确定新消息范围
2. 调用 LLM (helper model) 提取记忆
3. 写入记忆文件 (`write .claude/memory/xxx.md`)
4. 更新 MEMORY.md 索引

**记忆整理流程** (`runAutoDream`)：

1. 积累 5 个 session 触发
2. 只喂记忆列表（不含内容）给 LLM
3. 执行 merge/delete 操作（不做 create/update）
4. 更新 MEMORY.md 索引

#### 3.1.5 任务管理 (Line 1266-1507)

```javascript
// POST /tasks - 创建后台任务
// GET /tasks/:taskId/stream - SSE 实时输出
// GET /tasks/:taskId/output - 获取历史输出
// POST /tasks/:taskId/cancel - 取消任务
```

**实现方式**：
- 使用 `nohup` 执行命令
- 通过 PID 文件跟踪进程
- `tail -f` 实时输出日志

#### 3.1.6 配置管理 (Line 2258-2510)

```javascript
// GET /config - 获取当前配置
// POST /config - 更新配置
// POST /config/apply - 保存并应用配置（重启容器）
```

**配置更新流程**：
1. 更新 `.env` 文件
2. 更新 `docker-compose.yml` 中的 OPENCODE_CONFIG_CONTENT
3. 更新 `opencode.json`
4. 重启 OpenCode 容器

### 3.2 记忆系统 (`src/memory/`)

**Python 实现，提供统一的记忆管理接口**。

#### 3.2.1 类型定义 (`types.py`)

```python
class MemoryType(Enum):
    USER = "user"        # 用户偏好、角色
    FEEDBACK = "feedback" # 行为指导、纠正
    PROJECT = "project"  # 项目状态、决策
    REFERENCE = "reference" # 外部系统指针

@dataclass
class MemoryHeader:
    filename: str
    file_path: Path
    mtime_ms: float
    description: Optional[str]
    memory_type: Optional[MemoryType]
```

#### 3.2.2 管理器接口 (`manager.py`)

```python
class MemoryManager:
    def __init__(self, memory_dir, transcripts_dir, config, llm_client):
        self.scanner = MemoryScanner(memory_dir, config)
        self.index = MemoryIndex(memory_dir, config)
        self.topic_manager = TopicManager(memory_dir, config)
        self.relevance_finder = RelevanceFinder(scanner, config, llm_client)
        self.extractor = MemoryExtractor(memory_dir, config, llm_client)
        if transcripts_dir:
            self.transcript_store = TranscriptStore(transcripts_dir)
            self.transcript_search = TranscriptSearch(transcript_store)
            self.dream = MemoryDream(memory_dir, transcripts_dir, config, llm_client)
    
    # Layer 1: Index Operations
    def load_index(self) -> str
    def get_index_entries(self) -> List[tuple]
    
    # Layer 2: Topic File Operations
    def save_memory(self, filename, name, description, memory_type, content) -> Path
    def read_memory(self, filename) -> Optional[TopicFile]
    def delete_memory(self, filename) -> bool
    def list_memories(self) -> List[str]
    
    # Layer 3: Transcript Operations
    def search_transcripts(self, pattern, session_ids, max_results) -> List[Dict]
    
    # Relevance Search
    async def find_relevant(self, query, max_results) -> List[RelevantMemory]
    
    # Self-Healing
    async def extract_from_messages(self, messages) -> ExtractResult
    async def consolidate(self, session_ids) -> Optional[DreamResult]
    
    # System Prompt Generation
    def build_system_prompt_section(self) -> str
```

### 3.3 OpenCode Runtime

**配置文件** (`teams/team-a/opencode.json`)：

```json
{
  "model": "internal-llm/zhipuai/glm-5",
  "provider": {
    "internal-llm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Internal LLM",
      "env": ["LLM_API_KEY"],
      "options": { "baseURL": "..." },
      "models": { "zhipuai/glm-5": { "name": "glm-5" } }
    }
  },
  "server": { "hostname": "0.0.0.0", "port": 4096 },
  "instructions": ["./AGENTS.md"],
  "permission": {
    "skill": { "*": "allow" },
    "read": "allow", "list": "allow",
    "edit": "allow", "write": "allow", "bash": "allow"
  }
}
```

**API 端点**：

| 端点 | 方法 | 描述 |
|------|------|------|
| `/` | GET | 健康检查（返回 200 或 401） |
| `/session` | POST | 创建新会话 |
| `/session/:id` | GET | 获取会话信息 |
| `/session/:id/message` | POST | 发送消息 |
| `/event` | GET | SSE 事件流 |

### 3.4 Docker 部署

**服务架构**：

```yaml
services:
  opencode-team-a:    # Agent Runtime (端口 4101:4096)
  api-team-a:         # REST API (端口 4201:3000)
  ui-team-a:          # Web UI (端口 4301:80)
  ui-team-a-new:      # 新 UI (端口 4302:80)
  docling:            # 文档转换 (可选)
  init-convert-team-a: # 初始化文档转换
```

**网络通信**：

```
用户 → ui-team-a:4301 → api-team-a:4201 → opencode-team-a:4101
                                    │
                                    └→ teams/team-a (volume mount)
```

## 四、数据流分析

### 4.1 对话数据流

```
┌──────────┐     POST /chat      ┌───────────┐     POST /message     ┌─────────────┐
│  用户    │ ──────────────────► │  API      │ ───────────────────► │  OpenCode   │
│  浏览器  │                     │  Server   │                       │  Runtime    │
└──────────┘                     └───────────┘                       └─────────────┘
     ▲                                 │                                    │
     │                                 │ GET /event (SSE)                   │
     │                                 ▼                                    │
     │         SSE events         ┌───────────┐     SSE events       │
     └─────────────────────────── │  Event    │ ◄────────────────────┘
                                  │  Stream   │
                                  └───────────┘
                                        │
                                        ▼ 触发记忆整理
                                  ┌───────────┐
                                  │  Memory   │
                                  │  System   │
                                  └───────────┘
```

### 4.2 消息持久化

```
用户消息 → saveMessages(sessionId, messages)
              │
              ├── data/messages/{sessionId}.json (消息存储)
              │
              └── syncToTranscript(sessionId, messages)
                    │
                    └── teams/team-a/.claude/sessions/{sessionId}.jsonl (JSONL 格式)
```

### 4.3 文档上传转换

```
POST /upload (type=kb)
    │
    ├── 保存到 teams/team-a/kb/
    │
    └── 如果是 PDF/Office → python3 tools/auto_convert_all.py
                              │
                              └── 调用 Docling 服务 → 生成 .md 文件
```

## 五、关键发现与建议

### 5.1 硬编码路径问题

**问题文件**：`src/api/server.js`

| 行号 | 硬编码路径 | 用途 |
|------|-----------|------|
| 39 | `/data/agent_harness/data` | 数据目录 |
| 1616 | `/data/agent_harness/tools/auto_convert_all.py` | 文档转换 |
| 2260 | `/data/agent_harness/.env` | 环境变量 |
| 2261 | `/data/agent_harness/docker-compose.yml` | Docker 配置 |
| 2262 | `/data/agent_harness/teams/${TEAM_ID}/opencode.json` | OpenCode 配置 |
| 2524 | `/data/agent_harness/src` | Python 路径 |
| 2720 | `/data/agent_harness/tools/sync_transcripts.py` | 同步脚本 |
| 2831 | `/data/agent_harness/teams/${TEAM_ID}` | 团队目录 |

**建议**：改为使用环境变量 `PROJECT_ROOT` 或相对路径。

### 5.2 API 端点汇总

| 端点 | 方法 | 功能 | 认证 |
|------|------|------|------|
| `/health` | GET | 健康检查 | 无 |
| `/sessions` | GET/POST | 会话列表/创建 | 无 |
| `/sessions/:id` | GET/PATCH/DELETE | 会话操作 | 无 |
| `/sessions/:id/messages` | POST | 保存消息 | 无 |
| `/chat` | POST | 对话流 | 无 |
| `/meta` | GET | 元信息 | 无 |
| `/upload` | POST | 文件上传 | 无 |
| `/attachments/:sessionId` | GET | 附件列表 | 无 |
| `/config` | GET/POST | 配置管理 | 无 |
| `/config/apply` | POST | 应用配置 | 无 |
| `/memory` | GET | 记忆索引 | 无 |
| `/memory/list` | GET | 记忆列表 | 无 |
| `/memory/:filename` | GET | 读取记忆 | 无 |
| `/memory/search` | POST | 搜索记忆 | 无 |
| `/memory/consolidate` | POST | 整理记忆 | 无 |
| `/memory/status` | GET | 记忆状态 | 无 |
| `/memory/extract/:sessionId` | POST | 提取记忆 | 无 |
| `/transcript/sync` | POST | 同步 transcripts | 无 |
| `/transcript/list` | GET | Transcript 列表 | 无 |
| `/transcript/search` | GET | 搜索 transcripts | 无 |
| `/docs/convert` | POST | 文档转换 | 无 |
| `/docs/status` | GET | 文档状态 | 无 |
| `/tasks` | POST | 创建任务 | 无 |
| `/tasks/:taskId/stream` | GET | 任务输出流 | 无 |
| `/tasks/:taskId/output` | GET | 任务历史输出 | 无 |
| `/tasks/:taskId/cancel` | POST | 取消任务 | 无 |

### 5.3 与 D-Claw 架构对比

| 方面 | Agent Harness | D-Claw |
|------|--------------|--------|
| 主/从架构 | 单 Agent 独立 | 主 Agent + Domain Agent |
| 路由机制 | 无（用户直接选择 Team） | System Prompt 决策树 |
| 工具接入 | 无 MCP | MCP 协议 |
| 跨 Agent 通信 | 无 | mcp__domain_agent__ RPC |
| Skills 管理 | 文件系统 | Skill 懒加载 |
| 记忆系统 | 三层文件系统 | 相同 |

**差距**：缺少路由层和 Agent 间通信机制。

## 六、现有前端分析

### 6.1 UI 结构

```
src/ui/
├── index.html
├── src/
│   └── main.jsx
├── package.json
└── vite.config.js
```

**配置**：
- 构建输出到 `dist/team-a/`
- 代理 `/api` 到 `localhost:4201`

### 6.2 新前端 (frontend_new_build)

```
src/frontend_new_build/
├── src/               # React 组件
├── package.json
├── vite.config.js
└── components.json
```

**配置**：
- 使用 Tailwind CSS
- 构建输出到 `dist/team-a-new/`

## 七、总结

Agent Harness 是一个功能完整的单团队 Agent 平台，具备：

**优势**：
1. ✅ 完善的会话管理
2. ✅ 三层记忆系统
3. ✅ Skills 和 KB 支持
4. ✅ 文档自动转换
5. ✅ Docker 容器化
6. ✅ 离线部署支持

**待改进**：
1. ❌ 无多 Agent 路由
2. ❌ 无 Agent 间通信
3. ❌ 硬编码路径较多
4. ❌ 无统一认证

**建议的改进方向**（见 ROUTING_PLATFORM_DESIGN.md）：
1. 新增 Router 服务作为独立模块
2. 实现 Agent Registry 管理
3. 添加 MCP Server 支持 Claude Code 集成
4. 统一 Skills/KB 搜索
