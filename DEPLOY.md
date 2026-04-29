# Agent Harness 部署说明

## 一、环境要求

- Docker & Docker Compose
- Python 3.10+ (用于 Docling 服务)
- 约 20GB 磁盘空间 (模型文件)

## 二、目录结构

```
/data/agent_harness/
├── deploy/                    # 部署脚本
│   ├── start-docling-host.sh  # Docling 服务启动脚本
│   └── docling-server-with-image-desc.py
├── teams/team-a/              # 工作空间
│   ├── kb/                    # 知识库 (PDF/Word → 自动转 .md)
│   └── skills/                # 技能文档
├── models/huggingface/        # 模型缓存 (首次运行自动下载)
├── docker-compose.yml
├── .env                       # 环境变量配置
└── requirements-docling.txt   # Python 依赖
```

## 三、配置步骤

### 1. 配置环境变量

创建 `.env` 文件：

```bash
# LLM 配置 (必填)
LLM_BASE_URL=https://your-llm-api-url/v1
LLM_API_KEY=your-api-key

# 团队密码 (可选)
TEAM_A_PASSWORD=your-password

# 图片描述配置 (可选)
MIFY_API_KEY=your-mify-api-key          # mimo API key
DEFAULT_IMAGE_DESC_METHOD=mimo          # smolvlm / mimo / auto
```

### 2. 准备模型文件

Docling 模型 (首次启动自动下载，或手动放置):

```
/data/docling_models/           # Docling 模型目录
/data/agent_harness/models/huggingface/hub/   # SmolVLM 模型
```

### 3. 启动服务

```bash
cd /data/agent_harness

# 启动 Docling 服务 (宿主机)
./deploy/start-docling-host.sh start

# 启动 Docker 容器
docker compose up -d
```

## 四、服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| 前端 UI | 4301 | http://host:4301 |
| API | 4201 | http://host:4201 |
| OpenCode Agent | 4101 | http://host:4101 |
| Docling 转换 | 5001 | http://host:5001 |

## 五、常用命令

```bash
# Docling 服务
./deploy/start-docling-host.sh start    # 启动
./deploy/start-docling-host.sh stop     # 停止
./deploy/start-docling-host.sh status   # 状态
./deploy/start-docling-host.sh logs     # 日志

# Docker 服务
docker compose up -d                     # 启动
docker compose down                      # 停止
docker compose logs -f api-team-a        # 查看日志
docker compose restart api-team-a        # 重启服务
```

## 六、文档转换说明

**三种触发方式：**

1. **Docker 启动时** - 自动扫描 kb/skills 目录转换新文件
2. **Watchdog 监控** - 每 5 秒轮询，自动转换新增文件
3. **手动触发** - 前端页面点击刷新按钮

**三种图片描述方案：**

| 方案 | 说明 | 配置 |
|------|------|------|
| smolvlm | 本地模型，需 GPU | DEFAULT_IMAGE_DESC_METHOD=smolvlm |
| mimo | 调用 Mify API | DEFAULT_IMAGE_DESC_METHOD=mimo |
| auto | mimo 优先，失败降级到 smolvlm | DEFAULT_IMAGE_DESC_METHOD=auto |

## 七、离线部署

### 镜像文件 (images/ 目录)

**必需镜像：**

| 文件 | 大小 | 用途 |
|------|------|------|
| opencode.tar | 62M | OpenCode Agent 运行时 |
| node18-alpine.tar | 43M | API 服务基础镜像 |
| nginx-alpine.tar | 25M | 前端 UI 镜像 |
| python311-slim.tar | 44M | init-convert 容器镜像 |

**可选镜像：**

| 文件 | 大小 | 用途 |
|------|------|------|
| docling-offline-image.zip | 4.3G | Docker 模式运行 Docling (默认宿主机模式，不需要) |

**冗余文件：**

| 文件 | 说明 |
|------|------|
| python-base-image.zip | 与 python311-slim.tar 重复，可删除 |

### 导入镜像

```bash
cd /data/agent_harness
bash deploy/load-images.sh ./images
```

### 模型文件

| 目录 | 说明 |
|------|------|
| /data/docling_models/ | Docling 模型 (布局、OCR、公式识别等) |
| models/huggingface/hub/ | SmolVLM 图片描述模型 |

### 手动导入镜像 (备用)

```bash
docker load -i images/opencode.tar
docker load -i images/node18-alpine.tar
docker load -i images/nginx-alpine.tar
docker load -i images/python311-slim.tar
```
