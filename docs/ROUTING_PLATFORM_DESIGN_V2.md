# Agent Harness 路由与统一管理平台设计方案 v2

> 更新日期：2026-04-14
> 版本：v2.0
> 状态：待审核

## 一、核心概念澄清

### 1.1 teams 目录挂载关系

```
┌─────────────────────────────────────────────────────────────────────┐
│   teams/team-a/                                                     │
│   ├── AGENTS.md     ◄──── OpenCode 读取 (/workspace)               │
│   ├── kb/           ◄──── OpenCode 读取 (Agent 查询知识库)          │
│   ├── skills/       ◄──── OpenCode 读取 (Agent 执行技能)            │
│   ├── .claude/      ◄──── OpenCode + API 都会操作                   │
│   │   ├── memory/   ◄──── 记忆文件                                  │
│   │   └── sessions/ ◄──── 对话历史                                  │
│   └── attachments/  ◄──── API 管理 (上传/下载)                      │
│                                                                     │
│   Docker 挂载:                                                      │
│   - opencode-team-a: ./teams/team-a → /workspace                   │
│   - api-team-a:      ./teams/team-a → /teams/team-a                │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 MCP 协议与懒加载

**MCP (Model Context Protocol)** 是 Anthropic 提出的标准化协议，让 LLM 能够调用外部工具。

```
┌─────────────┐         MCP 协议          ┌─────────────┐
│   Claude    │ ◄───────────────────────► │  MCP Server │
│   (模型)    │   JSON-RPC 消息格式        │  (工具提供者) │
└─────────────┘                            └─────────────┘
```

**`mcp__domain_agent__analyze`** 是 D-Claw 的设计：把其他 Agent 包装成 MCP 工具。

```javascript
// 调用方式
mcp__domain_agent__analyze({
  agent_name: "performance",
  question: "分析这个 ANR...",
  context: { file: "xxx" }
})
```

**懒加载** = 只在需要时才读取，不提前加载到上下文。

```
用户输入 → 主 Agent LLM 决定调用哪个 Agent → 此时才加载详细路由规则
```

---

## 二、D-Claw 路由规则参考

### 2.1 两类能力来源

| 类型 | 本质 | 调用方式 |
|------|------|----------|
| Domain Agent | 独立 Agent 进程，有独立 context + 领域知识 | `domain_agent_analyze` MCP 工具 |
| MCP Server | 无状态工具调用，共享主 Agent context | `mcp__<name>__*` 工具 |

### 2.2 各 Agent 路由条件

| Agent | 触发关键词 / 场景 |
|-------|-----------------|
| Performance | 卡顿、启动慢、ANR、CPU/内存/IO、trace 文件、数仓查询、源码归因、patch |
| Game | 游戏帧率/FPS、游戏卡顿、游戏触控延迟、SurfaceFlinger 游戏场景 |
| Stability | 内核 panic/oops、OOM、hardlockup、crash、dmesg |
| Modem | 蜂窝网络、无服务/脱网、通话异常、数据断流、5G 信号 |
| Power | 功耗、温控、电池、wakelock、standby、suspend |
| Audio | 无声、杂音、蓝牙音频、录音、音效、视频播放 |
| Display | 花屏/绿线/撕裂、GPU/HWC/SurfaceFlinger、触摸输入、亮灭屏 |
| Black-Flicker-Glitch | 黑屏、白屏、闪屏、闪烁 |
| Desktop | 桌面布局/动画异常、图标丢失、Launcher |
| Framework | 动效体系、切换/过渡动画异常 |
| System UI | 状态栏、导航栏、通知栏、锁屏 |
| DFX | 可靠性/稳定性分析、故障诊断、根因分析 |
| 直接 MCP | 反馈查询、Jira、MiSight 等无状态工具 |

### 2.3 路由优先级

1. 性能类优先判断是否为游戏场景 → 是则走 Game Agent，否则走 Performance Agent
2. 显示类问题中，黑白花闪有专属 Agent，其余走 Display Agent
3. 无法路由时，直接使用对应 MCP 工具

---

## 三、设计目标

### 3.1 核心需求

1. **统一入口** - 一个平台管理多个 Agent（路由式入口，非分 Agent 选择）
2. **路由功能** - 智能识别任务，分发到对应 Agent
3. **统一管理** - 管理各 Agent 的元信息（skills/kb 权限隔离）
4. **两种调用方式**（同等重要）：
   - **Web UI**：路由式入口，用户输入问题后自动路由到对应 Agent
   - **Claude Code CLI**：通过 MCP 协议集成，让 Claude Code 作为主 Agent 调度各领域 Agent

### 3.2 两种调用方式详解

#### 3.2.1 Web UI 方式

```
用户访问 Router UI → 输入问题 → 路由引擎分析 → 显示推荐 Agent → 用户确认 → 进入对话
```

**适用场景**：
- 非 Claude Code 用户
- Web 端快速查询
- 可视化 Agent 选择

#### 3.2.2 Claude Code CLI 方式

```
Claude Code → MCP 工具调用 → Router API → 路由到领域 Agent → 返回结果到 CLI
```

**适用场景**：
- 开发者在终端使用 Claude Code
- 主 Agent 委托子任务给领域 Agent
- 自动化工作流集成

**MCP 工具列表**：
| 工具名称 | 功能 |
|----------|------|
| `mcp__router__list_agents` | 列出可用 Agent |
| `mcp__router__find_agent` | 根据问题找合适的 Agent |
| `mcp__router__call_agent` | 调用指定 Agent |
| `mcp__router__get_agent_info` | 获取 Agent 详细信息 |
| `mcp__router__route_and_call` | 自动路由并调用（一步完成） |

### 3.3 设计约束

1. **独立部署** - 新平台作为独立模块（`router/` 目录），不侵入现有代码
2. **端口隔离** - 不影响现有端口：
   - 4301：现有 UI (team-a)
   - 4302：新 UI (team-a-new)
   - 新端口：Router UI (4303)、Router API (4000)
3. **权限隔离** - 每个 Agent 的 skills/kb 只有该 Agent 可见
4. **向后兼容** - 现有 UI/API 保持可用

---

## 四、架构设计

### 4.1 整体架构

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         新架构 (多团队统一管理)                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Router Platform (新增独立模块)                     │   │
│  │                                                                      │   │
│  │  ┌─────────────────┐                                                │   │
│  │  │ Router UI       │ :4303 (新增)                                   │   │
│  │  │ (复制现有UI改造) │                                                │   │
│  │  └────────┬────────┘                                                │   │
│  │           │                                                          │   │
│  │           ▼                                                          │   │
│  │  ┌─────────────────┐    ┌─────────────┐    ┌─────────────┐          │   │
│  │  │ Router API      │    │ Agent       │    │ Routing     │          │   │
│  │  │ :4000           │◄──►│ Registry    │    │ Engine      │          │   │
│  │  │                 │    │ (统一管理)   │    │ (路由决策)   │          │   │
│  │  └────────┬────────┘    └─────────────┘    └─────────────┘          │   │
│  │           │                                                          │   │
│  │           │ HTTP 代理 / MCP 调用                                      │   │
│  │           │                                                          │   │
│  └───────────┼──────────────────────────────────────────────────────────┘   │
│              │                                                              │
│              ├──────────────────────┬──────────────────────┐                │
│              ▼                      ▼                      ▼                │
│  ┌───────────────────┐    ┌───────────────────┐    ┌───────────────────┐    │
│  │     Team A        │    │     Team B        │    │     Team C        │    │
│  │ ┌───────────────┐ │    │ ┌───────────────┐ │    │ ┌───────────────┐ │    │
│  │ │ OpenCode:4101 │ │    │ │ OpenCode:4102 │ │    │ │ OpenCode:4103 │ │    │
│  │ │ API:4201      │ │    │ │ API:4202      │ │    │ │ API:4203      │ │    │
│  │ │ UI:4301       │ │    │ │ UI:4302       │ │    │ │ UI:4304       │ │    │
│  │ └───────────────┘ │    │ └───────────────┘ │    │ └───────────────┘ │    │
│  │ skills/kb (隔离)  │    │ skills/kb (隔离)  │    │ skills/kb (隔离)  │    │
│  └───────────────────┘    └───────────────────┘    └───────────────────┘    │
│                                                                             │
│  端口规划:                                                                   │
│  - 4000: Router API                                                        │
│  - 4303: Router UI (路由式入口)                                              │
│  - 4301/4302: 现有 UI (保持不变)                                             │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 目录结构设计

```
/data/agent_harness/
├── router/                          # 新增：路由平台独立模块
│   ├── server.js                    # Router API Server
│   ├── package.json
│   ├── config/
│   │   ├── agents.yaml              # Agent 注册配置
│   │   └── routes.yaml              # 路由规则配置
│   ├── lib/
│   │   ├── agentRegistry.js         # Agent 注册表 (统一管理)
│   │   ├── router.js                # 路由引擎
│   │   ├── agentClient.js           # Agent 调用客户端
│   │   └── mcpServer.js             # MCP Server (Claude Code 集成)
│   ├── routes/
│   │   ├── agentRoutes.js           # Agent 相关路由
│   │   ├── sessionRoutes.js         # 会话路由
│   │   └── chatRoutes.js            # 对话路由
│   └── Dockerfile                   # Router 镜像
│
├── src/
│   ├── api/                         # 现有 API (保持不变)
│   ├── ui/                          # 现有 UI (保持不变)
│   ├── ui_router/                   # 新增：路由式 UI
│   │   ├── src/
│   │   │   ├── App.jsx              # 改造：路由式入口
│   │   │   ├── ChatView.jsx         # 复用：聊天界面
│   │   │   └── components/
│   │   ├── package.json
│   │   └── vite.config.js
│   └── memory/                      # 现有记忆系统
│
├── teams/                           # 现有：各团队目录
│   ├── team-a/
│   ├── team-b/
│   └── team-c/
│
└── docker-compose.yml               # 更新：添加 router 服务
```

### 4.3 核心组件设计

#### 4.3.1 Agent Registry (统一管理)

**职责**：管理各 Agent 的元信息，权限隔离。

**配置文件 (`config/agents.yaml`)：**

```yaml
agents:
  team-a:
    name: "Team A Agent"
    description: "研发助手，专注于 ARM CPU 和嵌入式开发"
    endpoint: "http://api-team-a:3000"
    healthCheck: "/health"
    
    # 路由关键词 (参考 D-Claw)
    routing:
      keywords:
        - "ARM"
        - "CPU"
        - "功耗"
        - "嵌入式"
        - "芯片"
      priority: 10  # 路由优先级
    
    # 该 Agent 独有的资源 (权限隔离)
    resources:
      skills:
        - name: "soc-power-prediction"
          description: "SoC 功耗预测技能"
      kb:
        - name: "ARM_TRM_CPU"
          description: "ARM CPU 技术参考手册"
    
    # 元数据
    metadata:
      owner: "team-a@example.com"
      created: "2024-03-01"
      tags: ["研发", "嵌入式", "芯片"]

  team-b:
    name: "Team B Agent"
    description: "测试助手，专注于测试用例和自动化测试"
    endpoint: "http://api-team-b:3000"
    healthCheck: "/health"
    
    routing:
      keywords:
        - "测试"
        - "用例"
        - "自动化"
        - "测试框架"
      priority: 10
    
    resources:
      skills:
        - name: "test-automation"
          description: "自动化测试技能"
      kb:
        - name: "test-cases"
          description: "测试用例知识库"
    
    metadata:
      owner: "team-b@example.com"
      created: "2024-03-01"
      tags: ["测试", "自动化"]
```

**API：**

```javascript
class AgentRegistry {
  // 获取所有 Agent 列表 (不含敏感信息)
  async listAgents() { ... }
  
  // 根据 ID 获取 Agent 详情
  async getAgent(agentId) { ... }
  
  // 搜索匹配的 Agent (用于路由)
  async findAgents(query, context) { ... }
  
  // 健康检查
  async healthCheck(agentId) { ... }
  
  // 获取 Agent 的资源 (权限隔离)
  async getAgentResources(agentId) { ... }
  
  // 动态注册 Agent
  async registerAgent(config) { ... }
  
  // 更新 Agent 配置
  async updateAgent(agentId, config) { ... }
}
```

#### 4.3.2 Router Engine (路由引擎)

**职责**：根据用户输入选择合适的 Agent。

**路由流程**：

```
用户输入
    │
    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Router Engine                                                       │
│                                                                      │
│  1. 关键词匹配                                                        │
│     - 遍历所有 Agent 的 routing.keywords                             │
│     - 计算匹配分数                                                    │
│                                                                      │
│  2. 上下文增强 (可选)                                                 │
│     - 结合历史对话                                                    │
│     - 用户偏好                                                        │
│                                                                      │
│  3. LLM 辅助路由 (可选，高精度场景)                                    │
│     - 调用 helper model 判断意图                                      │
│     - 返回最佳 Agent + 置信度                                        │
│                                                                      │
│  4. 综合评分                                                          │
│     - 返回推荐 Agent + 备选列表                                       │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
    │
    ▼
返回 { agentId, confidence, alternatives }
```

**路由规则格式 (`config/routes.yaml`)：**

```yaml
# 路由规则 (参考 D-Claw)
rules:
  # 优先级规则
  - name: "performance_vs_game"
    condition: "性能问题"
    priority_check:
      - keywords: ["游戏", "FPS", "Game"]
        target: "game-agent"
      - keywords: ["卡顿", "ANR", "启动慢"]
        target: "performance-agent"
  
  - name: "display_issues"
    condition: "显示问题"
    priority_check:
      - keywords: ["黑屏", "白屏", "闪屏", "闪烁"]
        target: "black-flicker-glitch-agent"
      - keywords: ["花屏", "绿线", "撕裂", "GPU"]
        target: "display-agent"

# 默认规则
default:
  - when_unsure: "ask_user"  # 或 "route_to_default_agent"
```

**API：**

```javascript
class Router {
  constructor(registry, config) {
    this.registry = registry;
    this.config = config;
  }
  
  // 主路由方法
  async route(userMessage, context = {}) {
    // 1. 关键词匹配
    const keywordMatches = await this.matchKeywords(userMessage);
    
    // 2. 应用优先级规则
    const prioritized = this.applyPriorityRules(keywordMatches, context);
    
    // 3. 可选：LLM 辅助
    if (this.config.useLLMRouting && prioritized.length === 0) {
      return await this.llmRoute(userMessage);
    }
    
    // 4. 返回结果
    return {
      agentId: prioritized[0]?.agentId,
      confidence: prioritized[0]?.score,
      alternatives: prioritized.slice(1, 3),
    };
  }
  
  // 构建 System Prompt 中的路由规则 (参考 D-Claw)
  buildRoutingPrompt() {
    const agents = this.registry.listAgents();
    return `
## Agent 路由规则

根据用户消息选择合适的 Agent：

| 关键词 | Agent | 说明 |
|--------|-------|------|
${agents.map(a => `| ${a.routing.keywords.join('/')} | ${a.id} | ${a.description} |`).join('\n')}

如果不确定，选择最相关的 Agent 或询问用户确认。
`;
  }
}
```

#### 4.3.3 Agent Client (Agent 调用客户端)

**职责**：调用目标 Agent，支持 HTTP 代理和 MCP 两种方式。

**HTTP 代理模式**（用于 Web 客户端）：

```javascript
class AgentClient {
  // 流式调用 Agent
  async streamCall(agentId, sessionId, message, res) {
    const agent = await this.registry.getAgent(agentId);
    
    // 设置 SSE headers
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    
    // 转发到目标 Agent
    const response = await fetch(`${agent.endpoint}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionId, message }),
    });
    
    // SSE 流式转发
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      const chunk = decoder.decode(value);
      res.write(chunk);
    }
    
    res.end();
  }
  
  // 创建会话
  async createSession(agentId) {
    const agent = await this.registry.getAgent(agentId);
    const response = await fetch(`${agent.endpoint}/sessions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    return response.json();
  }
  
  // 获取会话历史
  async getSession(agentId, sessionId) {
    const agent = await this.registry.getAgent(agentId);
    const response = await fetch(`${agent.endpoint}/sessions/${sessionId}`);
    return response.json();
  }
}
```

#### 4.3.4 MCP Server (Claude Code 集成)

**职责**：提供 MCP 协议接口，让 Claude Code 可以调用 Router。

**MCP 工具定义**：

```javascript
// router/mcpServer.js

const MCPServer = require('@anthropic/mcp-server');

const server = new MCPServer({
  name: "agent-router",
  version: "1.0.0",
  tools: [
    {
      name: "list_agents",
      description: "列出所有可用的 Agent",
      inputSchema: { type: "object", properties: {} },
      handler: async () => {
        const agents = await registry.listAgents();
        return agents.map(a => ({
          id: a.id,
          name: a.name,
          description: a.description,
          keywords: a.routing.keywords,
        }));
      }
    },
    {
      name: "find_agent",
      description: "根据用户问题找到最合适的 Agent",
      inputSchema: {
        type: "object",
        properties: {
          query: { type: "string", description: "用户问题或关键词" }
        },
        required: ["query"]
      },
      handler: async ({ query }) => {
        const result = await router.route(query);
        return result;
      }
    },
    {
      name: "call_agent",
      description: "调用指定 Agent 进行对话",
      inputSchema: {
        type: "object",
        properties: {
          agent_id: { type: "string", description: "Agent ID" },
          message: { type: "string", description: "要发送的消息" },
          session_id: { type: "string", description: "会话 ID (可选)" }
        },
        required: ["agent_id", "message"]
      },
      handler: async ({ agent_id, message, session_id }) => {
        // 创建或复用会话
        const sessionId = session_id || await agentClient.createSession(agent_id);
        
        // 调用 Agent
        const response = await agentClient.call(agent_id, sessionId, message);
        return response;
      }
    },
    {
      name: "get_agent_info",
      description: "获取 Agent 的详细信息，包括其 skills 和 kb",
      inputSchema: {
        type: "object",
        properties: {
          agent_id: { type: "string" }
        },
        required: ["agent_id"]
      },
      handler: async ({ agent_id }) => {
        const agent = await registry.getAgent(agent_id);
        const resources = await registry.getAgentResources(agent_id);
        return { ...agent, resources };
      }
    }
  ]
});

server.start();
```

**Claude Code 配置示例**：

```json
// opencode.json 中添加
{
  "mcpServers": {
    "agent-router": {
      "command": "node",
      "args": ["/data/agent_harness/router/mcpServer.js"],
      "env": {
        "ROUTER_API_URL": "http://localhost:4000"
      }
    }
  }
}
```

---

## 五、API 设计

### 5.1 Router API 端点

| 端点 | 方法 | 描述 | 权限 |
|------|------|------|------|
| `/health` | GET | 健康检查 | 公开 |
| `/agents` | GET | 列出所有 Agent | 公开 |
| `/agents/:id` | GET | 获取 Agent 详情 | 公开 |
| `/agents/:id/resources` | GET | 获取 Agent 资源 (skills/kb) | 公开 |
| `/route` | POST | 智能路由 (返回推荐 Agent) | 公开 |
| `/sessions` | POST | 创建会话 | 公开 |
| `/sessions/:id` | GET | 获取会话 (自动路由到正确 Agent) | 公开 |
| `/chat` | POST | 对话 (自动路由或指定 Agent) | 公开 |
| `/agents/:id/proxy/*` | ALL | 代理到目标 Agent (内部使用) | 内部 |

### 5.2 核心 API 示例

#### POST /route - 智能路由

```javascript
// 请求
{
  "message": "帮我分析一下 ARM CPU 的功耗问题",
  "context": {
    "sessionId": "xxx",  // 可选，历史上下文
    "userId": "xxx"      // 可选，用户偏好
  }
}

// 响应
{
  "recommendedAgent": {
    "id": "team-a",
    "name": "Team A Agent",
    "confidence": 0.85
  },
  "alternatives": [
    { "id": "team-c", "name": "Team C Agent", "confidence": 0.3 }
  ],
  "reasoning": "匹配关键词: ARM, CPU, 功耗"
}
```

#### POST /chat - 对话

```javascript
// 请求 - 自动路由
{
  "message": "帮我分析一下 ARM CPU 的功耗问题",
  "autoRoute": true  // 自动路由
}

// 请求 - 指定 Agent
{
  "message": "帮我分析一下 ARM CPU 的功耗问题",
  "agentId": "team-a",  // 指定 Agent
  "sessionId": "xxx"    // 可选，复用会话
}

// 响应 - SSE 流
data: {"type": "text", "content": "正在分析..."}
data: {"type": "tool", "name": "grep", "status": "running"}
data: {"type": "text", "content": "根据分析结果..."}
data: {"type": "done"}
```

---

## 六、UI 设计

### 6.1 Router UI (端口 4303)

**设计思路**：复制现有 UI 到 `src/ui_router/`，改造为路由式入口。

**关键改动**：

```
现有 UI 流程:
用户访问 → 选择 Team → 进入对话

Router UI 流程:
用户访问 → 输入问题 → 显示推荐 Agent → 确认/切换 → 对话
```

**界面结构**：

```
┌─────────────────────────────────────────────────────────────────────┐
│  Agent Router                                           [设置] [帮助] │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                                                             │   │
│  │  欢迎使用 Agent Router                                       │   │
│  │                                                             │   │
│  │  请输入您的问题，我会帮您找到最合适的 Agent                    │   │
│  │                                                             │   │
│  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │  │                                                     │   │   │
│  │  │  输入您的问题...                          [发送] ▶   │   │   │
│  │  │                                                     │   │   │
│  │  └─────────────────────────────────────────────────────┘   │   │
│  │                                                             │   │
│  │  可用 Agent:                                               │   │
│  │  ┌───────────┐ ┌───────────┐ ┌───────────┐                │   │
│  │  │ Team A    │ │ Team B    │ │ Team C    │                │   │
│  │  │ 研发助手  │ │ 测试助手  │ │ 运维助手  │                │   │
│  │  └───────────┘ └───────────┘ └───────────┘                │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  历史会话:                                                          │
│  ┌───────────────────────────────────────────────────────────────┐ │
│  │ 🔹 ARM CPU 功耗分析 - Team A (昨天)                           │ │
│  │ 🔹 测试用例生成 - Team B (3天前)                               │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**路由确认界面**：

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  您的问题: "帮我分析一下 ARM CPU 的功耗问题"                          │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  推荐 Agent:                                                │   │
│  │                                                             │   │
│  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │  │ ⭐ Team A Agent (推荐度: 85%)                        │   │   │
│  │  │   研发助手，专注于 ARM CPU 和嵌入式开发               │   │   │
│  │  │   匹配关键词: ARM, CPU, 功耗                         │   │   │
│  │  └─────────────────────────────────────────────────────┘   │   │
│  │                                                             │   │
│  │  其他可选 Agent:                                            │   │
│  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │  │   Team C Agent (推荐度: 30%)                         │   │   │
│  │  │   运维助手，专注于系统运维                            │   │   │
│  │  └─────────────────────────────────────────────────────┘   │   │
│  │                                                             │   │
│  │  [使用推荐 Agent]  [选择其他 Agent]  [取消]                 │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 七、端口规划

| 服务 | 端口 | 说明 | 状态 |
|------|------|------|------|
| opencode-team-a | 4101 | Agent Runtime | 现有 |
| api-team-a | 4201 | REST API | 现有 |
| ui-team-a | 4301 | Web Frontend (旧) | 现有 |
| ui-team-a-new | 4302 | Web Frontend (新) | 现有 |
| **router-api** | **4000** | Router API | **新增** |
| **router-ui** | **4303** | Router Frontend | **新增** |

---

## 八、Docker Compose 更新

```yaml
# docker-compose.yml 新增服务

services:
  # ===========================================================================
  # Router Platform (新增)
  # ===========================================================================
  
  router-api:
    build:
      context: .
      dockerfile: router/Dockerfile
    ports:
      - "4000:3000"
    environment:
      - CONFIG_PATH=/config
      - ROUTER_UI_URL=http://router-ui:80
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

  router-ui:
    build:
      context: .
      dockerfile: deploy/Dockerfile.ui
      args:
        - TEAM_ID=router  # 指向 dist/router/
    ports:
      - "4303:80"
    environment:
      - API_UPSTREAM_URL=http://router-api:3000
    depends_on:
      - router-api
    restart: unless-stopped
```

---

## 九、实施计划

### Phase 1: 基础框架 (3-5 天)

**目标**：搭建 Router API 骨架

| 任务 | 详情 | 产出 |
|------|------|------|
| 1.1 创建目录结构 | `router/` 目录及子目录 | 目录结构 |
| 1.2 实现 AgentRegistry | 读取 agents.yaml，提供 CRUD API | `lib/agentRegistry.js` |
| 1.3 实现 Router | 关键词匹配路由 | `lib/router.js` |
| 1.4 实现 AgentClient | HTTP 代理 + SSE 流式转发 | `lib/agentClient.js` |
| 1.5 实现 Router API | 核心 API 端点 | `server.js` + `routes/` |
| 1.6 Docker 化 | 编写 Dockerfile，更新 docker-compose | `router/Dockerfile` |

**验收标准**：
- `POST /route` 能正确返回推荐 Agent
- `POST /chat` 能代理到目标 Agent 并返回流式响应

### Phase 2: MCP Server (2-3 天)

**目标**：支持 Claude Code 集成

| 任务 | 详情 | 产出 |
|------|------|------|
| 2.1 实现 MCP Server | 暴露 list_agents, find_agent, call_agent 工具 | `lib/mcpServer.js` |
| 2.2 测试 MCP 集成 | 在 Claude Code 中配置并测试 | 测试报告 |
| 2.3 编写集成文档 | AGENTS.md 模板，使用示例 | 文档 |

**验收标准**：
- Claude Code 能通过 `mcp__router__*` 工具调用 Router

### Phase 3: Router UI (3-5 天)

**目标**：路由式 Web 界面

| 任务 | 详情 | 产出 |
|------|------|------|
| 3.1 复制 UI | 复制 src/ui 到 src/ui_router | 目录 |
| 3.2 改造入口 | 去掉 Team 选择，改为问题输入 | `App.jsx` |
| 3.3 添加路由确认 | 显示推荐 Agent，支持切换 | 新组件 |
| 3.4 适配 Router API | API 调用改为 Router API | API 层 |
| 3.5 构建 & 部署 | 构建产物到 dist/router/，添加 Docker 服务 | 部署配置 |

**验收标准**：
- 用户输入问题后能看到推荐 Agent
- 对话能正常进行

### Phase 4: 完善与测试 (2-3 天)

| 任务 | 详情 | 产出 |
|------|------|------|
| 4.1 健康检查 | 添加 Agent 健康检查，自动降级 | 功能 |
| 4.2 错误处理 | 完善 API 错误处理 | 功能 |
| 4.3 日志系统 | 添加结构化日志 | 功能 |
| 4.4 文档完善 | 更新 README，部署文档 | 文档 |

---

## 十、风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| 路由精度不足 | 任务分发错误 | 中 | 提供 Agent 选择确认界面；LLM 辅助路由 |
| Agent 不可用 | 服务中断 | 低 | 健康检查 + 自动降级到其他 Agent |
| 网络延迟 | 用户体验差 | 低 | 本地缓存 + 超时控制 |
| 配置复杂 | 运维困难 | 中 | 提供配置 UI + 自动发现 |
| 现有 UI 改造工作量 | 延期 | 中 | 先实现 API，UI 可迭代优化 |

---

## 十一、附录

### A. D-Claw 路由规则完整参考

| Agent | 触发关键词 |
|-------|-----------|
| Performance | 卡顿、启动慢、ANR、CPU/内存/IO、trace 文件、数仓查询、源码归因、patch |
| Game | 游戏帧率/FPS、游戏卡顿、游戏触控延迟、SurfaceFlinger 游戏场景 |
| Stability | 内核 panic/oops、OOM、hardlockup、crash、dmesg |
| Modem | 蜂窝网络、无服务/脱网、通话异常、数据断流、5G 信号、VoLTE/VoWiFi/VT |
| Power | 功耗、温控、电池、wakelock、standby、suspend |
| Audio | 无声、杂音、蓝牙音频、录音、音效、视频播放 |
| Display | 花屏/绿线/撕裂、GPU/HWC/SurfaceFlinger 合成、触摸输入、亮灭屏/亮度 |
| Black-Flicker-Glitch | 黑屏、白屏、闪屏、闪烁、壁纸黑屏、转场/解锁/启动黑屏 |
| Desktop | 桌面布局/动画异常、图标丢失、Launcher/HyperLauncher、壁纸黑屏 |
| Framework | 动效体系、切换/过渡动画异常、Transition 堆积 |
| System UI | 状态栏、导航栏、通知栏、锁屏、音量面板 |
| DFX | 可靠性/稳定性分析、故障诊断、根因分析、反馈标签识别/分类 |

### B. 端口汇总

| 端口 | 服务 | 类型 |
|------|------|------|
| 4000 | Router API | 新增 |
| 4101 | OpenCode Team A | 现有 |
| 4201 | API Team A | 现有 |
| 4301 | UI Team A | 现有 |
| 4302 | UI Team A New | 现有 |
| 4303 | Router UI | 新增 |

### C. 待确认事项

1. **LLM 辅助路由**：是否需要？如果需要，使用哪个模型？
2. **会话持久化**：Router 层是否需要持久化会话？还是完全代理？
3. **认证授权**：是否需要统一认证？还是沿用各 Agent 现有机制？
4. **日志追踪**：是否需要跨 Agent 的请求追踪（trace ID）？

---

## 审核确认

请确认以下关键点后开始实施：

- [ ] 端口规划 (4000, 4303) 是否合适？
- [ ] 目录结构 (`router/`, `src/ui_router/`) 是否符合预期？
- [ ] Phase 1-4 的实施顺序是否合理？
- [ ] 是否需要 LLM 辅助路由？
- [ ] 其他需要调整的地方？

确认后我将开始 Phase 1 的实现。
