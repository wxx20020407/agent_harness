#!/bin/bash
set -e

# 提示用户输入用户名
read -p "请输入您的用户名: " USERNAME

# 检查用户名是否为空
if [ -z "$USERNAME" ]; then
  echo "用户名不能为空！"
  exit 1
else
  echo "用户名为 ${USERNAME}"
fi

# 检查hostname
if ! command -v hostname &> /dev/null; then
  ServerType="NA"
else
  ServerType="XIAOMI_USER"
  # 获取服务器IP
  ServerIP=$(hostname -i 2>/dev/null | awk '{print $1}')
  echo "IP: ${ServerIP}"
  if [[ "$ServerIP" =~ ^10\.227 ]]; then
    ServerType="XR_USER"
  fi
fi

# 模板文件路径
XRBASE="${HOME}/.xrscm"
if [[ "${ServerType}" == "XR_USER" ]]; then
  GITTEMPLATE_FILE="http://gerrit.x-ringtek1.com/static/template/default_ugitconfig_xr.template"
else
  GITTEMPLATE_FILE="http://gerrit.x-ringtek1.com/static/template/default_ugitconfig.template"
fi
LOCAL_GITTEMPLATE="${XRBASE}/template/default_ugitconfig.template"
timestamp=$(date +"%Y-%m-%dT%H:%M:%SZ")

# 目标 Git 配置文件
GITCONFIG_FILE="$HOME/.gitconfig"

echo "=== 1. 获取玄戒GITCONFIG模板 ==="
if [ ! -f "${LOCAL_GITTEMPLATE}" ]; then
  echo "本地玄戒模板文件 ${LOCAL_GITTEMPLATE} 不存在！"
  echo "下载玄戒模板"
  mkdir -p $(dirname ${LOCAL_GITTEMPLATE})
  curl "${GITTEMPLATE_FILE}" -o ${LOCAL_GITTEMPLATE}
else
  echo "本地模板文件 ${LOCAL_GITTEMPLATE} 存在，强制更新！"
  curl "${GITTEMPLATE_FILE}" -o ${LOCAL_GITTEMPLATE}
fi

echo "=== 2. 将玄戒GITCONFIG模板配置到环境中 ==="
if [ -f "${GITCONFIG_FILE}" ]; then
  echo "本地模板文件 ${GITCONFIG_FILE} 已存在，将进行更名备份"
  mkdir -p "${XRBASE}/bak"
  mv "${GITCONFIG_FILE}" "${XRBASE}/bak/$(basename ${GITCONFIG_FILE}).${timestamp}"
fi

# 使用 sed 从模板文件创建新的 Git 配置文件
echo "生成本地模板文件 ${GITCONFIG_FILE}"
sed "s/<USERNAME>/${USERNAME}/g" "${LOCAL_GITTEMPLATE}" > "${GITCONFIG_FILE}"

# 输出成功信息
echo "本地GITCONFIG玄戒模板初始化已完成。"
