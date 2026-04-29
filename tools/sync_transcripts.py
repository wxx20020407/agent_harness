#!/usr/bin/env python3
"""
将 data/messages/*.json 转换为 .claude/sessions/*.jsonl 格式

Layer 3 (Transcript) 记忆系统：
- 路径: .claude/sessions/*.jsonl
- 格式: JSONL（每行一条消息）
- 用途: 原始对话日志归档，只写不读，通过 grep 精确检索
"""

import os
import json
from pathlib import Path
from datetime import datetime
from uuid import uuid4


def convert_json_to_jsonl(input_path: Path, output_path: Path) -> int:
    """
    将 JSON 格式的消息文件转换为 JSONL 格式

    Args:
        input_path: 输入的 JSON 文件路径 (data/messages/{sessionId}.json)
        output_path: 输出的 JSONL 文件路径 (.claude/sessions/{sessionId}.jsonl)

    Returns:
        转换的消息数量
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    messages = data.get('messages', [])
    count = 0

    with open(output_path, 'w', encoding='utf-8') as f:
        for msg in messages:
            # 构建 JSONL 格式的记录
            entry = {
                'uuid': msg.get('id', str(uuid4())),
                'role': msg.get('role', 'unknown'),
                'content': msg.get('content', ''),
                'timestamp': msg.get('timestamp') or datetime.now().isoformat(),
                'session_id': input_path.stem,  # 使用文件名作为 session_id
                'tool_uses': msg.get('tool_uses', []),
                'tool_results': msg.get('tool_results', []),
            }

            # 添加 thinking 相关字段
            if msg.get('thinking'):
                entry['thinking'] = msg.get('thinking')
            if msg.get('thinkingContent'):
                entry['thinking_content'] = msg.get('thinkingContent')

            # 添加附件信息
            if msg.get('attachments'):
                entry['attachments'] = msg.get('attachments')

            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            count += 1

    return count


def sync_all_sessions(messages_dir: Path, sessions_dir: Path, team_id: str = None) -> dict:
    """
    同步所有 session 文件

    Args:
        messages_dir: data/messages 目录
        sessions_dir: .claude/sessions 目录
        team_id: 团队 ID（可选，用于日志）

    Returns:
        同步统计信息
    """
    # 确保输出目录存在
    sessions_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        'converted': 0,
        'skipped': 0,
        'errors': 0,
        'total_messages': 0,
    }

    if not messages_dir.exists():
        print(f"[transcript] Messages directory not found: {messages_dir}")
        return stats

    for json_file in messages_dir.glob('*.json'):
        session_id = json_file.stem
        output_file = sessions_dir / f"{session_id}.jsonl"

        # 检查是否需要更新（源文件比目标新）
        if output_file.exists():
            src_mtime = json_file.stat().st_mtime
            dst_mtime = output_file.stat().st_mtime
            if src_mtime <= dst_mtime:
                stats['skipped'] += 1
                continue

        try:
            count = convert_json_to_jsonl(json_file, output_file)
            stats['converted'] += 1
            stats['total_messages'] += count
            print(f"[transcript] Converted {json_file.name} -> {output_file.name} ({count} messages)")
        except Exception as e:
            stats['errors'] += 1
            print(f"[transcript] Error converting {json_file.name}: {e}")

    return stats


def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description='Convert messages to transcript format')
    parser.add_argument('messages_dir', help='Path to data/messages directory')
    parser.add_argument('sessions_dir', help='Path to .claude/sessions directory')
    parser.add_argument('--team-id', help='Team ID for logging')

    args = parser.parse_args()

    messages_dir = Path(args.messages_dir)
    sessions_dir = Path(args.sessions_dir)

    stats = sync_all_sessions(messages_dir, sessions_dir, args.team_id)

    print(f"\n[transcript] Sync complete:")
    print(f"  - Converted: {stats['converted']} files")
    print(f"  - Skipped: {stats['skipped']} files (up to date)")
    print(f"  - Errors: {stats['errors']} files")
    print(f"  - Total messages: {stats['total_messages']}")


if __name__ == '__main__':
    main()
