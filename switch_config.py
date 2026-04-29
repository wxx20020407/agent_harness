#!/usr/bin/env python3
"""
一键切换 LLM 配置（base_url / api_key / model）

用法:
  python3 switch_config.py --model tongyi/kimi-k2.5
  python3 switch_config.py --base-url http://new-api.com/v1 --api-key sk-xxx
  python3 switch_config.py --model zhipuai/glm-5 --base-url http://model.mify.ai.srv/v1 --api-key sk-xxx

参数格式:
  --model provider/modelname  例如 tongyi/kimi-k2.5, zhipuai/glm-5
  --base-url URL              LLM API 地址
  --api-key KEY               API 密钥

会同时修改三个文件:
  1. .env              (LLM_BASE_URL, LLM_API_KEY)
  2. docker-compose.yml (OPENCODE_CONFIG_CONTENT)
  3. teams/team-a/opencode.json
"""

import argparse
import json
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, '.env')
COMPOSE_FILE = os.path.join(SCRIPT_DIR, 'docker-compose.yml')
OPENCODE_JSON = os.path.join(SCRIPT_DIR, 'teams', 'team-a', 'opencode.json')


def read_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write_file(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def update_env(base_url, api_key):
    """更新 .env 文件中的 LLM_BASE_URL 和 LLM_API_KEY"""
    content = read_file(ENV_FILE)
    if base_url:
        content = re.sub(r'^LLM_BASE_URL=.*$', f'LLM_BASE_URL={base_url}', content, flags=re.MULTILINE)
    if api_key:
        content = re.sub(r'^LLM_API_KEY=.*$', f'LLM_API_KEY={api_key}', content, flags=re.MULTILINE)
    write_file(ENV_FILE, content)
    print(f'[ok] .env 已更新')


def update_compose(model):
    """更新 docker-compose.yml 中的 OPENCODE_CONFIG_CONTENT"""
    if not model:
        return

    content = read_file(COMPOSE_FILE)

    # 提取当前的 OPENCODE_CONFIG_CONTENT JSON
    match = re.search(r"OPENCODE_CONFIG_CONTENT=(\{.*?\})'", content)
    if not match:
        print('[warn] docker-compose.yml 中未找到 OPENCODE_CONFIG_CONTENT')
        return

    try:
        config = json.loads(match.group(1))
    except json.JSONDecodeError:
        print('[warn] OPENCODE_CONFIG_CONTENT JSON 解析失败')
        return

    # provider/modelname -> provider 部分和 model 部分
    # model 格式: "internal-llm/provider/modelname"
    model_full = f'internal-llm/{model}'
    # model name 是最后一个 / 后面的部分用于显示
    model_display = model.split('/')[-1] if '/' in model else model

    config['model'] = model_full
    # 更新 models 字典
    config['provider']['internal-llm']['models'] = {
        model: {'name': model_display}
    }

    new_json = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
    new_line = f"OPENCODE_CONFIG_CONTENT={new_json}'"

    content = re.sub(
        r"OPENCODE_CONFIG_CONTENT=\{.*?\}'",
        new_line,
        content
    )
    write_file(COMPOSE_FILE, content)
    print(f'[ok] docker-compose.yml 已更新')


def update_opencode_json(model, base_url):
    """更新 opencode.json"""
    content = read_file(OPENCODE_JSON)
    config = json.loads(content)

    if model:
        model_full = f'internal-llm/{model}'
        model_display = model.split('/')[-1] if '/' in model else model

        config['model'] = model_full
        config['provider']['internal-llm']['models'] = {
            model: {'name': model_display}
        }

    if base_url:
        config['provider']['internal-llm']['options']['baseURL'] = base_url

    write_file(OPENCODE_JSON, json.dumps(config, indent=2, ensure_ascii=False) + '\n')
    print(f'[ok] opencode.json 已更新')


def main():
    parser = argparse.ArgumentParser(description='切换 LLM 配置')
    parser.add_argument('--model', help='模型名，格式: provider/modelname (如 tongyi/kimi-k2.5)')
    parser.add_argument('--base-url', help='LLM API 地址')
    parser.add_argument('--api-key', help='API 密钥')
    args = parser.parse_args()

    if not args.model and not args.base_url and not args.api_key:
        parser.print_help()
        print('\n当前配置:')
        # 显示当前配置
        env = read_file(ENV_FILE)
        for line in env.strip().split('\n'):
            if line.startswith('LLM_'):
                key, val = line.split('=', 1)
                if 'KEY' in key:
                    print(f'  {key}={val[:8]}...{val[-4:]}')
                else:
                    print(f'  {key}={val}')
        oc = json.loads(read_file(OPENCODE_JSON))
        print(f'  model={oc["model"]}')
        sys.exit(0)

    print(f'--- 切换配置 ---')
    if args.model:
        print(f'  模型: internal-llm/{args.model}')
    if args.base_url:
        print(f'  Base URL: {args.base_url}')
    if args.api_key:
        print(f'  API Key: {args.api_key[:8]}...')
    print()

    if args.base_url or args.api_key:
        update_env(args.base_url, args.api_key)

    if args.model:
        update_compose(args.model)

    update_opencode_json(args.model, args.base_url)

    print()
    print('配置已更新，运行 ./rebuild.sh 使其生效')


if __name__ == '__main__':
    main()
