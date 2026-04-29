# 文档转换 - 图片描述增强版

## 概述

本工具在 Docling 文档转换基础上，增加了图片描述功能，支持两种方案：

1. **mimo-v2-omni**：使用小米多模态模型（推荐）
2. **docling_builtin**：使用 Docling 内置的 SmolVLM 模型

支持自动回退：mimo 失败时自动回退到 docling 内置方案。

## 文件说明

| 文件 | 说明 |
|------|------|
| `/data/agent_harness/tools/doc2md_with_image_desc.py` | 命令行工具 |
| `/data/agent_harness/deploy/docling-server-with-image-desc.py` | HTTP 服务 |

## 使用方法

### 命令行工具

```bash
# 基本用法（自动选择方法）
python /data/agent_harness/tools/doc2md_with_image_desc.py input.pdf -o output.md

# 指定方法
python /data/agent_harness/tools/doc2md_with_image_desc.py input.pdf --method mimo -o output.md
python /data/agent_harness/tools/doc2md_with_image_desc.py input.pdf --method docling_builtin -o output.md
python /data/agent_harness/tools/doc2md_with_image_desc.py input.pdf --method none -o output.md  # 不描述图片

# 方法说明
# - mimo: 使用 mimo-v2-omni（需要 API key）
# - docling_builtin: 使用 Docling 内置（需要下载 SmolVLM 模型）
# - auto: 优先 mimo，失败回退（默认）
# - none: 不描述图片
```

### HTTP 服务

```bash
# 启动服务
python /data/agent_harness/deploy/docling-server-with-image-desc.py

# 或指定端口
DOCLING_PORT=5002 python /data/agent_harness/deploy/docling-server-with-image-desc.py
```

#### API 接口

**1. 按路径转换**

```bash
curl -X POST http://localhost:5001/convert-path \
  -H "Content-Type: application/json" \
  -d '{
    "path": "/path/to/document.pdf",
    "image_desc_method": "auto"
  }'
```

**2. 文件上传转换**

```bash
curl -X POST http://localhost:5001/convert \
  -F "file=@document.pdf"
```

**3. 健康检查**

```bash
curl http://localhost:5001/health
# 返回: {"status": "ok", "mimo_configured": true}
```

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `MIFY_API_KEY` / `LLM_API_KEY` | Mimo API 密钥 | 从 `.env` 读取 |
| `MIMO_API_URL` | Mimo API 地址 | `http://model.mify.ai.srv/v1/chat/completions` |
| `DOCLING_MODEL_PATH` | Docling 模型路径 | `/data/docling_models` |
| `DOCLING_PORT` | 服务端口 | `5001` |

### .env 文件

工具会自动从以下位置加载 `.env` 文件：
- `/data/agent_harness/.env`
- `/data/.env`

## 输出格式

转换后的 Markdown 会在末尾添加图片描述部分：

```markdown
## 正文内容...

<!-- image -->

---

## 图片描述

### 图片 1 (第 2 页)

**描述** (mimo): 这是一张存储阵列示意图，展示了 32x32 的网格结构...

### 图片 2 (第 5 页)

**描述** (mimo): 这是一个流程图，展示了数据处理的主要流程...
```

## 技术细节

### 方案对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| mimo-v2-omni | 效果好，中文支持强 | 需要 API 调用 |
| docling_builtin | 本地运行，无网络依赖 | 需要下载模型（~256MB） |

### 实现原理

1. **Docling 图片提取**：
   - 启用 `generate_picture_images=True`
   - 图片以 base64 Data URI 存储在 `PictureItem.image.uri`
   - 位置信息在 `PictureItem.prov`（页码、边界框）

2. **mimo-v2-omni 调用**：
   - 使用 OpenAI 兼容 API
   - 图片通过 `image_url` 类型传递
   - 推理结果在 `reasoning_content` 字段

3. **回退逻辑**：
   - 当 mimo 所有图片都失败时，尝试 docling 内置方案
   - 如果 docling 内置模型不存在，跳过图片描述

## 依赖

- `docling`：文档转换核心
- `fastapi` + `uvicorn`：HTTP 服务
- Python 标准库：`urllib.request`（API 调用）