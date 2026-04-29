# Agent Harness 路由与统一管理平台设计方案

## 一、现状调查分析

### 1.1 现有架构概览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            当前架构 (单团队独立部署)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  用户浏览器 ──► UI (Nginx:4301) ──► API (Node:4201) ──► OpenCode (4096)    │
│                                      │                                      │
│                                      ▼                                      │
│                              ┌──────────────┐                              │
│                              │ teams/team-a │                              │
│                              │  ├── kb/     │  ← 知识库                     │
│                              │  ├── skills/ │  ← 技能                       │
│                              │  ├── .claude/│  ← 记忆系统                    │
│                              │  └── AGENTS.md│                              │
│                              └──────────────┘                              │
│                                                                             │
│  Docker Services:                                                           │
│  - opencode-team-a (4101:4096) - Agent Runtime                             │
│  - api-team-a (4201:3000)    - REST API Layer                              │
│  - ui-team-a (4301:80)       - Web Frontend                                │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 核心组件分析

#### 1.2.1 API Server (`src/api/server.js`) - 约 2900 行

**主要功能模块：**

| 模块 | 端点 | 功能 |
|------|------|------|
| 会话管理 | `/sessions`, `/sessions/:id` | CRUD 会话，消息持久化 |
| 对话流 | `/chat` | SSE 流式对话，事件转换 |
| 记忆系统 | `/memory/*` | 三层记忆管理 (Layer 1/2/3) |
| 任务管理 | `/tasks/*` | 后台任务，SSE 输出流 |
| 配置管理 | `/config` | LLM 配置，模型切换 |
| 文档转换 | `/docs/convert` | Docling 文档转 Markdown |
| 附件管理 | `/upload`, `/attachments` | 文件上传下载 |

**关键数据流：**
```
用户消息 → API Server → OpenCode Runtime (SSE) → 事件转换 → 前端
                    ↓
              消息持久化 (data/messages/*.json)
              记忆提取 (memory/*.md)
              Transcript 同步 (.claude/sessions/*.jsonl)
```

#### 1.2.2 OpenCode Runtime

- **端口**: 4096 (容器内)
- **协议**: HTTP + SSE (Server-Sent Events)
- **认证**: Basic Auth (opencode:password)
- **配置**: `opencode.json` 定义模型、权限、指令

#### 1.2.3 记忆系统 (`src/memory/`)

**三层架构：**

```
Layer 1: MEMORY.md (索引层，≤200行，自动注入系统提示词)
Layer 2: *.md 文件 (主题记忆，按需读取)
Layer 3: sessions/*.jsonl (历史对话，grep 搜索)
```

**记忆类型：**
- `user` - 用户偏好、角色
- `feedback` - 行为指导、纠正
- `project` - 项目状态、决策
- `reference` - 外部系统指针

### 1.3 D-Claw 参考架构分析

D-Claw 是小米内部的成熟 Agent 平台，采用 **主 Agent + Domain Agent** 架构：

```
┌─────────────────────────────────────────────────────────────────┐
│                        D-Claw 架构                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  用户 (飞书) ──► Nanoclaw ──► Claude Code Agent (主 Agent)      │
│                                   │                             │
│                      ┌────────────┼────────────┐               │
│                      ▼            ▼            ▼               │
│              Performance    Stability     Modem    ...         │
│                Agent         Agent        Agent                │
│              (Domain)      (Domain)     (Domain)               │
│                                                                 │
│  关键机制:                                                       │
│  - MCP 协议挂载工具                                              │
│  - mcp__domain_agent__ 委托调用                                  │
│  - Skill 懒加载 (不常驻上下文)                                    │
│  - 路由规则在 System Prompt 内嵌决策树                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**核心设计原则：**
1. **上下文隔离** - Domain Agent 独立进程，避免污染主 Agent
2. **静态路由** - System Prompt 内嵌决策树
3. **MCP 协议** - 标准化工具接入层
4. **Skill 懒加载** - 复杂流程按需读取

### 1.4 Claude Code 源码分析

从 Claude Code 源码中发现的关键机制：

#### AgentTool (`src/tools/AgentTool/`)

- 支持子代理 (subagent) 调用
- 支持 `subagent_type` 指定代理类型
- 支持后台任务 (`run_in_background`)
- 支持隔离模式 (`isolation: worktree`)

#### AgentDefinition 结构

```typescript
type AgentDefinition = {
  agentType: string        // 代理类型标识
  whenToUse: string        // 使用场景描述
  tools?: string[]         // 允许的工具列表
  disallowedTools?: string[] // 禁用的工具
  skills?: string[]        // 预加载的技能
  mcpServers?: AgentMcpServerSpec[] // MCP 服务器配置
  hooks?: HooksSettings    // 会话钩子
  model?: string           // 模型覆盖
  permissionMode?: PermissionMode // 权限模式
  memory?: 'user' | 'project' | 'local' // 记忆范围
  isolation?: 'worktree' | 'remote' // 隔离模式
}
```

#### MCP 协议支持

- MCP Server 可以挂载到 Agent
- 支持 `mcp__*` 前缀的工具调用
- Domain Agent 通过 MCP RPC 调用

---

## 二、设计目标

### 2.1 核心需求

1. **统一入口** - 一个平台管理多个 Agent
2. **路由功能** - 智能识别任务，分发到对应 Agent
3. **资源管理** - 统一管理各团队的 Skills 和 Knowledge Base
4. **两种调用方式**：
   - 保留现有 Web 客户端
   - 支持 Claude Code 作为主 Agent 调用

### 2.2 设计原则

1. **独立部署** - 新平台作为独立模块，不侵入现有代码
2. **向后兼容** - 现有 UI 和 API 保持可用
3. **最小改动** - 复用现有组件，减少重构
4. **可扩展** - 支持后续新增团队和 Agent

---

## 三、架构设计

### 3.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         新架构 (多团队统一管理)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Router Platform (新增独立模块)                     │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │   │
│  │  │ Agent Registry │  │  Router    │  │ Skill/KB    │                  │   │
│  │  │ (Agent 注册表) │  │ (路由引擎)  │  │ Manager     │                  │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                  │   │
│  │         │                │                │                          │   │
│  │         └────────────────┼────────────────┘                          │   │
│  │                          ▼                                            │   │
│  │                 ┌─────────────────┐                                   │   │
│  │                 │  Router API     │ (新端口: 4000)                    │   │
│  │                 │  /agent/list    │                                   │   │
│  │                 │  /agent/find    │                                   │   │
│  │                 │  /agent/call    │                                   │   │
│  │                 │  /skill/search  │                                   │   │
│  │                 │  /kb/search     │                                   │   │
│  │                 └─────────────────┘                                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                   │                                         │
│          ┌────────────────────────┼────────────────────────┐               │
│          ▼                        ▼                        ▼               │
│  ┌───────────────┐        ┌───────────────┐        ┌───────────────┐       │
│  │   Team A      │        │   Team B      │        │   Team C      │       │
│  │   Agent       │        │   Agent       │        │   Agent       │       │
│  │ (现有部署)    │        │ (现有部署)    │        │ (新增)        │       │
│  └───────────────┘        └───────────────┘        └───────────────┘       │
│                                                                             │
│  调用方式:                                                                   │
│  1. Web Client ──► Router ──► Target Agent                                 │
│  2. Claude Code ──► Router API ──► Target Agent                            │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 目录结构设计

```
/data/agent_harness/
├── router/                          # 新增：路由平台独立模块
│   ├── server.js                    # Router API Server
│   ├── package.json
│   ├── config/
│   │   ├── agents.yaml              # Agent 注册配置
│   │   └── routes.yaml              # 路由规则配置
│   ├── lib/
│   │   ├── agentRegistry.js         # Agent 注册表
│   │   ├── router.js                # 路由引擎
│   │   ├── agentClient.js           # Agent 调用客户端
│   │   └── resourceManager.js       # Skills/KB 统一管理
│   ├── routes/
│   │   ├── agentRoutes.js           # Agent 相关路由
│   │   ├── skillRoutes.js           # Skill 搜索路由
│   │   └── kbRoutes.js              # KB 搜索路由
│   └── Dockerfile                   # Router 镜像
│
├── teams/                           # 现有：各团队目录
│   ├── team-a/
│   ├── team-b/
│   └── team-c/
│
├── src/                             # 现有：源码目录
│   ├── api/                         # 现有 API (保持不变)
│   ├── ui/                          # 现有 UI (保持不变)
│   └── memory/                      # 现有记忆系统
│
└── docker-compose.yml               # 更新：添加 router 服务
```

### 3.3 核心组件设计

#### 3.3.1 Agent Registry (Agent 注册表)

**配置文件格式 (`config/agents.yaml`)：**

```yaml
agents:
  team-a:
    name: "Team A Agent"
    description: "研发助手，专注于流程规范和技术问题"
    endpoint: "http://api-team-a:3000"
    healthCheck: "/health"
    capabilities:
      - "流程查询"
      - "技术问答"
      - "代码分析"
    keywords:
      - "team-a"
      - "研发"
      - "流程"
    skills:
      - soc-power-prediction
    kb:
      - ARM_TRM_CPU
    metadata:
      owner: "team-a@example.com"
      created: "2024-03-01"
      tags: ["研发", "嵌入式"]

  team-b:
    name: "Team B Agent"
    description: "测试助手，专注于测试用例和自动化测试"
    endpoint: "http://api-team-b:3000"
    healthCheck: "/health"
    capabilities:
      - "测试用例生成"
      - "自动化测试"
    keywords:
      - "team-b"
      - "测试"
      - "自动化"
```

**注册表 API：**

```javascript
class AgentRegistry {
  // 获取所有 Agent 列表
  async listAgents() { ... }
  
  // 根据 ID 获取 Agent
  async getAgent(agentId) { ... }
  
  // 搜索匹配的 Agent
  async findAgents(query) { ... }
  
  // 健康检查
  async healthCheck(agentId) { ... }
  
  // 动态注册 Agent
  async registerAgent(config) { ... }
}
```

#### 3.3.2 Router (路由引擎)

**路由策略：**

```javascript
class Router {
  // 意图识别 + Agent 匹配
  async route(userMessage, context) {
    // 1. 关键词匹配
    const keywordMatches = this.matchKeywords(userMessage);
    
    // 2. 能力匹配
    const capabilityMatches = this.matchCapabilities(userMessage, context);
    
    // 3. LLM 辅助路由 (可选)
    if (this.config.useLLMRouting) {
      return await this.llmRoute(userMessage, candidates);
    }
    
    // 4. 综合评分
    return this.scoreAndSelect(keywordMatches, capabilityMatches);
  }
  
  // 路由规则 (参考 D-Claw)
  async buildRoutingPrompt() {
    return `
## 路由规则

根据用户消息选择合适的 Agent：

| 关键词 | Agent | 说明 |
|--------|-------|------|
| ARM/CPU/功耗 | team-a | 芯片相关技术问题 |
| 测试/用例/自动化 | team-b | 测试相关问题 |
| ... | ... | ... |

如果不确定，选择最相关的 Agent 或询问用户。
`;
  }
}
```

#### 3.3.3 Agent Client (Agent 调用客户端)

**调用方式：**

```javascript
class AgentClient {
  // 调用指定 Agent
  async callAgent(agentId, message, options) {
    const agent = await registry.getAgent(agentId);
    
    // 方式 1: 直接转发到 Agent API
    return await this.forwardToAgent(agent.endpoint, message);
    
    // 方式 2: 创建新会话并对话
    const session = await this.createSession(agent.endpoint);
    return await this.chat(agent.endpoint, session.id, message);
  }
  
  // 流式调用
  async *streamCall(agentId, message) {
    const agent = await registry.getAgent(agentId);
    const response = await fetch(`${agent.endpoint}/chat`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
    
    // SSE 流式转发
    for await (const event of this.parseSSE(response.body)) {
      yield event;
    }
  }
}
```

#### 3.3.4 Resource Manager (资源管理器)

**统一管理 Skills 和 KB：**

```javascript
class ResourceManager {
  // 搜索所有团队的 Skills
  async searchSkills(query) {
    const results = [];
    for (const agent of await registry.listAgents()) {
      const skills = await this.loadAgentSkills(agent.id);
      const matches = this.matchSkills(query, skills);
      results.push(...matches.map(s => ({ ...s, agentId: agent.id })));
    }
    return results;
  }
  
  // 搜索所有团队的 KB
  async searchKB(query) {
    const results = [];
    for (const agent of await registry.listAgents()) {
      const kbFiles = await this.loadAgentKB(agent.id);
      const matches = await this.grepKB(query, kbFiles);
      results.push(...matches.map(k => ({ ...k, agentId: agent.id })));
    }
    return results;
  }
  
  // 获取特定 Skill 详情
  async getSkill(agentId, skillName) {
    const skillPath = path.join(TEAMS_DIR, agentId, 'skills', skillName);
    return await this.loadSkill(skillPath);
  }
}
```

### 3.4 API 设计

#### Router API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/agents` | GET | 列出所有 Agent |
| `/agents/:id` | GET | 获取 Agent 详情 |
| `/agents/find` | POST | 搜索匹配的 Agent |
| `/agents/:id/proxy/*` | ALL | 代理到目标 Agent |
| `/skills/search` | POST | 搜索所有 Skills |
| `/kb/search` | POST | 搜索所有 KB |
| `/route` | POST | 智能路由 (返回最佳 Agent) |
| `/chat` | POST | 通过路由对话 |

**关键 API 示例：**

```javascript
// POST /route - 智能路由
app.post('/route', async (req, res) => {
  const { message, context } = req.body;
  const result = await router.route(message, context);
  res.json({
    recommendedAgent: result.agentId,
    confidence: result.score,
    alternatives: result.alternatives,
  });
});

// POST /chat - 路由对话
app.post('/chat', async (req, res) => {
  const { message, agentId } = req.body;
  
  // 如果指定了 agentId，直接调用
  if (agentId) {
    return await agentClient.streamCall(agentId, message, res);
  }
  
  // 否则先路由再调用
  const route = await router.route(message);
  await agentClient.streamCall(route.agentId, message, res);
});
```

### 3.5 Docker Compose 更新

```yaml
# docker-compose.yml 新增服务
services:
  # 新增：Router 服务
  router:
    build:
      context: .
      dockerfile: router/Dockerfile
    ports:
      - "4000:3000"
    environment:
      - CONFIG_PATH=/config
    volumes:
      - ./router/config:/config:ro
      - ./teams:/teams:ro  # 只读访问所有团队
    depends_on:
      - api-team-a
      # - api-team-b  # 按需启用
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

---

## 四、两种调用方式实现

### 4.1 方式一：Web 客户端 (保留现有)

**方案：添加路由选择界面**

```
现有流程:
用户 → UI (选择 Team) → API → Agent

新流程:
用户 → UI (Router 入口) → Router → 目标 Agent
     │
     └─ 可选：显示推荐的 Agent
```

**实现方式：**

1. 新增 `/router` 入口页面
2. 用户输入消息后，先调用 `/route` 获取推荐 Agent
3. 用户确认后，通过 `/agents/:id/proxy/*` 转发

### 4.2 方式二：Claude Code 作为主 Agent

**方案：将 Router 注册为 MCP Server**

```
Claude Code (主 Agent)
      │
      ├── mcp__router__list_agents     # 列出可用 Agent
      ├── mcp__router__find_agent      # 查找 Agent
      ├── mcp__router__call_agent      # 调用 Agent
      ├── mcp__router__search_skills   # 搜索 Skills
      └── mcp__router__search_kb       # 搜索 KB
```

**MCP Server 配置示例：**

```json
{
  "mcpServers": {
    "agent-router": {
      "command": "node",
      "args": ["/data/agent_harness/router/mcp-server.js"],
      "env": {
        "ROUTER_URL": "http://localhost:4000"
      }
    }
  }
}
```

**Claude Code AGENTS.md 集成：**

```markdown
## Agent 调用

当用户需要调用其他 Agent 时，使用 `mcp__router__*` 工具：

1. **查找 Agent**: `mcp__router__find_agent({ query: "用户问题" })`
2. **调用 Agent**: `mcp__router__call_agent({ agentId: "team-a", message: "..." })`

示例：
用户: "帮我分析一下 ARM CPU 的功耗问题"
→ 调用 mcp__router__find_agent({ query: "ARM CPU 功耗" })
→ 返回 { agentId: "team-a", confidence: 0.9 }
→ 调用 mcp__router__call_agent({ agentId: "team-a", message: "..." })
```

---

## 五、实施计划

### 5.1 Phase 1: 基础框架 (1-2 周)

1. **创建 `router/` 目录结构**
2. **实现 AgentRegistry**
   - 读取 agents.yaml 配置
   - 提供基础 CRUD API
3. **实现 Router**
   - 关键词匹配路由
   - 基础路由 API
4. **实现 AgentClient**
   - 代理转发功能
   - SSE 流式支持
5. **Docker 化**
   - 编写 Dockerfile
   - 更新 docker-compose.yml

### 5.2 Phase 2: 资源管理 (1 周)

1. **实现 ResourceManager**
   - Skills 聚合搜索
   - KB 聚合搜索
2. **统一管理 API**
   - `/skills/search`
   - `/kb/search`

### 5.3 Phase 3: Claude Code 集成 (1 周)

1. **实现 MCP Server**
   - 暴露 router 工具
   - 实现 SSE 流式转发
2. **编写集成文档**
   - AGENTS.md 模板
   - 使用示例

### 5.4 Phase 4: UI 集成 (可选，待现有 UI debug 完成后)

1. **新增路由入口页面**
2. **Agent 选择推荐界面**
3. **统一资源浏览页面**

---

## 六、关键技术决策

### 6.1 路由策略

| 方案 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| 关键词匹配 | 简单、快速、无额外成本 | 精度有限 | ✓ 基础方案 |
| LLM 辅助 | 高精度、理解语义 | 延迟、成本 | ✓ 可选增强 |
| 向量相似度 | 平衡精度和速度 | 需要向量化 | 可选 |

**推荐**：关键词匹配作为基础，LLM 辅助作为可选增强

### 6.2 Agent 通信协议

| 方案 | 描述 | 适用场景 |
|------|------|---------|
| HTTP 代理 | 直接转发 REST/SSE 请求 | Web 客户端 |
| MCP 协议 | 标准 Agent-to-Agent | Claude Code 集成 |
| A2A 协议 | Agent-to-Agent 标准协议 | 跨平台调用 |

**推荐**：HTTP 代理 + MCP 双协议支持

### 6.3 隔离级别

- **无隔离**：Router 和 Agent 同进程，共享内存
- **容器隔离**：每个 Agent 独立容器 (当前架构)
- **进程隔离**：Agent 独立进程，通过 IPC 通信

**推荐**：保持现有容器隔离架构，Router 作为独立服务

---

## 七、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| 路由精度不足 | 任务分发错误 | 提供 Agent 选择确认界面 |
| Agent 不可用 | 服务中断 | 健康检查 + 自动降级 |
| 网络延迟 | 用户体验差 | 本地缓存 + 超时控制 |
| 配置复杂 | 运维困难 | 提供配置 UI + 自动发现 |

---

## 八、附录

### A. 参考架构

- **D-Claw**: 小米内部 Agent 平台，主 Agent + Domain Agent 架构
- **Claude Code**: Anthropic 官方 CLI，支持 subagent 和 MCP
- **OpenCode**: Agent Runtime，提供 SSE 流式对话

### B. 相关文件

- 现有 API: `/data/agent_harness/src/api/server.js`
- 现有 UI: `/data/agent_harness/src/ui/`
- 记忆系统: `/data/agent_harness/src/memory/`
- Docker 配置: `/data/agent_harness/docker-compose.yml`
- Claude Code 源码: `/data/collection-claude-code-source-code-main/`

### C. 术语表

| 术语 | 定义 |
|------|------|
| Agent | 具有特定能力的 AI 助手实例 |
| Router | 路由引擎，负责将任务分发到合适的 Agent |
| MCP | Model Context Protocol，模型上下文协议 |
| SSE | Server-Sent Events，服务器推送事件 |
| Domain Agent | 垂直领域的专业 Agent |
| Skill | 可复用的能力模板 |
| KB | Knowledge Base，知识库 |
