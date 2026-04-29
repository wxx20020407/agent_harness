/**
 * Router - 路由引擎
 *
 * 职责：
 * 1. 根据用户输入选择合适的 Agent
 * 2. 支持关键词匹配
 * 3. 支持优先级规则
 * 4. 可选 LLM 辅助路由
 *
 * 参考：D-Claw 路由架构
 */

export class Router {
  constructor(registry, config = {}) {
    this.registry = registry;
    this.config = config;
    this.rules = config.rules || [];
    this.keywordMappings = config.keyword_mappings || {};
    this.defaultBehavior = config.default || {
      when_unsure: 'ask_user',
      auto_route_threshold: 0.7,
      min_alternative_confidence: 0.3,
      max_alternatives: 3
    };
  }

  /**
   * 主路由方法
   */
  async route(userMessage, context = {}) {
    const queryLower = userMessage.toLowerCase();

    // 1. 直接关键词映射
    const directMatch = this.matchDirectKeywords(queryLower);
    if (directMatch && directMatch.recommendedAgent?.confidence >= this.defaultBehavior.auto_route_threshold) {
      // 检查目标 Agent 是否健康
      if (this.isAgentHealthy(directMatch.recommendedAgent.agentId)) {
        return directMatch;
      }
      // 不健康则降级到搜索
    }

    // 2. 规则匹配
    const ruleMatch = this.matchRules(userMessage, context);
    if (ruleMatch && this.isAgentHealthy(ruleMatch.recommendedAgent?.agentId)) {
      return ruleMatch;
    }

    // 3. 通用关键词搜索
    const searchResult = await this.searchAgents(userMessage, context);

    // 4. 如果有高置信度结果，返回
    if (searchResult.matches.length > 0 &&
        searchResult.matches[0].confidence >= this.defaultBehavior.auto_route_threshold) {
      return {
        recommendedAgent: searchResult.matches[0],
        alternatives: searchResult.matches.slice(1, this.defaultBehavior.max_alternatives + 1),
        method: 'keyword_search'
      };
    }

    // 5. 低置信度或无匹配
    return this.handleNoMatch(searchResult);
  }

  /**
   * 检查 Agent 是否健康
   */
  isAgentHealthy(agentId) {
    const agent = this.registry.agents.get(agentId);
    return agent && agent.status === 'active' && agent.endpoint?.healthy !== false;
  }

  /**
   * 直接关键词映射
   */
  matchDirectKeywords(query) {
    for (const [keyword, agentId] of Object.entries(this.keywordMappings)) {
      if (query.includes(keyword.toLowerCase())) {
        return {
          recommendedAgent: {
            agentId,
            confidence: 0.95,
            matchedKeywords: [keyword],
            method: 'direct_mapping'
          },
          alternatives: [],
          method: 'direct_mapping'
        };
      }
    }
    return null;
  }

  /**
   * 规则匹配 (参考 D-Claw)
   */
  matchRules(userMessage, context) {
    const queryLower = userMessage.toLowerCase();

    for (const rule of this.rules) {
      // 检查条件
      if (!this.checkCondition(rule.condition, queryLower, context)) {
        continue;
      }

      // 按优先级检查
      const priorityCheck = rule.priority_check || [];
      for (const check of priorityCheck) {
        const matchedKeywords = [];
        let totalWeight = 0;

        for (const keyword of check.keywords || []) {
          if (queryLower.includes(keyword.toLowerCase())) {
            matchedKeywords.push(keyword);
            totalWeight += check.weight || 1;
          }
        }

        if (matchedKeywords.length > 0) {
          return {
            recommendedAgent: {
              agentId: check.target,
              confidence: Math.min(totalWeight, 1),
              matchedKeywords,
              rule: rule.name
            },
            alternatives: [],
            method: 'rule_match',
            rule: rule.name
          };
        }
      }
    }

    return null;
  }

  /**
   * 检查规则条件
   */
  checkCondition(condition, queryLower, context) {
    if (!condition) return true;

    // 简单实现：检查条件关键词是否存在
    if (typeof condition === 'string') {
      // 例如 "性能问题" - 检查是否有性能相关词
      const performanceKeywords = ['性能', '卡顿', '慢', '性能分析'];
      const testKeywords = ['测试', '用例', '自动化'];
      const techKeywords = ['ARM', 'CPU', '芯片', 'SoC'];

      if (condition === '性能问题' || condition === '性能') {
        return performanceKeywords.some(k => queryLower.includes(k));
      }
      if (condition === '测试问题' || condition === '测试') {
        return testKeywords.some(k => queryLower.includes(k));
      }
      if (condition === '技术问题' || condition === '技术') {
        return techKeywords.some(k => queryLower.includes(k));
      }
    }

    return true;
  }

  /**
   * 搜索 Agent
   */
  async searchAgents(userMessage, context) {
    const matches = await this.registry.findAgents(userMessage, context);

    // 过滤低置信度结果
    const filtered = matches.filter(
      m => m.confidence >= this.defaultBehavior.min_alternative_confidence
    );

    return {
      matches: filtered.slice(0, this.defaultBehavior.max_alternatives + 1),
      total: filtered.length
    };
  }

  /**
   * 处理无匹配情况
   */
  handleNoMatch(searchResult) {
    const defaultAgent = this.defaultBehavior.default_agent;
    const whenUnsure = this.defaultBehavior.when_unsure;

    // 过滤掉不健康的 Agent
    const healthyMatches = searchResult.matches.filter(m => {
      const agent = this.registry.agents.get(m.agentId);
      return agent && agent.status === 'active' && agent.endpoint?.healthy !== false;
    });

    if (whenUnsure === 'route_to_default' && defaultAgent) {
      // 检查默认 Agent 是否健康
      const defaultAgentInfo = this.registry.agents.get(defaultAgent);
      if (defaultAgentInfo?.endpoint?.healthy !== false) {
        return {
          recommendedAgent: {
            agentId: defaultAgent,
            confidence: 0.5,
            reason: 'Default fallback'
          },
          alternatives: healthyMatches,
          method: 'default_fallback',
          needsConfirmation: true
        };
      }
    }

    if (whenUnsure === 'ask_user') {
      return {
        recommendedAgent: null,
        alternatives: healthyMatches,
        method: 'no_confident_match',
        needsConfirmation: true,
        message: '无法确定目标 Agent，请手动选择'
      };
    }

    // return_error
    return {
      recommendedAgent: null,
      alternatives: [],
      method: 'no_match',
      error: 'No suitable agent found'
    };
  }

  /**
   * 构建路由规则的 System Prompt 片段 (参考 D-Claw)
   */
  buildRoutingPrompt() {
    const agents = Array.from(this.registry.agents.values());

    let prompt = `## Agent 路由规则

根据用户消息选择合适的 Agent：

| 关键词 | Agent | 说明 |
|--------|-------|------|
`;

    for (const agent of agents) {
      if (agent.status !== 'active') continue;
      const keywords = agent.routing?.keywords?.slice(0, 5).join('/') || '-';
      prompt += `| ${keywords} | ${agent.id} | ${agent.description?.slice(0, 30) || ''} |\n`;
    }

    prompt += `
如果不确定，选择最相关的 Agent 或询问用户确认。

`;
    return prompt;
  }

  /**
   * 获取所有 Agent 的路由信息
   */
  getRoutingInfo() {
    const agents = Array.from(this.registry.agents.values());
    return agents
      .filter(a => a.status === 'active')
      .map(a => ({
        id: a.id,
        name: a.name,
        keywords: a.routing?.keywords || [],
        description: a.description
      }));
  }

  /**
   * 更新配置
   */
  updateConfig(config) {
    this.config = { ...this.config, ...config };
    this.rules = this.config.rules || this.rules;
    this.keywordMappings = this.config.keyword_mappings || this.keywordMappings;
    this.defaultBehavior = this.config.default || this.defaultBehavior;
  }
}

export default Router;
