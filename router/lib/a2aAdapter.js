/**
 * A2A Protocol Adapter
 *
 * 将 A2A (Agent2Agent) JSON-RPC 请求转换为内部 Router API 调用
 * 支持 message/send (非流式) 和 message/stream (SSE 流式)
 *
 * 基于 A2A Protocol v1.0 规范
 */

import { randomUUID } from 'crypto';

// A2A Task 状态枚举
const TASK_STATES = {
  UNSPECIFIED: 'TASK_STATE_UNSPECIFIED',
  SUBMITTED: 'TASK_STATE_SUBMITTED',
  WORKING: 'TASK_STATE_WORKING',
  COMPLETED: 'TASK_STATE_COMPLETED',
  FAILED: 'TASK_STATE_FAILED',
  INPUT_REQUIRED: 'TASK_STATE_INPUT_REQUIRED',
  CANCELED: 'TASK_STATE_CANCELED',
  REJECTED: 'TASK_STATE_REJECTED',
};

export class A2AAdapter {
  constructor(registry, agentClient, router) {
    this.registry = registry;
    this.agentClient = agentClient;
    this.router = router;
  }

  /**
   * 从 Registry 构建 A2A AgentCard
   */
  async buildAgentCard(baseUrl) {
    const agents = await this.registry.listAgents();
    const skills = [];

    for (const agent of agents) {
      const keywords = agent.routing?.keywords || [];
      // 每个 agent 的前 5 个关键词作为 skills
      for (const kw of keywords.slice(0, 5)) {
        skills.push({
          id: `${agent.id}-${kw.toLowerCase().replace(/\s+/g, '-')}`,
          name: kw,
          description: `${agent.name}: ${agent.description || ''}`,
          tags: agent.metadata?.tags || [],
        });
      }
    }

    return {
      name: 'Agent Harness Router',
      description: '多 Agent 智能路由平台，提供统一的 Agent 发现和调用接口',
      version: '1.0.0',
      supported_interfaces: [
        {
          url: `${baseUrl}/a2a`,
          protocol_binding: 'JSONRPC',
          protocol_version: '1.0',
        },
      ],
      capabilities: {
        streaming: true,
        push_notifications: false,
      },
      default_input_modes: ['text/plain', 'application/json'],
      default_output_modes: ['text/plain', 'application/json'],
      skills,
    };
  }

  /**
   * 从 A2A Message 的 parts 中提取文本
   */
  extractText(message) {
    if (!message?.parts) return '';
    return message.parts
      .filter(p => p.text)
      .map(p => p.text)
      .join('\n');
  }

  /**
   * 确定目标 Agent（自动路由或显式指定）
   */
  async resolveAgent(message) {
    // 优先使用 metadata 中显式指定的 agent_id
    const explicitId = message?.metadata?.agent_id;
    if (explicitId) {
      const agent = await this.registry.getAgent(explicitId);
      if (agent) return explicitId;
    }

    // 自动路由
    const text = this.extractText(message);
    if (!text) return null;

    const routeResult = await this.router.route(text);
    return routeResult.recommendedAgent?.agentId || null;
  }

  /**
   * 处理 message/send（非流式）
   */
  async handleSendMessage(params, res) {
    const { message, id } = params;

    if (!message?.parts?.length) {
      return res.json({
        jsonrpc: '2.0',
        id: id || null,
        error: { code: -32602, message: 'Invalid params: message.parts is required' },
      });
    }

    const textContent = this.extractText(message);
    const contextId = message.context_id || randomUUID();
    const taskId = randomUUID();

    // 确定目标 Agent
    let targetAgentId;
    try {
      targetAgentId = await this.resolveAgent(message);
    } catch (err) {
      return res.json({
        jsonrpc: '2.0',
        id: id || null,
        error: { code: -32603, message: `Routing error: ${err.message}` },
      });
    }

    if (!targetAgentId) {
      return res.json({
        jsonrpc: '2.0',
        id: id || null,
        error: { code: -32603, message: 'No suitable agent found for this message' },
      });
    }

    // 创建会话并调用
    try {
      const session = await this.agentClient.createSession(targetAgentId);
      const callResult = await this.agentClient.call(targetAgentId, session.sessionId, textContent);

      res.json({
        jsonrpc: '2.0',
        id: id || null,
        result: {
          task: {
            id: taskId,
            context_id: contextId,
            status: {
              state: TASK_STATES.COMPLETED,
              message: {
                message_id: randomUUID(),
                context_id: contextId,
                task_id: taskId,
                role: 'ROLE_AGENT',
                parts: [{ text: callResult.content }],
              },
              timestamp: new Date().toISOString(),
            },
            artifacts: [
              {
                artifact_id: `${taskId}-output`,
                name: 'response',
                parts: [{ text: callResult.content }],
              },
            ],
          },
        },
      });
    } catch (error) {
      res.json({
        jsonrpc: '2.0',
        id: id || null,
        result: {
          task: {
            id: taskId,
            context_id: contextId,
            status: {
              state: TASK_STATES.FAILED,
              message: {
                message_id: randomUUID(),
                context_id: contextId,
                task_id: taskId,
                role: 'ROLE_AGENT',
                parts: [{ text: `Agent call failed: ${error.message}` }],
              },
              timestamp: new Date().toISOString(),
            },
          },
        },
      });
    }
  }

  /**
   * 处理 message/stream（SSE 流式）
   */
  async handleStreamingMessage(params, res) {
    const { message, id } = params;

    if (!message?.parts?.length) {
      return res.json({
        jsonrpc: '2.0',
        id: id || null,
        error: { code: -32602, message: 'Invalid params: message.parts is required' },
      });
    }

    const textContent = this.extractText(message);
    const contextId = message.context_id || randomUUID();
    const taskId = randomUUID();

    let targetAgentId;
    try {
      targetAgentId = await this.resolveAgent(message);
    } catch {
      targetAgentId = null;
    }

    if (!targetAgentId) {
      return res.json({
        jsonrpc: '2.0',
        id: id || null,
        error: { code: -32603, message: 'No suitable agent found for this message' },
      });
    }

    // 设置 SSE
    res.setHeader('Content-Type', 'text/event-stream');
    res.setHeader('Cache-Control', 'no-cache');
    res.setHeader('Connection', 'keep-alive');
    res.flushHeaders();

    const sendEvent = (data) => {
      res.write(`data: ${JSON.stringify(data)}\n\n`);
    };

    // 发送初始状态: SUBMITTED → WORKING
    sendEvent({
      jsonrpc: '2.0',
      id: id || null,
      result: {
        status_update: {
          task_id: taskId,
          context_id: contextId,
          status: {
            state: TASK_STATES.SUBMITTED,
            timestamp: new Date().toISOString(),
          },
          final: false,
        },
      },
    });

    sendEvent({
      jsonrpc: '2.0',
      result: {
        status_update: {
          task_id: taskId,
          context_id: contextId,
          status: {
            state: TASK_STATES.WORKING,
            timestamp: new Date().toISOString(),
          },
          final: false,
        },
      },
    });

    try {
      const session = await this.agentClient.createSession(targetAgentId);

      // 调用内部 /chat 并收集 SSE 流
      const chatRes = await fetch(`${this.getRouterUrl()}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agentId: targetAgentId,
          sessionId: session.sessionId,
          message: textContent,
        }),
      });

      if (!chatRes.ok) {
        throw new Error(`Chat API error: ${chatRes.status}`);
      }

      // 读取内部 SSE 流，转换为 A2A 格式
      const reader = chatRes.body.getReader();
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

              if (event.type === 'text' && event.content) {
                fullContent += event.content;
              }
            } catch {}
          }
        }
      }

      // 发送最终 artifact
      sendEvent({
        jsonrpc: '2.0',
        result: {
          artifact_update: {
            task_id: taskId,
            context_id: contextId,
            artifact: {
              artifact_id: `${taskId}-output`,
              name: 'response',
              parts: [{ text: fullContent }],
            },
            append: false,
            last_chunk: true,
          },
        },
      });

      // 发送完成状态
      sendEvent({
        jsonrpc: '2.0',
        result: {
          status_update: {
            task_id: taskId,
            context_id: contextId,
            status: {
              state: TASK_STATES.COMPLETED,
              timestamp: new Date().toISOString(),
            },
            final: true,
          },
        },
      });
    } catch (error) {
      sendEvent({
        jsonrpc: '2.0',
        result: {
          status_update: {
            task_id: taskId,
            context_id: contextId,
            status: {
              state: TASK_STATES.FAILED,
              message: {
                message_id: randomUUID(),
                role: 'ROLE_AGENT',
                parts: [{ text: error.message }],
              },
              timestamp: new Date().toISOString(),
            },
            final: true,
          },
        },
      });
    }

    res.end();
  }

  /**
   * 获取 Router API 的内部 URL
   * 用于 A2A streaming 时调用内部 /chat 端点
   */
  getRouterUrl() {
    // 在 Docker 内部，server 监听在同一进程
    // 但 /chat 端点在同一个 Express app 上，所以直接用 localhost
    const port = process.env.PORT || '3000';
    return `http://localhost:${port}`;
  }

  /**
   * 主入口 — 分发 JSON-RPC 方法
   */
  async handle(req, res) {
    const { method, params, id } = req.body;

    switch (method) {
      case 'message/send':
        return this.handleSendMessage({ ...params, id }, res);
      case 'message/stream':
        return this.handleStreamingMessage({ ...params, id }, res);
      default:
        return res.json({
          jsonrpc: '2.0',
          id: id || null,
          error: { code: -32601, message: `Method not found: ${method}` },
        });
    }
  }
}
