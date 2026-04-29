---
name: agent-router
description: 多Agent智能路由平台，用于调度不同团队的Agent回答问题。触发词：路由、router、agent、调度、分配agent、找agent、agent-router
version: 1.0.0
---

# Agent Router - 多Agent智能路由

通过 HTTP API 调用 Agent Router 平台，将用户问题智能路由到最合适的团队 Agent 进行回答。

## 前置配置

Router API 地址通过环境变量 `ROUTER_API_URL` 配置，默认 `http://localhost:4000`。

```bash
# 确认 API 可达
curl -s ${ROUTER_API_URL:-http://localhost:4000}/health
```

## 可用 API 端点

| 功能 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 健康检查 | GET | `/health` | 检查所有 Agent 状态 |
| 列出所有 Agent | GET | `/agents` | 获取 Agent 列表及能力描述 |
| Agent 详情 | GET | `/agents/:id` | 获取单个 Agent 详细信息 |
| 智能路由 | POST | `/route` | 分析消息，推荐最合适的 Agent |
| 发送消息 | POST | `/chat` | 路由 + 对话，支持会话上下文 |
| 会话列表 | GET | `/sessions` | 获取所有会话 |
| 创建会话 | POST | `/sessions` | 创建新的对话会话 |
| 会话详情 | GET | `/sessions/:id` | 获取会话及消息历史 |
| 删除会话 | DELETE | `/sessions/:id` | 删除会话 |
| 更新会话 | PATCH | `/sessions/:id` | 更新会话标题等 |

## 执行步骤

### Step 1: 查看可用 Agent

```bash
curl -s ${ROUTER_API_URL:-http://localhost:4000}/agents | python3 -m json.tool
```

返回格式：
```json
{
  "agents": [
    {
      "id": "team-a",
      "name": "Team A Agent",
      "description": "...",
      "capabilities": ["ARM架构", "CPU设计", ...]
    }
  ]
}
```

### Step 2: 智能路由分析（可选）

如果不确定哪个 Agent 最合适，先用路由分析：

```bash
curl -s -X POST ${ROUTER_API_URL:-http://localhost:4000}/route \
  -H 'Content-Type: application/json' \
  -d '{"message": "用户的问题"}' | python3 -m json.tool
```

返回格式：
```json
{
  "recommendedAgent": {
    "agentId": "team-a",
    "agentName": "Team A Agent",
    "confidence": 0.85,
    "reason": "..."
  },
  "candidates": [...]
}
```

### Step 3: 发送消息并获取回答

#### 方式 A: 自动路由（推荐）

让 Router 自动选择最合适的 Agent：

```bash
curl -s -X POST ${ROUTER_API_URL:-http://localhost:4000}/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "用户的问题",
    "autoRoute": true
  }'
```

#### 方式 B: 指定 Agent

```bash
curl -s -X POST ${ROUTER_API_URL:-http://localhost:4000}/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "用户的问题",
    "agentId": "team-a"
  }'
```

#### 方式 C: 带会话上下文的多轮对话

```bash
# 第一轮：创建会话
curl -s -X POST ${ROUTER_API_URL:-http://localhost:4000}/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "第一轮问题",
    "autoRoute": true
  }'
# 返回中包含 routerSessionId

# 后续轮次：传入 routerSessionId 保持上下文
curl -s -X POST ${ROUTER_API_URL:-http://localhost:4000}/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "message": "后续问题",
    "routerSessionId": "上面返回的sessionId",
    "autoRoute": true
  }'
```

### Step 4: 解析响应

`/chat` 返回 SSE（Server-Sent Events）流，格式为：

```
data: {"type":"route_info","agentId":"team-a","agentName":"Team A Agent","routerSessionId":"..."}

data: {"type":"text","content":"这是回答的一部分"}

data: {"type":"thinking","content":"思考过程..."}

data: {"type":"done"}
```

解析方法：

```bash
# 获取纯文本回答（过滤 SSE 格式）
curl -s -X POST ${ROUTER_API_URL:-http://localhost:4000}/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "问题", "autoRoute": true}' \
  | grep '^data: ' \
  | sed 's/^data: //' \
  | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        evt = json.loads(line.strip())
        if evt.get('type') == 'route_info':
            print(f'[路由到: {evt.get(\"agentName\", evt.get(\"agentId\"))}]')
        elif evt.get('type') == 'text':
            print(evt.get('content', ''), end='')
        elif evt.get('type') == 'error':
            print(f'[错误: {evt.get(\"message\")}]', file=sys.stderr)
    except: pass
print()
"
```

### Step 5: 管理会话

```bash
# 列出所有会话
curl -s ${ROUTER_API_URL:-http://localhost:4000}/sessions | python3 -m json.tool

# 获取会话详情（含消息历史）
curl -s ${ROUTER_API_URL:-http://localhost:4000}/sessions/{sessionId} | python3 -m json.tool

# 删除会话
curl -s -X DELETE ${ROUTER_API_URL:-http://localhost:4000}/sessions/{sessionId}

# 更新会话标题
curl -s -X PATCH ${ROUTER_API_URL:-http://localhost:4000}/sessions/{sessionId} \
  -H 'Content-Type: application/json' \
  -d '{"title": "新标题"}'
```

## 工作流程

### 标准问答流程

1. 用户提问
2. 调用 `POST /chat`（`autoRoute: true`），Router 自动路由到最合适的 Agent
3. 从 SSE 流中解析 `route_info`（哪个 Agent 回答）和 `text`（回答内容）
4. 将回答呈现给用户，标注是哪个 Agent 回答的

### 多轮对话流程

1. 第一轮：调用 `POST /chat`，从响应中获取 `routerSessionId`
2. 后续轮次：传入同一个 `routerSessionId`，Router 会自动拼接跨团队上下文
3. 每轮回答都会标注是哪个 Agent 回答的

### 仅路由分析（不发送消息）

如果只想知道问题应该路由给哪个 Agent，不实际发送：

```bash
curl -s -X POST ${ROUTER_API_URL:-http://localhost:4000}/route \
  -H 'Content-Type: application/json' \
  -d '{"message": "问题"}'
```

## Agent 团队划分

| Agent ID | 团队 | 专长领域 |
|----------|------|----------|
| team-a | Team A | ARM架构、CPU设计、SoC、功耗分析、嵌入式系统 |
| team-b | Team B | 芯片验证、UVM、仿真、形式验证、时序分析 |
| team-c | Team C | 飞书集成、项目管理、文档协作、多维表格 |
| team-d | Team D | 架构图、可视化、Mermaid、PlantUML、图表生成 |

## 约束

- 回答用户时，必须标注是哪个 Agent/团队给出的回答
- 多轮对话时，始终传入 `routerSessionId` 以保持上下文连贯
- 如果 API 不可达，告知用户 Router 服务未启动，需要检查 `http://黄区服务器IP:4000`
- SSE 流中的 `thinking` 事件是 Agent 的思考过程，可以选择性展示给用户
- 会话数据持久化在服务端，关闭重开后历史对话仍在
