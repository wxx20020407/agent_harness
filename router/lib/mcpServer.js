/**
 * MCP Server - Model Context Protocol Server
 *
 * 提供 MCP 协议接口，让 Claude Code 可以通过 MCP 工具调用 Router
 *
 * 暴露的工具：
 * - mcp__router__list_agents: 列出所有可用 Agent
 * - mcp__router__find_agent: 根据问题找到合适的 Agent
 * - mcp__router__call_agent: 调用指定 Agent
 * - mcp__router__get_agent_info: 获取 Agent 详细信息
 *
 * 使用方式：
 * 在 Claude Code 的 opencode.json 中配置：
 * {
 *   "mcpServers": {
 *     "agent-router": {
 *       "command": "node",
 *       "args": ["/data/agent_harness/router/lib/mcpServer.js"],
 *       "env": {
 *         "ROUTER_API_URL": "http://localhost:4000"
 *       }
 *     }
 *   }
 * }
 */

import { createInterface } from 'readline';
import { spawn } from 'child_process';

// 配置
const ROUTER_API_URL = process.env.ROUTER_API_URL || 'http://localhost:4000';

// MCP 协议实现
class MCPServer {
  constructor() {
    this.tools = new Map();
    this.rl = createInterface({
      input: process.stdin,
      output: process.stdout,
      terminal: false
    });

    // 注册工具
    this.registerTools();
  }

  /**
   * 注册 MCP 工具
   */
  registerTools() {
    // 列出所有 Agent
    this.tools.set('list_agents', {
      name: 'list_agents',
      description: '列出所有可用的 Agent',
      inputSchema: {
        type: 'object',
        properties: {},
        required: []
      },
      handler: async () => {
        const response = await fetch(`${ROUTER_API_URL}/agents`);
        const data = await response.json();
        return data.agents.map(a => ({
          id: a.id,
          name: a.name,
          description: a.description,
          keywords: a.routing?.keywords?.slice(0, 5) || []
        }));
      }
    });

    // 查找 Agent
    this.tools.set('find_agent', {
      name: 'find_agent',
      description: '根据用户问题找到最合适的 Agent',
      inputSchema: {
        type: 'object',
        properties: {
          query: {
            type: 'string',
            description: '用户问题或关键词'
          }
        },
        required: ['query']
      },
      handler: async ({ query }) => {
        const response = await fetch(`${ROUTER_API_URL}/route`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: query })
        });
        const data = await response.json();
        return data;
      }
    });

    // 调用 Agent
    this.tools.set('call_agent', {
      name: 'call_agent',
      description: '调用指定 Agent 进行对话。返回 Agent 的完整响应。',
      inputSchema: {
        type: 'object',
        properties: {
          agent_id: {
            type: 'string',
            description: '要调用的 Agent ID'
          },
          message: {
            type: 'string',
            description: '要发送给 Agent 的消息'
          },
          session_id: {
            type: 'string',
            description: '会话 ID（可选，用于保持对话上下文）'
          }
        },
        required: ['agent_id', 'message']
      },
      handler: async ({ agent_id, message, session_id }) => {
        // 创建或复用会话
        let sessionId = session_id;
        if (!sessionId) {
          const sessionResponse = await fetch(`${ROUTER_API_URL}/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agentId: agent_id })
          });
          const sessionData = await sessionResponse.json();
          sessionId = sessionData.sessionId;
        }

        // 调用 Agent（非流式，收集完整响应）
        const response = await fetch(`${ROUTER_API_URL}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agentId: agent_id,
            sessionId,
            message
          })
        });

        // 收集 SSE 流
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullContent = '';
        const events = [];

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
          content: fullContent,
          session_id: sessionId,
          agent_id,
          event_count: events.length
        };
      }
    });

    // 获取 Agent 信息
    this.tools.set('get_agent_info', {
      name: 'get_agent_info',
      description: '获取指定 Agent 的详细信息，包括其 skills 和知识库',
      inputSchema: {
        type: 'object',
        properties: {
          agent_id: {
            type: 'string',
            description: 'Agent ID'
          }
        },
        required: ['agent_id']
      },
      handler: async ({ agent_id }) => {
        const [agentResponse, resourcesResponse] = await Promise.all([
          fetch(`${ROUTER_API_URL}/agents/${agent_id}`),
          fetch(`${ROUTER_API_URL}/agents/${agent_id}/resources`)
        ]);

        const agentData = await agentResponse.json();
        const resourcesData = await resourcesResponse.json();

        return {
          ...agentData.agent,
          resources: resourcesData.resources
        };
      }
    });

    // 路由并调用（一步完成）
    this.tools.set('route_and_call', {
      name: 'route_and_call',
      description: '自动路由到合适的 Agent 并调用。一步完成路由和调用。',
      inputSchema: {
        type: 'object',
        properties: {
          message: {
            type: 'string',
            description: '用户消息'
          }
        },
        required: ['message']
      },
      handler: async ({ message }) => {
        const response = await fetch(`${ROUTER_API_URL}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message,
            autoRoute: true
          })
        });

        // 收集 SSE 流
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let fullContent = '';
        const events = [];

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
          content: fullContent,
          event_count: events.length
        };
      }
    });
  }

  /**
   * 启动 MCP Server
   */
  start() {
    console.error('[MCP Server] Starting...');
    console.error(`[MCP Server] Router API URL: ${ROUTER_API_URL}`);

    this.rl.on('line', (line) => {
      this.handleMessage(line);
    });
  }

  /**
   * 处理消息
   */
  async handleMessage(line) {
    try {
      const message = JSON.parse(line);
      console.error('[MCP Server] Received:', message.method || 'response');

      if (message.method === 'initialize') {
        this.sendResponse({
          jsonrpc: '2.0',
          id: message.id,
          result: {
            protocolVersion: '2024-11-05',
            capabilities: {
              tools: {
                listChanged: false
              }
            },
            serverInfo: {
              name: 'agent-router',
              version: '1.0.0'
            }
          }
        });
      } else if (message.method === 'notifications/initialized') {
        // 客户端初始化完成通知，无需回复
      } else if (message.method === 'tools/list') {
        this.sendResponse({
          jsonrpc: '2.0',
          id: message.id,
          result: {
            tools: Array.from(this.tools.entries()).map(([name, tool]) => ({
              name,
              description: tool.description,
              inputSchema: tool.inputSchema
            }))
          }
        });
      } else if (message.method === 'tools/call') {
        const toolName = message.params?.name;
        const args = message.params?.arguments || {};

        const tool = this.tools.get(toolName);
        if (!tool) {
          this.sendResponse({
            jsonrpc: '2.0',
            id: message.id,
            error: { code: -32601, message: `Tool not found: ${toolName}` }
          });
          return;
        }

        try {
          const result = await tool.handler(args);
          this.sendResponse({
            jsonrpc: '2.0',
            id: message.id,
            result: {
              content: [{
                type: 'text',
                text: JSON.stringify(result, null, 2)
              }]
            }
          });
        } catch (error) {
          this.sendResponse({
            jsonrpc: '2.0',
            id: message.id,
            error: { code: -32000, message: error.message }
          });
        }
      }
    } catch (error) {
      console.error('[MCP Server] Error:', error.message);
    }
  }

  /**
   * 发送响应
   */
  sendResponse(response) {
    console.log(JSON.stringify(response));
  }
}

// 启动
const server = new MCPServer();
server.start();
