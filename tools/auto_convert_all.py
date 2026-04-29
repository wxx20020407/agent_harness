#!/usr/bin/env python3
"""
检查 Docling 服务是否在线，并等待其完成启动扫描。

Docling 服务现在会自动扫描并转换文档，Agent 不再负责转换。

用法: python3 auto_convert_all.py
"""

import json
import os
import sys
import time
from urllib.request import Request, urlopen
from urllib.error import URLError

DOCLING_URL = os.environ.get('DOCLING_URL', 'http://docling:5000')


def wait_for_docling(timeout=300):
    """等待 docling 服务就绪

    Docling 服务会在启动时自动扫描转换文档，
    这里只等待服务上线即可。
    """
    print(f'[docling-check] 等待 Docling 服务 ({DOCLING_URL}) ...')
    start = time.time()
    while time.time() - start < timeout:
        try:
            req = Request(f'{DOCLING_URL}/health')
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                if data.get('status') == 'ok':
                    print('[docling-check] ✅ Docling 服务已就绪')
                    print(f'[docling-check]    - mimo_configured: {data.get("mimo_configured")}')
                    print(f'[docling-check]    - default_method: {data.get("default_method")}')
                    return True
        except Exception as e:
            pass
        time.sleep(3)
    print('[docling-check] ⚠️ Docling 服务未就绪，继续启动...')
    return False


def main():
    """主函数：只检查 Docling 服务状态"""
    import argparse

    parser = argparse.ArgumentParser(description='Check Docling service status')
    parser.add_argument('--timeout', '-t', type=int, default=300,
                        help='Timeout in seconds (default: 300)')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Quiet mode, only exit code')

    args = parser.parse_args()

    if args.quiet:
        # 静默模式，只返回退出码
        try:
            req = Request(f'{DOCLING_URL}/health')
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                if data.get('status') == 'ok':
                    sys.exit(0)
        except:
            pass
        sys.exit(1)

    # 正常模式：等待服务就绪
    success = wait_for_docling(args.timeout)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
