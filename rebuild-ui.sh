#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "========== 1. 构建前端 =========="
cd src/ui
/home/xring/node-v24.11.0-linux-x64/bin/node node_modules/.bin/vite build
cd ../..

echo "========== 2. 复制产物到 dist =========="
rm -rf dist/team-a/assets/*
cp -r src/dist/team-a/* dist/team-a/

echo "--- dist 文件及时间 ---"
ls -lh dist/team-a/assets/

echo "========== 3. 重建并重启服务 =========="
./rebuild.sh
