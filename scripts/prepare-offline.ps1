# =============================================================================
# 离线部署准备脚本（Windows，无需 Docker）
# 在有网机器上运行，准备所有离线部署所需的文件
#
# 运行方式（在项目根目录）：
#   powershell -ExecutionPolicy Bypass -File scripts\prepare-offline.ps1
#
# 需要：Node.js 18+，npm，curl（Git for Windows 自带）
# =============================================================================

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

Write-Host ""
Write-Host "=== Agent Harness 离线部署准备 ===" -ForegroundColor Cyan
Write-Host "项目根目录: $ProjectRoot"
Write-Host ""

# ─── Step 1: npm install API 依赖 ────────────────────────────────────────────
Write-Host "[1/4] npm install API 依赖..." -ForegroundColor Yellow
Set-Location "$ProjectRoot\src\api"
npm install --omit=dev
if ($LASTEXITCODE -ne 0) { throw "API npm install 失败" }
Write-Host "      ✓ src/api/node_modules 安装完成" -ForegroundColor Green

# ─── Step 2: npm install UI 依赖 + 构建每个团队 ──────────────────────────────
Write-Host ""
Write-Host "[2/4] npm install UI 依赖..." -ForegroundColor Yellow
Set-Location "$ProjectRoot\src\ui"
npm install
if ($LASTEXITCODE -ne 0) { throw "UI npm install 失败" }
Write-Host "      ✓ src/ui/node_modules 安装完成" -ForegroundColor Green

# 构建每个团队的 UI 产物到 dist/<team-id>/
# 新增团队时在此处追加
$Teams = @(
    @{ Id = "team-a"; Name = "Team A Agent" }
    # @{ Id = "team-b"; Name = "Team B Agent" }
    # @{ Id = "team-c"; Name = "Team C Agent" }
)

foreach ($team in $Teams) {
    Write-Host ""
    Write-Host "      构建 UI: $($team.Name) -> dist/$($team.Id)/" -ForegroundColor Yellow
    $env:VITE_TEAM_NAME = $team.Name
    $env:VITE_API_URL   = "/api"
    npm run build -- --outDir "$ProjectRoot\dist\$($team.Id)"
    if ($LASTEXITCODE -ne 0) { throw "UI 构建失败: $($team.Id)" }
    Write-Host "      ✓ dist/$($team.Id)/ 构建完成" -ForegroundColor Green
}

Set-Location $ProjectRoot

# ─── Step 3: 下载 crane（拉取 Docker 镜像无需 Docker daemon）─────────────────
Write-Host ""
Write-Host "[3/4] 下载 crane 工具..." -ForegroundColor Yellow

$CraneDir  = "$ProjectRoot\.crane-tmp"
$CraneExe  = "$CraneDir\crane.exe"
New-Item -ItemType Directory -Force -Path $CraneDir | Out-Null

if (-not (Test-Path $CraneExe)) {
    # 获取最新版本号（用 curl.exe 避免 PowerShell 的 curl 别名问题）
    Write-Host "      获取最新版本..."
    try {
        $LatestJson = & curl.exe -fsSL "https://api.github.com/repos/google/go-containerregistry/releases/latest"
        $Version = ($LatestJson | ConvertFrom-Json).tag_name
    } catch { $Version = $null }

    if (-not $Version) {
        $Version = "v0.20.2"   # fallback 到已知稳定版
        Write-Host "      无法获取最新版，使用 $Version" -ForegroundColor DarkYellow
    } else {
        Write-Host "      最新版: $Version"
    }

    # v0.21+ 包名从 crane_* 改为 go-containerregistry_*，内含 crane.exe
    $TarUrl = "https://github.com/google/go-containerregistry/releases/download/$Version/go-containerregistry_Windows_x86_64.tar.gz"
    Write-Host "      下载: $TarUrl"
    & curl.exe -fSL -o "$CraneDir\crane.tar.gz" $TarUrl
    if ($LASTEXITCODE -ne 0) { throw "下载 crane 失败，URL: $TarUrl" }

    # 用 Windows System32 的 tar.exe 解压（绕过 Git Bash 的 /usr/bin/tar）
    $winTar = Join-Path $env:SystemRoot "System32\tar.exe"
    & $winTar xf "$CraneDir\crane.tar.gz" -C "$CraneDir"
    if (-not (Test-Path $CraneExe)) { throw "解压后未找到 crane.exe，请检查 $CraneDir" }
    Write-Host "      ✓ crane.exe 准备完成" -ForegroundColor Green
} else {
    Write-Host "      ✓ crane.exe 已存在，跳过下载" -ForegroundColor Green
}

# ─── Step 4: 拉取 Docker 基础镜像 ────────────────────────────────────────────
Write-Host ""
Write-Host "[4/4] 拉取 Docker 镜像（crane pull）..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "$ProjectRoot\images" | Out-Null

# --format tarball：生成 docker-load 兼容格式（Docker Image Spec，而非 OCI Layout）

# node:18-alpine（API 运行时）
Write-Host "      拉取 node:18-alpine..."
& $CraneExe pull --format tarball node:18-alpine "$ProjectRoot\images\node18-alpine.tar"
if ($LASTEXITCODE -ne 0) { throw "拉取 node:18-alpine 失败" }
Write-Host "      ✓ images/node18-alpine.tar" -ForegroundColor Green

# nginx:alpine（UI 静态托管）
Write-Host "      拉取 nginx:alpine..."
& $CraneExe pull --format tarball nginx:alpine "$ProjectRoot\images\nginx-alpine.tar"
if ($LASTEXITCODE -ne 0) { throw "拉取 nginx:alpine 失败" }
Write-Host "      ✓ images/nginx-alpine.tar" -ForegroundColor Green

# ── opencode 镜像 ──────────────────────────────────────────────────────────────
# 如果你的 opencode 镜像还没有保存为 tar，取消下面注释并填入实际镜像引用
# （crane 可以直接从 ghcr.io 拉取）
#
# $OpenCodeRef = "ghcr.io/sst/opencode:latest"
# Write-Host "      拉取 opencode..."
# & $CraneExe pull --format tarball $OpenCodeRef "$ProjectRoot\images\opencode.tar"
# Write-Host "      ✓ images/opencode.tar" -ForegroundColor Green
#
# 如果你已经有 opencode.tar 文件，直接把它放到 images/ 目录即可

# 清理临时文件
Remove-Item -Recurse -Force $CraneDir

# ─── 完成 ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== 准备完成！===" -ForegroundColor Cyan
Write-Host ""
Write-Host "下一步：将以下文件/目录打包传输到离线机器（保持目录结构）" -ForegroundColor White
Write-Host ""
Write-Host "  必须传输："
Write-Host "    images/              ← Docker 基础镜像（node, nginx）"
Write-Host "    dist/                ← 各团队 UI 预构建产物"
Write-Host "    src/api/node_modules ← API 依赖"
Write-Host "    src/api/server.js"
Write-Host "    src/api/package.json"
Write-Host "    src/ui/              ← 源码（Dockerfile 需要）"
Write-Host "    teams/               ← 团队配置"
Write-Host "    deploy/              ← Dockerfile 等"
Write-Host "    docker-compose.yml"
Write-Host "    .env.example"
Write-Host ""
Write-Host "  不要忘记：将 opencode 镜像也放到 images/ 目录！" -ForegroundColor Yellow
Write-Host "    文件名建议：images/opencode.tar"
Write-Host ""
Write-Host "  在离线机器上运行："
Write-Host "    bash deploy/load-images.sh ./images"
Write-Host "    cp .env.example .env  # 填写配置"
Write-Host "    docker compose build"
Write-Host "    docker compose up -d"
Write-Host ""
