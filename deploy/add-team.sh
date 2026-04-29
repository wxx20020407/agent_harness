#!/bin/bash
# =============================================================================
# 新增团队脚本
# 用法: bash deploy/add-team.sh <team-id> <team-name> [password]
# 示例: bash deploy/add-team.sh team-c "Team C Agent" team-c-secret
# =============================================================================
set -e

TEAM_ID=${1:?用法: add-team.sh <team-id> <team-name> [password]}
TEAM_NAME=${2:?用法: add-team.sh <team-id> <team-name> [password]}
PASSWORD=${3:-${TEAM_ID}-secret}

# 端口自动分配（根据已有团队数量）
TEAM_COUNT=$(ls -d teams/team-* 2>/dev/null | wc -l)
RUNTIME_PORT=$((4101 + TEAM_COUNT))
API_PORT=$((4201 + TEAM_COUNT))
UI_PORT=$((4301 + TEAM_COUNT))

echo ">>> 创建团队: ${TEAM_ID} (${TEAM_NAME})"
echo "    端口: runtime=${RUNTIME_PORT}, api=${API_PORT}, ui=${UI_PORT}"

# 1. 创建目录结构
mkdir -p "teams/${TEAM_ID}/skills"
mkdir -p "teams/${TEAM_ID}/kb"

# 2. opencode.json
cat > "teams/${TEAM_ID}/opencode.json" << JSONEOF
{
  "\$schema": "https://opencode.ai/config.json",
  "model": "internal-llm/your-model-id",
  "provider": {
    "internal-llm": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Internal LLM",
      "env": ["LLM_API_KEY"],
      "options": {
        "baseURL": "\${LLM_BASE_URL}"
      },
      "models": {
        "your-model-id": {
          "name": "Your Model"
        }
      }
    }
  },
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
JSONEOF

# 3. AGENTS.md
cat > "teams/${TEAM_ID}/AGENTS.md" << 'MDEOF'
# 团队规则

## 知识库使用规则
- 收到用户提问后，先用 list 工具列出 kb/ 目录下的所有文件
- 根据用户问题的关键词，判断需要读取哪些文件
- 只读取相关文件，不要一次性读完所有文档
- 回答时引用具体的文件名和内容出处

## 行为规则
- 不确定的内容明确说明"我不确定"
- 默认不修改任何文件
- 不执行 bash 命令
MDEOF

# 4. 示例 kb 文件
cat > "teams/${TEAM_ID}/kb/readme.md" << MDEOF
# ${TEAM_NAME} 知识库

在此目录下添加 .md 文件，Agent 将能够读取这些文档回答问题。
MDEOF

# 5. 追加 docker-compose.yml 服务配置（输出片段，需手动添加）
cat << COMPOSEEOF

>>> 请将以下内容追加到 docker-compose.yml 的 services 节点：

  opencode-${TEAM_ID}:
    image: \${OPENCODE_IMAGE:-ghcr.io/sst/opencode:latest}
    command: serve --hostname 0.0.0.0 --port 4096
    working_dir: /workspace
    volumes:
      - ./teams/${TEAM_ID}:/workspace:ro
    environment:
      - OPENCODE_SERVER_PASSWORD=\${${TEAM_ID^^}_PASSWORD:-${PASSWORD}}
      - LLM_BASE_URL=\${LLM_BASE_URL}
      - LLM_API_KEY=\${LLM_API_KEY:-}
      - BUN_CONFIG_REGISTRY=http://127.0.0.1:0
    ports:
      - "${RUNTIME_PORT}:4096"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:4096/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    restart: unless-stopped

  api-${TEAM_ID}:
    build:
      context: .
      dockerfile: deploy/Dockerfile.api
    environment:
      - TEAM_ID=${TEAM_ID}
      - TEAM_NAME=${TEAM_NAME}
      - TEAM_DIR=/teams/${TEAM_ID}
      - OPENCODE_URL=http://opencode-${TEAM_ID}:4096
      - OPENCODE_PASSWORD=\${${TEAM_ID^^}_PASSWORD:-${PASSWORD}}
      - PORT=3000
    volumes:
      - ./teams/${TEAM_ID}:/teams/${TEAM_ID}:ro
    ports:
      - "${API_PORT}:3000"
    depends_on:
      opencode-${TEAM_ID}:
        condition: service_healthy
    restart: unless-stopped

  ui-${TEAM_ID}:
    build:
      context: .
      dockerfile: deploy/Dockerfile.ui
      args:
        - VITE_TEAM_NAME=${TEAM_NAME}
    environment:
      - API_UPSTREAM_URL=http://api-${TEAM_ID}:3000
    ports:
      - "${UI_PORT}:80"
    depends_on:
      - api-${TEAM_ID}
    restart: unless-stopped

>>> 并在 .env 中添加：
${TEAM_ID^^}_PASSWORD=${PASSWORD}

COMPOSEEOF

echo ">>> 团队目录 teams/${TEAM_ID}/ 创建完成"
echo ">>> 请按上方提示更新 docker-compose.yml 和 .env，然后运行："
echo "    docker compose up -d opencode-${TEAM_ID} api-${TEAM_ID} ui-${TEAM_ID}"
