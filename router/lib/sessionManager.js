/**
 * Session Manager - Router 级会话管理
 *
 * 职责：
 * 1. 管理 Router 级别的会话（独立于各 Team 的 OpenCode 会话）
 * 2. 持久化会话和消息到 data/ 目录
 * 3. 构建跨团队上下文
 * 4. 维护 routerSession → teamSession 的映射
 */

import { randomUUID } from 'crypto';
import { readFile, writeFile, unlink, mkdir } from 'fs/promises';
import { existsSync } from 'fs';
import { join, dirname } from 'path';

const DATA_DIR = process.env.DATA_DIR || join(process.cwd(), 'data');
const SESSIONS_FILE = join(DATA_DIR, 'router_sessions.json');
const MESSAGES_DIR = join(DATA_DIR, 'router_messages');

function genId() {
  return Math.random().toString(36).slice(2);
}

export class SessionManager {
  constructor() {
    // 确保目录存在
    if (!existsSync(MESSAGES_DIR)) {
      mkdir(MESSAGES_DIR, { recursive: true }).catch(() => {});
    }
    // 写锁，防止并发写入导致 JSON 文件损坏
    this._writeLock = Promise.resolve();
  }

  _withLock(fn) {
    this._writeLock = this._writeLock.then(fn).catch(fn);
    return this._writeLock;
  }

  // ─── 会话 CRUD ─────────────────────────────────────────────────────────

  async loadSessions() {
    try {
      const raw = await readFile(SESSIONS_FILE, 'utf-8');
      const data = JSON.parse(raw);
      return data.sessions || [];
    } catch {
      return [];
    }
  }

  async saveSessions(sessions) {
    const data = JSON.stringify({ sessions }, null, 2);
    await this._withLock(() => writeFile(SESSIONS_FILE, data));
  }

  async createSession() {
    const sessions = await this.loadSessions();
    const session = {
      id: randomUUID(),
      title: '新会话',
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      currentAgentId: null,
      teamSessions: {}, // { "team-a": "opencode-session-id", ... }
    };
    sessions.unshift(session);
    await this.saveSessions(sessions);

    // 创建空消息文件
    await this.saveMessages(session.id, []);

    return session;
  }

  async getSessions() {
    const sessions = await this.loadSessions();
    // 加载每个会话的最后一条消息作为预览
    const result = [];
    for (const s of sessions) {
      const messages = await this.loadMessages(s.id);
      const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
      result.push({
        ...s,
        messageCount: messages.length,
        lastMessage: lastMsg ? lastMsg.content?.slice(0, 60) : null,
        lastAgentId: lastMsg?.agentId || s.currentAgentId,
      });
    }
    return result;
  }

  async getSession(id) {
    const sessions = await this.loadSessions();
    const session = sessions.find(s => s.id === id);
    if (!session) return null;

    const messages = await this.loadMessages(id);
    return { ...session, messages };
  }

  async deleteSession(id) {
    const sessions = await this.loadSessions();
    const filtered = sessions.filter(s => s.id !== id);
    await this.saveSessions(filtered);

    // 删除消息文件
    const msgFile = join(MESSAGES_DIR, `${id}.json`);
    try { await unlink(msgFile); } catch {}
  }

  async updateSession(id, updates) {
    const sessions = await this.loadSessions();
    const idx = sessions.findIndex(s => s.id === id);
    if (idx < 0) return null;

    Object.assign(sessions[idx], updates, { updatedAt: new Date().toISOString() });
    await this.saveSessions(sessions);
    return sessions[idx];
  }

  // ─── 消息管理 ─────────────────────────────────────────────────────────

  async loadMessages(sessionId) {
    const msgFile = join(MESSAGES_DIR, `${sessionId}.json`);
    try {
      const raw = await readFile(msgFile, 'utf-8');
      const data = JSON.parse(raw);
      return data.messages || [];
    } catch {
      return [];
    }
  }

  async saveMessages(sessionId, messages) {
    const msgFile = join(MESSAGES_DIR, `${sessionId}.json`);
    const data = JSON.stringify({ messages }, null, 2);
    await this._withLock(() => writeFile(msgFile, data));
  }

  async addMessage(sessionId, message) {
    const messages = await this.loadMessages(sessionId);
    const msg = {
      id: genId(),
      ...message,
      timestamp: new Date().toISOString(),
    };
    messages.push(msg);
    await this.saveMessages(sessionId, messages);

    // 更新会话的 updatedAt
    await this.updateSession(sessionId, {});

    return msg;
  }

  // ─── 上下文构建 ───────────────────────────────────────────────────────

  async buildContext(sessionId) {
    const messages = await this.loadMessages(sessionId);
    if (messages.length <= 1) return ''; // 只有一条消息（当前的），无需上下文

    // 排除最后一条（当前用户消息），构建历史上下文
    const history = messages.slice(0, -1);
    if (history.length === 0) return '';

    const lines = history.map(m => {
      if (m.role === 'user') {
        return `用户: ${m.content}`;
      } else {
        const agentLabel = m.agentName || m.agentId || 'Agent';
        return `${agentLabel}: ${m.content}`;
      }
    });

    return lines.join('\n\n');
  }

  // ─── Team Session 映射 ────────────────────────────────────────────────

  async getTeamSession(routerSessionId, agentId) {
    const sessions = await this.loadSessions();
    const session = sessions.find(s => s.id === routerSessionId);
    if (!session) return null;
    return session.teamSessions?.[agentId] || null;
  }

  async setTeamSession(routerSessionId, agentId, teamSessionId) {
    const sessions = await this.loadSessions();
    const idx = sessions.findIndex(s => s.id === routerSessionId);
    if (idx < 0) return;

    if (!sessions[idx].teamSessions) {
      sessions[idx].teamSessions = {};
    }
    sessions[idx].teamSessions[agentId] = teamSessionId;
    sessions[idx].currentAgentId = agentId;
    sessions[idx].updatedAt = new Date().toISOString();
    await this.saveSessions(sessions);
  }
}

export default SessionManager;
