#!/bin/bash
# 宿主机运行 Docling 服务脚本
# 用法: ./deploy/start-docling-host.sh [start|stop|status|logs]

set -e
cd /data/agent_harness

VENV_DIR="venv-docling"
PID_FILE="logs/docling.pid"
LOG_FILE="logs/docling.log"
PORT=5001

start() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "Docling already running (PID: $(cat $PID_FILE))"
        return 1
    fi

    echo "Starting docling server on port $PORT..."

    # 创建虚拟环境（如果不存在）
    if [ ! -d "$VENV_DIR" ]; then
        echo "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
        source "$VENV_DIR/bin/activate"
        echo "Installing dependencies (this may take a few minutes)..."
        pip install docling flask fastapi uvicorn -i https://pypi.tuna.tsinghua.edu.cn/simple
    else
        source "$VENV_DIR/bin/activate"
    fi

    # 检查模型路径
    if [ ! -d "/data/docling_models" ]; then
        echo "❌ 模型目录不存在: /data/docling_models"
        echo "请先执行: mv /data/docling/models /data/docling_models"
        return 1
    fi

    # 确保日志目录存在
    mkdir -p logs

    # 启动服务（带图片描述增强版）
    nohup python deploy/docling-server-with-image-desc.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    sleep 3
    if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "✅ Docling started successfully (PID: $(cat $PID_FILE))"
        echo "   Port: $PORT"
        echo "   Logs: $LOG_FILE"
        echo "   Health check: curl http://localhost:$PORT/health"
    else
        echo "❌ Failed to start docling. Check logs: $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

stop() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping docling (PID: $PID)..."

            # First try SIGTERM (graceful shutdown)
            kill "$PID" 2>/dev/null

            # Wait up to 10 seconds for process to exit
            for i in {1..10}; do
                if ! kill -0 "$PID" 2>/dev/null; then
                    echo "✅ Stopped gracefully."
                    rm -f "$PID_FILE"
                    return 0
                fi
                sleep 1
                echo "  Waiting... ($i/10)"
            done

            # If still running, force kill
            if kill -0 "$PID" 2>/dev/null; then
                echo "⚠️  Process still running, force killing..."
                kill -9 "$PID" 2>/dev/null
                sleep 1
                if ! kill -0 "$PID" 2>/dev/null; then
                    echo "✅ Force stopped."
                else
                    echo "❌ Failed to stop process $PID"
                    return 1
                fi
            fi
            rm -f "$PID_FILE"
        else
            echo "Docling not running (stale PID file)"
            rm -f "$PID_FILE"
        fi
    else
        echo "No PID file found. Checking for orphaned processes..."
        # Try to find and kill orphaned python processes running docling server
        ORPHAN_PID=$(pgrep -f "docling-server" 2>/dev/null | head -1)
        if [ -n "$ORPHAN_PID" ]; then
            echo "Found orphaned process (PID: $ORPHAN_PID), killing..."
            kill -9 "$ORPHAN_PID" 2>/dev/null && echo "✅ Killed orphaned process"
        else
            echo "No docling process found."
        fi
    fi
}

status() {
    if [ -f "$PID_FILE" ] && kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "Docling running (PID: $(cat $PID_FILE), port: $PORT)"
        curl -s http://localhost:$PORT/health && echo "" || echo "Health check failed"
    else
        echo "Docling not running"
    fi
}

logs() {
    tail -f "$LOG_FILE"
}

case "${1:-start}" in
    start)  start ;;
    stop)   stop ;;
    status) status ;;
    logs)   logs ;;
    restart) stop; sleep 1; start ;;
    *)      echo "Usage: $0 {start|stop|status|logs|restart}" ;;
esac