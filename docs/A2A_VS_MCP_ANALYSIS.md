# A2A 协议深度分析与 MCP 对比报告

> 分析日期：2026-04-16
> 分析对象：Google A2A (Agent2Agent) Protocol v1.0
> 目的：评估 Agent Harness Router 项目是否适合采用 A2A 协议

---

## 一、A2A 协议概述

### 1.1 什么是 A2A

Agent2Agent (A2A) 是由 Google 开发并捐赠给 Linux 基金会的开放协议，旨在实现 AI Agent 之间的通信和互操作。

**核心定位**：
> "An open protocol enabling communication and interoperability between opaque agentic applications."
> 
> 一个开放协议，使不透明的代理应用之间能够通信和互操作。

### 1.2 设计目标

| 目标 | 说明 |
|------|------|
| **互操作性** | 连接不同框架构建的 Agent（LangGraph, CrewAI, Semantic Kernel 等） |
| **协作能力** | Agent 可以委托子任务、交换信息、协调行动 |
| **安全性** | Agent 交互无需共享内部记忆、工具或专有逻辑 |
| **异步优先** | 原生支持长时间运行的任务和人机交互场景 |
| **企业就绪** | 支持认证、授权、安全、隐私、追踪和监控 |

### 1.3 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 3: Protocol Bindings (协议绑定层)                      │
│  ├── JSON-RPC Methods                                        │
│  ├── gRPC RPCs                                               │
│  ├── HTTP/REST Endpoints                                     │
│  └── Custom Bindings                                         │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Abstract Operations (抽象操作层)                    │
│  ├── Send Message                                            │
│  ├── Stream Message                                          │
│  ├── Get Task / List Tasks / Cancel Task                     │
│  └── Push Notification Config                                │
├─────────────────────────────────────────────────────────────┤
│  Layer 1: Canonical Data Model (规范数据模型层)               │
│  ├── Task (任务)                                              │
│  ├── Message (消息)                                           │
│  ├── Part (内容片段)                                          │
│  ├── Artifact (产物)                                          │
│  └── AgentCard (Agent 卡片)                                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、A2A 核心概念详解

### 2.1 Agent Card（Agent 卡片）

Agent Card 是 Agent 的"数字名片"，是一个 JSON 元数据文档，包含：

```json
{
  "name": "Recipe Agent",
  "description": "Agent that helps users with recipes and cooking.",
  "version": "1.0.0",
  "supportedInterfaces": [
    {
      "url": "https://api.example.com/a2a/v1",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "capabilities": {
    "streaming": true,
    "pushNotifications": true
  },
  "skills": [
    {
      "id": "recipe-search",
      "name": "Recipe Search",
      "description": "Search for recipes based on ingredients",
      "tags": ["cooking", "recipes", "food"],
      "examples": ["Find recipes with chicken and rice"]
    }
  ],
  "securitySchemes": { ... },
  "defaultInputModes": ["text/plain", "application/json"],
  "defaultOutputModes": ["text/plain", "application/json"]
}
```

**关键作用**：
- Agent 发现和能力声明
- 交互模式协商
- 安全要求声明

### 2.2 Task（任务）

Task 是 A2A 的核心工作单元，具有完整的生命周期：

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  SUBMITTED  │ ──► │   WORKING   │ ──► │  COMPLETED  │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ├──► INPUT_REQUIRED (等待输入)
                           ├──► AUTH_REQUIRED (需要认证)
                           ├──► FAILED (失败)
                           ├──► CANCELED (取消)
                           └──► REJECTED (拒绝)
```

**Task 结构**：
```json
{
  "id": "task-uuid",
  "contextId": "conversation-uuid",
  "status": {
    "state": "TASK_STATE_WORKING",
    "message": { ... },
    "timestamp": "2026-04-16T10:00:00Z"
  },
  "artifacts": [ ... ],
  "history": [ ... ],
  "metadata": { ... }
}
```

### 2.3 Message 与 Part

**Message** 代表一轮对话，包含角色（user/agent）和多个 Part：

```json
{
  "messageId": "msg-uuid",
  "contextId": "conversation-uuid",
  "taskId": "task-uuid",
  "role": "user",
  "parts": [
    { "text": "请分析这个文件" },
    { "url": "https://example.com/file.pdf", "mediaType": "application/pdf" }
  ]
}
```

**Part 类型**：
| 类型 | 字段 | 用途 |
|------|------|------|
| 文本 | `text` | 纯文本内容 |
| 二进制 | `raw` | 内联文件数据（Base64） |
| 引用 | `url` | 外部文件 URL |
| 结构化 | `data` | JSON 对象/数组 |

### 2.4 Artifact（产物）

Artifact 是 Task 的输出结果：

```json
{
  "artifactId": "artifact-uuid",
  "name": "analysis_report.pdf",
  "description": "分析报告",
  "parts": [
    { "raw": "base64...", "mediaType": "application/pdf" }
  ]
}
```

### 2.5 交互模式

A2A 支持三种交互模式：

| 模式 | 描述 | 适用场景 |
|------|------|----------|
| **Request/Response** | 同步请求，轮询获取结果 | 简单查询 |
| **SSE Streaming** | Server-Sent Events 实时流 | 长任务进度、增量结果 |
| **Push Notifications** | Webhook 异步推送 | 超长任务、断连场景 |

---

## 三、A2A 与 MCP 深度对比

### 3.1 核心差异

| 维度 | A2A | MCP |
|------|-----|-----|
| **通信对象** | Agent ↔ Agent | Agent ↔ Tool/Resource |
| **抽象层级** | 应用层协议 | 工具调用协议 |
| **对端特性** | 不透明、有状态、自治 | 透明、无状态、被动 |
| **交互模式** | 对话式、多轮、协作 | 函数调用式、单次执行 |
| **状态管理** | Task 有完整生命周期 | 无状态概念 |
| **发现机制** | Agent Card 声明能力 | 工具列表 + Schema |
| **传输协议** | HTTP + JSON-RPC / gRPC | JSON-RPC over stdio/SSE |
| **流式支持** | 原生 SSE + Push | SSE (2025-03-26 版本) |
| **标准组织** | Linux Foundation | Anthropic |

### 3.2 架构定位对比

```
                    ┌─────────────────────────────────────────┐
                    │              用户/应用                   │
                    └─────────────────┬───────────────────────┘
                                      │
                    ┌─────────────────▼───────────────────────┐
                    │           Client Agent                   │
                    │  (协调者/主 Agent)                        │
                    └─────────┬───────────────┬────────────────┘
                              │               │
         ┌────────────────────┘               └────────────────────┐
         │ A2A                                                     │ A2A
         ▼                                                         ▼
┌─────────────────┐                                     ┌─────────────────┐
│  Remote Agent A │                                     │  Remote Agent B │
│  (领域 Agent)    │                                    │  (领域 Agent)    │
└────────┬────────┘                                     └────────┬────────┘
         │ MCP                                                   │ MCP
         ▼                                                       ▼
┌─────────────────┐                                     ┌─────────────────┐
│ Tools/Resources │                                     │ Tools/Resources │
│ - Database      │                                     │ - API           │
│ - File System   │                                     │ - Calculator    │
└─────────────────┘                                     └─────────────────┘
```

**关键洞察**：
- **MCP** = Agent 如何使用工具（垂直集成）
- **A2A** = Agent 如何与 Agent 协作（水平互联）

### 3.3 详细对比表

#### 3.3.1 协议层面对比

| 特性 | A2A | MCP |
|------|-----|-----|
| **协议版本** | v1.0.0 (2025) | v2025-03-26 |
| **消息格式** | JSON-RPC 2.0 | JSON-RPC 2.0 |
| **传输** | HTTP(S) / gRPC | stdio / SSE / Streamable HTTP |
| **Schema 定义** | Protocol Buffers | JSON Schema |
| **扩展机制** | AgentExtension URI | 自定义 Tools |

#### 3.3.2 语义层面对比

| 概念 | A2A | MCP |
|------|-----|-----|
| **能力声明** | AgentCard (skills, capabilities) | tools/list (name, inputSchema) |
| **调用入口** | SendMessage | tools/call |
| **返回结果** | Task / Message / Artifact | Tool Result (content) |
| **状态追踪** | Task lifecycle (7 states) | 无 |
| **上下文** | contextId 跨 Task 关联 | Session (实现相关) |
| **流式** | TaskStatusUpdateEvent / TaskArtifactUpdateEvent | SSE events |

#### 3.3.3 安全层面对比

| 安全特性 | A2A | MCP |
|----------|-----|-----|
| **认证声明** | AgentCard.securitySchemes | 无标准声明 |
| **认证传递** | HTTP Headers | 实现/传输层处理 |
| **支持方案** | API Key, HTTP Auth, OAuth2, OIDC, mTLS | 传输层安全 |
| **Push 安全** | JWT + JWKS 签名验证 | N/A |

### 3.4 互补关系

A2A 和 MCP **不是竞争关系，而是互补关系**：

```
┌─────────────────────────────────────────────────────────────────────┐
│                    完整的 Agentic 架构                               │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                      A2A 层                                   │  │
│  │   Agent-to-Agent 通信、协作、任务委托                          │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                      Agent 层                                 │  │
│  │   每个独立 Agent 的内部逻辑、推理、规划                         │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                              │                                      │
│                              ▼                                      │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                      MCP 层                                   │  │
│  │   Agent-to-Tool 通信、资源访问、工具调用                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**示例场景**（汽车修理店）：
1. **用户 → Agent (A2A)**：顾客说"我的车有异响"
2. **Agent A → Agent B (A2A)**：经理 Agent 委托给技师 Agent
3. **Agent B → Tool (MCP)**：技师 Agent 调用诊断扫描工具
4. **Agent B → Agent C (A2A)**：技师 Agent 向零件供应商 Agent 订购零件

---

## 四、Agent Harness Router 适用性评估

### 4.1 当前架构回顾

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Agent Harness Router 架构                         │
│                                                                     │
│  ┌─────────────────┐                                                │
│  │ Router UI :4303 │  (路由式入口)                                   │
│  └────────┬────────┘                                                │
│           │ HTTP                                                    │
│           ▼                                                         │
│  ┌─────────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Router API :4000│◄──►│ Registry    │    │ Router      │         │
│  │                 │    │ (agents.yaml)│    │ Engine      │         │
│  └────────┬────────┘    └─────────────┘    └─────────────┘         │
│           │ HTTP Proxy / MCP                                          │
│           ├──────────────────────┬──────────────────────┐           │
│           ▼                      ▼                      ▼           │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │ Team A Agent    │    │ Team B Agent    │    │ Team C Agent    │  │
│  │ (芯片研发)       │    │ (芯片验证)       │    │ (其他)          │  │
│  │ API:4201        │    │ API:4202        │    │ API:4203        │  │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 当前实现方式

| 组件 | 当前实现 | 协议 |
|------|----------|------|
| Router → Agent | HTTP Proxy + SSE | 自定义 REST API |
| Claude Code → Router | MCP Tools | MCP (JSON-RPC) |
| Agent 发现 | agents.yaml | 静态配置 |
| 路由决策 | 关键词 + 规则匹配 | 自定义逻辑 |
| 会话管理 | Agent 内部 | 无统一标准 |

### 4.3 A2A 适用性分析

#### 4.3.1 适用场景（推荐采用 A2A）

| 场景 | 当前问题 | A2A 解决方案 |
|------|----------|-------------|
| **Agent 间协作** | 无标准协议，自定义实现 | 标准化的 Task/Message 语义 |
| **任务状态追踪** | 各 Agent 内部管理，不可见 | 统一的 Task 生命周期 |
| **能力发现** | 静态配置，运行时不可更新 | AgentCard 动态声明 |
| **多轮对话** | 各 Agent 自己维护 context | contextId 标准化关联 |
| **长时间任务** | 无标准进度反馈 | SSE Streaming + Push |
| **跨团队互操作** | 需要对接文档 | 协议标准化自动互操作 |

#### 4.3.2 不适用场景（当前方案更合适）

| 场景 | A2A 限制 | 当前方案优势 |
|------|----------|-------------|
| **内部路由** | A2A 面向公开 Agent | 简单 HTTP 足够 |
| **轻量调用** | A2A 有协议开销 | 直接 REST 更轻量 |
| **Claude Code 集成** | Claude Code 原生支持 MCP | MCP 更直接 |
| **工具调用** | A2A 不适合工具调用 | MCP 专为此设计 |

### 4.4 采用策略建议

#### 策略 A：完全采用 A2A（不推荐）

**优点**：
- 完全符合开放标准
- 支持与其他 A2A Agent 互操作

**缺点**：
- 改造成本高
- Claude Code 集成需额外适配层
- 对内部通信过于重量级

#### 策略 B：混合架构（推荐）

**核心思路**：
- **对外暴露**：提供 A2A 接口，允许外部 Agent 接入
- **对内通信**：保持现有 HTTP + MCP 混合模式
- **Router 角色**：A2A Gateway + MCP Server 双重身份

```
┌─────────────────────────────────────────────────────────────────────┐
│                    混合架构建议                                       │
│                                                                     │
│  外部 Agent ──────► A2A Gateway ──────► Router Engine               │
│                           │                                         │
│                           ▼                                         │
│  Claude Code ──────► MCP Server ──────► Router Engine               │
│                           │                                         │
│                           ▼                                         │
│  Web UI ──────────► REST API ────────► Router Engine               │
│                                                │                    │
│                    ┌───────────────────────────┼──────────────────┐ │
│                    │                           ▼                  │ │
│                    │  ┌─────────┐  ┌─────────┐  ┌─────────┐       │ │
│                    │  │ Team A  │  │ Team B  │  │ Team C  │       │ │
│                    │  │(内部HTTP)│  │(内部HTTP)│  │(A2A可选)│       │ │
│                    │  └─────────┘  └─────────┘  └─────────┘       │ │
│                    └──────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

#### 策略 C：暂不采用（观察）

**适用条件**：
- 当前需求已满足
- 无外部 Agent 互操作需求
- 不想引入协议复杂度

---

## 五、实施建议

### 5.1 如果选择采用 A2A

#### 第一阶段：Agent Card 支持

```yaml
# agents.yaml 增强（兼容 A2A AgentCard 格式）
agents:
  team-a:
    name: "Team A Agent"
    description: "芯片研发助手"
    version: "1.0.0"
    
    # A2A 兼容的能力声明
    a2a:
      capabilities:
        streaming: true
        pushNotifications: false
      skills:
        - id: "power-analysis"
          name: "功耗分析"
          description: "ARM CPU 功耗预测和分析"
          tags: ["ARM", "CPU", "功耗", "性能"]
```

#### 第二阶段：A2A 协议适配器

```javascript
// router/lib/a2aAdapter.js
export class A2AAdapter {
  // 将内部 Agent 信息转换为 AgentCard
  toAgentCard(agent) {
    return {
      name: agent.name,
      description: agent.description,
      version: agent.version || "1.0.0",
      supportedInterfaces: [{
        url: agent.endpoint.url,
        protocolBinding: "JSONRPC",
        protocolVersion: "1.0"
      }],
      capabilities: {
        streaming: true,
        pushNotifications: false
      },
      skills: this.toSkills(agent.routing.keywords, agent.resources)
    };
  }
  
  // 将 A2A SendMessage 转换为内部 Chat 请求
  fromSendMessage(request) {
    return {
      agentId: this.routeToAgent(request.message),
      message: this.extractText(request.message.parts),
      sessionId: request.message.contextId
    };
  }
}
```

#### 第三阶段：A2A 端点

```javascript
// A2A 协议端点（JSON-RPC 2.0）
app.post('/a2a', async (req, res) => {
  const { jsonrpc, method, params, id } = req.body;
  
  switch (method) {
    case 'SendMessage':
      const result = await a2aAdapter.handleSendMessage(params);
      res.json({ jsonrpc: "2.0", result, id });
      break;
    
    case 'GetTask':
      const task = await a2aAdapter.handleGetTask(params);
      res.json({ jsonrpc: "2.0", result: task, id });
      break;
      
    // ... 其他方法
  }
});

// Agent Card 端点
app.get('/.well-known/agent-card', (req, res) => {
  res.json(routerAgentCard);
});
```

### 5.2 改造成本估算

| 改造项 | 工作量 | 风险 |
|--------|--------|------|
| AgentCard 支持 | 2-3 天 | 低 |
| JSON-RPC 端点 | 3-5 天 | 中 |
| Task 生命周期 | 5-7 天 | 中 |
| SSE Streaming | 2-3 天 | 低 |
| Push Notifications | 3-5 天 | 中 |
| 测试和文档 | 3-5 天 | 低 |
| **总计** | **18-28 天** | **中** |

---

## 六、结论

### 6.1 核心结论

| 问题 | 回答 |
|------|------|
| A2A 是否适合 Router？ | **部分适合**，适合对外互操作，不适合内部通信 |
| 是否应该立即采用？ | **建议观察**，等待生态成熟 |
| 如何与 MCP 配合？ | A2A 对外，MCP 对 Claude Code，HTTP 对内部 |

### 6.2 关键洞察

1. **A2A 和 MCP 互补**：A2A 解决 Agent 间协作，MCP 解决 Agent 使用工具
2. **A2A 更适合公开互操作**：跨组织、跨框架的 Agent 协作
3. **内部通信无需 A2A**：当前 HTTP + MCP 方案足够高效
4. **可渐进式采用**：先支持 AgentCard，再支持完整协议

### 6.3 行动建议

**短期（当前）**：
- 保持现有架构
- 研究添加 AgentCard 格式的能力声明
- 关注 A2A 生态发展

**中期（3-6 个月）**：
- 评估外部 Agent 接入需求
- 如果有需求，实现 A2A Gateway
- 保持 MCP 支持（Claude Code 集成）

**长期（6+ 个月）**：
- 根据生态成熟度决定深度采用
- 考虑成为 A2A 社区贡献者
- 推动企业级 A2A 最佳实践

---

## 附录

### A. A2A 资源链接

- 官方文档：https://a2a-protocol.org
- GitHub：https://github.com/a2aproject/A2A
- Python SDK：https://github.com/a2aproject/a2a-python
- 规范文件：specification/a2a.proto

### B. MCP 资源链接

- 官方文档：https://modelcontextprotocol.io
- 规范：https://spec.modelcontextprotocol.io
- Python SDK：https://github.com/modelcontextprotocol/python-sdk

### C. 相关概念对照表

| A2A 概念 | MCP 对应 | 说明 |
|----------|----------|------|
| AgentCard | tools/list 响应 | 能力声明方式不同 |
| SendMessage | tools/call | 语义不同（对话 vs 调用） |
| Task | 无 | A2A 特有 |
| Message | 无 | A2A 特有 |
| Part | Tool Result Content | 类似的复合结构 |
| contextId | Session ID | 概念相似 |
| Artifact | 无 | A2A 特有 |
