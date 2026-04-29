# Agent Harness 技术开发方案（修订版）

## 一、OpenCode Serve 并发能力评估

### 调研结论

经过对 OpenCode 官方文档、SDK 源码、GitHub Issues 和社区项目的深入调研，**OpenCode serve 模式可以支持多用户并发使用，但存在明确的限制和风险**，需要在架构设计中针对性处理。

### 支持并发的证据

1. **会话级隔离**：OpenCode 的 session 系统基于 SQLite 持久化存储，每个用户可以创建独立的 session，session 之间数据天然隔离
2. **SDK 完备性**：官方 `@opencode-ai/sdk` 提供了完整的 TypeScript 类型安全客户端，支持 session 创建、prompt 发送、SSE 事件流订阅等全部操作
3. **多客户端架构**：官方明确说明"This architecture lets opencode support multiple clients"，TUI、Web、Desktop、IDE 插件都是通过同一套 server API 交互
4. **SSE 事件流**：server 支持 Server-Sent Events 实时推送，可以实现流式输出

### 并发风险

1. **Session 锁机制**：OpenCode 内部有 session 级别的锁（`SessionLockedError`），同一个 session 同一时间只能处理一个请求。但不同 session 之间可以并发
2. **文件系统冲突**：GitHub Issue #4251 记录了多个并发 session 操作同一工作目录时的文件追踪混乱问题。这是 OpenCode 作为"编码工具"的固有特性——所有 session 共享同一个文件系统
3. **SQLite 写入瓶颈**：SQLite 的写入是串行的，高并发写入可能成为瓶颈，但对于 5-10 人的团队规模影响有限
4. **进程资源**：每个活跃 session 的 LLM 请求是异步的，但 bash 命令执行是阻塞的，多用户同时触发 bash 操作可能互相干扰

### 对本方案的影响评估

**好消息**：本方案的使用场景是"团队研发助手"（问答、知识检索、技能执行），**不是**多人同时编辑同一个代码库。permissions 配置中 `edit`/`write`/`bash` 设为 `ask`，Agent 不会主动修改文件。因此文件冲突风险大幅降低。

**结论**：每个团队一个 OpenCode runtime 容器的架构可行，单团队 5-10 人并发使用在 permissions 限制到位的情况下是安全的。但需要在 API 层做并发保护。

---

## 二、修订后的架构设计

### 核心变更

相比原方案，修订版做了以下关键调整：

1. **UI 和 API 统一代码、参数化部署**（原方案每团队复制独立项目，运维成本高）
2. **第一版就做 SSE 流式输出**（原方案先做整段返回，体验太差）
3. **增加 API 层并发保护和错误兜底**（原方案缺失）
4. **kb/ 文档按需读取策略**（原方案未说明）
5. **增加容器健康检查和自动恢复**（原方案缺失）
6. **简化目录结构**（从 6 个项目减为 2 个）

### 架构图

```
浏览器 :4301  ──> gateway (Nginx)
浏览器 :4302  ──>   ├── team-a → unified-ui (env: TEAM=a) → unified-api (env: TEAM=a) → opencode:4101
浏览器 :4303  ──>   ├── team-b → unified-ui (env: TEAM=b) → unified-api (env: TEAM=b) → opencode:4102
                     └── team-c → unified-ui (env: TEAM=c) → unified-api (env: TEAM=c) → opencode:4103
```

关键原则：**一套代码，多实例部署**。新增团队只需要：
1. 创建 `teams/team-x/` 目录
2. 在 `docker-compose.yml` 加一组服务
3. 在 Nginx 加一条路由

---

## 三、目录结构（简化版）

```
/opt/agent-harness/
  teams/                          # 团队只维护这个目录
    team-a/
      skills/
        weekly-report/
          SKILL.md
      kb/
        faq.md
        process.md
      AGENTS.md
      opencode.json
    team-b/
      ...
    team-c/
      ...

  src/                            # 统一代码库（一套代码）
    api/                          # 后端，通过环境变量区分团队
      package.json
      server.js
    ui/                           # 前端，通过环境变量区分团队
      package.json
      vite.config.js
      src/
        App.jsx
        ...

  deploy/
    docker-compose.yml
    nginx.conf
    Dockerfile.api
    Dockerfile.ui
```

**对比原方案**：从 6 个独立项目（team-a-ui, team-a-api, team-b-ui...）缩减为 2 个（api + ui），通过环境变量实例化。

---

## 四、团队配置规范

每个团队提供 4 个文件/目录，与原方案一致，但增加了 AGENTS.md 的重要指导。

### 1. AGENTS.md（增强版）

```markdown
# 团队规则

## 知识库使用规则
- 收到用户提问后，先用 find.files 列出 kb/ 目录下的所有文件
- 根据用户问题的关键词，判断需要读取哪些文件
- 只读取相关文件，不要一次性读完所有文档
- 回答时引用具体的文件名和内容出处

## 行为规则
- 不确定的内容明确说明"我不确定"
- 回答尽量引用 kb/ 中的文件名
- 默认不修改任何文件
- 不执行 bash 命令，除非用户明确要求且确认

## 技能使用
- 识别到用户意图匹配 skills/ 中某个技能时，优先使用该技能的流程
- 执行技能前向用户确认
```

这段规则的核心目的是**控制 Agent 只做读取操作**，避免多用户并发时的文件系统冲突。

### 2. opencode.json（调整权限）

```json
{
  "$schema": "https://opencode.ai/config.json",
  "server": {
    "hostname": "0.0.0.0",
    "port": 4096
  },
  "instructions": ["./AGENTS.md"],
  "permission": {
    "skill": { "*": "allow" },
    "read": "allow",
    "list": "allow",
    "edit": "deny",
    "write": "deny",
    "bash": "deny"
  }
}
```

**关键变更**：将 `edit`/`write`/`bash` 从 `ask` 改为 `deny`。原方案用 `ask` 意味着 Agent 会请求人类批准，但在多用户 web 场景下没有人批准——会导致 session 卡住。直接 `deny` 更安全。

如果某些团队确实需要 Agent 写文件或执行命令，可以单独配置为 `allow`，但需要明确知晓并发风险。

---

## 五、后端设计（unified-api）

### 技术栈

- Node.js + Express
- `@opencode-ai/sdk`（官方 Stainless 生成的 SDK）
- 环境变量驱动：`TEAM_ID`、`TEAM_NAME`、`OPENCODE_URL`、`TEAM_DIR`

### 接口设计

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /health | 健康检查，含 runtime 连通性 |
| GET | /meta | 返回团队名、skills 列表、kb 文件列表 |
| POST | /session | 创建新会话，返回 sessionId |
| POST | /chat | SSE 流式对话（第一版就做流式） |
| GET | /sessions | 列出历史会话（可选，第二阶段加） |

### /chat 接口设计（SSE 流式）

这是核心接口，直接做成 SSE 而非先做整段返回再改：

```
POST /chat
Content-Type: application/json

请求体:
{
  "sessionId": "uuid",
  "message": "帮我根据资料写周报"
}

响应: text/event-stream
data: {"type": "text", "content": "根据"}
data: {"type": "text", "content": " kb/faq.md"}
data: {"type": "text", "content": " 中的内容..."}
data: {"type": "tool", "name": "file.read", "status": "running"}
data: {"type": "tool", "name": "file.read", "status": "done"}
data: {"type": "done", "sessionId": "uuid"}
```

实现方式：调用 `client.session.prompt()` 后，通过 `client.event.subscribe()` 监听 SSE 事件流，将 `message.part.updated` 事件中的 delta 增量转发给前端。

### 并发保护

```javascript
// 内存中维护 session 级别的锁
const sessionLocks = new Map();

async function handleChat(req, res) {
  const { sessionId, message } = req.body;

  // 同一 session 不允许并发请求
  if (sessionLocks.get(sessionId)) {
    return res.status(429).json({
      error: "该会话正在处理中，请等待上一条消息完成"
    });
  }

  sessionLocks.set(sessionId, true);
  try {
    // ... 调用 OpenCode SDK
  } finally {
    sessionLocks.delete(sessionId);
  }
}
```

### 错误处理

```javascript
// 统一错误处理中间件
app.use((err, req, res, next) => {
  // OpenCode runtime 不可达
  if (err.code === 'ECONNREFUSED') {
    return res.status(503).json({
      error: "Agent 服务暂时不可用，请稍后重试"
    });
  }
  // 请求超时
  if (err.code === 'TIMEOUT') {
    return res.status(504).json({
      error: "Agent 响应超时，请重试或简化问题"
    });
  }
  // 默认错误
  res.status(500).json({ error: "内部错误" });
});
```

### /health 接口（增强版）

```javascript
app.get('/health', async (req, res) => {
  try {
    const health = await client.global.health();
    res.json({
      api: "healthy",
      runtime: "healthy",
      runtimeVersion: health.data.version,
      teamId: process.env.TEAM_ID
    });
  } catch (e) {
    res.status(503).json({
      api: "healthy",
      runtime: "unreachable",
      teamId: process.env.TEAM_ID
    });
  }
});
```

---

## 六、前端设计（unified-ui）

### 技术栈

- React + Vite
- 不使用状态管理库（useState 够用）
- 不使用组件库（自己写几个简单组件）
- 通过 `VITE_TEAM_NAME` 和 `VITE_API_URL` 环境变量区分团队

### 页面结构

```
┌─────────────────────────────────────┐
│  [Team A Agent]      [会话ID]  [新会话] │
├─────────────────────────────────────┤
│                                     │
│  [Agent] 你好，我是 Team A 的助手     │
│                                     │
│           [User] 帮我查一下FAQ中...   │
│                                     │
│  [Agent] 正在读取 kb/faq.md...      │  ← 流式渲染
│  根据文档内容，...                    │
│                                     │
├─────────────────────────────────────┤
│  ┌──────────────────────┐ [发送]     │
│  │ 输入你的问题...       │            │
│  └──────────────────────┘            │
├─────────────────────────────────────┤
│  Skills: weekly-report | kb: faq.md  │  ← 折叠区
└─────────────────────────────────────┘
```

### SSE 消费

```javascript
async function sendMessage(sessionId, message) {
  const response = await fetch(`${API_URL}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sessionId, message })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    // 解析 SSE data 行，更新消息状态
    for (const line of chunk.split('\n')) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6));
        handleEvent(event); // 更新 React state
      }
    }
  }
}
```

### 用户体验兜底

- **Loading 状态**：发送消息后立即显示"正在思考..."动画
- **超时处理**：60 秒无响应提示"响应超时，请重试"
- **断线重连**：SSE 连接断开后自动重试一次
- **错误提示**：runtime 不可达时显示明确错误，而不是空白
- **消息确认**：用户发送的消息立即显示在界面上（乐观更新）

---

## 七、容器化部署

### docker-compose.yml 结构

```yaml
version: '3.8'

services:
  # ===== Runtime 层 =====
  opencode-team-a:
    image: opencode/opencode:latest
    command: opencode serve --hostname 0.0.0.0 --port 4096
    working_dir: /workspace
    volumes:
      - ./teams/team-a:/workspace:ro     # 只读挂载，防止 Agent 意外写入
    environment:
      - OPENCODE_SERVER_PASSWORD=team-a-secret
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    ports:
      - "4101:4096"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:4096/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped

  # Team B、C 同结构，端口 4102、4103

  # ===== API 层 =====
  api-team-a:
    build:
      context: ./src/api
      dockerfile: ../deploy/Dockerfile.api
    environment:
      - TEAM_ID=team-a
      - TEAM_NAME=Team A Agent
      - TEAM_DIR=/teams/team-a
      - OPENCODE_URL=http://opencode-team-a:4096
      - OPENCODE_PASSWORD=team-a-secret
      - PORT=3000
    volumes:
      - ./teams/team-a:/teams/team-a:ro
    ports:
      - "4201:3000"
    depends_on:
      opencode-team-a:
        condition: service_healthy
    restart: unless-stopped

  # Team B、C 同结构，端口 4202、4203

  # ===== UI 层 =====
  ui-team-a:
    build:
      context: ./src/ui
      dockerfile: ../deploy/Dockerfile.ui
      args:
        - VITE_TEAM_NAME=Team A Agent
        - VITE_API_URL=http://agent-host:4201
    ports:
      - "4301:80"
    depends_on:
      - api-team-a
    restart: unless-stopped

  # Team B、C 同结构，端口 4302、4303
```

### 关键设计点

1. **团队目录只读挂载**（`:ro`）：从容器层面防止 Agent 修改文件，与 permission deny 双重保障
2. **healthcheck**：runtime 容器自动健康检查，unhealthy 时自动重启
3. **depends_on + condition**：API 层等 runtime 健康后才启动
4. **restart: unless-stopped**：容器异常退出自动恢复

### 新增团队脚本

```bash
#!/bin/bash
# add-team.sh <team-id> <team-name>
TEAM_ID=$1
TEAM_NAME=$2

# 1. 创建团队目录
mkdir -p teams/$TEAM_ID/{skills,kb}

# 2. 生成默认配置
cat > teams/$TEAM_ID/opencode.json << EOF
{
  "\$schema": "https://opencode.ai/config.json",
  "server": { "hostname": "0.0.0.0", "port": 4096 },
  "instructions": ["./AGENTS.md"],
  "permission": {
    "skill": { "*": "allow" },
    "read": "allow", "list": "allow",
    "edit": "deny", "write": "deny", "bash": "deny"
  }
}
EOF

# 3. 生成默认 AGENTS.md
cat > teams/$TEAM_ID/AGENTS.md << 'EOF'
# 团队规则
- 先用 find.files 列出 kb/ 目录，根据问题按需读取
- 回答引用具体文件名
- 不确定就明说
- 不修改任何文件
EOF

echo "团队 $TEAM_ID 创建完成"
echo "请在 docker-compose.yml 中添加对应服务组"
echo "然后运行 docker compose up -d"
```

---

## 八、端口规划（与原方案一致）

| 角色 | Team A | Team B | Team C |
|------|--------|--------|--------|
| Runtime (OpenCode) | 4101 | 4102 | 4103 |
| API | 4201 | 4202 | 4203 |
| UI | 4301 | 4302 | 4303 |

对外可通过 Nginx 配成子域名：

- `team-a.agent.company` → :4301
- `team-b.agent.company` → :4302
- `team-c.agent.company` → :4303

---

## 十、验收标准（增强版）

1. 打开 Team A 页面，不会看到团队选择（天然隔离）
2. 提问后能拿到 Team A runtime 的回答，且消息逐字流式显示
3. Team A 回答能正确引用 kb/ 中的具体文件内容
4. Team A 能识别 skills/ 中的技能并按流程执行
5. Team A 页面不可能串到 Team B 数据
6. **新增**：Agent 无法修改文件或执行 bash 命令
7. **新增**：Runtime 挂掉时前端显示明确错误提示而非空白
8. **新增**：两个用户同时在 Team A 对话，各自独立不干扰

---

## 十二、后续迭代优先级

MVP 跑通后，建议按以下顺序逐步增强：

1. **会话持久化**：API 层会话信息持久化到文件或 Redis，容器重启不丢失
2. **用户登录**：集成公司 SSO 或简单的用户名密码认证
3. **kb/ 向量检索**：将知识库文档做 embedding，改用语义检索替代全文扫描
4. **统一首页**：一个入口页展示所有团队链接，但不做复杂的团队管理
5. **用量统计**：记录每个团队的 token 消耗和调用次数
6. **多模型支持**：允许团队在 opencode.json 中配置不同的 LLM 供应商