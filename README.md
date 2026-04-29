# Agent Harness

多团队 AI 助手部署框架。一套代码，多实例隔离部署，支持智能路由、Claude Code 集成和三层自愈记忆系统。

<img width="2044" height="676" alt="image" src="https://github.com/user-attachments/assets/08c29769-ba18-485c-bd2f-48a368fc6520" />


## 使用场景

当一个组织内有多个团队（如芯片研发、验证、项目管理、架构设计），每个团队需要**独立的 AI 助手**，各自拥有不同的知识库、技能和系统提示词，但又希望有一个**统一入口**智能分发请求时，Agent Harness 提供了完整的解决方案。

核心诉求：
- **团队隔离**：每个团队的对话、知识库、配置完全独立，互不干扰
- **统一入口**：用户无需关心该找哪个 Agent，Router 自动路由
- **离线部署**：支持内网纯 Docker 部署，无外网依赖
- **记忆持久化**：对话跨会话保留，Agent 越用越懂用户

## 整体架构

```
                          ┌─────────────────────┐
                          │   Router Platform    │
                          │  :4000 (API)         │
                          │  :4303 (UI)          │
                          │                      │
                          │  三层路由引擎          │
                          │  MCP Server          │
                          │  A2A Protocol        │
                          └────────┬────────────┘
                                   │ HTTP + SSE
               ┌───────────────────┼───────────────────┐
               │                   │                   │
       ┌───────▼───────┐   ┌───────▼───────┐   ┌───────▼───────┐
       │   Team A       │   │   Team B       │   │   Team C/D    │
       │  :4201 API     │   │  :4202 API     │   │  :4203/4 API  │
       │  :4301 UI      │   │  :4312 UI      │   │  :4313/14 UI  │
       │  :4101 Runtime │   │  :4102 Runtime │   │  :4103/4      │
       └───────────────┘   └───────────────┘   └───────────────┘
               │                   │                   │
               └───────────────────┼───────────────────┘
                                   │
                               LLM API
                          (GLM-5 / Qwen / etc.)
```

每个团队 3 个容器：`opencode-team-x`（Agent Runtime）+ `api-team-x`（API 网关）+ `ui-team-x`（前端）。

Docker Compose 一键启动 16 个服务（4 team x 3 容器 + Router API + Router UI + Docling 等）。

## 核心功能

### 1. 对话永久化管理

对话不是用完即弃。每次会话的完整记录（用户消息、Agent 回复、工具调用）以 JSONL 格式持久化存储在 `data/` 目录下。

- **会话恢复**：关闭浏览器后重新打开，历史对话完整保留
- **会话列表**：左侧栏展示所有历史会话，支持搜索和切换
- **会话分享**：生成公开链接分享给同事（Token 鉴权，7 天过期）

<img width="1372" height="1079" alt="image" src="https://github.com/user-attachments/assets/4396c04c-55bf-4e0d-920e-bf9225670ce6" />


### 2. 流式输出与工具调用标注

Agent 的回复以 SSE（Server-Sent Events）流式推送到前端，用户可以实时看到 Agent 的思考过程。

- **逐字流式**：回复内容实时渲染，无需等待完整响应
- **工具调用可视化**：当 Agent 调用工具（读文件、执行命令、搜索知识库）时，前端实时展示工具名称、参数和执行结果
- **思考过程展示**：显示 Agent 的推理链，让用户理解"为什么这样做"

### 3. SubAgent 调用

Agent 可以根据任务需要，自动调用其他专业 Agent 完成子任务。

```
用户: "帮我分析这段 UVM 代码的性能问题"
      ↓
Team A Agent (主 Agent)
      ↓ 发现涉及 UVM 验证
      调用 Team B Agent (SubAgent)
      ↓ 返回分析结果
      Team A Agent 综合回答
```

SubAgent 调用通过 Router 的 `call_agent` MCP 工具实现，支持跨团队上下文传递。

### 4. 文件系统

每个团队拥有独立的文件系统空间，Agent 可以在其中读写文件。

- **知识库文档**（`teams/<team>/kb/`）：Agent 按需读取，支撑回答的准确性
- **技能文件**（`teams/<team>/skills/`）：定义 Agent 的专业能力
- **附件管理**：支持文件上传，前端拖拽上传，Agent 可直接读取分析
- **文档自动转换**：PDF/Word/PPT 通过 Docling 服务自动转为 Markdown，Agent 可直接解析

### 5. 三层自愈记忆系统

移植自 Claude Code v2.1.88 的记忆架构，让 Agent 跨会话记住用户偏好和项目上下文。

```
┌─────────────────────────────────────────────────────────┐
│  Layer 1: MEMORY.md Index (索引层)                       │
│  - 常驻上下文，最多 200 行                                │
│  - 只存指针，不存数据                                     │
├─────────────────────────────────────────────────────────┤
│  Layer 2: Topic Files (知识层)            ↓ 按需加载      │
│  - 四种类型: user / feedback / project / reference       │
│  - 被索引引用时才读入上下文                                │
├─────────────────────────────────────────────────────────┤
│  Layer 3: Transcript Grep (日志层)        ↓ 仅 grep      │
│  - JSONL 原始对话记录                                     │
│  - 从不完整回读，只通过 grep 精确检索                      │
└─────────────────────────────────────────────────────────┘
         ↑                                    ↑
    extractMemories                     autoDream
   (实时记忆提取)                    (后台记忆整理)
```

- **记忆提取**：会话过程中自动提取用户偏好、项目决策等关键信息
- **记忆整理**：后台自动合并冗余记忆、删除过期内容（只合并，不创造）
- **写入纪律**：只有文件写入成功后才更新索引，防止"记忆指向不存在的内容"

### 6. 智能路由（Router）

Router 是整个系统的"大脑"，负责将用户请求智能分发到最合适的团队 Agent。

```
┌──────────────────────────────────────────────────────────────┐
│                     Router Platform                          │
│                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐      │
│  │  Agent       │    │  Routing    │    │  Session    │      │
│  │  Registry    │    │  Engine     │    │  Manager    │      │
│  │             │    │             │    │             │      │
│  │ agents.yaml │    │ routes.yaml │    │ 跨团队上下文 │      │
│  │ 健康检查     │    │ 三层路由    │    │ 会话映射    │      │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘      │
│         │                  │                  │              │
│  ┌──────▼──────────────────▼──────────────────▼──────┐      │
│  │              Express Server (:3000)                │      │
│  │                                                    │      │
│  │  POST /chat  →  路由  →  SSE 流式转发              │      │
│  │  GET  /agents →  列出所有 Agent                    │      │
│  │  POST /route  →  仅路由不执行                       │      │
│  └────────────────────────────────────────────────────┘      │
│                                                              │
│  ┌────────────────────────────────────────────────────┐      │
│  │  MCP Server (stdio)     A2A Adapter (JSON-RPC)     │      │
│  │  5 tools:               AgentCard                  │      │
│  │  - list_agents          message/send               │      │
│  │  - find_agent           message/stream (SSE)       │      │
│  │  - call_agent           Task lifecycle             │      │
│  │  - get_agent_info                                  │      │
│  │  - route_and_call                                  │      │
│  └────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────┘
```

<img width="965" height="1347" alt="image" src="https://github.com/user-attachments/assets/a9394766-1f26-4f6b-b2c8-68bb9ebe3903" />

<img width="1578" height="1138" alt="image" src="https://github.com/user-attachments/assets/a80db49f-ed0f-43d4-aa44-b9c7ddaafb40" />


**三层路由引擎**：
1. **关键词直接映射**：如 "UVM" → team-b，"飞书" → team-c
2. **规则匹配**：加权关键词组，处理边界消歧（如 "功耗" 可能是 team-a 的芯片功耗或 team-b 的验证功耗）
3. **置信度决策**：auto_route_threshold = 0.7，低于阈值时询问用户选择

**健康检查**：每 30 秒探测各团队 API，自动剔除不可用的 Agent。

### 7. Claude Code 集成（MCP → A2A）

Router 同时实现了 MCP（Model Context Protocol）和 A2A（Agent-to-Agent）两种协议，让 Claude Code 可以直接调用团队 Agent。

```
┌─────────────┐     stdio JSON-RPC      ┌─────────────┐
│ Claude Code │ ◄──────────────────────► │ MCP Server  │
│  (Client)   │     5 MCP tools          │ (router/)   │
└─────────────┘                          └──────┬──────┘
                                                │
                                         HTTP + SSE
                                                │
                                         ┌──────▼──────┐
                                         │ Agent Client │
                                         │ (代理转发)    │
                                         └──────┬──────┘
                                                │
                              ┌─────────────────┼─────────────────┐
                              │                 │                 │
                       ┌──────▼──────┐   ┌──────▼──────┐   ┌─────▼──────┐
                       │  Team A API │   │  Team B API │   │ Team C API │
                       └─────────────┘   └─────────────┘   └────────────┘
```

**MCP 工具**（Claude Code 可直接调用）：
- `list_agents`：列出所有可用 Agent 及其能力描述
- `find_agent`：根据问题内容智能匹配最合适的 Agent
- `call_agent`：调用指定 Agent 执行任务，支持 SSE 流式返回
- `get_agent_info`：获取 Agent 详细信息（skills、KB、配置）
- `route_and_call`：一步完成路由 + 调用

**A2A 协议**（支持外部 Agent 互调）：
- 遵循 A2A Protocol v1.0 规范
- `AgentCard`：每个 Agent 自描述能力
- `message/send`：同步调用
- `message/stream`：SSE 流式调用
- Task 生命周期管理：submitted → working → completed/failed

## 项目结构

```
agent_harness/
├── docker-compose.yml          # 全量编排（16 个服务）
├── .env.example                # 环境变量模板
│
├── router/                     # Router 平台
│   ├── server.js               # Express 服务主入口
│   ├── lib/
│   │   ├── router.js           # 三层路由引擎
│   │   ├── agentRegistry.js    # Agent 注册与健康检查
│   │   ├── agentClient.js      # HTTP 代理 + SSE 转发
│   │   ├── sessionManager.js   # 跨团队会话管理
│   │   ├── mcpServer.js        # MCP Server（5 tools）
│   │   └── a2aAdapter.js       # A2A Protocol 适配器
│   └── config/
│       ├── agents.yaml         # Agent 定义（4 teams）
│       └── routes.yaml         # 路由规则
│
├── src/
│   ├── api/server.js           # 团队 API 服务（3000+ 行核心逻辑）
│   ├── memory/                 # 三层自愈记忆系统（Python）
│   │   ├── index_layer.py      # Layer 1: MEMORY.md 索引
│   │   ├── topic_layer.py      # Layer 2: 主题文件
│   │   ├── transcript_layer.py # Layer 3: 对话日志
│   │   ├── extract.py          # 实时记忆提取
│   │   └── dream.py            # 后台记忆整理
│   ├── frontend_new_2/         # 前端（Vite + React + Tailwind CSS）
│   └── file_search/            # 文件搜索工具
│
├── teams/                      # 团队配置（核心维护目录）
│   ├── team-a/                 # 研发助手（ARM/芯片/嵌入式）
│   │   ├── AGENTS.md           # 系统提示词
│   │   ├── opencode.json       # 模型配置
│   │   ├── kb/                 # 知识库
│   │   └── skills/             # 技能
│   ├── team-b/                 # 验证助手（UVM/仿真）
│   ├── team-c/                 # 飞书集成助手
│   └── team-d/                 # 架构图助手
│
├── deploy/                     # 部署文件
│   ├── Dockerfile.api          # API 容器
│   ├── Dockerfile.ui           # UI 容器（nginx）
│   ├── Dockerfile.opencode     # Runtime 容器
│   ├── add-team.sh             # 新增团队脚本
│   ├── save-images.sh          # 离线：保存镜像
│   └── load-images.sh          # 离线：加载镜像
│
├── docs/                       # 架构文档
│   ├── A2A_VS_MCP_ANALYSIS.md  # A2A vs MCP 深度对比
│   └── ROUTING_PLATFORM_DESIGN*.md
│
└── tools/                      # 工具脚本
    ├── auto_convert_all.py     # 批量文档转换
    └── sync_transcripts.py     # 对话记录同步
```

## 解决的小巧思

### 离线部署的一致性问题

内网环境无法 `docker pull`，镜像需要手动搬运。解决方案：
- `save-images.sh` / `load-images.sh` 一键导出/导入所有依赖镜像
- Dockerfile 中用 `COPY node_modules/` 替代 `RUN npm install`，构建阶段不联网
- 模型文件通过 HuggingFace cache 目录挂载，首次下载后永久复用

### OpenCode 事件格式兼容

OpenCode 的 SSE 事件格式随版本变化，前端可能收不到回复。解决方案：
- `server.js` 中 `translateEvent()` 函数做事件格式适配层
- 将 OpenCode 的私有事件格式统一转换为前端约定的标准格式
- 新增事件类型时只需修改这一个函数

### 多团队配置的维护成本

4 个团队如果各自独立配置，维护成本高。解决方案：
- Docker Compose 使用 YAML anchors（`x-api-common`、`x-ui-common`）消除重复
- `deploy/add-team.sh` 脚本自动化新增团队流程
- 每个团队只需维护 `teams/<team-id>/` 目录，其他全部共用

### 跨团队上下文传递

Router 转发请求到 Team A 后，如果需要调用 Team B，上下文会丢失。解决方案：
- Router 维护独立的 `routerSession`，与各团队的 `teamSession` 做映射
- 跨团队调用时，Router 自动构建上下文摘要传递给目标 Agent
- `sessionManager.js` 管理整个生命周期

### 文档格式碎片化

团队知识库中混杂 PDF、Word、PPT、Markdown，Agent 无法统一解析。解决方案：
- Docling 服务统一转换为 Markdown
- 三种触发方式：启动时自动扫描、Watchdog 监控新增文件、前端手动刷新
- 图片描述支持本地模型（SmolVLM）和 API 调用（mimo）两种方案

## 快速开始

### 1. 准备配置

```bash
cp .env.example .env
# 编辑 .env，填写 LLM API Key
```

必填项：
- `OPENCODE_IMAGE`：opencode 镜像名（`docker images` 查看）
- `LLM_BASE_URL`：LLM 服务地址（OpenAI 兼容接口）
- `LLM_API_KEY`：API Key
- `TEAM_A_PASSWORD`：访问密码

### 2. 配置模型

在 `teams/team-a/opencode.json` 中通过 `provider` 字段配置 LLM 端点：

```json
{
  "model": "internal-llm/your-model-id",
  "provider": {
    "internal-llm": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "${LLM_BASE_URL}" },
      "models": { "your-model-id": { "name": "Your Model" } }
    }
  }
}
```

### 3. 启动

```bash
# 在线环境
docker compose up -d

# 离线环境（先在有网机器上）
bash deploy/save-images.sh ./images
# 传到目标机器后
bash deploy/load-images.sh ./images
docker compose build && docker compose up -d
```

### 4. 验证

```bash
docker compose ps
curl http://localhost:4201/health
# 浏览器打开 http://服务器IP:4301
```

### 5. 新增团队

```bash
bash deploy/add-team.sh team-e "Team E Agent"
# 按提示更新 docker-compose.yml 和 .env
docker compose up -d opencode-team-e api-team-e ui-team-e
```

## 端口规划

| 服务 | Team A | Team B | Team C | Team D |
|------|--------|--------|--------|--------|
| Runtime | 4101 | 4102 | 4103 | 4104 |
| API | 4201 | 4202 | 4203 | 4204 |
| UI | 4301 | 4312 | 4313 | 4314 |

| 全局服务 | 端口 |
|---------|------|
| Router API | 4000 |
| Router UI | 4303 |
| Docling | 4501 |

## 调试

```bash
# 查看团队 Agent 日志
docker compose logs -f opencode-team-a

# 查看 API 层日志
docker compose logs -f api-team-a

# 查看 Router 日志
docker compose logs -f router-api

# 检查 opencode 健康
docker exec opencode-team-a wget -qO- http://localhost:4096/health
```
