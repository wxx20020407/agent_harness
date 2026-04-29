/**
 * Router API Server
 *
 * 核心功能：
 * 1. Agent 管理 API
 * 2. 智能路由
 * 3. 对话代理
 */

import express from 'express';
import cors from 'cors';
import { readFile } from 'fs/promises';
import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import YAML from 'yaml';

import { getRegistry } from './lib/agentRegistry.js';
import { Router } from './lib/router.js';
import { AgentClient } from './lib/agentClient.js';
import { A2AAdapter } from './lib/a2aAdapter.js';
import { SessionManager } from './lib/sessionManager.js';
import { logger } from './lib/logger.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

// 配置
const PORT = parseInt(process.env.PORT || '3000', 10);
const CONFIG_PATH = process.env.CONFIG_PATH || join(__dirname, 'config');

// Express 应用
const app = express();
app.use(cors());
app.use(express.json({ limit: '50mb' }));

// 请求 ID 中间件（用于日志追踪）
app.use((req, res, next) => {
  req.id = Math.random().toString(36).slice(2, 10);
  res.setHeader('X-Request-Id', req.id);
  next();
});

// 请求日志中间件
app.use(logger.requestLogger());

// 全局变量
let registry = null;
let router = null;
let agentClient = null;
let a2aAdapter = null;
let sessionManager = null;

// =============================================================================
// 初始化
// =============================================================================

async function init() {
  logger.info('Initializing Router...');

  // 初始化 Registry
  registry = await getRegistry(join(CONFIG_PATH, 'agents.yaml'));

  // 初始化 Router
  const routesConfig = await loadRoutesConfig();
  router = new Router(registry, routesConfig);

  // 初始化 AgentClient
  agentClient = new AgentClient(registry);

  // 初始化 A2A Adapter
  a2aAdapter = new A2AAdapter(registry, agentClient, router);

  // 初始化 SessionManager
  sessionManager = new SessionManager();

  // 启动健康检查
  startHealthCheck();

  logger.info('Router initialized', { agentCount: registry.size() });
}

async function loadRoutesConfig() {
  const routesPath = join(CONFIG_PATH, 'routes.yaml');
  if (existsSync(routesPath)) {
    const content = await readFile(routesPath, 'utf-8');
    return YAML.parse(content);
  }
  return {};
}

function startHealthCheck() {
  // 每 30 秒检查一次
  setInterval(async () => {
    try {
      const status = await registry.healthCheckAll();
      const healthyCount = Object.values(status).filter(s => s.healthy).length;
      logger.debug('Health check completed', { healthyCount, total: Object.keys(status).length });
    } catch (error) {
      logger.error('Health check error', { error: error.message });
    }
  }, 30000);

  // 初始检查
  registry.healthCheckAll().catch(() => {});
}

// =============================================================================
// API Routes
// =============================================================================

// Health check
app.get('/health', async (req, res) => {
  try {
    const healthStatus = await registry.healthCheckAll();
    const healthy = Object.values(healthStatus).every(h => h.healthy);

    res.status(healthy ? 200 : 503).json({
      status: healthy ? 'healthy' : 'degraded',
      agents: healthStatus,
      timestamp: new Date().toISOString()
    });
  } catch (error) {
    res.status(503).json({
      status: 'unhealthy',
      error: error.message
    });
  }
});

// List agents
app.get('/agents', async (req, res) => {
  try {
    const agents = await registry.listAgents();
    res.json({ agents });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get agent by ID
app.get('/agents/:id', async (req, res) => {
  try {
    const agent = await registry.getAgent(req.params.id);
    if (!agent) {
      return res.status(404).json({ error: 'Agent not found' });
    }
    res.json({ agent });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get agent resources
app.get('/agents/:id/resources', async (req, res) => {
  try {
    const resources = await registry.getAgentResources(req.params.id);
    if (!resources) {
      return res.status(404).json({ error: 'Agent not found' });
    }
    res.json({ agentId: req.params.id, resources });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Route - 智能路由
app.post('/route', async (req, res) => {
  try {
    const { message, context } = req.body;

    if (!message) {
      return res.status(400).json({ error: 'Missing message' });
    }

    const result = await router.route(message, context || {});
    logger.info('Route completed', {
      requestId: req.id,
      messagePreview: message.slice(0, 50),
      recommendedAgent: result.recommendedAgent?.agentId,
      method: result.method
    });
    res.json(result);
  } catch (error) {
    logger.error('Route error', { requestId: req.id, error: error.message });
    res.status(500).json({ error: error.message, requestId: req.id });
  }
});

// ─── Router Session Management ────────────────────────────────────────────

// List sessions
app.get('/sessions', async (req, res) => {
  try {
    const sessions = await sessionManager.getSessions();
    res.json({ sessions });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Create session
app.post('/sessions', async (req, res) => {
  try {
    const session = await sessionManager.createSession();
    res.json({ session });
  } catch (error) {
    console.error('[Router] Create session error:', error.message);
    res.status(500).json({ error: error.message });
  }
});

// Get session + messages
app.get('/sessions/:sessionId', async (req, res) => {
  try {
    const session = await sessionManager.getSession(req.params.sessionId);
    if (!session) {
      return res.status(404).json({ error: 'Session not found' });
    }
    res.json({ session });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Delete session
app.delete('/sessions/:sessionId', async (req, res) => {
  try {
    await sessionManager.deleteSession(req.params.sessionId);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Update session (title, etc.)
app.patch('/sessions/:sessionId', async (req, res) => {
  try {
    const session = await sessionManager.updateSession(req.params.sessionId, req.body);
    if (!session) {
      return res.status(404).json({ error: 'Session not found' });
    }
    res.json({ session });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// ─── Chat - 流式对话（带跨团队上下文）──────────────────────────────────────

app.post('/chat', async (req, res) => {
  try {
    const { message, agentId, routerSessionId, autoRoute } = req.body;

    if (!message) {
      return res.status(400).json({ error: 'Missing message' });
    }

    // 1. 确定目标 Agent（路由时只用当前消息）
    let targetAgentId = agentId;
    if (!targetAgentId) {
      if (autoRoute) {
        const route = await router.route(message);
        if (route.recommendedAgent) {
          targetAgentId = route.recommendedAgent.agentId;
        } else {
          return res.status(400).json({
            error: 'Could not determine target agent',
            suggestion: 'Please specify an agentId'
          });
        }
      } else {
        return res.status(400).json({
          error: 'Missing agentId',
          suggestion: 'Specify agentId or set autoRoute: true'
        });
      }
    }

    // 2. 查找或创建 Router 会话
    let session = null;
    if (routerSessionId) {
      session = await sessionManager.getSession(routerSessionId);
    }
    if (!session) {
      session = await sessionManager.createSession();
    }

    // 3. 添加用户消息到 Router 会话
    const agent = await registry.getAgentInternal(targetAgentId);
    await sessionManager.addMessage(session.id, {
      role: 'user',
      content: message,
    });

    // 更新会话标题（用第一条用户消息）
    if (session.title === '新会话') {
      const title = message.length > 30 ? message.slice(0, 30) + '...' : message;
      await sessionManager.updateSession(session.id, { title, currentAgentId: targetAgentId });
      session.title = title;
    }

    // 4. 构建跨团队上下文（全部历史）
    const context = await sessionManager.buildContext(session.id);

    // 5. 获取或创建 Team 会话
    let teamSessionId = await sessionManager.getTeamSession(session.id, targetAgentId);
    if (!teamSessionId) {
      const teamSession = await agentClient.createSession(targetAgentId);
      teamSessionId = teamSession.sessionId;
      await sessionManager.setTeamSession(session.id, targetAgentId, teamSessionId);
    }

    // 6. 发送路由信息事件
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders();

    res.write(`data: ${JSON.stringify({
      type: 'route_info',
      agentId: targetAgentId,
      agentName: agent?.name || targetAgentId,
      routerSessionId: session.id,
    })}\n\n`);

    // 7. 用临时 buffer 收集 SSE 响应，同时转发给客户端
    const collectedContent = { text: '', thinking: '' };
    const originalWrite = res.write.bind(res);
    const originalEnd = res.end.bind(res);

    // 拦截写入以收集内容
    res.write = function(chunk, ...args) {
      const str = typeof chunk === 'string' ? chunk : chunk.toString();
      // 解析 SSE 事件以收集内容
      const lines = str.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6));
            if (event.type === 'text' && event.content) {
              collectedContent.text += event.content;
            } else if (event.type === 'thinking' && event.content) {
              collectedContent.thinking += event.content;
            }
          } catch {}
        }
      }
      return originalWrite(chunk, ...args);
    };

    res.end = function(chunk, ...args) {
      if (chunk) {
        const str = typeof chunk === 'string' ? chunk : chunk.toString();
        const lines = str.split('\n');
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6));
              if (event.type === 'text' && event.content) {
                collectedContent.text += event.content;
              }
            } catch {}
          }
        }
      }

      // 8. 保存助手消息到 Router 会话
      if (collectedContent.text) {
        sessionManager.addMessage(session.id, {
          role: 'assistant',
          content: collectedContent.text,
          agentId: targetAgentId,
          agentName: agent?.name || targetAgentId,
          thinkingContent: collectedContent.thinking || '',
        }).catch(e => console.error('[Router] Failed to save message:', e.message));
      }

      return originalEnd(chunk, ...args);
    };

    // 9. 调用 Team API（带上下文）
    await agentClient.streamCallWithContext(targetAgentId, teamSessionId, message, context, res);

  } catch (error) {
    console.error('[Router] Chat error:', error.message);

    if (!res.headersSent) {
      res.status(500).json({ error: error.message });
    } else {
      res.write(`data: ${JSON.stringify({ type: 'error', message: error.message })}\n\n`);
      res.end();
    }
  }
});

// Agent proxy - 代理到目标 Agent
app.all('/agents/:id/proxy/*', async (req, res) => {
  try {
    const agentId = req.params.id;
    const proxyPath = req.params[0] || '';
    const method = req.method;

    await agentClient.proxyRequest(agentId, method, `/${proxyPath}`, req, res);
  } catch (error) {
    res.status(502).json({ error: error.message });
  }
});

// =============================================================================
// A2A Protocol Endpoints
// =============================================================================

// A2A Agent Card
app.get('/.well-known/agent-card.json', async (req, res) => {
  try {
    const baseUrl = `${req.protocol}://${req.get('host')}`;
    const card = await a2aAdapter.buildAgentCard(baseUrl);
    res.json(card);
  } catch (error) {
    logger.error('AgentCard error', { requestId: req.id, error: error.message });
    res.status(500).json({ error: error.message });
  }
});

// A2A JSON-RPC endpoint
app.post('/a2a', async (req, res) => {
  try {
    const { jsonrpc, method, id } = req.body;

    if (jsonrpc !== '2.0' || !method) {
      return res.status(400).json({
        jsonrpc: '2.0',
        id: id || null,
        error: { code: -32600, message: 'Invalid Request: requires jsonrpc 2.0 and method' },
      });
    }

    logger.info('A2A request', { requestId: req.id, method, id });
    await a2aAdapter.handle(req, res);
  } catch (error) {
    logger.error('A2A error', { requestId: req.id, error: error.message });
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: '2.0',
        id: req.body?.id || null,
        error: { code: -32603, message: error.message },
      });
    }
  }
});

// Root info
app.get('/', (req, res) => {
  res.json({
    name: 'Agent Harness Router',
    version: '1.0.0',
    agents: registry.size(),
    endpoints: {
      health: 'GET /health',
      agents: 'GET /agents',
      agent: 'GET /agents/:id',
      resources: 'GET /agents/:id/resources',
      route: 'POST /route',
      sessions: 'GET /sessions',
      createSession: 'POST /sessions',
      session: 'GET /sessions/:sessionId',
      deleteSession: 'DELETE /sessions/:sessionId',
      updateSession: 'PATCH /sessions/:sessionId',
      chat: 'POST /chat',
      proxy: 'ALL /agents/:id/proxy/*',
      a2a: 'POST /a2a',
      agentCard: 'GET /.well-known/agent-card.json'
    }
  });
});

// =============================================================================
// Error handling
// =============================================================================

app.use((err, req, res, next) => {
  const requestId = req.id || 'unknown';
  logger.error('Unhandled error', {
    requestId,
    error: err.message,
    stack: err.stack,
    path: req.path,
    method: req.method
  });

  // 统一错误响应格式
  const statusCode = err.statusCode || err.status || 500;
  const errorResponse = {
    error: err.message || 'Internal server error',
    requestId,
    timestamp: new Date().toISOString()
  };

  // 开发环境下返回堆栈信息
  if (process.env.NODE_ENV !== 'production' && err.stack) {
    errorResponse.stack = err.stack;
  }

  res.status(statusCode).json(errorResponse);
});

// =============================================================================
// Start server
// =============================================================================

async function start() {
  try {
    await init();

    app.listen(PORT, () => {
      logger.info('Server started', { port: PORT, configPath: CONFIG_PATH });
    });
  } catch (error) {
    logger.error('Failed to start server', { error: error.message, stack: error.stack });
    process.exit(1);
  }
}

start();
