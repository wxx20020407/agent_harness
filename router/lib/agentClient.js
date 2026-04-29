/**
 * Agent Client - 代理调用目标 Agent
 *
 * 职责：
 * 1. HTTP 代理到目标 Agent
 * 2. SSE 流式转发
* 3. 会话管理
 */

import { randomUUID } from 'crypto';

export class AgentClient {
  constructor(registry, config = {}) {
    this.registry = registry;
    this.config = {
      timeout: 300000, // 5 minutes default
      ...config
    };

    // 活跃会话缓存 (sessionId -> { agentId, lastActivity })
    this.activeSessions = new Map();
  }

  /**
   * 创建会话
   */
  async createSession(agentId) {
    const agent = await this.registry.getAgentInternal(agentId);
    if (!agent) {
      throw new Error(`Agent not found: ${agentId}`);
    }

    const url = `${agent.endpoint.url}/sessions`;

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(this.config.timeout)
      });

      if (!response.ok) {
        throw new Error(`Failed to create session: ${response.status}`);
      }

      const data = await response.json();
      const sessionId = data.sessionId || data.id;

      // 记录活跃会话
      this.activeSessions.set(sessionId, {
        agentId,
        lastActivity: Date.now()
      });

      return {
        sessionId,
        agentId,
        agentName: agent.name
      };
    } catch (error) {
      console.error(`[AgentClient] Failed to create session for ${agentId}:`, error.message);
      throw error;
    }
  }

  /**
   * 获取会话信息
   */
  async getSession(agentId, sessionId) {
    const agent = await this.registry.getAgentInternal(agentId);
    if (!agent) {
      throw new Error(`Agent not found: ${agentId}`);
    }

    const url = `${agent.endpoint.url}/sessions/${sessionId}`;

    try {
      const response = await fetch(url, {
        signal: AbortSignal.timeout(this.config.timeout)
      });

      if (!response.ok) {
        if (response.status === 404) {
          return null; // 会话不存在
        }
        throw new Error(`Failed to get session: ${response.status}`);
      }

      const data = await response.json();

      // 更新活跃时间
      if (this.activeSessions.has(sessionId)) {
        this.activeSessions.get(sessionId).lastActivity = Date.now();
      }

      return data;
    } catch (error) {
      console.error(`[AgentClient] Failed to get session ${sessionId}:`, error.message);
      throw error;
    }
  }

  /**
   * 流式调用 Agent
   */
  async streamCall(agentId, sessionId, message, res) {
    const agent = await this.registry.getAgentInternal(agentId);
    if (!agent) {
      throw new Error(`Agent not found: ${agentId}`);
    }

    const url = `${agent.endpoint.url}/chat`;

    // 设置 SSE headers
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.setHeader('X-Accel-Buffering', 'no');
    res.flushHeaders();

    const sendEvent = (obj) => {
      if (!res.writableEnded) {
        res.write(`data: ${JSON.stringify(obj)}\n\n`);
      }
    };

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId,
          message
        }),
        signal: AbortSignal.timeout(agent.endpoint.timeout || this.config.timeout)
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Unknown error');
        sendEvent({
          type: 'error',
          message: `Agent returned ${response.status}: ${errorText}`
        });
        res.end();
        return;
      }

      // 流式转发
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // 解析 SSE 事件
        const lines = buffer.split('\n');
        buffer = lines.pop(); // 保留未完成的行

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            // 直接转发
            if (!res.writableEnded) {
              res.write(line + '\n\n');
            }
          }
        }
      }

      // 更新活跃时间
      if (this.activeSessions.has(sessionId)) {
        this.activeSessions.get(sessionId).lastActivity = Date.now();
      }

      res.end();
    } catch (error) {
      console.error(`[AgentClient] Stream call failed:`, error.message);
      sendEvent({
        type: 'error',
        message: error.message || 'Connection failed'
      });
      res.end();
    }
  }

  /**
   * 带上下文的流式调用 Agent
   * 发送 { sessionId, message, context } 到团队 API
   * context 是跨团队的完整对话历史
   */
  async streamCallWithContext(agentId, sessionId, message, context, res) {
    const agent = await this.registry.getAgentInternal(agentId);
    if (!agent) {
      throw new Error(`Agent not found: ${agentId}`);
    }

    const url = `${agent.endpoint.url}/chat`;

    // 设置 SSE headers（仅当调用方未设置时）
    if (!res.headersSent) {
      res.setHeader('Content-Type', 'text/event-stream');
      res.setHeader('Cache-Control', 'no-cache');
      res.setHeader('Connection', 'keep-alive');
      res.setHeader('X-Accel-Buffering', 'no');
      res.flushHeaders();
    }

    // 带背压处理的写入（超时保护）
    const writeSSE = (data) => {
      return new Promise((resolve) => {
        if (res.writableEnded) return resolve();
        const ok = res.write(data);
        if (ok) {
          resolve();
        } else {
          const onDrain = () => { clearTimeout(t); resolve(); };
          const t = setTimeout(() => {
            res.removeListener('drain', onDrain);
            resolve(); // 超时后继续，避免卡死
          }, 10000);
          res.once('drain', onDrain);
        }
      });
    };

    const sendEvent = async (obj) => {
      await writeSSE(`data: ${JSON.stringify(obj)}\n\n`);
    };

    try {
      const body = { sessionId, message };
      if (context) {
        body.context = context;
      }

      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(agent.endpoint.timeout || this.config.timeout)
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => 'Unknown error');
        await sendEvent({
          type: 'error',
          message: `Agent returned ${response.status}: ${errorText}`
        });
        res.end();
        return;
      }

      // 流式转发（带背压处理 + keepalive）
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let lastWriteTime = Date.now();

      // 每 15 秒发送 SSE 注释保活，防止代理超时
      const keepalive = setInterval(() => {
        if (!res.writableEnded && Date.now() - lastWriteTime > 15000) {
          res.write(': keepalive\n\n');
          lastWriteTime = Date.now();
        }
      }, 15000);

      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // 解析 SSE 事件
          const lines = buffer.split('\n');
          buffer = lines.pop(); // 保留未完成的行

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              await writeSSE(line + '\n\n');
              lastWriteTime = Date.now();
            }
          }
        }
      } finally {
        clearInterval(keepalive);
      }

      // 更新活跃时间
      if (this.activeSessions.has(sessionId)) {
        this.activeSessions.get(sessionId).lastActivity = Date.now();
      }

      res.end();
    } catch (error) {
      console.error(`[AgentClient] Stream call with context failed:`, error.message);
      await sendEvent({
        type: 'error',
        message: error.message || 'Connection failed'
      });
      if (!res.writableEnded) res.end();
    }
  }

  /**
   * 非流式调用 Agent (等待完整响应)
   */
  async call(agentId, sessionId, message) {
    const agent = await this.registry.getAgentInternal(agentId);
    if (!agent) {
      throw new Error(`Agent not found: ${agentId}`);
    }

    const url = `${agent.endpoint.url}/chat`;

    // 收集完整响应
    const events = [];

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sessionId,
          message
        }),
        signal: AbortSignal.timeout(agent.endpoint.timeout || this.config.timeout)
      });

      if (!response.ok) {
        throw new Error(`Agent returned ${response.status}`);
      }

      // 解析 SSE 流
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6));
              events.push(event);
              if (event.type === 'text' && event.content) {
                fullContent += event.content;
              }
            } catch {}
          }
        }
      }

      return {
        events,
        content: fullContent,
        sessionId,
        agentId
      };
    } catch (error) {
      console.error(`[AgentClient] Call failed:`, error.message);
      throw error;
    }
  }

  /**
   * 代理任意请求到目标 Agent
   */
  async proxyRequest(agentId, method, path, req, res) {
    const agent = await this.registry.getAgentInternal(agentId);
    if (!agent) {
      return res.status(404).json({ error: `Agent not found: ${agentId}` });
    }

    const url = `${agent.endpoint.url}${path}`;

    try {
      const options = {
        method,
        headers: {
          'Content-Type': req.headers['content-type'] || 'application/json'
        }
      };

      if (method !== 'GET' && method !== 'HEAD' && req.body) {
        options.body = JSON.stringify(req.body);
      }

      const response = await fetch(url, {
        ...options,
        signal: AbortSignal.timeout(agent.endpoint.timeout || this.config.timeout)
      });

      // 转发响应头
      response.headers.forEach((value, key) => {
        if (key.toLowerCase() !== 'content-encoding') {
          res.setHeader(key, value);
        }
      });

      // 转发响应体
      const body = await response.text();
      res.status(response.status).send(body);
    } catch (error) {
      console.error(`[AgentClient] Proxy request failed:`, error.message);
      res.status(502).json({ error: `Proxy error: ${error.message}` });
    }
  }

  /**
   * 获取会话所属的 Agent
   */
  getAgentForSession(sessionId) {
    return this.activeSessions.get(sessionId)?.agentId || null;
  }

  /**
   * 清理过期会话
   */
  cleanupExpiredSessions(maxAge = 3600000) { // 默认 1 小时
    const now = Date.now();
    for (const [sessionId, info] of this.activeSessions) {
      if (now - info.lastActivity > maxAge) {
        this.activeSessions.delete(sessionId);
      }
    }
  }
}

export default AgentClient;
