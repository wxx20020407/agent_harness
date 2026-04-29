#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "========== 1. 停止所有服务 =========="
docker compose down

echo "========== 2. 清理附件目录 =========="
# 用 docker 容器清理（容器有 root 权限，不需要 sudo）
docker run --rm -v "$(pwd)/teams/team-a:/data" python:3.11-slim sh -c "rm -rf /data/attachments/*" 2>/dev/null || echo "附件目录已清空或不存在"

echo "========== 3. 同步 Transcript (Layer 3) =========="
mkdir -p teams/team-a/.claude/sessions
python3 tools/sync_transcripts.py data/messages teams/team-a/.claude/sessions --team-id team-a || echo "Transcript 同步完成"

echo "========== 4. 重建所有镜像 =========="
docker compose build

echo "========== 5. 启动所有服务 =========="
docker compose up -d

echo "========== 6. 等待服务启动 =========="
sleep 5

echo "========== 7. 检查 Docling 服务 =========="
if curl -s http://localhost:5001/health | grep -q "ok"; then
    echo "✅ Docling 服务正常 (端口 5001)"
else
    echo "⚠️  Docling 服务未运行，请先启动: ./deploy/start-docling-host.sh start"
fi

echo "========== 8. 自动转换文档 =========="
if curl -s http://localhost:5001/health | grep -q "ok"; then
    echo "正在转换 kb/skills 中的文档..."
    docker compose run --rm init-convert-team-a || echo "文档转换完成或跳过"
else
    echo "⚠️  跳过文档转换（Docling 服务未运行）"
fi

echo "========== 9. 查看启动状态 =========="
docker compose ps

echo ""
echo "========== 10. 验证配置 =========="
echo "--- opencode 模型配置 ---"
docker compose exec opencode-team-a env | grep OPENCODE_CONFIG_CONTENT || echo "(未找到)"

echo ""
echo "--- API server.js 前5行 ---"
docker compose exec api-team-a head -5 /app/server.js || echo "(读取失败)"

echo ""
echo "--- UI 静态文件及时间 ---"
docker compose exec ui-team-a ls -lh /usr/share/nginx/html/assets/ || echo "(读取失败)"

echo ""
echo "--- 本地 dist 文件及时间 ---"
ls -lh dist/team-a/assets/ || echo "(未找到)"

echo ""
echo "--- Transcript 文件 ---"
ls -lh teams/team-a/.claude/sessions/ || echo "(未找到)"

echo ""
echo "========== 完成 =========="
