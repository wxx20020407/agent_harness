# Agent Router - MCP & A2A Integration Guide

## 1. Claude Code MCP 集成

### 配置方法

将以下配置添加到 Claude Code 的 settings.json 中：

**方法 A：直接编辑 settings.json**

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

settings.json 路径：
- macOS/Linux: `~/.claude/settings.json`（全局）或项目目录下的 `.claude/settings.json`（项目级）

**方法 B：使用 claude mcp add 命令**

```bash
claude mcp add agent-router -e ROUTER_API_URL=http://localhost:4000 -- node /data/agent_harness/router/lib/mcpServer.js
```

### 前置条件

1. Router API 已启动（`docker compose up -d router-api`）
2. Router 监听在 `http://localhost:4000`
3. Node.js 18+ 可用

### MCP 工具列表

配置成功后，Claude Code 会自动注册以下 5 个工具（名称前缀 `mcp__agent-router__`）：

| 工具名 | 说明 | 必需参数 |
|--------|------|----------|
| `list_agents` | 列出所有可用 Agent | 无 |
| `find_agent` | 根据问题找到最合适的 Agent | `query` |
| `call_agent` | 调用指定 Agent 进行对话 | `agent_id`, `message` |
| `get_agent_info` | 获取 Agent 详细信息（skills、kb） | `agent_id` |
| `route_and_call` | 自动路由 + 调用（一步完成） | `message` |

### 使用示例

在 Claude Code 中可以直接使用：

```
# 查看有哪些 Agent 可用
> 用 list_agents 看看有哪些 agent

# 自动路由并调用
> 帮我问一下 ARM CPU 功耗分析怎么做（用 route_and_call）

# 指定 Agent 调用
> 用 team-b agent 帮我写一个 UVM testbench（用 call_agent，agent_id: team-b）
```

### 可用 Agent

| Agent ID | 名称 | 专长 |
|----------|------|------|
| `team-a` | Team A Agent | ARM CPU、嵌入式开发、芯片、功耗分析 |
| `team-b` | Team B Agent | UVM 验证、仿真调试、断言、覆盖率 |
| `team-c` | Team C Agent | 飞书集成、项目管理、多维表格 |
| `team-d` | Team D Agent | 架构图生成、系统可视化、SVG |

---

## 2. A2A Protocol 端点

Router 同时支持 A2A (Agent2Agent) 协议，外部 A2A 客户端可以直接调用。

### Agent Card 发现

```bash
curl http://localhost:4000/.well-known/agent-card.json
```

### message/send（非流式）

```bash
curl -X POST http://localhost:4000/a2a \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "id": "req-1",
    "params": {
      "message": {
        "parts": [{"text": "ARM CPU 功耗分析怎么做"}]
      }
    }
  }'
```

指定目标 Agent：

```bash
curl -X POST http://localhost:4000/a2a \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "id": "req-2",
    "params": {
      "message": {
        "parts": [{"text": "写一个 UVM testbench"}],
        "metadata": {"agent_id": "team-b"}
      }
    }
  }'
```

### message/stream（SSE 流式）

```bash
curl -X POST http://localhost:4000/a2a \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/stream",
    "id": "req-3",
    "params": {
      "message": {
        "parts": [{"text": "画一个微服务架构图"}]
      }
    }
  }'
```

### A2A 响应格式

**非流式响应：**

```json
{
  "jsonrpc": "2.0",
  "id": "req-1",
  "result": {
    "task": {
      "id": "<task-uuid>",
      "context_id": "<context-uuid>",
      "status": {
        "state": "TASK_STATE_COMPLETED",
        "message": {
          "role": "ROLE_AGENT",
          "parts": [{"text": "Agent 的回复内容..."}]
        },
        "timestamp": "2024-01-01T00:00:00.000Z"
      },
      "artifacts": [{
        "artifact_id": "<task-id>-output",
        "name": "response",
        "parts": [{"text": "Agent 的回复内容..."}]
      }]
    }
  }
}
```

**流式 SSE 事件序列：**

1. `TASK_STATE_SUBMITTED` — 任务已提交
2. `TASK_STATE_WORKING` — 正在处理
3. `artifact_update` — 响应内容
4. `TASK_STATE_COMPLETED` — 处理完成（final: true）

---

## 3. API 端点一览

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | API 信息 |
| `/health` | GET | 健康检查 |
| `/agents` | GET | 列出所有 Agent |
| `/agents/:id` | GET | 获取 Agent 详情 |
| `/agents/:id/resources` | GET | 获取 Agent 资源 |
| `/route` | POST | 智能路由 |
| `/sessions` | POST | 创建会话 |
| `/sessions/:id` | GET | 获取会话 |
| `/chat` | POST | 流式对话（SSE） |
| `/agents/:id/proxy/*` | ALL | 代理到目标 Agent |
| `/.well-known/agent-card.json` | GET | A2A Agent Card |
| `/a2a` | POST | A2A JSON-RPC 端点 |

Router 监听端口：`4000`（Docker 映射 4000:3000）
