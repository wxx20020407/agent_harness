# Agent Harness 多 Agent 调度平台汇报

> 日期：2026-04-16
> 汇报人：研发团队
> 目标：向 IT 部门汇报 Multi Agent 调度平台的设计方案和当前进展

---

## 一、设计方案

### 1.1 设计目标

我们正在构建一个 **多 Agent 统一调度平台**，核心目标是：

| 目标 | 说明 |
|------|------|
| **统一入口** | 一个平台管理多个团队 Agent，用户无需分别访问 |
| **智能路由** | 根据用户问题自动识别并分发到最合适的 Agent |
| **权限隔离** | 各 Agent 的 Skills/KB 资源独立，互不干扰 |
| **双端支持** | 同时支持 Web UI 和 Claude Code CLI 两种调用方式 |

### 1.2 两种调用方式

平台支持两种同等重要的调用方式：

#### 方式一：Web UI（路由式入口）

```
用户访问 Router UI → 输入问题 → 路由引擎分析 → 显示推荐 Agent → 确认 → 对话
```

**特点**：
- 类似 Claude Code 的入口体验
- 用户输入后自动推荐 Agent
- 支持用户手动切换 Agent

#### 方式二：Claude Code CLI（MCP 集成）

```
Claude Code 终端 → MCP 工具调用 → Router API → 领域 Agent → 结果返回 CLI
```

**特点**：
- 开发者在 Claude Code 中直接调用
- 主 Agent 可委托子任务给领域 Agent
- 支持自动化工作流

**MCP 工具列表**：

| 工具 | 功能 | 使用场景 |
|------|------|----------|
| `list_agents` | 列出所有可用 Agent | 了解有哪些 Agent 可用 |
| `find_agent` | 根据问题找合适 Agent | 路由预判 |
| `call_agent` | 调用指定 Agent | 执行具体任务 |
| `route_and_call` | 自动路由并调用 | 一步完成，最常用 |

### 1.3 架构设计

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Multi Agent 调度平台架构                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Router Platform (路由层)                          │   │
│  │                                                                      │   │
│  │  ┌─────────────────┐     ┌─────────────────┐                        │   │
│  │  │ Router UI       │     │ MCP Server      │                        │   │
│  │  │ :4303           │     │ (Claude Code)   │                        │   │
│  │  │ Web 端入口       │     │ CLI 端入口       │                        │   │
│  │  └────────┬────────┘     └────────┬────────┘                        │   │
│  │           │                       │                                  │   │
│  │           └───────────┬───────────┘                                  │   │
│  │                       │                                              │   │
│  │                       ▼                                              │   │
│  │  ┌─────────────────────────────────────────────────────────────┐    │   │
│  │  │                   Router API :4000                          │    │   │
│  │  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │    │   │
│  │  │  │ Agent       │  │ Routing     │  │ Agent       │         │    │   │
│  │  │  │ Registry    │  │ Engine      │  │ Client      │         │    │   │
│  │  │  │ (注册管理)   │  │ (路由决策)   │  │ (调用代理)   │         │    │   │
│  │  │  └─────────────┘  └─────────────┘  └─────────────┘         │    │   │
│  │  └─────────────────────────────────────────────────────────────┘    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│              ┌─────────────────────┼─────────────────────┐                 │
│              ▼                     ▼                     ▼                 │
│  ┌───────────────────┐  ┌───────────────────┐  ┌───────────────────┐      │
│  │     Team A        │  │     Team B        │  │     Team C        │      │
│  │   芯片研发 Agent   │  │   芯片验证 Agent   │  │   其他 Agent      │      │
│  │                   │  │                   │  │                   │      │
│  │  ┌─────────────┐  │  │  ┌─────────────┐  │  │  ┌─────────────┐  │      │
│  │  │ OpenCode    │  │  │  │ OpenCode    │  │  │  │ OpenCode    │  │      │
│  │  │ (LLM Runtime)│ │  │  │ (LLM Runtime)│ │  │  │ (LLM Runtime)│ │      │
│  │  └─────────────┘  │  │  └─────────────┘  │  │  └─────────────┘  │      │
│  │                   │  │                   │  │                   │      │
│  │  Skills/KB (隔离) │  │  Skills/KB (隔离) │  │  Skills/KB (隔离) │      │
│  └───────────────────┘  └───────────────────┘  └───────────────────┘      │
│                                                                             │
│  端口规划:                                                                   │
│  - 4000: Router API (路由引擎)                                               │
│  - 4303: Router UI (Web 入口)                                                │
│  - 4201/4202/...: 各 Team API                                                │
│  - 4301/4302/...: 各 Team UI                                                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.4 核心组件

| 组件 | 职责 | 技术实现 |
|------|------|----------|
| **Agent Registry** | Agent 注册、发现、健康检查 | YAML 配置 + 内存缓存 |
| **Routing Engine** | 关键词匹配、规则路由、置信度计算 | 规则引擎 + 关键词映射 |
| **Agent Client** | HTTP 代理、SSE 流转发、会话管理 | HTTP Client + EventSource |
| **MCP Server** | 暴露 MCP 工具供 Claude Code 调用 | JSON-RPC 2.0 over stdio |

### 1.5 路由机制

```
用户输入 → 关键词提取 → 规则匹配 → 置信度计算 → 返回推荐 Agent
                │
                ├── 直接关键词映射（功耗 → team-a）
                ├── 规则优先级匹配（UVM/验证 → team-b）
                └── 通用关键词搜索（备选方案）
```

**路由规则示例**：

```yaml
keyword_mappings:
  "ARM": "team-a"
  "功耗": "team-a"
  "UVM": "team-b"
  "断言": "team-b"

rules:
  - name: "verification_routing"
    condition: "验证问题"
    priority_check:
      - keywords: ["UVM", "验证", "Testbench"]
        target: "team-b"
        weight: 1.0
```

### 1.6 当前实现状态

| 功能 | 状态 | 说明 |
|------|------|------|
| Router API | ✅ 已完成 | 端口 4000，支持路由、代理、健康检查 |
| Router UI | ✅ 已完成 | 端口 4303，路由式入口 |
| MCP Server | ✅ 已完成 | 5 个工具，支持 Claude Code 集成 |
| Team A Agent | ✅ 已完成 | 芯片研发助手 |
| Team B Agent | ✅ 已完成 | 芯片验证助手 |
| 健康检查/降级 | ✅ 已完成 | Agent 不可用时自动降级 |
| 结构化日志 | ✅ 已完成 | JSON 格式，支持请求追踪 |

---

## 二、难点问题

### 2.1 用户组权限规划

#### 问题描述

用户不应该看到所有 Agent，原因包括：
1. **工作相关性**：用户只关心自己工作范围内的 Agent
2. **权限隔离**：某些 Agent 涉及敏感数据，需要权限控制
3. **体验优化**：减少干扰，只展示相关的 Agent

**核心问题**：
- 如何定义用户组？
- 如何关联用户组和 Agent？
- 如何在 Router 层实现权限过滤？

#### 当前实现方案

目前采用 **静态配置 + 简单过滤** 的方式：

```yaml
# agents.yaml
agents:
  team-a:
    name: "芯片研发 Agent"
    metadata:
      owner: "team-a@example.com"
      tags: ["研发", "嵌入式", "芯片", "ARM"]
      # 未实现：allowed_groups: ["chip-team", "rd-dept"]
      # 未实现：visibility: "internal"  # public/internal/private
```

**当前状态**：所有 Agent 对所有用户可见（无权限控制）

**待实现方案**：

```
┌─────────────────────────────────────────────────────────────┐
│                    用户权限模型建议                          │
│                                                             │
│  用户 ──属于──► 用户组 ──拥有──► Agent 访问权限              │
│                                                             │
│  示例：                                                      │
│  用户 zhang.san ──属于──► chip-team 组                      │
│  chip-team 组 ──可访问──► [team-a, team-b]                  │
│                                                             │
│  Router 在路由时：                                           │
│  1. 获取用户身份（从 Token/Session）                         │
│  2. 查询用户所属组                                           │
│  3. 过滤出可访问的 Agent 列表                                │
│  4. 仅在可见范围内进行路由                                   │
└─────────────────────────────────────────────────────────────┘
```

---

### 2.2 路由设计

#### 问题描述

路由是平台的核心功能，面临以下挑战：

1. **准确性**：如何准确识别用户意图并路由到正确的 Agent？
2. **歧义处理**：多个 Agent 都相关时如何处理？
3. **边界情况**：无法匹配任何 Agent 时如何处理？
4. **扩展性**：新增 Agent 后如何更新路由规则？

#### 当前实现方案

采用 **三层路由机制**：

```
┌─────────────────────────────────────────────────────────────┐
│                    当前路由实现                              │
│                                                             │
│  Layer 1: 直接关键词映射                                     │
│  ├── "功耗" → team-a                                        │
│  ├── "UVM" → team-b                                         │
│  └── 置信度 0.95，直接返回                                   │
│                                                             │
│  Layer 2: 规则匹配                                          │
│  ├── 按 condition 筛选规则                                   │
│  ├── 按 priority_check 顺序匹配关键词                        │
│  └── 置信度 = 匹配权重和                                     │
│                                                             │
│  Layer 3: 通用关键词搜索                                     │
│  ├── 遍历所有 Agent 的 keywords                              │
│  ├── 计算匹配分数                                            │
│  └── 返回 Top-N 候选                                        │
│                                                             │
│  Fallback: 无匹配时                                          │
│  ├── ask_user: 返回候选列表让用户选择                        │
│  ├── route_to_default: 路由到默认 Agent                      │
│  └── return_error: 返回错误                                  │
└─────────────────────────────────────────────────────────────┘
```

**配置示例**：

```yaml
# routes.yaml
rules:
  - name: "verification_routing"
    condition: "验证问题"
    priority_check:
      - keywords: ["UVM", "验证", "Testbench"]
        target: "team-b"
        weight: 1.0

keyword_mappings:
  "ARM": "team-a"
  "UVM": "team-b"

default:
  when_unsure: "ask_user"
  auto_route_threshold: 0.7
  min_alternative_confidence: 0.3
```

**已知局限**：
- 纯关键词匹配，无语义理解
- 无法处理复杂多意图
- 规则需要手动维护

**后续优化方向**：
- 引入 LLM 辅助路由（低置信度时调用）
- 支持多 Agent 协作路由
- 基于历史对话学习路由偏好

---

### 2.3 Agent 执行结果返回 Claude Code

#### 问题描述

Claude Code 通过 MCP 调用 Agent 后，需要将执行结果正确返回到 CLI 界面：

1. **流式输出**：Agent 响应通常是流式的，如何传递？
2. **多轮对话**：如何保持会话上下文？
3. **结果格式**：Agent 返回的文本、文件如何呈现？

#### 当前实现方案

采用 **MCP 工具 + 非流式收集** 的方式：

```
┌─────────────────────────────────────────────────────────────┐
│                Claude Code 调用 Agent 流程                   │
│                                                             │
│  Claude Code CLI                                            │
│       │                                                     │
│       │ MCP tools/call (mcp__router__call_agent)            │
│       ▼                                                     │
│  MCP Server (router/lib/mcpServer.js)                       │
│       │                                                     │
│       │ 创建/复用 Session                                   │
│       ▼                                                     │
│  Router API                                                 │
│       │                                                     │
│       │ HTTP POST /chat                                     │
│       ▼                                                     │
│  目标 Agent (team-a/team-b)                                 │
│       │                                                     │
│       │ SSE 流式响应                                        │
│       ▼                                                     │
│  MCP Server 收集完整响应                                     │
│       │                                                     │
│       │ 返回 JSON 结果                                      │
│       ▼                                                     │
│  Claude Code CLI 显示结果                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**MCP 工具实现**（`call_agent`）：

```javascript
// router/lib/mcpServer.js
handler: async ({ agent_id, message, session_id }) => {
  // 1. 创建或复用会话
  let sessionId = session_id;
  if (!sessionId) {
    const sessionResponse = await fetch(`${ROUTER_API_URL}/sessions`, {
      method: 'POST',
      body: JSON.stringify({ agentId: agent_id })
    });
    sessionId = (await sessionResponse.json()).sessionId;
  }

  // 2. 调用 Agent（非流式，收集完整响应）
  const response = await fetch(`${ROUTER_API_URL}/chat`, {
    method: 'POST',
    body: JSON.stringify({ agentId: agent_id, sessionId, message })
  });

  // 3. 收集 SSE 流
  const reader = response.body.getReader();
  let fullContent = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // 解析 SSE 事件，拼接 content
    fullContent += parseSSEContent(value);
  }

  // 4. 返回完整结果给 Claude Code
  return {
    content: fullContent,
    session_id: sessionId,
    agent_id
  };
}
```

**当前状态**：
- ✅ 支持调用指定 Agent
- ✅ 支持会话保持（通过 session_id）
- ✅ 返回完整文本结果
- ⚠️ 非流式输出（Claude Code 会等待完整响应）
- ❌ 文件/Artifact 返回未支持

**后续优化方向**：
- 支持 MCP Streamable HTTP（流式返回）
- 支持 Artifact 作为 MCP Resource 返回
- 优化长时间任务的等待体验

---

## 三、下一步计划

| 优先级 | 任务 | 预计工时 |
|--------|------|----------|
| P0 | 用户组权限设计和实现 | 3-5 天 |
| P1 | LLM 辅助路由（提升准确率） | 3-5 天 |
| P1 | MCP 流式输出支持 | 2-3 天 |
| P2 | 多 Agent 协作路由 | 5-7 天 |
| P2 | 路由规则管理 UI | 5-7 天 |

---

## 四、演示

### 4.1 服务状态

```bash
# 查看所有服务状态
curl http://localhost:4000/health
```

### 4.2 路由测试

```bash
# 测试路由功能
curl -X POST http://localhost:4000/route \
  -H 'Content-Type: application/json' \
  -d '{"message":"ARM CPU功耗分析"}'
```

### 4.3 Claude Code 集成

在 Claude Code 中配置 MCP 后，可直接使用：

```
用户：帮我分析一下这个 UVM 验证环境
Claude Code：[调用 mcp__router__route_and_call] → 路由到 team-b → 返回结果
```

---

## 五、讨论事项

1. **用户组管理**：是否对接现有 AD/LDAP？还是独立管理？
2. **权限粒度**：Agent 级别还是 Skill/KB 级别？
3. **审计需求**：是否需要记录所有路由和调用日志？
4. **监控告警**：Router 层是否需要接入统一监控平台？
