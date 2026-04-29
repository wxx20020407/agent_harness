#!/usr/bin/env python3
"""
文档转换工具 - 支持图片描述增强版

特性：
1. 支持两种图片描述方案：
   - mimo-v2-omni: 使用小米多模态模型（推荐）
   - docling_builtin: 使用 Docling 内置的 SmolVLM 模型
2. 自动回退：mimo 失败时回退到 docling 内置方案
3. 输出增强的 Markdown，图片占位符替换为描述文本

用法：
  python doc2md_with_image_desc.py input.pdf
  python doc2md_with_image_desc.py input.pdf --method mimo
  python doc2md_with_image_desc.py input.pdf --method docling_builtin
  python doc2md_with_image_desc.py input.pdf --method auto  # 先尝试 mimo，失败回退

环境变量：
  MIFY_API_KEY - mimo API 密钥
  MIMO_API_URL - mimo API 地址（默认 http://model.mify.ai.srv/v1/chat/completions）
  DOCLING_MODEL_PATH - Docling 模型路径
"""

import argparse
import base64
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Optional

import urllib.request
import urllib.error

# Docling 相关导入
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.document import PictureItem

# =====================================================================
# 配置
# =====================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Doc2MdImageDesc")

# 默认配置
DEFAULT_MIMO_API_URL = os.environ.get('MIMO_API_URL', 'http://model.mify.ai.srv/v1/chat/completions')
# API Key 优先级: MIFY_API_KEY > LLM_API_KEY (从 .env 读取)
DEFAULT_MIMO_API_KEY = os.environ.get('MIFY_API_KEY') or os.environ.get('LLM_API_KEY', '')
DEFAULT_MIMO_MODEL = "xiaomi/mimo-v2-omni"
DEFAULT_DOCLING_MODEL_PATH = os.environ.get('DOCLING_MODEL_PATH', '/data/docling_models')

# 尝试从 .env 文件加载配置
def load_env_file():
    """从 .env 文件加载环境变量"""
    env_paths = [
        '/data/agent_harness/.env',
        '/data/.env',
        os.path.expanduser('~/.env'),
    ]
    for env_path in env_paths:
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        # 只设置未定义的环境变量
                        if key not in os.environ:
                            os.environ[key] = value

# 启动时加载 .env
load_env_file()
# 重新读取可能从 .env 加载的 API Key
if not DEFAULT_MIMO_API_KEY:
    DEFAULT_MIMO_API_KEY = os.environ.get('MIFY_API_KEY') or os.environ.get('LLM_API_KEY', '')

# 图片描述提示词
MIMO_PROMPT = """请用中文简要描述这张图片的内容。
如果是图表（如柱状图、折线图、饼图等），请说明：
1. 图表类型
2. 主要数据或趋势
3. 关键信息点
如果是流程图或示意图，请描述其结构和主要流程。
请用简洁的语言，不超过 200 字。"""

DOCLING_PROMPT = "Describe this image in a few sentences."


class DescriptionMethod(Enum):
    """图片描述方法"""
    MIMO = "mimo"              # 使用 mimo-v2-omni
    DOCLING_BUILTIN = "docling_builtin"  # 使用 Docling 内置
    AUTO = "auto"              # 自动选择（优先 mimo，失败回退）
    NONE = "none"              # 不描述，只提取图片


@dataclass
class PictureInfo:
    """图片信息"""
    index: int
    label: str
    page: Optional[int]
    bbox: Optional[tuple]
    base64_data: str
    mime_type: str
    size_kb: float
    description: Optional[str] = None
    description_method: Optional[str] = None
    description_error: Optional[str] = None


@dataclass
class ConversionResult:
    """转换结果"""
    markdown: str
    pictures: list = field(default_factory=list)
    method_used: Optional[str] = None
    fallback_used: bool = False
    processing_time: float = 0.0


# =====================================================================
# Mimo VLM 调用
# =====================================================================
def describe_image_with_mimo(
    base64_image: str,
    mime_type: str = "image/png",
    api_url: str = DEFAULT_MIMO_API_URL,
    api_key: str = DEFAULT_MIMO_API_KEY,
    model: str = DEFAULT_MIMO_MODEL,
    prompt: str = MIMO_PROMPT,
    timeout: int = 30
) -> tuple[bool, str]:
    """
    调用 mimo-v2-omni 描述图片

    Returns:
        (success, description_or_error)
    """
    if not api_key:
        return False, "MIFY_API_KEY 未设置"

    # 构造 data URI
    data_uri = f"data:{mime_type};base64,{base64_image}"

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are MiMo, an AI assistant developed by Xiaomi. Describe images concisely and accurately in Chinese."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri}
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }
        ],
        "max_completion_tokens": 256
    }

    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            message = result["choices"][0]["message"]
            # mimo-v2-omni 是推理模型，内容可能在 reasoning_content 或 content 中
            description = message.get("content") or message.get("reasoning_content") or ""
            if description:
                return True, description
            else:
                return False, "API 返回空内容"
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        return False, f"HTTP {e.code}: {error_body[:200]}"
    except urllib.error.URLError as e:
        return False, f"连接错误: {e.reason}"
    except Exception as e:
        return False, str(e)


# =====================================================================
# Docling 内置图片描述
# =====================================================================
def describe_images_with_docling_builtin(
    pdf_path: str,
    model_path: str = DEFAULT_DOCLING_MODEL_PATH,
    prompt: str = DOCLING_PROMPT
) -> tuple[bool, list[PictureInfo] | str]:
    """
    使用 Docling 内置的 SmolVLM 模型描述图片

    注意：需要先下载 SmolVLM 模型到 model_path

    Returns:
        (success, pictures_or_error)
    """
    try:
        # 检查模型是否存在
        smolvlm_path = Path(model_path) / "HuggingFaceTB--SmolVLM-256M-Instruct"
        if not smolvlm_path.exists():
            return False, f"SmolVLM 模型不存在: {smolvlm_path}\n请运行: docling-tools models download-hf-repo HuggingFaceTB/SmolVLM-256M-Instruct"

        pipeline_options = PdfPipelineOptions()
        pipeline_options.artifacts_path = model_path
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

        # 启用图片描述
        pipeline_options.do_picture_description = True
        pipeline_options.generate_picture_images = True

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

        result = converter.convert(pdf_path)
        doc = result.document

        pictures = []
        for item, level in doc.iterate_items():
            if isinstance(item, PictureItem) and item.image:
                # 提取图片数据
                uri = str(item.image.uri)
                if uri.startswith('data:'):
                    header, base64_data = uri.split(',', 1)
                    mime_type = header.split(':')[1].split(';')[0]

                    pic = PictureInfo(
                        index=len(pictures),
                        label=str(item.label),
                        page=item.prov[0].page_no if item.prov else None,
                        bbox=(item.prov[0].bbox.l, item.prov[0].bbox.t,
                              item.prov[0].bbox.r, item.prov[0].bbox.b) if item.prov else None,
                        base64_data=base64_data,
                        mime_type=mime_type,
                        size_kb=len(base64.b64decode(base64_data)) / 1024
                    )

                    # 获取描述（在 meta 或 annotations 中）
                    if item.meta:
                        # 尝试从 meta 获取描述
                        if hasattr(item.meta, 'description'):
                            pic.description = item.meta.description
                            pic.description_method = "docling_builtin"

                    pictures.append(pic)

        return True, pictures

    except Exception as e:
        return False, f"Docling 内置描述失败: {e}"


# =====================================================================
# 主转换流程
# =====================================================================
def convert_with_image_description(
    pdf_path: str,
    method: DescriptionMethod = DescriptionMethod.AUTO,
    model_path: str = DEFAULT_DOCLING_MODEL_PATH,
    mimo_api_url: str = DEFAULT_MIMO_API_URL,
    mimo_api_key: str = DEFAULT_MIMO_API_KEY,
    verbose: bool = True
) -> ConversionResult:
    """
    转换 PDF 并增强图片描述

    Args:
        pdf_path: PDF 文件路径
        method: 图片描述方法
        model_path: Docling 模型路径
        mimo_api_url: Mimo API 地址
        mimo_api_key: Mimo API 密钥
        verbose: 是否输出详细日志

    Returns:
        ConversionResult
    """
    start_time = time.time()

    if verbose:
        logger.info(f"开始转换: {pdf_path}")
        logger.info(f"图片描述方法: {method.value}")

    # Step 1: 使用 Docling 转换，启用图片提取
    pipeline_options = PdfPipelineOptions()
    pipeline_options.artifacts_path = model_path
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
    pipeline_options.generate_picture_images = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    result = converter.convert(pdf_path)
    doc = result.document

    # Step 2: 提取图片信息
    pictures: list[PictureInfo] = []
    for item, level in doc.iterate_items():
        if isinstance(item, PictureItem) and item.image:
            uri = str(item.image.uri)
            if uri.startswith('data:'):
                header, base64_data = uri.split(',', 1)
                mime_type = header.split(':')[1].split(';')[0]

                pic = PictureInfo(
                    index=len(pictures),
                    label=str(item.label),
                    page=item.prov[0].page_no if item.prov else None,
                    bbox=(item.prov[0].bbox.l, item.prov[0].bbox.t,
                          item.prov[0].bbox.r, item.prov[0].bbox.b) if item.prov else None,
                    base64_data=base64_data,
                    mime_type=mime_type,
                    size_kb=len(base64.b64decode(base64_data)) / 1024
                )
                pictures.append(pic)

    if verbose:
        logger.info(f"找到 {len(pictures)} 个图片")

    # Step 3: 根据方法描述图片
    method_used = None
    fallback_used = False

    if method == DescriptionMethod.NONE:
        # 不描述
        method_used = "none"

    elif method == DescriptionMethod.MIMO:
        # 只使用 mimo
        for pic in pictures:
            success, result_str = describe_image_with_mimo(
                pic.base64_data,
                pic.mime_type,
                mimo_api_url,
                mimo_api_key
            )
            if success:
                pic.description = result_str
                pic.description_method = "mimo"
            else:
                pic.description_error = result_str
        method_used = "mimo"

    elif method == DescriptionMethod.DOCLING_BUILTIN:
        # 只使用 docling 内置
        success, result_data = describe_images_with_docling_builtin(pdf_path, model_path)
        if success:
            # 合并描述结果
            for pic in pictures:
                for described_pic in result_data:
                    if pic.index == described_pic.index:
                        pic.description = described_pic.description
                        pic.description_method = "docling_builtin"
                        break
        else:
            for pic in pictures:
                pic.description_error = str(result_data)
        method_used = "docling_builtin"

    elif method == DescriptionMethod.AUTO:
        # 先尝试 mimo，失败回退到 docling 内置
        mimo_success_count = 0
        mimo_fail_count = 0

        for pic in pictures:
            success, result_str = describe_image_with_mimo(
                pic.base64_data,
                pic.mime_type,
                mimo_api_url,
                mimo_api_key
            )
            if success:
                pic.description = result_str
                pic.description_method = "mimo"
                mimo_success_count += 1
            else:
                pic.description_error = result_str
                mimo_fail_count += 1

        # 如果 mimo 全部失败，尝试回退到 docling 内置
        if mimo_fail_count > 0 and mimo_success_count == 0:
            if verbose:
                logger.warning(f"mimo 全部失败，尝试回退到 docling 内置方案...")

            success, result_data = describe_images_with_docling_builtin(pdf_path, model_path)
            if success:
                for pic in pictures:
                    for described_pic in result_data:
                        if pic.index == described_pic.index:
                            pic.description = described_pic.description
                            pic.description_method = "docling_builtin"
                            pic.description_error = None
                            break
                fallback_used = True
                method_used = "docling_builtin (fallback)"
            else:
                if verbose:
                    logger.error(f"docling 内置方案也失败: {result_data}")
                method_used = "mimo (failed)"
        else:
            method_used = "mimo"
            if mimo_fail_count > 0:
                method_used = f"mimo ({mimo_success_count}/{len(pictures)} success)"

    # Step 4: 生成增强的 Markdown
    md_output = doc.export_to_markdown()

    # 在 Markdown 末尾添加图片描述
    if pictures:
        desc_section = "\n\n---\n\n## 图片描述\n\n"
        for pic in pictures:
            desc_section += f"### 图片 {pic.index + 1}"
            if pic.page:
                desc_section += f" (第 {pic.page} 页)"
            desc_section += "\n\n"

            if pic.description:
                desc_section += f"**描述** ({pic.description_method}): {pic.description}\n\n"
            elif pic.description_error:
                desc_section += f"**描述失败**: {pic.description_error}\n\n"
            else:
                desc_section += "*未生成描述*\n\n"

        md_output += desc_section

    processing_time = time.time() - start_time

    if verbose:
        logger.info(f"转换完成，耗时 {processing_time:.2f}s")
        logger.info(f"使用方法: {method_used}")

    return ConversionResult(
        markdown=md_output,
        pictures=pictures,
        method_used=method_used,
        fallback_used=fallback_used,
        processing_time=processing_time
    )


# =====================================================================
# CLI 入口
# =====================================================================
def main():
    parser = argparse.ArgumentParser(
        description='文档转 Markdown（支持图片描述）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s input.pdf                    # 自动选择方法
  %(prog)s input.pdf --method mimo      # 使用 mimo-v2-omni
  %(prog)s input.pdf --method docling_builtin  # 使用 Docling 内置
  %(prog)s input.pdf --method none      # 不描述图片
  %(prog)s input.pdf -o output.md       # 输出到文件
        """
    )

    parser.add_argument('input', help='输入 PDF 文件')
    parser.add_argument('-o', '--output', help='输出 Markdown 文件（默认输出到 stdout）')
    parser.add_argument(
        '--method',
        choices=[m.value for m in DescriptionMethod],
        default='auto',
        help='图片描述方法（默认 auto）'
    )
    parser.add_argument('--model-path', default=DEFAULT_DOCLING_MODEL_PATH, help='Docling 模型路径')
    parser.add_argument('--mimo-url', default=DEFAULT_MIMO_API_URL, help='Mimo API 地址')
    parser.add_argument('--mimo-key', default=DEFAULT_MIMO_API_KEY, help='Mimo API 密钥')
    parser.add_argument('-q', '--quiet', action='store_true', help='安静模式')

    args = parser.parse_args()

    # 检查输入文件
    if not os.path.exists(args.input):
        print(f"错误: 文件不存在: {args.input}", file=sys.stderr)
        sys.exit(1)

    # 执行转换
    result = convert_with_image_description(
        pdf_path=args.input,
        method=DescriptionMethod(args.method),
        model_path=args.model_path,
        mimo_api_url=args.mimo_url,
        mimo_api_key=args.mimo_key,
        verbose=not args.quiet
    )

    # 输出结果
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result.markdown)
        if not args.quiet:
            print(f"[ok] {args.input} -> {args.output}")
            print(f"     方法: {result.method_used}, 图片: {len(result.pictures)}, 耗时: {result.processing_time:.2f}s")
    else:
        print(result.markdown)


if __name__ == '__main__':
    main()