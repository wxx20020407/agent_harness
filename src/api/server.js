/**
 * Agent Harness - Unified API Server
 * 通过环境变量区分团队，一套代码多实例部署
 *
 * 环境变量:
 *   TEAM_ID        - 团队标识，如 team-a
 *   TEAM_NAME      - 团队名称，如 "Team A Agent"
 *   TEAM_DIR       - 团队目录路径（容器内），如 /teams/team-a
 *   OPENCODE_URL   - opencode runtime 地址，如 http://opencode-team-a:4096
 *   OPENCODE_PASSWORD - opencode server password
 *   PORT           - API 监听端口，默认 3000
 */

import express from 'express';
import cors from 'cors';
import { readdir, readFile, writeFile, mkdir, unlink } from 'fs/promises';
import { existsSync, createReadStream, statSync, openSync, readSync, closeSync } from 'fs';
import path from 'path';
import { exec, spawn } from 'child_process';
import { promisify } from 'util';
import { randomUUID } from 'crypto';
import multer from 'multer';

const execAsync = promisify(exec);

const app = express();
app.use(cors());
app.use(express.json());

// ─── 配置 ────────────────────────────────────────────────────────────────────
const TEAM_ID = process.env.TEAM_ID || 'unknown';
const TEAM_NAME = process.env.TEAM_NAME || 'Agent';
const TEAM_DIR = process.env.TEAM_DIR || '/teams/' + TEAM_ID;
const OPENCODE_URL = (process.env.OPENCODE_URL || 'http://localhost:4096').replace(/\/$/, '');
const OPENCODE_PASSWORD = process.env.OPENCODE_PASSWORD || '';
const PORT = parseInt(process.env.PORT || '3000', 10);

// ─── 数据存储 ──────────────────────────────────────────────────────────────────
const DATA_DIR = '/data/agent_harness/data';
const SESSIONS_FILE = path.join(DATA_DIR, 'sessions.json');
const MESSAGES_DIR = path.join(DATA_DIR, 'messages');
const TASKS_DIR = path.join(DATA_DIR, 'tasks');

// 确保数据目录存在
async function ensureDataDirs() {
  await mkdir(DATA_DIR, { recursive: true });
  await mkdir(MESSAGES_DIR, { recursive: true });
  await mkdir(TASKS_DIR, { recursive: true });
}
ensureDataDirs().catch(console.error);

// 清理空会话（启动时执行）
async function cleanupEmptySessions() {
  try {
    const data = await loadSessions();
    const sessions = data.sessions || [];
    const validSessions = [];
    const removedSessions = [];

    for (const session of sessions) {
      const messagesData = await loadMessages(session.id);
      const messages = messagesData.messages || [];
      const hasUserMsg = messages.some(m => m.role === 'user');

      if (hasUserMsg) {
        validSessions.push(session);
      } else {
        removedSessions.push(session.id);
        // 删除空消息文件
        try {
          await unlink(getMessagesPath(session.id));
        } catch {}
        // 删除空 transcript 文件
        try {
          await unlink(path.join(TRANSCRIPTS_DIR, `${session.id}.jsonl`));
        } catch {}
      }
    }

    if (removedSessions.length > 0) {
      console.log(`[cleanup] Removed ${removedSessions.length} empty sessions: ${removedSessions.join(', ')}`);
      data.sessions = validSessions;
      await saveSessions(data);
    }
  } catch (e) {
    console.error('[cleanup] Failed to cleanup empty sessions:', e.message);
  }
}
// 延迟执行清理，等待其他初始化完成
setTimeout(cleanupEmptySessions, 1000);

// ─── 文件上传配置 ──────────────────────────────────────────────────────────────
// 附件存储到 teams/{teamId}/attachments（opencode 可直接访问）
const ATTACHMENTS_DIR = path.join(TEAM_DIR, 'attachments');

// Multer 配置 - 存储到临时目录
const uploadStorage = multer.diskStorage({
  destination: async (req, file, cb) => {
    const tmpDir = '/tmp/uploads';
    await mkdir(tmpDir, { recursive: true });
    cb(null, tmpDir);
  },
  filename: (req, file, cb) => {
    // 保持原始文件名（包括路径，如果是文件夹上传）
    // webkitRelativePath 在文件夹上传时包含相对路径
    // 但 multer 的 originalname 只包含文件名，我们需要保留原始路径
    // 使用 Buffer 来处理可能包含路径分隔符的文件名
    const safeName = Buffer.from(file.originalname).toString('utf-8');
    cb(null, safeName);
  },
});

const uploadMiddleware = multer({
  storage: uploadStorage,
  limits: { fileSize: 50 * 1024 * 1024 }, // 50MB 限制
});

// 会话数据结构
async function loadSessions() {
  try {
    const data = await readFile(SESSIONS_FILE, 'utf-8');
    return JSON.parse(data);
  } catch {
    return { sessions: [] };
  }
}

async function saveSessions(data) {
  await writeFile(SESSIONS_FILE, JSON.stringify(data, null, 2));
}

// 消息数据结构
function getMessagesPath(sessionId) {
  return path.join(MESSAGES_DIR, `${sessionId}.json`);
}

async function loadMessages(sessionId) {
  try {
    const path = getMessagesPath(sessionId);
    const data = await readFile(path, 'utf-8');
    const parsed = JSON.parse(data);
    console.log(`[loadMessages] Loaded ${parsed.messages?.length || 0} messages from ${path}`);
    return parsed;
  } catch (e) {
    console.error(`[loadMessages] Failed to load messages for ${sessionId}:`, e.message);
    return { messages: [] };
  }
}

async function saveMessages(sessionId, data) {
  await writeFile(getMessagesPath(sessionId), JSON.stringify(data, null, 2));

  // 同步到 transcript (Layer 3)
  syncToTranscript(sessionId, data.messages || []).catch(e =>
    console.error('[transcript] Sync failed:', e.message)
  );
}

// Transcript 目录路径
const TRANSCRIPTS_DIR = path.join(TEAM_DIR, '.claude', 'sessions');

// 同步消息到 transcript (JSONL 格式)
async function syncToTranscript(sessionId, messages) {
  if (!messages || messages.length === 0) return;

  try {
    await mkdir(TRANSCRIPTS_DIR, { recursive: true });
    const transcriptPath = path.join(TRANSCRIPTS_DIR, `${sessionId}.jsonl`);

    // 追加写入 JSONL 格式
    const lines = messages.map(msg => {
      const entry = {
        uuid: msg.id || randomUUID(),
        role: msg.role || 'unknown',
        content: msg.content || '',
        timestamp: msg.timestamp || new Date().toISOString(),
        session_id: sessionId,
        tool_uses: msg.tool_uses || [],
        tool_results: msg.tool_results || [],
      };
      if (msg.thinking) entry.thinking = msg.thinking;
      if (msg.thinkingContent) entry.thinking_content = msg.thinkingContent;
      if (msg.attachments) entry.attachments = msg.attachments;
      return JSON.stringify(entry);
    }).join('\n') + '\n';

    await writeFile(transcriptPath, lines);
    console.log(`[transcript] Synced ${messages.length} messages to ${sessionId}.jsonl`);
  } catch (e) {
    console.error('[transcript] Sync error:', e.message);
  }
}

// 任务数据结构
function getTaskLogPath(taskId) {
  return path.join(TASKS_DIR, `${taskId}.log`);
}

function getTaskPidPath(taskId) {
  return path.join(TASKS_DIR, `${taskId}.pid`);
}

function getTaskMetaPath(taskId) {
  return path.join(TASKS_DIR, `${taskId}.json`);
}

async function loadTaskMeta(taskId) {
  try {
    const data = await readFile(getTaskMetaPath(taskId), 'utf-8');
    return JSON.parse(data);
  } catch {
    return null;
  }
}

async function saveTaskMeta(taskId, meta) {
  await writeFile(getTaskMetaPath(taskId), JSON.stringify(meta, null, 2));
}

// 活跃任务跟踪
const activeTasks = new Map(); // taskId -> { pid, status, startTime }

// ─── 并发锁 ──────────────────────────────────────────────────────────────────
// 同一 session 同一时间只允许一个 /chat 请求
const sessionLocks = new Map();

// ─── 记忆系统 (参考 Claude Code 设计) ───────────────────────────────────────────
// MEMORY_DIR 已在文件开头定义
const MEMORY_CURSOR_FILE = path.join(DATA_DIR, 'memory_cursors.json');
const MEMORY_STATE_FILE = path.join(DATA_DIR, 'memory_state.json');

// 记忆提取配置
const EXTRACT_MEMORY_THRESHOLD = 10; // 对话超过 10 条时触发
const AUTO_DREAM_SESSION_THRESHOLD = 5; // 积累 5 个 session 时触发 auto dream
const AUTO_DREAM_TIME_THRESHOLD = 24 * 60 * 60 * 1000; // 24 小时

// Auto dream 最大记忆容量限制（防止超过 LLM token 限制）
const AUTO_DREAM_MAX_MEMORIES = 20;  // 最多处理 20 个记忆文件
const AUTO_DREAM_MAX_CONTENT_PER_MEMORY = 500;  // 每个记忆最多 500 字符
const AUTO_DREAM_MAX_PROMPT_CHARS = 15000;  // prompt 最大字符数（约 10k tokens）

// 内存中的 cursor 状态 (sessionId -> lastProcessedMessageIndex)
const memoryCursors = new Map();

// 正在整理的 session (防止重复)
const extractingSessions = new Set();

// Auto dream 队列
let autoDreamQueue = [];
let autoDreamRunning = false;

// 记忆整理定时器 (sessionId -> setTimeout handle)
const memoryConsolidateTimers = new Map();
const MEMORY_CONSOLIDATE_DELAY = 30 * 1000; // 对话结束后 30 秒整理

// 取消记忆整理定时器
function cancelMemoryConsolidate(sessionId) {
  const timer = memoryConsolidateTimers.get(sessionId);
  if (timer) {
    clearTimeout(timer);
    memoryConsolidateTimers.delete(sessionId);
    console.log(`[memory] Cancelled consolidate timer for ${sessionId}`);
  }
}

// 安排延迟的记忆整理
async function scheduleMemoryConsolidate(opencodeSessionId) {
  // 取消之前的定时器
  cancelMemoryConsolidate(opencodeSessionId);

  // 查找对应的本地 session ID
  let localSessionId = null;
  try {
    const sessionsData = await loadSessions();
    const session = (sessionsData.sessions || []).find(s => s.opencodeSessionId === opencodeSessionId);
    if (session) {
      localSessionId = session.id;
    } else {
      console.log(`[memory] No local session found for opencode session ${opencodeSessionId}`);
      return;
    }
  } catch (e) {
    console.error(`[memory] Failed to find local session:`, e.message);
    return;
  }

  // 设置新的定时器
  const timer = setTimeout(async () => {
    memoryConsolidateTimers.delete(opencodeSessionId);
    console.log(`[memory] Running delayed consolidate for ${opencodeSessionId} (local: ${localSessionId})`);
    try {
      const messagesData = await loadMessages(localSessionId);
      const messages = messagesData.messages || [];
      console.log(`[memory] Loaded ${messages.length} messages for session ${localSessionId}`);
      const result = await extractMemoriesFromSession(localSessionId, messages, false);
      console.log(`[memory] Extract result:`, JSON.stringify(result));
    } catch (e) {
      console.error(`[memory] Consolidate failed:`, e.message);
    }
  }, MEMORY_CONSOLIDATE_DELAY);

  memoryConsolidateTimers.set(opencodeSessionId, timer);
  console.log(`[memory] Scheduled consolidate for ${opencodeSessionId} in ${MEMORY_CONSOLIDATE_DELAY}ms`);
}

// 初始化 cursor 状态
async function initMemoryCursors() {
  try {
    if (existsSync(MEMORY_CURSOR_FILE)) {
      const data = JSON.parse(await readFile(MEMORY_CURSOR_FILE, 'utf-8'));
      for (const [sessionId, cursor] of Object.entries(data)) {
        memoryCursors.set(sessionId, cursor);
      }
    }
    console.log(`[memory] Loaded ${memoryCursors.size} cursors from file`);
  } catch (e) {
    console.error('[memory] Failed to load cursors:', e.message);
  }
}

// Rebuild cursor 初始化：为所有现有 session 初始化 cursor 到末尾
// 这样只有新对话才会被处理
async function rebuildCursorsForAllSessions() {
  try {
    const sessionsData = await loadSessions();
    const sessions = sessionsData.sessions || [];
    let newCursors = 0;

    for (const session of sessions) {
      // 如果该 session 还没有 cursor，初始化到末尾
      if (!memoryCursors.has(session.id)) {
        const messagesData = await loadMessages(session.id);
        const messages = messagesData.messages || [];

        if (messages.length > 0) {
          memoryCursors.set(session.id, {
            lastMessageIndex: messages.length,
            extracted: false,  // 标记为未提取，但 cursor 在末尾
            rebuilt: true,     // 标记为 rebuild 初始化
            rebuiltAt: Date.now(),
          });
          newCursors++;
        }
      }
    }

    if (newCursors > 0) {
      await saveMemoryCursors();
      console.log(`[memory] Rebuilt cursors for ${newCursors} sessions (cursor at end)`);
    }
  } catch (e) {
    console.error('[memory] Failed to rebuild cursors:', e.message);
  }
}

// 启动时初始化 cursor，然后 rebuild
initMemoryCursors().then(() => {
  // 延迟执行 rebuild，等待其他初始化完成
  setTimeout(rebuildCursorsForAllSessions, 2000);
});

// 保存 cursor 状态
async function saveMemoryCursors() {
  try {
    const data = Object.fromEntries(memoryCursors);
    await writeFile(MEMORY_CURSOR_FILE, JSON.stringify(data, null, 2));
  } catch (e) {
    console.error('[memory] Failed to save cursors:', e.message);
  }
}

// 获取记忆状态
async function getMemoryState() {
  try {
    if (existsSync(MEMORY_STATE_FILE)) {
      return JSON.parse(await readFile(MEMORY_STATE_FILE, 'utf-8'));
    }
  } catch {}
  return {
    lastAutoDreamAt: 0,
    sessionsSinceLastDream: [],
  };
}

// 保存记忆状态
async function saveMemoryState(state) {
  try {
    await writeFile(MEMORY_STATE_FILE, JSON.stringify(state, null, 2));
  } catch (e) {
    console.error('[memory] Failed to save state:', e.message);
  }
}

// 检查消息是否只是招呼语
function isGreetingOnly(messages) {
  const greetings = ['你好', '您好', 'hi', 'hello', '嗨', '早上好', '下午好', '晚上好'];
  const userMessages = messages.filter(m => m.role === 'user');

  if (userMessages.length === 0) return true;

  // 只有一条用户消息且是招呼语
  if (userMessages.length === 1) {
    const content = userMessages[0].content?.toLowerCase().trim() || '';
    return greetings.some(g => content === g || content === g + '！');
  }

  return false;
}

// 获取 session 消息数量（用户消息）
function getUserMessageCount(messages) {
  return messages.filter(m => m.role === 'user').length;
}

// Extract Memories: 从 session 提取记忆
async function extractMemoriesFromSession(sessionId, messages, force = false) {
  console.log(`[memory] extractMemoriesFromSession called with sessionId=${sessionId}, messages.length=${messages?.length}, force=${force}`);

  // 防止重复整理
  if (extractingSessions.has(sessionId)) {
    console.log(`[memory] Session ${sessionId} already being extracted`);
    return { skipped: true, reason: 'already_extracting' };
  }

  // 获取 cursor
  const cursor = memoryCursors.get(sessionId) || { lastMessageIndex: 0, extracted: false };
  console.log(`[memory] Cursor for ${sessionId}:`, JSON.stringify(cursor));

  // 计算新消息数量
  const newMessageCount = messages.length - cursor.lastMessageIndex;

  // 如果已经整理过且没有新消息，跳过（force 时强制重新处理所有消息）
  if (!force && cursor.extracted && newMessageCount <= 0) {
    return { skipped: true, reason: 'already_extracted' };
  }

  // 获取需要处理的消息（force 时处理全部，否则只处理新消息）
  const messagesToProcess = force ? messages : messages.slice(cursor.lastMessageIndex);
  console.log(`[memory] messagesToProcess.length=${messagesToProcess.length}, newMessageCount=${newMessageCount}`);

  // 检查是否只是招呼
  if (!force && isGreetingOnly(messagesToProcess)) {
    return { skipped: true, reason: 'greeting_only' };
  }

  extractingSessions.add(sessionId);

  try {
    console.log(`[memory] Extracting from session ${sessionId}, ${messagesToProcess.length} messages`);

    // 调用 LLM 提取记忆
    const result = await callExtractMemoryLLM(sessionId, messagesToProcess);

    // 更新 cursor
    memoryCursors.set(sessionId, {
      lastMessageIndex: messages.length,
      extracted: true,
      extractedAt: Date.now(),
    });
    await saveMemoryCursors();

    return result;
  } finally {
    extractingSessions.delete(sessionId);
  }
}

// 调用 LLM 提取记忆
async function callExtractMemoryLLM(sessionId, messages) {
  // 构建对话内容
  const conversationText = messages
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .slice(-20) // 最多取最近 20 条
    .map(m => `${m.role === 'user' ? '用户' : '助手'}: ${m.content?.slice(0, 500) || ''}`)
    .join('\n\n');

  // 获取 LLM 配置
  let baseUrl = '';
  let apiKey = '';

  if (existsSync(ENV_FILE)) {
    const envContent = await readFile(ENV_FILE, 'utf-8');
    const baseUrlMatch = envContent.match(/^LLM_BASE_URL=(.*)$/m);
    const apiKeyMatch = envContent.match(/^LLM_API_KEY=(.*)$/m);
    if (baseUrlMatch) baseUrl = baseUrlMatch[1].trim();
    if (apiKeyMatch) apiKey = apiKeyMatch[1].trim();
  }

  // 使用 helper model（保持完整格式，如 zhipuai/glm-4-flash）
  const helperModel = process.env.LLM_HELPER_MODEL || 'zhipuai/glm-4-flash';
  // 直接使用完整模型名，不做拆分
  const model = helperModel;

  console.log(`[memory] LLM config: baseUrl=${baseUrl}, model=${model}`);

  if (!baseUrl || !apiKey) {
    return { skipped: true, reason: 'no_llm_config' };
  }

  // 读取现有记忆文件列表
  const existingMemories = await listMemoryFiles();

  const prompt = `你是一个记忆管理助手，负责从对话中提取真正值得长期记住的信息。

## 对话内容
${conversationText}

## 现有记忆文件
${existingMemories.map(m => `- ${m.name} (${m.type}): ${m.description}`).join('\n') || '(无)'}

## 核心原则

**宁缺毋滥！** 只有真正重要、跨会话有用的信息才值得保存。

## 必须保存的内容（只选最重要的）

1. **用户偏好**: 用户明确、反复强调的工作方式偏好
   - 例如："用中文回答"、"不要加总结段落"、"代码用 TypeScript"

2. **项目关键决策**: 影响项目方向的重要决定，不是临时任务
   - 例如："决定使用 PostgreSQL 替代 MySQL"、"API 版本锁定为 v2"

3. **跨会话上下文**: 需要在未来会话中记住的项目状态
   - 例如："Bug #123 已修复，等待测试确认"、"下周截止日期是 4月15日"

## 绝对不要保存的内容

- ❌ 临时的文件创建/编辑动作（"用户要求创建 xx 文件"）
- ❌ 已完成的任务详情（任务做完了就不需要记住）
- ❌ 代码片段或技术细节（可从代码库查询）
- ❌ 单次对话中的临时信息
- ❌ 模糊或没有价值的描述（"完成 xx 分析"、"处理了 xx 问题"）
- ❌ 与现有记忆重复或高度相似的内容

## 质量标准

每个记忆必须满足：
1. **具体**: 有明确的实质内容，不是泛泛而谈
2. **持久**: 在未来会话中确实有用
3. **独特**: 不与现有记忆重复（检查上面的现有记忆列表！）
4. **重要**: 错过这个信息会导致未来工作出错或低效

## 输出格式 (JSON)

\`\`\`json
{
  "memories": [
    {
      "type": "user|feedback|project|reference",
      "name": "简短英文标识",
      "description": "一句话精准描述（不超过50字）",
      "content": "详细内容，包含足够的上下文使其独立可理解"
    }
  ]
}
\`\`\`

**如果找不到符合标准的记忆，返回空数组: {"memories": []}**

记住：10个垃圾记忆不如1个高质量记忆。不确定是否保存？那就不要保存。`;

  try {
    const llmRes = await fetch(`${baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: model,
        messages: [{ role: 'user', content: prompt }],
        max_tokens: 1000,
        temperature: 0.3,
      }),
      signal: AbortSignal.timeout(60000),
    });

    if (!llmRes.ok) {
      throw new Error(`LLM API error: ${llmRes.status}`);
    }

    const llmData = await llmRes.json();
    let responseText = llmData.choices?.[0]?.message?.content?.trim() || '';

    // 提取 JSON
    const jsonMatch = responseText.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return { skipped: true, reason: 'no_json', response: responseText };
    }

    const parsed = JSON.parse(jsonMatch[0]);
    const memories = parsed.memories || [];

    if (memories.length === 0) {
      return { skipped: true, reason: 'no_memories' };
    }

    // 保存记忆文件
    const savedMemories = [];
    await mkdir(MEMORY_DIR, { recursive: true });

    for (const mem of memories) {
      const filename = `${mem.name}.md`;
      const filepath = path.join(MEMORY_DIR, filename);

      const frontmatter = `---
name: ${mem.name}
description: ${mem.description}
type: ${mem.type}
session: ${sessionId}
created: ${new Date().toISOString()}
---

${mem.content}`;

      await writeFile(filepath, frontmatter);
      savedMemories.push({ filename, ...mem });
    }

    // 更新 MEMORY.md 索引
    await updateMemoryIndex(savedMemories);

    return {
      success: true,
      sessionId,
      memoriesSaved: savedMemories.length,
      memories: savedMemories,
    };
  } catch (e) {
    console.error('[memory] Extract LLM error:', e.message);
    return { error: e.message };
  }
}

// 列出记忆文件
async function listMemoryFiles() {
  try {
    if (!existsSync(MEMORY_DIR)) return [];
    const files = await readdir(MEMORY_DIR);
    const memories = [];

    for (const file of files) {
      if (!file.endsWith('.md') || file === 'MEMORY.md') continue;

      try {
        const content = await readFile(path.join(MEMORY_DIR, file), 'utf-8');
        const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
        if (frontmatterMatch) {
          const frontmatter = frontmatterMatch[1];
          const nameMatch = frontmatter.match(/^name:\s*(.+)$/m);
          const descMatch = frontmatter.match(/^description:\s*(.+)$/m);
          const typeMatch = frontmatter.match(/^type:\s*(.+)$/m);

          memories.push({
            filename: file,
            name: nameMatch?.[1] || file,
            description: descMatch?.[1] || '',
            type: typeMatch?.[1] || 'unknown',
          });
        }
      } catch {}
    }

    return memories;
  } catch {
    return [];
  }
}

// 更新 MEMORY.md 索引
async function updateMemoryIndex(newMemories) {
  const indexPath = path.join(MEMORY_DIR, 'MEMORY.md');
  await mkdir(MEMORY_DIR, { recursive: true });

  let existingContent = '';
  if (existsSync(indexPath)) {
    existingContent = await readFile(indexPath, 'utf-8');
  }

  // 添加新记忆到索引
  const newEntries = newMemories.map(m =>
    `- [${m.name}](${m.filename}) — ${m.description}`
  ).join('\n');

  // 找到插入位置
  const lines = existingContent.split('\n');
  let insertIdx = lines.length;

  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i].startsWith('- [')) {
      insertIdx = i + 1;
      break;
    }
  }

  // 检查是否已存在
  for (const mem of newMemories) {
    const existingLine = lines.find(l => l.includes(`[${mem.name}]`));
    if (!existingLine) {
      lines.splice(insertIdx, 0, `- [${mem.name}](${mem.filename}) — ${mem.description}`);
      insertIdx++;
    }
  }

  await writeFile(indexPath, lines.join('\n'));
}

// 检查是否需要触发 extract memories
async function checkAndExtractMemories(sessionId, messages, isSwitchingSession = false) {
  const cursor = memoryCursors.get(sessionId) || { lastMessageIndex: 0, extracted: false };
  const newMessageCount = messages.length - cursor.lastMessageIndex;
  const userMsgCount = getUserMessageCount(messages.slice(cursor.lastMessageIndex));

  // 条件 1: 用户切换 session
  if (isSwitchingSession && userMsgCount > 0 && !isGreetingOnly(messages.slice(cursor.lastMessageIndex))) {
    console.log(`[memory] Trigger: session switch, ${userMsgCount} user messages`);
    return extractMemoriesFromSession(sessionId, messages);
  }

  // 条件 2: 对话超过阈值
  if (userMsgCount >= EXTRACT_MEMORY_THRESHOLD) {
    console.log(`[memory] Trigger: ${userMsgCount} user messages >= ${EXTRACT_MEMORY_THRESHOLD}`);
    return extractMemoriesFromSession(sessionId, messages);
  }

  return { skipped: true, reason: 'conditions_not_met' };
}

// Auto Dream: 整理所有 session 的记忆
async function checkAndScheduleAutoDream(sessionId) {
  const state = await getMemoryState();

  // 添加到 session 列表（去重）
  if (!state.sessionsSinceLastDream.includes(sessionId)) {
    state.sessionsSinceLastDream.push(sessionId);
    await saveMemoryState(state);
  }

  // 检查是否满足触发条件（只用 session 数量，不用时间）
  const sessionCount = state.sessionsSinceLastDream.length;

  if (sessionCount >= AUTO_DREAM_SESSION_THRESHOLD) {
    if (!autoDreamRunning) {
      console.log(`[memory] Auto dream scheduled: ${sessionCount} sessions`);
      autoDreamQueue.push({
        sessions: [...state.sessionsSinceLastDream],
        triggeredAt: Date.now(),
        reason: 'session_threshold',
      });

      // 异步执行
      processAutoDreamQueue();
    }
  }
}

// 处理 auto dream 队列
async function processAutoDreamQueue() {
  if (autoDreamRunning || autoDreamQueue.length === 0) return;

  autoDreamRunning = true;
  const task = autoDreamQueue.shift();

  try {
    console.log(`[memory] Running auto dream for ${task.sessions.length} sessions`);

    const result = await runAutoDream(task.sessions);

    // 更新状态
    const state = await getMemoryState();
    state.lastAutoDreamAt = Date.now();
    state.sessionsSinceLastDream = [];
    state.lastDreamResult = result;
    await saveMemoryState(state);

    console.log(`[memory] Auto dream completed:`, result);
  } catch (e) {
    console.error(`[memory] Auto dream failed:`, e.message);
  } finally {
    autoDreamRunning = false;

    // 继续处理队列
    if (autoDreamQueue.length > 0) {
      processAutoDreamQueue();
    }
  }
}

// 执行 auto dream
// Dream 只做整理（merge/delete/update），不做提取（不 create）
// 只喂记忆列表，不喂记忆内容
async function runAutoDream(sessionIds) {
  // 读取现有记忆列表
  const existingMemories = await listMemoryFiles();

  // 如果没有记忆文件，跳过
  if (existingMemories.length === 0) {
    return { skipped: true, reason: 'no_memories' };
  }

  // 限制记忆数量，按修改时间排序（最新的优先）
  const sortedMemories = existingMemories
    .sort((a, b) => (b.mtimeMs || 0) - (a.mtimeMs || 0))
    .slice(0, AUTO_DREAM_MAX_MEMORIES);

  if (sortedMemories.length < existingMemories.length) {
    console.log(`[memory] Auto dream: limiting from ${existingMemories.length} to ${sortedMemories.length} memories`);
  }

  // 获取 LLM 配置
  let baseUrl = '';
  let apiKey = '';

  if (existsSync(ENV_FILE)) {
    const envContent = await readFile(ENV_FILE, 'utf-8');
    const baseUrlMatch = envContent.match(/^LLM_BASE_URL=(.*)$/m);
    const apiKeyMatch = envContent.match(/^LLM_API_KEY=(.*)$/m);
    if (baseUrlMatch) baseUrl = baseUrlMatch[1].trim();
    if (apiKeyMatch) apiKey = apiKeyMatch[1].trim();
  }

  const helperModel = process.env.LLM_HELPER_MODEL || 'zhipuai/glm-4-flash';
  const model = helperModel;  // 保持完整格式

  if (!baseUrl || !apiKey) {
    return { skipped: true, reason: 'no_llm_config' };
  }

  // 构建记忆列表（只喂列表，不喂内容）
  // 格式：- [type] filename: description
  const memoryList = sortedMemories.map(m => `- [${m.type}] ${m.filename}: ${m.description}`).join('\n');

  const prompt = `你是一个记忆整理助手。

## 现有记忆文件列表

${memoryList}

## 任务

**核心目标：让记忆库更精简、更有价值。**

请根据文件名和描述，判断哪些记忆需要整理：

### 1. 合并重复记忆（最高优先级）★★★
识别描述相似或明显重复的记忆，合并为一个。

### 2. 删除低价值记忆 ★★★
删除以下类型：
- 描述空洞（如"用户要求创建 xx 文件"）
- 已完成的临时任务
- 过时信息
- 与其他记忆高度重复

## 输出格式 (JSON)

\`\`\`json
{
  "actions": [
    {"action": "merge", "source_files": ["a.md", "b.md"], "target_file": "merged_name.md", "reason": "合并原因"},
    {"action": "delete", "filename": "xxx.md", "reason": "删除原因"}
  ]
}
\`\`\`

**重要原则：**
- Dream 只做整理，不做提取。禁止 create 操作！
- 宁缺毋滥！如果记忆质量很好，返回 {"actions": []}
- 优先 merge 和 delete，减少文件数量
- 只输出 JSON，不要其他内容`;

  console.log(`[memory] Auto dream: processing ${sortedMemories.length} memories`);

  try {
    const llmRes = await fetch(`${baseUrl}/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: model,
        messages: [{ role: 'user', content: prompt }],
        max_tokens: 2000,
        temperature: 0.3,
      }),
      signal: AbortSignal.timeout(120000),
    });

    if (!llmRes.ok) {
      throw new Error(`LLM API error: ${llmRes.status}`);
    }

    const llmData = await llmRes.json();
    let responseText = llmData.choices?.[0]?.message?.content?.trim() || '';

    const jsonMatch = responseText.match(/\{[\s\S]*\}/);
    if (!jsonMatch) {
      return { skipped: true, reason: 'no_json' };
    }

    const parsed = JSON.parse(jsonMatch[0]);
    const actions = parsed.actions || [];

    // 执行操作（Dream 只做 merge 和 delete，不做 create/update）
    const results = { deleted: 0, merged: 0 };
    await mkdir(MEMORY_DIR, { recursive: true });

    for (const action of actions) {
      // 跳过 create 和 update（Dream 不做这些）
      if (action.action === 'create' || action.action === 'update') {
        console.log(`[memory] Auto dream: skipping ${action.action} action (not allowed in dream)`);
        continue;
      }

      if (action.action === 'merge') {
        // 合并操作：读取源文件内容，合并后创建新文件，删除源文件
        if (!action.source_files || action.source_files.length < 2) {
          console.log(`[memory] Auto dream: merge requires at least 2 source files, skipping`);
          continue;
        }

        // 读取所有源文件内容
        const mergedContents = [];
        let mergedType = 'project';
        let mergedDescription = '';

        for (const srcFile of action.source_files) {
          const srcPath = path.join(MEMORY_DIR, srcFile);
          if (existsSync(srcPath)) {
            const content = await readFile(srcPath, 'utf-8');
            // 提取 frontmatter 信息
            const fmMatch = content.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/);
            if (fmMatch) {
              const fm = fmMatch[1];
              const typeMatch = fm.match(/^type:\s*(.+)$/m);
              const descMatch = fm.match(/^description:\s*(.+)$/m);
              if (typeMatch) mergedType = typeMatch[1].trim();
              if (descMatch && !mergedDescription) mergedDescription = descMatch[1].trim();
              mergedContents.push(`--- 来自 ${srcFile} ---\n${fmMatch[2].trim()}`);
            }
          }
        }

        if (mergedContents.length > 0) {
          const targetFile = action.target_file || `merged_${Date.now()}.md`;
          const targetPath = path.join(MEMORY_DIR, targetFile);
          const mergedName = targetFile.replace('.md', '');
          const frontmatter = `---
name: ${mergedName}
description: ${action.reason || mergedDescription || '合并记忆'}
type: ${mergedType}
created: ${new Date().toISOString()}
merged_from: ${action.source_files.join(', ')}
---

${mergedContents.join('\n\n')}`;
          await writeFile(targetPath, frontmatter);

          // 删除源文件
          for (const srcFile of action.source_files) {
            const srcPath = path.join(MEMORY_DIR, srcFile);
            if (existsSync(srcPath)) {
              await unlink(srcPath);
              results.deleted++;
            }
          }
          results.merged++;
          console.log(`[memory] Auto dream: merged ${action.source_files.length} files into ${targetFile}`);
        }
      } else if (action.action === 'delete') {
        const filepath = path.join(MEMORY_DIR, action.filename);
        if (existsSync(filepath)) {
          await unlink(filepath);
          results.deleted++;
          console.log(`[memory] Auto dream: deleted ${action.filename} (${action.reason || 'no reason'})`);
        }
      }
    }

    // 更新 MEMORY.md
    const allMemories = await listMemoryFiles();
    const indexContent = allMemories.map(m => `- [${m.name}](${m.filename}) — ${m.description}`).join('\n');
    await writeFile(path.join(MEMORY_DIR, 'MEMORY.md'), `# Memory Index\n\n${indexContent}`);

    return { success: true, ...results };
  } catch (e) {
    console.error('[memory] Auto dream LLM error:', e.message);
    return { error: e.message };
  }
}

// ─── opencode HTTP 工具 ──────────────────────────────────────────────────────
// 直接调用 opencode REST API（比 SDK 更稳定，依赖更少，适合离线部署）

function opencodeHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (OPENCODE_PASSWORD) {
    const encoded = Buffer.from(`opencode:${OPENCODE_PASSWORD}`).toString('base64');
    h['Authorization'] = `Basic ${encoded}`;
  }
  return h;
}

async function opencodeRequest(method, path, body) {
  const url = `${OPENCODE_URL}${path}`;
  const opts = {
    method,
    headers: opencodeHeaders(),
  };
  if (body) opts.body = JSON.stringify(body);

  const res = await fetch(url, opts);
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw Object.assign(new Error(`opencode ${method} ${path} -> ${res.status}`), {
      status: res.status,
      body: text,
    });
  }
  return res.json();
}

// ─── GET /health ──────────────────────────────────────────────────────────────
app.get('/health', async (req, res) => {
  try {
    // 检查 opencode 是否可达（401 也算正常，说明服务在运行）
    const url = `${OPENCODE_URL}/`;
    const r = await fetch(url, { signal: AbortSignal.timeout(5000) });
    const healthy = r.status === 200 || r.status === 401;
    res.status(healthy ? 200 : 503).json({
      api: 'healthy',
      runtime: healthy ? 'healthy' : 'unreachable',
      teamId: TEAM_ID,
    });
  } catch (e) {
    res.status(503).json({
      api: 'healthy',
      runtime: 'unreachable',
      error: e.message,
      teamId: TEAM_ID,
    });
  }
});

// ─── 会话管理 API ─────────────────────────────────────────────────────────────

// 当前活跃的 session（用于检测切换）
let currentActiveSessionId = null;

// GET /sessions - 获取所有会话列表
app.get('/sessions', async (req, res) => {
  try {
    const data = await loadSessions();
    // 按更新时间倒序排列
    const sessions = (data.sessions || []).sort((a, b) =>
      new Date(b.updatedAt) - new Date(a.updatedAt)
    );

    res.json({ sessions });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /sessions/:id - 获取会话详情 + 消息历史
app.get('/sessions/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const data = await loadSessions();
    const session = (data.sessions || []).find(s => s.id === id);

    if (!session) {
      return res.status(404).json({ error: '会话不存在' });
    }

    // 检查 opencode session 是否有效，如果无效则创建新的
    if (session.opencodeSessionId) {
      try {
        // 尝试获取 opencode session 信息
        await opencodeRequest('GET', `/session/${session.opencodeSessionId}`);
      } catch (e) {
        if (e.status === 404 || e.message?.includes('not found') || e.message?.includes('NotFoundError')) {
          console.log(`[session] opencode session ${session.opencodeSessionId} not found, creating new one...`);
          // opencode session 不存在，创建新的
          try {
            const newData = await opencodeRequest('POST', '/session', {});
            const newOpencodeSessionId = newData?.id || newData?.data?.id;
            if (newOpencodeSessionId) {
              session.opencodeSessionId = newOpencodeSessionId;
              // 更新 sessions.json
              const idx = (data.sessions || []).findIndex(s => s.id === id);
              if (idx >= 0) {
                data.sessions[idx].opencodeSessionId = newOpencodeSessionId;
                await saveSessions(data);
              }
              console.log(`[session] Created new opencode session ${newOpencodeSessionId} for local session ${id}`);

              // 同步历史消息到新的 opencode session
              try {
                const historyData = await loadMessages(id);
                const historyMessages = historyData.messages || [];
                if (historyMessages.length > 0) {
                  // 构建历史上下文摘要
                  const historyContext = historyMessages.map(m => {
                    const role = m.role === 'user' ? '用户' : '助手';
                    const content = m.content || '';
                    const truncated = content.length > 2000 ? content.slice(0, 2000) + '...[截断]' : content;
                    return `${role}: ${truncated}`;
                  }).join('\n\n---\n\n');

                  const contextMessage = `[历史对话恢复]\n以下是我们之前的对话历史，请在回复时参考这些上下文：\n\n${historyContext}\n\n---\n\n请记住以上对话内容，我会继续与你交流。`;

                  // 异步发送历史上下文
                  const contextUrl = `${OPENCODE_URL}/session/${newOpencodeSessionId}/message`;
                  fetch(contextUrl, {
                    method: 'POST',
                    headers: opencodeHeaders(),
                    body: JSON.stringify({
                      parts: [{ type: 'text', text: contextMessage }],
                    }),
                  }).then(r => {
                    if (r.ok) {
                      console.log(`[session] Synced ${historyMessages.length} messages to new opencode session`);
                    } else {
                      r.text().then(t => console.error('[session] Failed to sync history:', r.status, t)).catch(() => {});
                    }
                  }).catch(err => console.error('[session] History sync error:', err.message));
                }
              } catch (historyErr) {
                console.error('[session] Failed to load/sync history:', historyErr.message);
              }
            }
          } catch (createErr) {
            console.error('[session] Failed to create new opencode session:', createErr.message);
          }
        }
      }
    }

    const messagesData = await loadMessages(id);
    const messages = messagesData.messages || [];

    // 检测 session 切换
    const isSwitchingSession = currentActiveSessionId && currentActiveSessionId !== id;
    const previousSessionId = currentActiveSessionId;

    // 更新当前活跃 session
    currentActiveSessionId = id;

    // 如果是切换 session，异步整理旧 session 的记忆
    if (isSwitchingSession && previousSessionId) {
      const prevMessagesData = await loadMessages(previousSessionId);
      const prevMessages = prevMessagesData.messages || [];

      // 异步整理，不阻塞响应
      checkAndExtractMemories(previousSessionId, prevMessages, true).catch(e =>
        console.error(`[memory] Extract on switch failed:`, e.message)
      );
    }

    // 检查是否需要整理当前 session（对话超过阈值）
    checkAndExtractMemories(id, messages, false).catch(e =>
      console.error(`[memory] Extract on threshold failed:`, e.message)
    );

    // 检查是否需要触发 auto dream
    checkAndScheduleAutoDream(id).catch(e =>
      console.error(`[memory] Auto dream check failed:`, e.message)
    );

    // 如果有活跃任务，附加任务状态
    let taskStatus = null;
    if (session.activeTaskId) {
      const taskMeta = await loadTaskMeta(session.activeTaskId);
      if (taskMeta) {
        taskStatus = {
          taskId: session.activeTaskId,
          status: taskMeta.status,
          exitCode: taskMeta.exitCode,
        };
      }
    }

    res.json({
      session: { ...session, taskStatus },
      messages: messagesData.messages || [],
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /sessions - 创建新会话
app.post('/sessions', async (req, res) => {
  try {
    const { title } = req.body || {};
    const sessionId = randomUUID();
    const now = new Date().toISOString();

    const session = {
      id: sessionId,
      title: title || '新会话',
      createdAt: now,
      updatedAt: now,
      hasUnread: false,
      activeTaskId: null,
    };

    // 创建 opencode session
    try {
      const data = await opencodeRequest('POST', '/session', {});
      session.opencodeSessionId = data?.id || data?.data?.id;
    } catch (e) {
      console.error('[session] Failed to create opencode session:', e.message);
    }

    // 保存到 sessions.json（chat handler 需要通过本地 ID 查找 opencodeSessionId）
    try {
      const sessionsData = await loadSessions();
      sessionsData.sessions = sessionsData.sessions || [];
      sessionsData.sessions.unshift(session);
      await saveSessions(sessionsData);
    } catch (e) {
      console.error('[session] Failed to save session:', e.message);
    }

    res.json({ sessionId, session });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// PATCH /sessions/:id - 更新会话
app.patch('/sessions/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const { title, hasUnread, activeTaskId } = req.body || {};

    const data = await loadSessions();
    const idx = (data.sessions || []).findIndex(s => s.id === id);

    if (idx === -1) {
      return res.status(404).json({ error: '会话不存在' });
    }

    // 更新标题（防止默认标题覆盖有意义标题）
    if (title !== undefined) {
      const currentTitle = data.sessions[idx].title;
      // 如果新标题是默认格式，且当前标题有意义，则忽略更新
      if (!isDefaultTitle(title) || !currentTitle || isDefaultTitle(currentTitle)) {
        data.sessions[idx].title = title;
      } else {
        console.log(`[session] Ignoring default title "${title}" for session ${id} (current: "${currentTitle}")`);
      }
    }

    if (hasUnread !== undefined) data.sessions[idx].hasUnread = hasUnread;
    if (activeTaskId !== undefined) data.sessions[idx].activeTaskId = activeTaskId;
    data.sessions[idx].updatedAt = new Date().toISOString();

    await saveSessions(data);
    res.json({ session: data.sessions[idx] });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 检查标题是否是默认格式（如 "New session - 2026-04-15T09:23:33.697Z"）
function isDefaultTitle(title) {
  if (!title) return true;
  // 检查是否是默认格式的标题
  // opencode 的默认标题格式：New session + 时间戳
  const defaultPatterns = [
    /^New session\s*-\s*\d{4}-\d{2}-\d{2}T/i,  // "New session - 2026-04-15T..."
    /^New Session\s*-\s*\d{4}-\d{2}-\d{2}T/i,  // 大小写变体
    /^新会话\s*-\s*\d{4}-\d{2}-\d{2}T/i,       // 中文版本
    /^New session$/i,                           // 纯 "New session"
    /^新会话$/,                                  // 纯中文
  ];
  return defaultPatterns.some(p => p.test(title.trim()));
}

// PATCH /sessions/by-opencode/:opencodeSessionId - 通过 opencode session ID 更新会话标题
app.patch('/sessions/by-opencode/:opencodeSessionId', async (req, res) => {
  try {
    const { opencodeSessionId } = req.params;
    const { title } = req.body || {};

    if (!title) {
      return res.status(400).json({ error: '缺少 title' });
    }

    const data = await loadSessions();
    const idx = (data.sessions || []).findIndex(s => s.opencodeSessionId === opencodeSessionId);

    if (idx === -1) {
      return res.status(404).json({ error: '会话不存在' });
    }

    const currentTitle = data.sessions[idx].title;

    // 防止默认标题覆盖有意义的标题
    // 如果新标题是默认格式，且当前标题有意义，则忽略更新
    if (isDefaultTitle(title) && currentTitle && !isDefaultTitle(currentTitle)) {
      console.log(`[session] Ignoring default title "${title}" for opencode session ${opencodeSessionId} (current: "${currentTitle}")`);
      return res.json({ session: data.sessions[idx], skipped: true, reason: 'default_title_ignored' });
    }

    data.sessions[idx].title = title;
    data.sessions[idx].updatedAt = new Date().toISOString();

    await saveSessions(data);
    console.log(`[session] Updated title for opencode session ${opencodeSessionId}: "${title}"`);
    res.json({ session: data.sessions[idx] });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// DELETE /sessions/:id - 删除会话
app.delete('/sessions/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const data = await loadSessions();
    const idx = (data.sessions || []).findIndex(s => s.id === id);

    if (idx === -1) {
      return res.status(404).json({ error: '会话不存在' });
    }

    // 取消活跃任务
    const session = data.sessions[idx];
    if (session.activeTaskId && activeTasks.has(session.activeTaskId)) {
      const task = activeTasks.get(session.activeTaskId);
      if (task.pid) {
        try {
          process.kill(task.pid, 'SIGTERM');
        } catch (e) {
          // 进程可能已结束
        }
      }
      activeTasks.delete(session.activeTaskId);
    }

    // 删除会话
    data.sessions.splice(idx, 1);
    await saveSessions(data);

    // 删除消息文件
    const msgPath = getMessagesPath(id);
    try {
      const { unlink, rm } = await import('fs/promises');
      await unlink(msgPath);
    } catch {}

    // 删除附件目录
    const attachDir = path.join(ATTACHMENTS_DIR, id);
    try {
      const { rm } = await import('fs/promises');
      await rm(attachDir, { recursive: true, force: true });
    } catch {}

    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── 任务管理 API ─────────────────────────────────────────────────────────────

// POST /tasks - 创建后台任务
app.post('/tasks', async (req, res) => {
  try {
    const { sessionId, command, cwd } = req.body || {};

    if (!command) {
      return res.status(400).json({ error: '缺少 command' });
    }

    const taskId = randomUUID();
    const logPath = getTaskLogPath(taskId);
    const pidPath = getTaskPidPath(taskId);
    const now = new Date().toISOString();

    // 保存任务元数据
    await saveTaskMeta(taskId, {
      id: taskId,
      sessionId,
      command,
      status: 'running',
      createdAt: now,
      startedAt: now,
    });

    // 使用 nohup 执行命令
    const workDir = cwd || TEAM_DIR;
    const nohupCmd = `nohup ${command} > ${logPath} 2>&1 & echo $! > ${pidPath}`;

    exec(nohupCmd, { cwd: workDir }, (error, stdout, stderr) => {
      if (error) {
        console.error('[task] Failed to start:', error.message);
      }
    });

    // 稍后读取 PID
    setTimeout(async () => {
      try {
        const pidData = await readFile(pidPath, 'utf-8');
        const pid = parseInt(pidData.trim(), 10);
        if (pid) {
          activeTasks.set(taskId, { pid, status: 'running', startTime: Date.now() });
          console.log(`[task] Started ${taskId}, PID: ${pid}`);
        }
      } catch (e) {
        console.error('[task] Failed to read PID:', e.message);
      }
    }, 500);

    res.json({ taskId, status: 'running' });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /tasks/:taskId/stream - SSE 实时输出流
app.get('/tasks/:taskId/stream', async (req, res) => {
  const { taskId } = req.params;

  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
    'X-Accel-Buffering': 'no',
  });

  const sendEvent = (obj) => {
    if (!res.writableEnded) {
      res.write(`data: ${JSON.stringify(obj)}\n\n`);
    }
  };

  const logPath = getTaskLogPath(taskId);
  const meta = await loadTaskMeta(taskId);

  if (!meta) {
    sendEvent({ type: 'error', message: '任务不存在' });
    return res.end();
  }

  // 先发送历史内容（最后 100 行）
  try {
    const { stdout } = await execAsync(`tail -100 ${logPath} 2>/dev/null || echo ''`);
    if (stdout.trim()) {
      sendEvent({ type: 'history', lines: stdout });
    }
  } catch {}

  // 发送当前状态
  sendEvent({ type: 'status', status: meta.status, exitCode: meta.exitCode });

  // 如果任务还在运行，用 tail -f 实时跟踪
  if (meta.status === 'running') {
    const tail = spawn('tail', ['-f', logPath]);
    let lastSize = 0;

    tail.stdout.on('data', (data) => {
      sendEvent({ type: 'line', line: data.toString() });
    });

    tail.stderr.on('data', (data) => {
      console.error('[tail stderr]', data.toString());
    });

    // 定期检查任务状态
    const checkInterval = setInterval(async () => {
      const currentMeta = await loadTaskMeta(taskId);
      if (currentMeta && currentMeta.status !== 'running') {
        sendEvent({ type: 'status', status: currentMeta.status, exitCode: currentMeta.exitCode });
        sendEvent({ type: 'done' });
        tail.kill();
        clearInterval(checkInterval);
        if (!res.writableEnded) res.end();
      }
    }, 2000);

    // 客户端断开时清理
    req.on('close', () => {
      tail.kill();
      clearInterval(checkInterval);
    });
  } else {
    // 任务已完成，直接发送 done
    sendEvent({ type: 'done' });
    res.end();
  }
});

// GET /tasks/:taskId/output - 获取历史输出
app.get('/tasks/:taskId/output', async (req, res) => {
  try {
    const { taskId } = req.params;
    const { lines = 100 } = req.query;

    const meta = await loadTaskMeta(taskId);
    if (!meta) {
      return res.status(404).json({ error: '任务不存在' });
    }

    const logPath = getTaskLogPath(taskId);
    let output = '';

    try {
      const result = await execAsync(`tail -${lines} ${logPath} 2>/dev/null || echo ''`);
      output = result.stdout;
    } catch {
      output = '';
    }

    res.json({
      taskId,
      status: meta.status,
      exitCode: meta.exitCode,
      output,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /tasks/:taskId/cancel - 取消任务
app.post('/tasks/:taskId/cancel', async (req, res) => {
  try {
    const { taskId } = req.params;
    const meta = await loadTaskMeta(taskId);

    if (!meta) {
      return res.status(404).json({ error: '任务不存在' });
    }

    if (meta.status !== 'running') {
      return res.status(400).json({ error: '任务已结束' });
    }

    // 尝试杀死进程
    const task = activeTasks.get(taskId);
    if (task?.pid) {
      try {
        process.kill(task.pid, 'SIGTERM');
      } catch (e) {
        // 进程可能已结束
      }
      activeTasks.delete(taskId);
    }

    // 更新状态
    meta.status = 'cancelled';
    meta.exitCode = -1;
    meta.finishedAt = new Date().toISOString();
    await saveTaskMeta(taskId, meta);

    res.json({ success: true, status: 'cancelled' });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// 任务完成回调 - 触发 LLM 分析
async function onTaskComplete(taskId, exitCode) {
  const meta = await loadTaskMeta(taskId);
  if (!meta || !meta.sessionId) return;

  // 更新任务状态
  meta.status = exitCode === 0 ? 'completed' : 'failed';
  meta.exitCode = exitCode;
  meta.finishedAt = new Date().toISOString();
  await saveTaskMeta(taskId, meta);

  // 更新会话
  const data = await loadSessions();
  const session = (data.sessions || []).find(s => s.id === meta.sessionId);
  if (session) {
    session.hasUnread = true;
    session.activeTaskId = null;
    session.updatedAt = new Date().toISOString();
    await saveSessions(data);
  }

  activeTasks.delete(taskId);
  console.log(`[task] ${taskId} completed with exit code ${exitCode}`);
}

// 后台监控进程 - 检查任务状态
async function startTaskMonitor() {
  setInterval(async () => {
    for (const [taskId, task] of activeTasks) {
      try {
        // 检查进程是否还在运行
        process.kill(task.pid, 0);
      } catch (e) {
        // 进程已结束
        const meta = await loadTaskMeta(taskId);
        if (meta && meta.status === 'running') {
          // 读取退出码（从日志或默认）
          await onTaskComplete(taskId, 0);
        }
      }
    }
  }, 5000);
}
startTaskMonitor();

// ─── GET /meta ────────────────────────────────────────────────────────────────
// 返回团队名、skills 列表、kb 文件列表
app.get('/meta', async (req, res) => {
  const skills = [];
  const kbFiles = [];

  try {
    const skillsDir = path.join(TEAM_DIR, 'skills');
    if (existsSync(skillsDir)) {
      const dirs = await readdir(skillsDir, { withFileTypes: true });
      for (const d of dirs) {
        if (d.isDirectory()) skills.push(d.name);
      }
    }
  } catch (_) {}

  try {
    const kbDir = path.join(TEAM_DIR, 'kb');
    if (existsSync(kbDir)) {
      const files = await readdir(kbDir);
      kbFiles.push(...files.filter(f => f.endsWith('.md') || f.endsWith('.txt')));
    }
  } catch (_) {}

  res.json({ teamId: TEAM_ID, teamName: TEAM_NAME, skills, kbFiles });
});

// ─── POST /upload ──────────────────────────────────────────────────────────────
// 上传文件到指定目录
// type: 'skill' | 'kb' | 'attachment'
// 文件存储位置：
//   - skill: teams/{teamId}/skills/{filename}
//   - kb: teams/{teamId}/kb/{filename}
//   - attachment: data/attachments/{sessionId}/{filename}
app.post('/upload', uploadMiddleware.array('files', 100), async (req, res) => {
  try {
    const { type, sessionId } = req.body;
    const files = req.files;

    if (!files || files.length === 0) {
      return res.status(400).json({ error: '没有选择文件' });
    }

    // 根据类型确定目标目录
    let targetDir;
    const sid = sessionId || 'default';  // 会话ID，用于附件目录隔离
    if (type === 'skill') {
      targetDir = path.join(TEAM_DIR, 'skills');
    } else if (type === 'kb') {
      targetDir = path.join(TEAM_DIR, 'kb');
    } else if (type === 'attachment') {
      // 附件存储到 /data/attachments/{sessionId} 目录（按会话隔离）
      targetDir = path.join(ATTACHMENTS_DIR, sid);
    } else {
      return res.status(400).json({ error: '无效的上传类型' });
    }

    // 确保目标目录存在
    await mkdir(targetDir, { recursive: true });

    const uploadedFiles = [];
    const { rename, copyFile, stat } = await import('fs/promises');

    for (const file of files) {
      // 处理文件夹上传：webkitRelativePath 包含相对路径
      // 例如：folder/subfolder/file.txt
      let relativePath = file.originalname;

      // 检查是否有 webkitRelativePath（文件夹上传时会有）
      if (file.path && file.path.includes('/')) {
        // 从临时文件路径中提取原始相对路径
        // multer 会把文件存到 /tmp/uploads/，文件名可能包含路径信息
        // 我们需要从 request 中获取原始路径信息
      }

      // 简单处理：直接使用 originalname
      // 如果是文件夹上传，originalname 可能包含路径分隔符
      const targetPath = path.join(targetDir, file.originalname);
      const targetFileDir = path.dirname(targetPath);

      // 确保目标文件的目录存在
      await mkdir(targetFileDir, { recursive: true });

      // 移动文件（从临时目录到目标目录）
      try {
        await rename(file.path, targetPath);
      } catch (e) {
        // 如果跨设备移动失败，使用复制+删除
        await copyFile(file.path, targetPath);
        await unlink(file.path);
      }

      uploadedFiles.push({
        id: 'att_' + randomUUID().slice(0, 8),  // 附件唯一 ID
        name: file.originalname,
        size: file.size,
        path: type === 'attachment'
          ? path.join('attachments', sid, file.originalname)  // 相对于 /workspace 的路径
          : path.join(type, file.originalname),
        uploadedAt: new Date().toISOString(),
      });

      // 如果是 KB 文件且是 Office/PDF，触发自动转换
      if (type === 'kb') {
        const ext = path.extname(file.originalname).toLowerCase();
        if (['.pdf', '.docx', '.xlsx', '.pptx'].includes(ext)) {
          // 异步触发转换，不阻塞响应
          exec(`python3 /data/agent_harness/tools/auto_convert_all.py ${targetDir}`).catch(e => {
            console.error('[upload] Conversion failed:', e.message);
          });
        }
      }
    }

    res.json({
      success: true,
      type,
      files: uploadedFiles,
      message: `成功上传 ${files.length} 个文件`,
    });
  } catch (e) {
    console.error('[upload error]', e);
    res.status(500).json({ error: '上传失败: ' + e.message });
  }
});

// ─── GET /attachments/:sessionId ───────────────────────────────────────────────
// 获取会话的附件列表
app.get('/attachments/:sessionId', async (req, res) => {
  try {
    const { sessionId } = req.params;
    const attachDir = path.join(ATTACHMENTS_DIR, sessionId);

    if (!existsSync(attachDir)) {
      return res.json({ files: [] });
    }

    const files = await readdir(attachDir);
    const fileList = await Promise.all(
      files.map(async f => {
        const filePath = path.join(attachDir, f);
        const stats = await import('fs/promises').then(m => m.stat(filePath));
        return {
          name: f,
          size: stats.size,
          createdAt: stats.birthtime,
        };
      })
    );

    res.json({ files: fileList });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── GET /attachments/:sessionId/:filename ──────────────────────────────────────
// 下载附件
app.get('/attachments/:sessionId/:filename', async (req, res) => {
  try {
    const { sessionId, filename } = req.params;
    const filePath = path.join(ATTACHMENTS_DIR, sessionId, filename);

    if (!existsSync(filePath)) {
      return res.status(404).json({ error: '文件不存在' });
    }

    res.download(filePath);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── POST /session ────────────────────────────────────────────────────────────
// 创建新会话，返回 sessionId
app.post('/session', async (req, res) => {
  try {
    const data = await opencodeRequest('POST', '/session', {});
    // opencode 返回 { id: "..." } 或 { data: { id: "..." } }
    const sessionId = data?.id || data?.data?.id;
    if (!sessionId) throw new Error('opencode 未返回 sessionId，响应：' + JSON.stringify(data));
    res.json({ sessionId });
  } catch (e) {
    if (e.code === 'ECONNREFUSED' || e.message?.includes('fetch failed')) {
      return res.status(503).json({ error: 'Agent 服务暂时不可用，请稍后重试' });
    }
    res.status(500).json({ error: e.message });
  }
});

// ─── POST /chat ───────────────────────────────────────────────────────────────
// 流式对话：先建 SSE 连接监听 opencode Bus 事件，再发 message
//
// opencode v1.2.24 API:
//   GET  /event                        → SSE 事件流（Bus 全量广播）
//   POST /session/:id/message          → 发送消息（同步等完成，返回完整 JSON）
//   Body: { parts: [{ type: "text", text: "..." }] }
//
// 请求体: { sessionId: string, message: string }
// 响应: text/event-stream → 前端格式

// 辅助函数：创建新的 opencode session 并同步历史消息
async function createNewOpencodeSessionWithHistory(localSession, sessionsData) {
  try {
    const newData = await opencodeRequest('POST', '/session', {});
    const newOpencodeSessionId = newData?.id || newData?.data?.id;
    if (newOpencodeSessionId) {
      opencodeSessionId = newOpencodeSessionId;
      // 更新 sessions.json
      const idx = (sessionsData.sessions || []).findIndex(s => s.id === localSession.id);
      if (idx >= 0) {
        sessionsData.sessions[idx].opencodeSessionId = newOpencodeSessionId;
        await saveSessions(sessionsData);
      }
      console.log(`[chat] Created new opencode session ${newOpencodeSessionId} for local session ${localSession.id}`);

      // 同步历史消息到新的 opencode session
      try {
        const historyMessages = await loadMessages(localSession.id);
        const messages = historyMessages.messages || [];
        if (messages.length > 0) {
          // 构建历史上下文摘要
          const historyContext = messages.map(m => {
            const role = m.role === 'user' ? '用户' : '助手';
            const content = m.content || '';
            const truncated = content.length > 2000 ? content.slice(0, 2000) + '...[截断]' : content;
            return `${role}: ${truncated}`;
          }).join('\n\n---\n\n');

          const contextMessage = `[历史对话恢复]\n以下是我们之前的对话历史，请在回复时参考这些上下文：\n\n${historyContext}\n\n---\n\n请记住以上对话内容，我会继续与你交流。`;

          // 异步发送历史上下文
          const contextUrl = `${OPENCODE_URL}/session/${newOpencodeSessionId}/message`;
          fetch(contextUrl, {
            method: 'POST',
            headers: opencodeHeaders(),
            body: JSON.stringify({
              parts: [{ type: 'text', text: contextMessage }],
            }),
          }).then(r => {
            if (r.ok) {
              console.log(`[chat] Synced ${messages.length} messages to new opencode session`);
            } else {
              r.text().then(t => console.error('[chat] Failed to sync history:', r.status, t)).catch(() => {});
            }
          }).catch(err => console.error('[chat] History sync error:', err.message));
        }
      } catch (historyErr) {
        console.error('[chat] Failed to load/sync history:', historyErr.message);
      }
    }
  } catch (createErr) {
    console.error('[chat] Failed to create new opencode session:', createErr.message);
  }
}

app.post('/chat', async (req, res) => {
  let { sessionId, message, context } = req.body || {};

  if (!sessionId || !message) {
    return res.status(400).json({ error: '缺少 sessionId 或 message' });
  }

  // 并发锁
  if (sessionLocks.get(sessionId)) {
    return res.status(429).json({ error: '该会话正在处理中，请等待上一条消息完成' });
  }
  sessionLocks.set(sessionId, true);
  const lockSessionId = sessionId; // 保存原始 sessionId 用于解锁

  // 用户发新消息，取消之前的记忆整理定时器
  cancelMemoryConsolidate(sessionId);

  // 验证 opencode session 是否有效，如果无效则创建新的
  let opencodeSessionId = sessionId;
  let needsSessionUpdate = false;
  let localSessionId = null;

  // 查找本地 session 记录
  try {
    const sessionsData = await loadSessions();
    const localSession = (sessionsData.sessions || []).find(s =>
      s.id === sessionId || s.opencodeSessionId === sessionId
    );

    if (localSession) {
      localSessionId = localSession.id;

      // 检查是否有 opencode session ID
      if (localSession.opencodeSessionId) {
        // 验证 opencode session 是否有效
        try {
          await opencodeRequest('GET', `/session/${localSession.opencodeSessionId}`);
          opencodeSessionId = localSession.opencodeSessionId;
        } catch (e) {
          if (e.status === 404 || e.message?.includes('not found') || e.message?.includes('NotFoundError')) {
            console.log(`[chat] opencode session ${localSession.opencodeSessionId} not found, creating new one...`);
            // opencode session 不存在，创建新的并同步历史
            await createNewOpencodeSessionWithHistory(localSession, sessionsData);
          }
        }
      } else {
        // 没有 opencode session ID，需要创建新的
        console.log(`[chat] No opencode session for local session ${localSession.id}, creating new one...`);
        await createNewOpencodeSessionWithHistory(localSession, sessionsData);
      }
    }
  } catch (e) {
    console.error('[chat] Session validation error:', e.message);
  }

  // 更新 sessionId 为有效的 opencode session ID
  sessionId = opencodeSessionId;

  // 设置 SSE headers
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders();

  const sendEvent = (obj) => {
    if (!res.writableEnded) res.write(`data: ${JSON.stringify(obj)}\n\n`);
  };

  let sseAbort = null;
  let finished = false;

  const cleanup = (reason) => {
    if (finished) return;
    finished = true;
    sessionLocks.delete(lockSessionId);
    if (sseAbort) { sseAbort.abort(); sseAbort = null; }
  };

  res.on('close', () => cleanup('res.close'));

  // 5 分钟超时（LLM 响应可能很慢）
  const timeout = setTimeout(() => {
    sendEvent({ type: 'error', message: 'Agent 响应超时（15分钟），请重试或简化问题' });
    if (!res.writableEnded) res.end();
    cleanup('timeout');
  }, 900_000); // 15分钟

  try {
    // ── Step 1: 建立 SSE 连接 ──
    sseAbort = new AbortController();
    const sseUrl = `${OPENCODE_URL}/event`;
    const sseResponse = await fetch(sseUrl, {
      headers: opencodeHeaders(),
      signal: sseAbort.signal,
    });

    if (!sseResponse.ok) {
      throw new Error(`opencode SSE /event -> ${sseResponse.status}`);
    }

    const sseReader = sseResponse.body.getReader();
    const sseDecoder = new TextDecoder();
    let sseBuf = '';
    const reasoningPartIDs = new Set();
    const displayedAgents = new Set(); // 跟踪已显示的 agent，避免重复

    // 解析 SSE 缓冲区中的事件（不消费 reader，只解析已有的 buf）
    const parseSSELines = (lines) => {
      const events = [];
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;
        try { events.push(JSON.parse(raw)); } catch {}
      }
      return events;
    };

    // ── Step 2: 排空旧事件，等 session 空闲 ──
    // 如果上一条消息还在处理，SSE 流会有旧事件，全部丢弃直到 session.idle
    let sessionReady = false;
    const drainTimeout = setTimeout(() => { sessionReady = true; }, 5000); // 最多等5秒

    while (!sessionReady && !finished) {
      const { done, value } = await sseReader.read();
      if (done) break;

      sseBuf += sseDecoder.decode(value, { stream: true });
      const lines = sseBuf.split('\n');
      sseBuf = lines.pop();

      for (const evt of parseSSELines(lines)) {
        const t = evt?.type || evt?.event;
        console.log('[drain]', t);
        if (t === 'session.idle') {
          sessionReady = true;
          break;
        }
      }
    }
    clearTimeout(drainTimeout);

    if (finished) { cleanup('drain-finished'); return; }

    // ── Step 3: session 已空闲，发送新消息并读取响应 ──
    // 如果有 context（来自 Router 的跨团队上下文），将其拼接到消息前面
    let finalMessage = message;
    if (context) {
      finalMessage = `[Router 上下文]\n以下是用户在多Agent对话中的完整历史，请在回复时参考这些上下文：\n\n${context}\n---\n\n[当前问题]\n${message}`;
    }

    const msgUrl = `${OPENCODE_URL}/session/${sessionId}/message`;
    try {
      const msgRes = await fetch(msgUrl, {
        method: 'POST',
        headers: opencodeHeaders(),
        body: JSON.stringify({
          parts: [{ type: 'text', text: finalMessage }],
        }),
      });

      if (!msgRes.ok) {
        const errText = await msgRes.text().catch(() => 'Unknown error');
        console.error('[msg post]', msgRes.status, errText);
        sendEvent({ type: 'error', message: `OpenCode 返回 ${msgRes.status}: ${errText}` });
        if (!res.writableEnded) res.end();
        cleanup('msg-error');
        return;
      }

      // 读取 OpenCode 响应（JSON 格式，包含 parts 数组）
      const rawBody = await msgRes.text();
      console.log('[msg post] Response status:', msgRes.status, 'body length:', rawBody.length, 'preview:', rawBody.slice(0, 200));
      let msgData;
      try {
        msgData = JSON.parse(rawBody);
      } catch (e) {
        console.error('[msg post] Failed to parse response:', rawBody.slice(0, 200));
        sendEvent({ type: 'error', message: 'Agent 返回了无效的响应格式' });
        if (!res.writableEnded) res.end();
        cleanup('parse-error');
        return;
      }
      const parts = msgData?.parts || [];

      // ── Step 4: 将 parts 转换为 SSE 事件流回客户端 ──
      for (const part of parts) {
        if (finished) break;

        if (part.type === 'reasoning' && part.text) {
          sendEvent({ type: 'thinking', content: part.text });
        } else if (part.type === 'text' && part.text) {
          sendEvent({ type: 'text', content: part.text });
        } else if (part.type === 'tool') {
          sendEvent({
            type: 'tool',
            tool: part.tool,
            name: part.tool,
            command: part.command || null,
            status: part.state || 'completed',
          });
        }
      }

      // 发送完成事件
      sendEvent({ type: 'done' });
      scheduleMemoryConsolidate(sessionId);

    } catch (e) {
      console.error('[msg post error]', e.message);
      if (!finished) sendEvent({ type: 'error', message: e.message });
    }

    clearTimeout(timeout);
    if (!res.writableEnded) res.end();
  } catch (e) {
    clearTimeout(timeout);
    cleanup();
    console.error('[chat error]', e.name, e.message, e.cause || '');
    cleanup('catch');
    if (!res.writableEnded) {
      if (e.code === 'ECONNREFUSED' || e.message?.includes('fetch failed')) {
        sendEvent({ type: 'error', message: 'Agent 服务暂时不可用，请稍后重试' });
      } else {
        sendEvent({ type: 'error', message: e.message || '未知错误' });
      }
      res.end();
    }
  }
});

// ─── opencode 事件转换 ────────────────────────────────────────────────────────
// opencode 服务端推送的事件格式转换为前端期望的格式
// 如果事件格式不对，在这里调整即可
function translateEvent(event, reasoningPartIDs, sessionId, displayedAgents = new Set()) {
  const t = event?.type || event?.event;

  // 流式文本 delta（主要的流式事件）
  if (t === 'message.part.delta') {
    const props = event?.properties || {};
    // reasoning 部分转为 thinking 事件，供前端显示
    if (reasoningPartIDs && props.partID && reasoningPartIDs.has(props.partID)) {
      if (props.field === 'text' && props.delta) {
        return { type: 'thinking', content: props.delta };
      }
      return null;
    }
    if (props.field === 'text' && props.delta) {
      return { type: 'text', content: props.delta };
    }
    return null;
  }

  // 工具调用（opencode 中表现为 message.part.updated，type=tool）
  if (t === 'message.part.updated') {
    const part = event?.properties?.part || {};
    console.log('[part.updated] type:', part.type, 'tool:', part.tool, 'state:', JSON.stringify(part.state));

    // opencode 的 tool 事件结构：{ type: 'tool', tool: 'skill'|'bash'|'glob'|'read'|..., state: { status, input, output } }
    if (part.type === 'tool' && part.state) {
      const status = part.state.status; // pending, running, completed, failed
      let toolType = part.tool || 'unknown'; // skill, bash, glob, read, etc.

      // 根据工具类型提取显示信息
      let displayName = toolType;
      let command = null;

      // 检测是否为记忆操作（read/write/edit/grep 对 .claude/memory 或 .claude/sessions）
      // opencode 传递的路径字段名不统一，需要检查多个可能的字段
      const filePath = part.state?.input?.path || part.state?.input?.file || part.state?.input?.filePath || '';
      const grepPattern = part.state?.input?.pattern || part.state?.input?.query || '';
      const grepPath = part.state?.input?.path || part.state?.input?.filePath || '';
      const editFilePath = part.state?.input?.file_path || part.state?.input?.filePath || '';
      const writeFilePath = part.state?.input?.file_path || part.state?.input?.filePath || '';

      // 统一检测所有记忆相关路径（包括 /workspace/.claude/... 格式）
      const memoryPaths = [
        filePath,
        grepPath,
        editFilePath,
        writeFilePath,
      ];

      const isMemoryPath = memoryPaths.some(p =>
        p.includes('.claude/memory/') ||
        p.includes('.claude\\memory\\') ||
        p.includes('.claude/sessions/') ||
        p.includes('.claude\\sessions\\') ||
        p.includes('/.claude/memory/') ||
        p.includes('\\.claude\\memory\\') ||
        p.includes('/.claude/sessions/') ||
        p.includes('\\.claude\\sessions\\')
      );

      // 调试日志：显示路径和检测结果
      if (isMemoryPath || toolType === 'edit' || toolType === 'write') {
        console.log(`[memory check] tool=${toolType}, filePath=${filePath}, editFilePath=${editFilePath}, writeFilePath=${writeFilePath}, isMemoryPath=${isMemoryPath}`);
      }

      // read 工具读取 memory/sessions 目录
      const isMemoryRead = toolType === 'read' && isMemoryPath;

      // write 工具写入 memory/sessions 目录
      const isMemoryWrite = toolType === 'write' && isMemoryPath;

      // edit 工具编辑 memory/sessions 目录
      const isMemoryEdit = toolType === 'edit' && isMemoryPath;

      // grep 工具搜索 memory 或 sessions 目录（Layer 3: Transcript）
      const isMemoryGrep = toolType === 'grep' && isMemoryPath;

      // 检测 task 工具（SubAgent 调用）
      if (toolType === 'task') {
        const taskInput = part.state?.input || {};
        const subagentType = taskInput.subagent_type || taskInput.agent;
        const taskDesc = taskInput.description || (taskInput.prompt ? taskInput.prompt.slice(0, 30) : '');

        // 只在有明确的 subagent 类型时才显示
        if (!subagentType) {
          return null;
        }

        toolType = 'subagent';
        displayName = `${subagentType}${taskDesc ? `: ${taskDesc}` : ''}${taskDesc.length >= 30 ? '...' : ''}`;
      } else if (isMemoryRead) {
        toolType = 'memory';
        const memMatch = filePath.match(/(?:memory|sessions)\/([^/]+\.md|[^/]+\.jsonl)$/);
        displayName = memMatch ? `读取: ${memMatch[1]}` : `读取记忆文件`;
      } else if (isMemoryWrite) {
        toolType = 'memory';
        const memMatch = writeFilePath.match(/(?:memory|sessions)\/([^/]+\.md|[^/]+\.jsonl)$/);
        displayName = memMatch ? `写入: ${memMatch[1]}` : `写入记忆文件`;
      } else if (isMemoryEdit) {
        toolType = 'memory';
        const memMatch = editFilePath.match(/(?:memory|sessions)\/([^/]+\.md|[^/]+\.jsonl)$/);
        displayName = memMatch ? `编辑: ${memMatch[1]}` : `编辑记忆文件`;
      } else if (isMemoryGrep) {
        toolType = 'memory';
        displayName = `搜索: ${grepPattern.slice(0, 30)}${grepPattern.length > 30 ? '...' : ''}`;
      } else if (toolType === 'skill') {
        // skill 显示名称
        displayName = part.state?.input?.name || toolType;
      } else if (toolType === 'bash') {
        // bash 显示完整命令
        const bashInput = part.state?.input || {};
        command = bashInput.command || bashInput.cmd || '';
        displayName = command;
      } else if (toolType === 'glob') {
        // glob 显示 pattern
        const pattern = part.state?.input?.pattern || part.state?.input?.glob || '';
        displayName = pattern;
      } else if (toolType === 'read') {
        // read 显示文件路径
        displayName = filePath;
      }

      // 如果没有具体内容（只显示工具类型），则不返回事件
      if (!displayName || displayName === toolType) {
        return null;
      }

      return { type: 'tool', tool: toolType, name: displayName, command, status };
    }

    // 兼容旧格式
    if (part.type === 'tool-use' || part.type === 'tool-call') {
      return { type: 'skill', name: part.toolName || part.name || 'unknown', status: 'running' };
    }
    if (part.type === 'tool-result') {
      return { type: 'skill', name: part.toolName || part.name || 'unknown', status: 'completed' };
    }

    // reasoning 部分更新 - 标记 thinking 开始
    if (part.type === 'reasoning') {
      return { type: 'thinking_start' };
    }
    return null;
  }

  // 消息息更新 - 检测 agent 切换
  // 注意：OpenCode 中所有 assistant 消息都有 parentID（指向用户消息）
  // 所以不能用 parentID 来判断是否是 subagent
  // SubAgent 通过 task 工具来识别
  if (t === 'message.updated') {
    const info = event?.properties?.info || {};
    const agent = info.agent || 'unknown';
    const mode = info.mode || agent; // build, plan, general, explore
    const role = info.role;

    // 只在 assistant 消息且是第一条时显示 agent（通过去重避免重复）
    if (role === 'assistant') {
      const agentKey = `${agent}:${mode}`;
      if (!displayedAgents.has(agentKey)) {
        displayedAgents.add(agentKey);
        // 根据消息内容提取简短描述
        const tokens = info.tokens || {};
        const hasToolCalls = info.finish === 'tool-calls';
        let description = '';
        if (hasToolCalls) {
          description = '调用工具中...';
        }
        return {
          type: 'agent_switch',
          agent,
          agentType: 'primary',
          mode,
          description
        };
      }
    }
    return null;
  }

  // session 更新 - 捕获 title 变化
  if (t === 'session.updated') {
    const info = event?.properties?.info || {};
    const title = info.title;
    const sessionID = info.id;

    if (title && sessionID) {
      // 过滤掉默认标题，不发送给前端
      if (isDefaultTitle(title)) {
        console.log(`[session.updated] Ignoring default title "${title}" for session ${sessionID}`);
        return null;
      }
      console.log(`[session.updated] title="${title}" sessionID=${sessionID}`);
      return { type: 'title_update', title, opencodeSessionId: sessionID };
    }
    return null;
  }

  // session 空闲 → 完成
  if (t === 'session.idle') {
    return { type: 'done' };
  }

  // 错误 - 输出完整错误信息用于调试
  if (t === 'session.error') {
    const errObj = event?.properties?.error || {};
    const errData = errObj?.data || {};
    const msg = errData?.message || errObj?.message || event?.message || '未知错误';
    const detail = JSON.stringify(errObj, null, 0);
    console.error('[session.error]', detail);
    return { type: 'error', message: `${msg} | 详情: ${detail}` };
  }

  // 捕获所有未处理的事件类型中的错误信息
  if (t && (t.includes('error') || t.includes('fail'))) {
    const detail = JSON.stringify(event, null, 0);
    console.error('[unknown error event]', detail);
    return { type: 'error', message: `[${t}] ${detail}` };
  }

  return null; // 忽略其他事件
}

// ─── 消息持久化 API ─────────────────────────────────────────────────────────
// POST /sessions/:id/messages - 保存消息到会话
app.post('/sessions/:id/messages', async (req, res) => {
  try {
    const { id } = req.params;
    const { messages, opencodeSessionId, title } = req.body || {};

    if (!messages || !Array.isArray(messages)) {
      return res.status(400).json({ error: '缺少 messages 数组' });
    }

    // 检查是否有用户消息（空会话不保存）
    const hasUserMsg = messages.some(m => m.role === 'user');
    if (!hasUserMsg) {
      console.log(`[messages] Skipping save for session ${id}: no user messages`);
      return res.json({ success: true, skipped: true, reason: 'no_user_messages' });
    }

    // 保存消息
    await saveMessages(id, { messages });

    // 更新或创建会话记录
    const data = await loadSessions();
    const idx = (data.sessions || []).findIndex(s => s.id === id);
    const now = new Date().toISOString();

    if (idx >= 0) {
      // 更新现有会话
      data.sessions[idx].updatedAt = now;
      // 只存储有意义的标题（非默认标题）
      if (title && !isDefaultTitle(title)) {
        data.sessions[idx].title = title;
      }
    } else {
      // 创建新会话记录
      data.sessions = data.sessions || [];
      // 只存储有意义的标题，否则使用默认"新会话"
      const finalTitle = (title && !isDefaultTitle(title)) ? title : '新会话';
      data.sessions.unshift({
        id,
        title: finalTitle,
        createdAt: now,
        updatedAt: now,
        hasUnread: false,
        activeTaskId: null,
        opencodeSessionId: opencodeSessionId || null,
      });
      console.log(`[messages] Created session record for ${id}`);
    }

    await saveSessions(data);
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// DELETE /sessions/:id - 删除会话（如果没有任何消息）
app.delete('/sessions/:id/empty', async (req, res) => {
  try {
    const { id } = req.params;
    const messagesData = await loadMessages(id);
    const messages = messagesData.messages || [];

    // 只有没有用户消息才删除
    const hasUserMsg = messages.some(m => m.role === 'user');
    if (!hasUserMsg) {
      const data = await loadSessions();
      const idx = (data.sessions || []).findIndex(s => s.id === id);
      if (idx >= 0) {
        data.sessions.splice(idx, 1);
        await saveSessions(data);
        // 删除消息文件
        try {
          const { unlink } = await import('fs/promises');
          await unlink(getMessagesPath(id));
        } catch {}
      }
      return res.json({ deleted: true });
    }
    res.json({ deleted: false, reason: 'has_messages' });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── 配置管理 ─────────────────────────────────────────────────────────────────
// 配置文件路径（使用宿主机路径，因为容器内 teams 目录是只读挂载）
const ENV_FILE = '/data/agent_harness/.env';
const COMPOSE_FILE = '/data/agent_harness/docker-compose.yml';
const OPENCODE_JSON = `/data/agent_harness/teams/${TEAM_ID}/opencode.json`;

// 可用模型列表
const AVAILABLE_MODELS = [
  { id: 'zhipuai/glm-5', name: 'GLM-5 (智谱)' },
  { id: 'zhipuai/glm-4.5', name: 'GLM-4.5 (智谱)' },
  { id: 'azure_openai/gpt-4o-mini', name: 'GPT-4o Mini (Azure)' },
  { id: 'azure_openai/gpt-4o', name: 'GPT-4o (Azure)' },
  { id: 'azure_openai/o1-mini', name: 'O1 Mini (Azure)' },
  { id: 'tongyi/qwen3-max', name: 'Qwen3 Max (通义)' },
  { id: 'tongyi/qwen3-next-80b-a3b-thinking', name: 'Qwen3 Thinking (通义)' },
  { id: 'tongyi/kimi-k2-thinking', name: 'Kimi K2 Thinking (通义)' },
  { id: 'baidu_qianfan/ernie-5.0-thinking-latest', name: 'ERNIE 5.0 Thinking (百度)' },
  { id: 'tongyi/deepseek-r1', name: 'DeepSeek R1 (通义)' },
  { id: 'tongyi/deepseek-v3.1', name: 'DeepSeek V3.1 (通义)' },
  { id: 'vertex_ai/gemini-2.5-flash', name: 'Gemini 2.5 Flash (Vertex)' },
  { id: 'volcengine_maas/doubao-1-5-thinking-pro', name: 'Doubao Thinking (火山)' },
  { id: 'moonshotai/Kimi-K2-Thinking', name: 'Kimi K2 Thinking (Moonshot)' },
];

// 更新 .env 文件
async function updateEnv(baseUrl, apiKey) {
  if (!existsSync(ENV_FILE)) return;
  let content = await readFile(ENV_FILE, 'utf-8');
  if (baseUrl) {
    content = content.replace(/^LLM_BASE_URL=.*$/m, `LLM_BASE_URL=${baseUrl}`);
  }
  if (apiKey) {
    content = content.replace(/^LLM_API_KEY=.*$/m, `LLM_API_KEY=${apiKey}`);
  }
  await writeFile(ENV_FILE, content);
}

// 更新 docker-compose.yml 中的 OPENCODE_CONFIG_CONTENT
async function updateCompose(model) {
  if (!model || !existsSync(COMPOSE_FILE)) return;

  const content = await readFile(COMPOSE_FILE, 'utf-8');

  // 找到 OPENCODE_CONFIG_CONTENT 行并提取 JSON
  const lines = content.split('\n');
  let targetLineIdx = -1;
  let configJson = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const match = line.match(/OPENCODE_CONFIG_CONTENT='(.+)'$/);
    if (match) {
      targetLineIdx = i;
      try {
        configJson = JSON.parse(match[1]);
      } catch (e) {
        console.error('[updateCompose] Failed to parse JSON:', e.message);
        return;
      }
      break;
    }
  }

  if (targetLineIdx === -1 || !configJson) return;

  try {
    // 更新模型配置
    configJson.model = `internal-llm/${model}`;
    const modelDisplay = model.split('/').pop();
    configJson.provider['internal-llm'].models = {
      [model]: { name: modelDisplay }
    };

    // 重建 JSON 字符串（紧凑格式，无空格）
    const newJson = JSON.stringify(configJson);
    lines[targetLineIdx] = `      - 'OPENCODE_CONFIG_CONTENT=${newJson}'`;

    await writeFile(COMPOSE_FILE, lines.join('\n'));
  } catch (e) {
    console.error('[updateCompose] Failed:', e.message);
  }
}

// 更新 opencode.json
async function updateOpencodeJson(model, baseUrl) {
  if (!existsSync(OPENCODE_JSON)) return;

  const content = await readFile(OPENCODE_JSON, 'utf-8');
  const config = JSON.parse(content);

  if (model) {
    config.model = `internal-llm/${model}`;
    const modelDisplay = model.split('/').pop();
    config.provider['internal-llm'].models = {
      [model]: { name: modelDisplay }
    };
  }

  if (baseUrl) {
    config.provider['internal-llm'].options.baseURL = baseUrl;
  }

  await writeFile(OPENCODE_JSON, JSON.stringify(config, null, 2) + '\n');
}

// GET /config - 获取当前配置
app.get('/config', async (req, res) => {
  try {
    // 读取 .env 文件
    let baseUrl = '';
    let apiKey = '';
    if (existsSync(ENV_FILE)) {
      const envContent = await readFile(ENV_FILE, 'utf-8');
      const baseUrlMatch = envContent.match(/^LLM_BASE_URL=(.*)$/m);
      const apiKeyMatch = envContent.match(/^LLM_API_KEY=(.*)$/m);
      if (baseUrlMatch) baseUrl = baseUrlMatch[1].trim();
      if (apiKeyMatch) apiKey = apiKeyMatch[1].trim();
    }

    // 读取 opencode.json
    let currentModel = '';
    if (existsSync(OPENCODE_JSON)) {
      const configContent = await readFile(OPENCODE_JSON, 'utf-8');
      const config = JSON.parse(configContent);
      currentModel = config.model?.replace('internal-llm/', '') || '';
    }

    res.json({
      baseUrl,
      apiKey: apiKey ? apiKey.slice(0, 8) + '...' + apiKey.slice(-4) : '',
      apiKeyConfigured: !!apiKey,
      currentModel,
      availableModels: AVAILABLE_MODELS,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /config - 更新配置（同时更新三个文件）
app.post('/config', async (req, res) => {
  try {
    const { baseUrl, apiKey, model } = req.body || {};
    const changes = [];

    // 1. 更新 .env
    if (baseUrl || apiKey) {
      await updateEnv(baseUrl, apiKey);
      changes.push('.env');
    }

    // 2. 更新 docker-compose.yml
    if (model) {
      await updateCompose(model);
      changes.push('docker-compose.yml');
    }

    // 3. 更新 opencode.json
    if (model || baseUrl) {
      await updateOpencodeJson(model, baseUrl);
      changes.push('opencode.json');
    }

    res.json({
      success: true,
      message: `Configuration saved to: ${changes.join(', ')}`,
      files: changes,
      needRestart: true  // 需要重启容器才能生效
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /config/apply - 保存并应用配置（一键完成）
app.post('/config/apply', async (req, res) => {
  try {
    const { baseUrl, apiKey, model } = req.body || {};
    const steps = [];

    // Step 1: 保存配置
    steps.push('Saving configuration...');
    if (baseUrl || apiKey) {
      await updateEnv(baseUrl, apiKey);
      steps.push('✓ .env updated');
    }
    if (model) {
      await updateCompose(model);
      steps.push('✓ docker-compose.yml updated');
    }
    if (model || baseUrl) {
      await updateOpencodeJson(model, baseUrl);
      steps.push('✓ opencode.json updated');
    }

    // Step 2: 重启容器
    steps.push('Restarting opencode container...');
    const containerName = process.env.OPENCODE_CONTAINER || 'agent_harness-opencode-team-a-1';
    try {
      const { stdout, stderr } = await execAsync(
        `docker restart ${containerName} 2>&1`,
        { timeout: 30000 }
      );
      if (stderr && !stdout) {
        console.error('Docker restart stderr:', stderr);
      }
    } catch (dockerErr) {
      // 捕获更详细的错误信息
      console.error('Docker restart failed:', dockerErr);
      throw new Error(`Docker restart failed: ${dockerErr.message}\nstdout: ${dockerErr.stdout || 'N/A'}\nstderr: ${dockerErr.stderr || 'N/A'}`);
    }
    steps.push('✓ Container restarted');

    // Step 3: 等待容器健康
    steps.push('Waiting for container to be healthy...');
    let healthy = false;
    for (let i = 0; i < 30; i++) {
      await new Promise(r => setTimeout(r, 1000));
      try {
        const check = await execAsync(
          'wget -q --server-response -O/dev/null http://127.0.0.1:4101/ 2>&1 | grep -qE "HTTP/[0-9.]+ (200|401)" && echo ok || echo fail',
          { timeout: 5000 }
        );
        if (check.stdout.trim() === 'ok') {
          healthy = true;
          break;
        }
      } catch (_) {}
    }

    if (healthy) {
      steps.push('✓ Container is healthy');
    } else {
      steps.push('⚠ Container may need more time to start');
    }

    res.json({
      success: true,
      message: 'Configuration applied successfully!',
      steps,
      healthy,
      needRefresh: true  // 前端需要刷新页面
    });
  } catch (e) {
    console.error('Config apply error:', e);
    const containerName = process.env.OPENCODE_CONTAINER || 'agent_harness-opencode-team-a-1';
    res.status(500).json({
      error: 'Failed to apply configuration: ' + e.message,
      stdout: e.stdout || null,
      stderr: e.stderr || null,
      hint: `Try manually: docker restart ${containerName}`
    });
  }
});

// ─── 记忆系统集成 ─────────────────────────────────────────────────────────────
const MEMORY_DIR = path.join(TEAM_DIR, '.claude', 'memory');

// 调用 Python 记忆 API
async function callMemoryAPI(action, params = {}) {
  const pythonCode = `
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, '/data/agent_harness/src')
from memory import MemoryManager, MemoryAttachmentManager
from memory.attachment import build_memory_system_prompt

async def main():
    try:
        memory_dir = Path("${MEMORY_DIR}")
        action = "${action}"
        params = ${JSON.stringify(params)}

        if action == 'get_system_prompt':
            result = build_memory_system_prompt(memory_dir)
            print(json.dumps({'success': True, 'content': result}))

        elif action == 'get_index':
            manager = MemoryManager(memory_dir)
            index = manager.read_index()
            print(json.dumps({'success': True, 'index': index}))

        elif action == 'list_memories':
            manager = MemoryManager(memory_dir)
            memories = manager.list_topic_files()
            print(json.dumps({'success': True, 'memories': [m.__dict__ for m in memories]}))

        elif action == 'read_memory':
            manager = MemoryManager(memory_dir)
            filename = params.get('filename')
            content = manager.read_memory(filename)
            print(json.dumps({'success': True, 'content': content}))

        elif action == 'find_relevant':
            attachment_manager = MemoryAttachmentManager(memory_dir)
            query = params.get('query', '')
            attachments = await attachment_manager.find_relevant_memories(query)
            print(json.dumps({
                'success': True,
                'attachments': [a.to_dict() for a in attachments]
            }))

        elif action == 'consolidate':
            from memory.dream import MemoryDreamer
            manager = MemoryManager(memory_dir)
            dreamer = MemoryDreamer(manager)
            result = await dreamer.dream()
            print(json.dumps({'success': True, 'result': result}))

        else:
            print(json.dumps({'success': False, 'error': f'Unknown action: {action}'}))

    except Exception as e:
        print(json.dumps({'success': False, 'error': str(e)}))

asyncio.run(main())
`;

  try {
    const { stdout, stderr } = await execAsync(
      `python3 -c '${pythonCode.replace(/'/g, "'\"'\"'")}'`,
      { timeout: 60000 }
    );

    const result = JSON.parse(stdout);
    if (!result.success) {
      throw new Error(result.error || 'Unknown error');
    }
    return result;
  } catch (e) {
    console.error('[memory API]', e.message);
    throw e;
  }
}

// GET /memory - 获取记忆索引 (Layer 1: MEMORY.md)
app.get('/memory', async (req, res) => {
  try {
    const indexPath = path.join(MEMORY_DIR, 'MEMORY.md');
    if (existsSync(indexPath)) {
      const content = await readFile(indexPath, 'utf-8');
      res.json({ success: true, content });
    } else {
      res.json({ success: true, content: '# Memory Index\n\n(暂无记忆)' });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /memory/list - 列出所有记忆文件
app.get('/memory/list', async (req, res) => {
  try {
    const memories = await listMemoryFiles();
    res.json({ success: true, memories });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /memory/:filename - 读取单个记忆
app.get('/memory/:filename', async (req, res) => {
  try {
    const { filename } = req.params;
    const filepath = path.join(MEMORY_DIR, filename);
    if (existsSync(filepath)) {
      const content = await readFile(filepath, 'utf-8');
      res.json({ success: true, content });
    } else {
      res.status(404).json({ error: '记忆文件不存在' });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /memory/search - 搜索相关记忆 (Layer 2)
app.post('/memory/search', async (req, res) => {
  try {
    const { query } = req.body || {};
    if (!query) {
      return res.status(400).json({ error: '缺少 query' });
    }
    // 简单的关键词搜索
    const memories = await listMemoryFiles();
    const results = memories.filter(m =>
      m.name.toLowerCase().includes(query.toLowerCase()) ||
      m.description.toLowerCase().includes(query.toLowerCase())
    );
    res.json({ success: true, results });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /memory/consolidate - 手动触发 auto dream
app.post('/memory/consolidate', async (req, res) => {
  try {
    const state = await getMemoryState();
    const sessions = state.sessionsSinceLastDream || [];

    if (sessions.length === 0) {
      // 如果没有积累的 session，使用所有 session
      const data = await loadSessions();
      const allSessions = (data.sessions || []).map(s => s.id);
      if (allSessions.length > 0) {
        const result = await runAutoDream(allSessions);
        res.json({ success: true, result, sessions: allSessions.length });
      } else {
        res.json({ success: true, result: { skipped: true, reason: 'no_sessions' } });
      }
    } else {
      const result = await runAutoDream(sessions);
      res.json({ success: true, result, sessions: sessions.length });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /memory/status - 获取记忆系统状态
app.get('/memory/status', async (req, res) => {
  try {
    const memories = await listMemoryFiles();
    const state = await getMemoryState();

    // 读取 MEMORY.md 大小
    let indexSize = 0;
    const indexPath = path.join(MEMORY_DIR, 'MEMORY.md');
    if (existsSync(indexPath)) {
      const stats = await import('fs/promises').then(m => m.stat(indexPath));
      indexSize = stats.size;
    }

    res.json({
      memoryFileCount: memories.length,
      indexSize: indexSize,
      indexSizeKB: Math.round(indexSize / 1024 * 10) / 10,
      lastAutoDreamAt: state.lastAutoDreamAt ? new Date(state.lastAutoDreamAt).toISOString() : null,
      sessionsSinceLastDream: (state.sessionsSinceLastDream || []).length,
      autoDreamRunning,
      autoDreamQueueLength: autoDreamQueue.length,
      extractingSessions: Array.from(extractingSessions),
      extractThreshold: EXTRACT_MEMORY_THRESHOLD,
      autoDreamThreshold: AUTO_DREAM_SESSION_THRESHOLD,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// POST /transcript/sync - 同步所有 messages 到 transcript (Layer 3)
app.post('/transcript/sync', async (req, res) => {
  try {
    const { execAsync } = await import('child_process');
    const { promisify } = await import('util');
    const exec = promisify((await import('child_process')).exec);

    // 调用 Python 脚本同步
    const cmd = `python3 /data/agent_harness/tools/sync_transcripts.py ${MESSAGES_DIR} ${TRANSCRIPTS_DIR} --team-id ${TEAM_ID}`;
    const { stdout, stderr } = await exec(cmd, { timeout: 60000 });

    res.json({
      success: true,
      output: stdout,
      error: stderr || null,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /transcript/list - 列出所有 transcript 文件
app.get('/transcript/list', async (req, res) => {
  try {
    if (!existsSync(TRANSCRIPTS_DIR)) {
      return res.json({ files: [] });
    }

    const files = await readdir(TRANSCRIPTS_DIR);
    const fileList = files
      .filter(f => f.endsWith('.jsonl'))
      .map(f => ({ name: f, path: path.join(TRANSCRIPTS_DIR, f) }));

    res.json({ files: fileList, dir: TRANSCRIPTS_DIR });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// GET /transcript/search - 在 transcript 中搜索 (grep 风格)
app.get('/transcript/search', async (req, res) => {
  try {
    const { q, sessionId } = req.query;
    if (!q) {
      return res.status(400).json({ error: 'Missing query parameter q' });
    }

    if (!existsSync(TRANSCRIPTS_DIR)) {
      return res.json({ results: [] });
    }

    // 使用 grep 搜索
    const { exec } = await import('child_process');
    const { promisify } = await import('util');
    const execAsync = promisify(exec);

    const pattern = q.replace(/'/g, "'\"'\"'");
    const sessionFilter = sessionId ? `/${sessionId}.jsonl` : '/*.jsonl';
    const cmd = `grep -h "${pattern}" ${TRANSCRIPTS_DIR}${sessionFilter} 2>/dev/null | head -50`;

    const { stdout } = await execAsync(cmd, { timeout: 30000 });
    const lines = stdout.trim().split('\n').filter(l => l);

    const results = lines.map(line => {
      try {
        return JSON.parse(line);
      } catch {
        return { raw: line };
      }
    });

    res.json({ query: q, count: results.length, results });
  } catch (e) {
    // grep 没有匹配时返回 exit code 1
    if (e.message?.includes('code 1') || e.message?.includes('Command failed')) {
      return res.json({ query: req.query.q, count: 0, results: [] });
    }
    res.status(500).json({ error: e.message });
  }
});

// POST /memory/extract/:sessionId - 手动触发提取指定 session 的记忆
app.post('/memory/extract/:sessionId', async (req, res) => {
  try {
    const { sessionId } = req.params;
    console.log(`[memory] Manual extract for session ${sessionId}`);
    const messagesData = await loadMessages(sessionId);
    const messages = messagesData.messages || [];
    console.log(`[memory] Loaded ${messages.length} messages from ${getMessagesPath(sessionId)}`);

    const result = await extractMemoriesFromSession(sessionId, messages, true);
    res.json({ success: true, result });
  } catch (e) {
    console.error(`[memory] Manual extract error:`, e.message);
    res.status(500).json({ error: e.message });
  }
});

// GET /memory/cursor/:sessionId - 获取指定 session 的 cursor 状态
app.get('/memory/cursor/:sessionId', async (req, res) => {
  try {
    const { sessionId } = req.params;
    const cursor = memoryCursors.get(sessionId) || { lastMessageIndex: 0, extracted: false };
    res.json({ sessionId, cursor });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── 文档转换 ─────────────────────────────────────────────────────────────────
const DOCLING_URL = process.env.DOCLING_URL || 'http://localhost:5001';

// POST /docs/convert - 手动触发文档转换
app.post('/docs/convert', async (req, res) => {
  try {
    const { force = false } = req.body || {};

    // 调用 auto_convert_all.py
    const cmd = force
      ? `python3 /data/agent_harness/tools/auto_convert_all.py /data/agent_harness/teams/${TEAM_ID}/kb /data/agent_harness/teams/${TEAM_ID}/skills`
      : `python3 /data/agent_harness/tools/auto_convert_all.py /data/agent_harness/teams/${TEAM_ID}/kb /data/agent_harness/teams/${TEAM_ID}/skills`;

    const { stdout, stderr } = await execAsync(cmd, { timeout: 600_000 });

    res.json({
      success: true,
      output: stdout,
      error: stderr || null,
    });
  } catch (e) {
    res.status(500).json({
      error: '文档转换失败: ' + e.message,
      output: e.stdout || null,
    });
  }
});

// GET /docs/status - 获取文档转换状态
app.get('/docs/status', async (req, res) => {
  try {
    // 统计 kb 和 skills 目录中的文件
    const stats = { kb: { total: 0, converted: 0 }, skills: { total: 0, converted: 0 } };

    for (const subdir of ['kb', 'skills']) {
      const dir = path.join(TEAM_DIR, subdir);
      if (!existsSync(dir)) continue;

      const files = await readdir(dir, { withFileTypes: true });
      for (const f of files) {
        if (!f.isFile()) continue;
        const ext = path.extname(f.name).toLowerCase();
        if (['.pdf', '.xlsx', '.xls', '.docx', '.pptx'].includes(ext)) {
          stats[subdir].total++;
          const mdPath = path.join(dir, path.basename(f.name, ext) + '.md');
          if (existsSync(mdPath)) {
            stats[subdir].converted++;
          }
        }
      }
    }

    res.json({
      teamId: TEAM_ID,
      stats,
      doclingUrl: DOCLING_URL,
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ─── 错误中间件 ───────────────────────────────────────────────────────────────
app.use((err, req, res, next) => {
  console.error('[error]', err);
  if (err.code === 'ECONNREFUSED') {
    return res.status(503).json({ error: 'Agent 服务暂时不可用，请稍后重试' });
  }
  res.status(500).json({ error: '内部错误' });
});

// ─── 启动 ─────────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`[api] ${TEAM_NAME} (${TEAM_ID}) listening on :${PORT}`);
  console.log(`[api] opencode URL: ${OPENCODE_URL}`);
  console.log(`[api] team dir:     ${TEAM_DIR}`);
});
