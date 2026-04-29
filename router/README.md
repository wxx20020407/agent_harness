# Agent Harness Router Platform

统一的 Agent 路由管理平台，支持智能路由和多团队 Agent 管理。

## 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                    Router Platform                               │
│                                                                  │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐        │
│  │ Router UI   │     │ Router API  │     │ MCP Server  │        │
│  │ :4303       │────▶│ :4000       │────▶│ (Claude)    │        │
│  └─────────────┘     └──────┬──────┘     └─────────────┘        │
│                             │                                    │
│              ┌──────────────┼──────────────┐                    │
│              ▼              ▼              ▼                    │
│       ┌───────────┐  ┌───────────┐  ┌───────────┐              │
│       │ Team A    │  │ Team B    │  │ Team C    │              │
│       │ :4201     │  │ :4202     │  │ :4203     │              │
│       │ 芯片研发   │  │ 芯片验证   │  │ ...       │              │
│       └───────────┘  └───────────┘  └───────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

## 快速开始

### 1. 启动所有服务

```bash
cd /data/agent_harness
docker compose up -d
```

### 2. 访问服务

| 服务 | 地址 | 说明 |
|------|------|------|
| Router UI | http://localhost:4303 | 路由式入口 |
| Router API | http://localhost:4000 | REST API |
| Team A UI | http://localhost:4301 | 芯片研发助手 |
| Team B UI | http://localhost:4312 | 芯片验证助手 |

## 核心功能

### 1. 智能路由

根据用户输入自动选择合适的 Agent：

```bash
# 路由测试
curl -X POST http://localhost:4000/route \
  -H 'Content-Type: application/json' \
  -d '{"message": "ARM CPU功耗分析"}'

# 响应
{
  "recommendedAgent": {
    "agentId": "team-a",
    "confidence": 0.95,
    "matchedKeywords": ["ARM", "功耗"]
  },
  "method": "direct_mapping"
}
```

### 2. 对话代理

```bash
# 自动路由对话
curl -X POST http://localhost:4000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "UVM验证环境怎么搭建", "autoRoute": true}'
```

### 3. MCP 集成

在 Claude Code 的配置中添加：

```json
{
  "mcpServers": {
    "agent-router": {
      "command": "node",
      "args": ["/data/agent_harness/router/lib/mcpServer.js"],
      "env": {
        "ROUTER_API_URL": "http://localhost:4000"
      }
    }
  }
}
```

可用的 MCP 工具：
- `mcp__router__list_agents` - 列出所有 Agent
- `mcp__router__find_agent` - 根据问题找到合适的 Agent
- `mcp__router__call_agent` - 调用指定 Agent
- `mcp__router__get_agent_info` - 获取 Agent 详细信息
- `mcp__router__route_and_call` - 自动路由并调用

## API 参考

### GET /health

健康检查，返回所有 Agent 的健康状态。

### GET /agents

列出所有可用的 Agent。

### GET /agents/:id

获取指定 Agent 的详细信息。

### GET /agents/:id/resources

获取 Agent 的资源（skills/kb）列表。

### POST /route

智能路由，返回推荐的 Agent。

**请求体：**
```json
{
  "message": "用户问题",
  "context": {}  // 可选
}
```

### POST /sessions

创建会话。

**请求体：**
```json
{
  "agentId": "team-a"
}
```

### POST /chat

对话接口，支持 SSE 流式响应。

**请求体：**
```json
{
  "message": "用户消息",
  "agentId": "team-a",      // 可选，指定 Agent
  "sessionId": "xxx",       // 可选，复用会话
  "autoRoute": false        // 可选，自动路由
}
```

## 配置

### Agent 配置 (config/agents.yaml)

```yaml
agents:
  team-a:
    name: "Team A Agent"
    description: "研发助手，专注于 ARM CPU 和嵌入式开发"
    endpoint:
      url: "http://api-team-a:3000"
      healthCheck: "/health"
    routing:
      keywords:
        - "ARM"
        - "CPU"
        - "功耗"
      priority: 10
    resources:
      skills:
        - name: "soc-power-prediction"
          description: "SoC 功耗预测技能"
      kb:
        - name: "ARM_TRM_CPU"
          description: "ARM CPU 技术参考手册"
```

### 路由规则 (config/routes.yaml)

```yaml
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
  "功耗": "team-a"

default:
  when_unsure: "ask_user"
  auto_route_threshold: 0.7
```

## 日志

Router 使用结构化 JSON 日志，便于收集和分析：

```json
{"timestamp":"2026-04-15T15:00:00.000Z","level":"INFO","context":"Router","message":"Request completed","requestId":"abc123","method":"POST","path":"/route","statusCode":200,"duration":"15ms"}
```

启用调试日志：
```bash
export LOG_LEVEL=debug
```

## 开发

### 本地运行

```bash
cd router
npm install
npm start
```

### 构建 Docker 镜像

```bash
docker compose build router-api router-ui
```

## 端口规划

| 端口 | 服务 | 说明 |
|------|------|------|
| 4000 | Router API | 路由引擎 |
| 4303 | Router UI | 路由式入口 |
| 4101 | OpenCode Team A | Agent Runtime |
| 4201 | API Team A | REST API |
| 4301 | UI Team A | Web Frontend |
| 4102 | OpenCode Team B | Agent Runtime |
| 4202 | API Team B | REST API |
| 4312 | UI Team B | Web Frontend |
