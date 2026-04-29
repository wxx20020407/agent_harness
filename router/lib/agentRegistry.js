/**
 * Agent Registry - Agent 注册表
 *
 * 职责：
 * 1. 管理 Agent 配置信息
 * 2. 提供健康检查
 * 3. 支持关键词搜索
 * 4. 权限隔离：每个 Agent 的资源只有自己可见
 */

import { readFile } from 'fs/promises';
import { existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';
import YAML from 'yaml';

const __dirname = dirname(fileURLToPath(import.meta.url));

class AgentRegistry {
  constructor(configPath = null) {
    this.configPath = configPath || join(__dirname, '../config/agents.yaml');
    this.agents = new Map();
    this.defaults = {};
    this.healthStatus = new Map();
    this.lastHealthCheck = new Map();
    this.config = null;
  }

  /**
   * 初始化：加载配置文件
   */
  async init() {
    await this.loadConfig();
    console.log(`[AgentRegistry] Loaded ${this.agents.size} agents`);
  }

  /**
   * 加载配置文件
   */
  async loadConfig() {
    try {
      if (!existsSync(this.configPath)) {
        console.warn(`[AgentRegistry] Config file not found: ${this.configPath}`);
        return;
      }

      const content = await readFile(this.configPath, 'utf-8');
      this.config = YAML.parse(content);

      // 解析 agents
      if (this.config.agents) {
        for (const [id, agent] of Object.entries(this.config.agents)) {
          this.agents.set(id, {
            id,
            ...agent,
            status: agent.metadata?.status || 'active'
          });
        }
      }

      // 解析 defaults
      this.defaults = this.config.defaults || {};

    } catch (error) {
      console.error('[AgentRegistry] Failed to load config:', error.message);
      throw error;
    }
  }

  /**
   * 重载配置（热更新）
   */
  async reload() {
    console.log('[AgentRegistry] Reloading configuration...');
    this.agents.clear();
    await this.loadConfig();
    console.log(`[AgentRegistry] Reloaded ${this.agents.size} agents`);
  }

  // ===========================================================================
  // Agent 查询方法
  // ===========================================================================

  /**
   * 获取所有 Agent 列表（不含敏感信息）
   */
  async listAgents() {
    const agents = [];
    for (const [id, agent] of this.agents) {
      agents.push(this.sanitizeAgent(agent));
    }
    return agents;
  }

  /**
   * 根据 ID 获取 Agent 详情
   */
  async getAgent(agentId) {
    const agent = this.agents.get(agentId);
    if (!agent) {
      return null;
    }
    return this.sanitizeAgent(agent);
  }

  /**
   * 获取 Agent 完整信息（包含 endpoint 等）
   */
  async getAgentInternal(agentId) {
    return this.agents.get(agentId) || null;
  }

  /**
   * 根据关键词搜索匹配的 Agent
   */
  async findAgents(query, context = {}) {
    const queryLower = query.toLowerCase();
    const matches = [];

    for (const [id, agent] of this.agents) {
      // 跳过非活跃 Agent
      if (agent.status !== 'active') continue;

      let score = 0;
      let matchedKeywords = [];

      // 关键词匹配
      if (agent.routing?.keywords) {
        for (const keyword of agent.routing.keywords) {
          if (queryLower.includes(keyword.toLowerCase())) {
            score += 1;
            matchedKeywords.push(keyword);
          }
        }
      }

      // 描述匹配
      if (agent.description) {
        const descLower = agent.description.toLowerCase();
        for (const word of queryLower.split(/\s+/)) {
          if (word.length > 1 && descLower.includes(word)) {
            score += 0.3;
          }
        }
      }

      if (score > 0) {
        // 归一化分数
        const maxScore = agent.routing?.keywords?.length || 1;
        const normalizedScore = Math.min(score / maxScore, 1);

        matches.push({
          agentId: id,
          agent: this.sanitizeAgent(agent),
          score: normalizedScore,
          matchedKeywords,
          confidence: normalizedScore
        });
      }
    }

    // 按分数降序排列
    matches.sort((a, b) => b.score - a.score);

    return matches;
  }

  /**
   * 清理 Agent 信息（移除敏感字段）
   */
  sanitizeAgent(agent) {
    const { endpoint, ...rest } = agent;
    return {
      ...rest,
      endpoint: endpoint ? {
        // 不暴露内部 URL，只返回健康状态
        healthy: this.healthStatus.get(agent.id) || false
      } : undefined
    };
  }

  // ===========================================================================
  // 资源管理（权限隔离）
  // ===========================================================================

  /**
   * 获取 Agent 的资源（skills 和 kb）
   * 注意：每个 Agent 只能访问自己的资源
   */
  async getAgentResources(agentId) {
    const agent = this.agents.get(agentId);
    if (!agent) {
      return null;
    }

    return {
      skills: agent.resources?.skills || [],
      kb: agent.resources?.kb || []
    };
  }

  /**
   * 检查资源是否属于指定 Agent
   */
  async checkResourceOwnership(agentId, resourceType, resourceName) {
    const agent = this.agents.get(agentId);
    if (!agent || !agent.resources) {
      return false;
    }

    const resources = resourceType === 'skill'
      ? agent.resources.skills
      : agent.resources.kb;

    if (!resources) {
      return false;
    }

    return resources.some(r => r.name === resourceName);
  }

  // ===========================================================================
  // 健康检查
  // ===========================================================================

  /**
   * 检查单个 Agent 健康状态
   */
  async healthCheck(agentId) {
    const agent = this.agents.get(agentId);
    if (!agent) {
      return { healthy: false, error: 'Agent not found' };
    }

    if (!agent.endpoint?.url) {
      return { healthy: false, error: 'No endpoint configured' };
    }

    const healthUrl = `${agent.endpoint.url}${agent.endpoint.healthCheck || '/health'}`;
    const timeout = this.defaults.healthCheckInterval || 30000;

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      const response = await fetch(healthUrl, {
        method: 'GET',
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      const healthy = response.status === 200 || response.status === 401;
      this.healthStatus.set(agentId, healthy);
      this.lastHealthCheck.set(agentId, Date.now());

      return {
        healthy,
        status: response.status,
        lastCheck: new Date().toISOString()
      };
    } catch (error) {
      this.healthStatus.set(agentId, false);
      this.lastHealthCheck.set(agentId, Date.now());

      return {
        healthy: false,
        error: error.message,
        lastCheck: new Date().toISOString()
      };
    }
  }

  /**
   * 检查所有 Agent 健康状态
   */
  async healthCheckAll() {
    const results = {};
    const checks = [];

    for (const [id] of this.agents) {
      checks.push(
        this.healthCheck(id).then(result => {
          results[id] = result;
        })
      );
    }

    await Promise.all(checks);
    return results;
  }

  /**
   * 获取缓存的健康状态
   */
  getCachedHealthStatus(agentId) {
    return this.healthStatus.get(agentId) || false;
  }

  // ===========================================================================
  // 动态注册
  // ===========================================================================

  /**
   * 动态注册 Agent
   */
  async registerAgent(config) {
    const id = config.id;
    if (!id) {
      throw new Error('Agent ID is required');
    }

    if (this.agents.has(id)) {
      console.warn(`[AgentRegistry] Agent ${id} already exists, updating...`);
    }

    this.agents.set(id, {
      id,
      ...config,
      status: config.status || 'active'
    });

    console.log(`[AgentRegistry] Registered agent: ${id}`);
    return this.sanitizeAgent(this.agents.get(id));
  }

  /**
   * 更新 Agent 配置
   */
  async updateAgent(agentId, updates) {
    const existing = this.agents.get(agentId);
    if (!existing) {
      throw new Error(`Agent ${agentId} not found`);
    }

    const updated = {
      ...existing,
      ...updates,
      id: agentId  // 确保 ID 不被修改
    };

    this.agents.set(agentId, updated);
    console.log(`[AgentRegistry] Updated agent: ${agentId}`);

    return this.sanitizeAgent(updated);
  }

  /**
   * 注销 Agent
   */
  async unregisterAgent(agentId) {
    if (!this.agents.has(agentId)) {
      return false;
    }

    this.agents.delete(agentId);
    this.healthStatus.delete(agentId);
    this.lastHealthCheck.delete(agentId);

    console.log(`[AgentRegistry] Unregistered agent: ${agentId}`);
    return true;
  }

  // ===========================================================================
  // 工具方法
  // ===========================================================================

  /**
   * 获取 Agent 数量
   */
  size() {
    return this.agents.size;
  }

  /**
   * 检查 Agent 是否存在
   */
  has(agentId) {
    return this.agents.has(agentId);
  }

  /**
   * 获取默认配置
   */
  getDefaults() {
    return { ...this.defaults };
  }
}

// 导出单例
let registryInstance = null;

export async function getRegistry(configPath = null) {
  if (!registryInstance) {
    registryInstance = new AgentRegistry(configPath);
    await registryInstance.init();
  }
  return registryInstance;
}

export { AgentRegistry };
export default AgentRegistry;
