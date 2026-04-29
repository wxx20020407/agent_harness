"""
Docling Document Conversion Service - Enhanced with Image Description

Features:
- Support two image description methods: mimo-v2-omni and SmolVLM
- Options: smolvlm, mimo, auto (mimo with fallback to smolvlm)
- Context-aware description with surrounding text
- Image descriptions inserted at placeholder positions
- Compatible with Open WebUI API protocol (/v1/convert/file)
- Auto-watch document directories and convert new files

Start:
  python deploy/docling-server-with-image-desc.py

Environment Variables:
  DOCLING_PORT - Server port (default 5001)
  DOCLING_MODEL_PATH - Model path
  MIFY_API_KEY / LLM_API_KEY - Mimo API key
  MIMO_API_URL - Mimo API URL
  DEFAULT_IMAGE_DESC_METHOD - Default image description method (default mimo)
  WATCH_DIRS - Directories to watch, comma-separated (default: /data/agent_harness/teams/team-a/kb,/data/agent_harness/teams/team-a/skills)
  WATCH_ENABLED - Enable file watching (default: true)
"""

import os
import re
import io
import shutil
import tempfile
import logging
import uvicorn
import time
import base64
import json
import urllib.request
import urllib.error
import threading
from enum import Enum
from typing import Optional, List, Tuple
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# Docling
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.datamodel.document import PictureItem, TextItem
from docling_core.types.doc import ImageRefMode

# SmolVLM
import torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForImageTextToText

# =====================================================================
# Configuration
# =====================================================================
MODEL_PATH = os.environ.get("DOCLING_MODEL_PATH", "/data/docling_models")
SMOLVLM_MODEL_PATH = os.path.join(MODEL_PATH, "HuggingFaceTB--SmolVLM-256M-Instruct")
PORT = int(os.environ.get("DOCLING_PORT", 5001))
MIMO_API_URL = os.environ.get("MIMO_API_URL", "http://model.mify.ai.srv/v1/chat/completions")
# Mimo API Key - 优先环境变量，其次默认值（仅用于 docling 图片描述）
MIMO_API_KEY = os.environ.get("MIFY_API_KEY") or os.environ.get("LLM_API_KEY", "") or "sk-oDsTRNe5Ymyvf8pkvXfIWmZOzha50hxqiIMBz80C5oJmg1tq"
MIMO_MODEL = "xiaomi/mimo-v2-omni"

DEFAULT_IMAGE_DESC_METHOD = os.environ.get("DEFAULT_IMAGE_DESC_METHOD", "mimo")

# Watchdog configuration
WATCH_ENABLED = os.environ.get("WATCH_ENABLED", "true").lower() in ("true", "1", "yes")
WATCH_DIRS = os.environ.get("WATCH_DIRS", "/data/agent_harness/teams/team-a/kb,/data/agent_harness/teams/team-a/skills")
WATCH_SUPPORTED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.docx', '.pptx'}

# Load .env file
def load_env_file():
    env_paths = ['/data/agent_harness/.env', '/data/.env']
    for env_path in env_paths:
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        if key.strip() not in os.environ:
                            os.environ[key.strip()] = value.strip()

load_env_file()
# 如果环境变量中有值，优先使用环境变量
env_key = os.environ.get("MIFY_API_KEY") or os.environ.get("LLM_API_KEY", "")
if env_key:
    MIMO_API_KEY = env_key

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DoclingImageDescService")

app = FastAPI(title="Docling-Serve with Image Description")

# Global instances
doc_converter = None
smolvlm_processor = None
smolvlm_model = None
watcher_thread = None
watcher_stop_event = threading.Event()
startup_scan_complete = threading.Event()  # 标记 startup-scan 是否完成


class DescriptionMethod(str, Enum):
    SMOLVLM = "smolvlm"
    MIMO = "mimo"
    AUTO = "auto"
    NONE = "none"


# =====================================================================
# System Prompt for Image Description
# =====================================================================
SYSTEM_PROMPT = """Describe the image from technical documentation. Output ONLY the description, nothing else.

Rules:
- Do NOT start with greetings, acknowledgments, or phrases like "Got it", "Sure", "Let me", "Let's", "Here's", "I'll", "Okay"
- Do NOT include reasoning steps, self-corrections, or chain-of-thought
- Do NOT use conversational language
- Start directly with the factual description

Focus on:
1. Data: numerical values, measurements, labels visible in the image
2. Structure: how elements relate to each other (tables, charts, diagrams, flowcharts)
3. Key findings: main insights from the image

Be precise and technical. Use the same language as the surrounding context text."""


def build_image_prompt(context_before: str, context_after: str) -> str:
    """Build prompt with surrounding context."""
    prompt_parts = [SYSTEM_PROMPT]

    if context_before:
        prompt_parts.append(f"\n\n[Context Before Image]\n{context_before[:500]}")

    if context_after:
        prompt_parts.append(f"\n\n[Context After Image]\n{context_after[:500]}")

    prompt_parts.append("\n\nBased on the context and the image, provide a detailed technical description. Use the same language as the context text.")

    return "".join(prompt_parts)


def clean_llm_preamble(text: str) -> str:
    """Remove common LLM preamble/conversational artifacts from description."""
    if not text:
        return text

    # Patterns to strip from the beginning (case-insensitive)
    preamble_patterns = [
        r"^(?:Got it|Sure|Okay|OK|Let me|Let's|I'll|I will|Here's|Here is|Certainly|Of course|Alright)[,.:!]?\s*",
        r"^(?:Let's (?:break|tackle|start|analyze|look|examine|describe)[^.]*[.!]\s*)",
        r"^(?:First,?\s+(?:I need to|let me|let's|looking at)[^.]*[.!]\s*)",
    ]

    result = text.strip()
    for pattern in preamble_patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE).strip()

    # Remove trailing chain-of-thought artifacts
    cot_patterns = [
        r"\s*(?:Wait,|Hmm,|Now,? let me|Now,? structure this)[^]]*$",
    ]
    for pattern in cot_patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE).strip()

    return result


# =====================================================================
# Mimo VLM Call
# =====================================================================
def describe_image_with_mimo(
    base64_image: str,
    mime_type: str = "image/png",
    context_before: str = "",
    context_after: str = "",
    timeout: int = 180,
    max_retries: int = 3
) -> Tuple[bool, str]:
    """Call mimo-v2-omni to describe image with context. Retries on timeout."""
    if not MIMO_API_KEY:
        return False, "API Key not configured"

    prompt = build_image_prompt(context_before, context_after)
    data_uri = f"data:{mime_type};base64,{base64_image}"

    payload = {
        "model": MIMO_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Describe images from technical documentation. Output ONLY the factual description. Do NOT start with greetings, acknowledgments, or phrases like 'Got it', 'Sure', 'Let me'. Do NOT include reasoning steps or self-corrections. Start directly with the description. Be precise and technical. Use the same language as the provided context."
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": prompt}
                ]
            }
        ],
        "max_completion_tokens": 512
    }

    req_data = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MIMO_API_KEY}"
    }

    last_error = ""
    for attempt in range(max_retries):
        req = urllib.request.Request(MIMO_API_URL, data=req_data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                message = result["choices"][0]["message"]
                description = message.get("content") or message.get("reasoning_content") or ""
                if description:
                    description = description.replace("<end_of_utterance>", "").strip()
                    description = clean_llm_preamble(description)
                return True, description if description else "Empty description"
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            break  # HTTP errors are not retryable
        except Exception as e:
            last_error = str(e)
            if attempt < max_retries - 1:
                wait = (attempt + 1) * 5  # 5s, 10s backoff
                logger.warning(f"Mimo attempt {attempt + 1}/{max_retries} failed ({last_error}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                logger.warning(f"Mimo all {max_retries} attempts failed: {last_error}")

    return False, last_error


# =====================================================================
# SmolVLM Call
# =====================================================================
def init_smolvlm():
    """Initialize SmolVLM model and processor."""
    global smolvlm_processor, smolvlm_model

    if smolvlm_processor is not None:
        return

    logger.info(f"Loading SmolVLM model from: {SMOLVLM_MODEL_PATH}")

    smolvlm_processor = AutoProcessor.from_pretrained(SMOLVLM_MODEL_PATH)
    smolvlm_processor.tokenizer.padding_side = "left"

    smolvlm_model = AutoModelForImageTextToText.from_pretrained(
        SMOLVLM_MODEL_PATH,
        torch_dtype=torch.bfloat16,
        device_map="auto"
    )
    smolvlm_model.eval()

    logger.info("SmolVLM model loaded successfully")


def describe_image_with_smolvlm(
    image: Image.Image,
    context_before: str = "",
    context_after: str = ""
) -> str:
    """Call SmolVLM to describe image with context."""
    global smolvlm_processor, smolvlm_model

    init_smolvlm()

    prompt = build_image_prompt(context_before, context_after)

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": prompt}
            ]
        }
    ]

    formatted_prompt = smolvlm_processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )

    inputs = smolvlm_processor(
        text=formatted_prompt,
        images=[image],
        return_tensors="pt"
    ).to(smolvlm_model.device)

    with torch.inference_mode():
        output = smolvlm_model.generate(
            **inputs,
            max_new_tokens=256,
            do_sample=False
        )

    generated_text = smolvlm_processor.decode(output[0], skip_special_tokens=True)

    if "Assistant:" in generated_text:
        generated_text = generated_text.split("Assistant:")[-1].strip()

    generated_text = generated_text.replace("<end_of_utterance>", "").strip()
    generated_text = clean_llm_preamble(generated_text)

    return generated_text


# =====================================================================
# Initialize Docling Converter
# =====================================================================
def init_converter():
    """Initialize Docling converter without built-in picture description."""
    global doc_converter
    try:
        logger.info(f"Loading Docling models, path: {MODEL_PATH}")
        pipeline_options = PdfPipelineOptions()
        pipeline_options.artifacts_path = MODEL_PATH
        pipeline_options.do_table_structure = True
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE
        pipeline_options.generate_picture_images = True

        # Disable built-in picture description - we'll do it manually with context
        pipeline_options.do_picture_description = False

        doc_converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        logger.info("Docling models loaded successfully!")
        logger.info(f"Mimo API: {MIMO_API_URL}")
        logger.info(f"Mimo API Key: {'Configured' if MIMO_API_KEY else 'Not configured'}")
        logger.info(f"Default image description method: {DEFAULT_IMAGE_DESC_METHOD}")
    except Exception as e:
        logger.error(f"Failed to load models: {e}")
        raise e


# =====================================================================
# File Watcher (Watchdog)
# =====================================================================
def convert_file_if_needed(filepath: str) -> bool:
    """Convert a file if its .md doesn't exist.

    Returns:
        True if converted, False if skipped or failed
    """
    try:
        # Check if already converted
        md_path = str(Path(filepath).with_suffix('.md'))
        if os.path.exists(md_path):
            logger.info(f"[watcher] Skip (exists): {os.path.basename(filepath)}")
            return False

        # Wait for file to be fully written (large files)
        time.sleep(1)

        # Convert
        logger.info(f"[watcher] Converting: {os.path.basename(filepath)}")
        result = convert_with_image_description(filepath, DescriptionMethod(DEFAULT_IMAGE_DESC_METHOD))

        # Write .md
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(result['markdown'])

        logger.info(f"[watcher] Done: {os.path.basename(md_path)}")
        return True

    except Exception as e:
        logger.error(f"[watcher] Failed: {filepath} - {e}")
        return False


def scan_and_convert_all():
    """Scan all watched directories and convert files without .md counterpart.

    This runs once at startup, before the watcher starts polling.
    """
    watch_dirs = [d.strip() for d in WATCH_DIRS.split(',') if d.strip()]
    watch_dirs = [d for d in watch_dirs if os.path.isdir(d)]

    if not watch_dirs:
        logger.warning("[startup-scan] No valid directories to scan")
        return

    logger.info(f"[startup-scan] Scanning directories for unconverted files...")

    files_to_convert = []
    for watch_dir in watch_dirs:
        for root, _, filenames in os.walk(watch_dir):
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext not in WATCH_SUPPORTED_EXTENSIONS:
                    continue

                fpath = os.path.join(root, fname)
                md_path = str(Path(fpath).with_suffix('.md'))

                # Skip if .md already exists
                if os.path.exists(md_path):
                    continue

                files_to_convert.append(fpath)

    if not files_to_convert:
        logger.info("[startup-scan] No new files to convert")
        return

    logger.info(f"[startup-scan] Found {len(files_to_convert)} files to convert")

    success = 0
    failed = 0
    for i, fpath in enumerate(files_to_convert, 1):
        fname = os.path.basename(fpath)
        logger.info(f"[startup-scan] [{i}/{len(files_to_convert)}] Converting: {fname}")

        try:
            result = convert_with_image_description(fpath, DescriptionMethod(DEFAULT_IMAGE_DESC_METHOD))

            # Write .md file
            md_path = str(Path(fpath).with_suffix('.md'))
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(result['markdown'])

            logger.info(f"[startup-scan] [{i}/{len(files_to_convert)}] Done: {os.path.basename(md_path)} ({result['method_used']})")
            success += 1
        except Exception as e:
            logger.error(f"[startup-scan] [{i}/{len(files_to_convert)}] Failed: {fname} - {e}")
            failed += 1

    logger.info(f"[startup-scan] Completed: {success} success, {failed} failed")


def scan_and_convert_all_wrapper():
    """Wrapper that runs scan_and_convert_all and starts watcher when done."""
    try:
        scan_and_convert_all()
    finally:
        # Mark scan as complete
        startup_scan_complete.set()
        logger.info("[startup-scan] Scan complete, starting watcher...")
        # Start watcher after scan completes
        start_watcher()


def watcher_loop():
    """Watchdog thread main loop using simple polling."""
    import time

    # Parse watch directories
    watch_dirs = [d.strip() for d in WATCH_DIRS.split(',') if d.strip()]
    watch_dirs = [d for d in watch_dirs if os.path.isdir(d)]

    if not watch_dirs:
        logger.warning("[watcher] No valid directories to watch")
        return

    logger.info(f"[watcher] Watching: {watch_dirs}")

    # Track file mtimes
    file_mtimes = {}

    # Initial scan: record existing files
    for watch_dir in watch_dirs:
        for root, _, filenames in os.walk(watch_dir):
            for fname in filenames:
                ext = Path(fname).suffix.lower()
                if ext in WATCH_SUPPORTED_EXTENSIONS:
                    fpath = os.path.join(root, fname)
                    try:
                        file_mtimes[fpath] = os.path.getmtime(fpath)
                    except:
                        pass

    logger.info(f"[watcher] Tracking {len(file_mtimes)} existing files")

    # Poll loop
    while not watcher_stop_event.is_set():
        try:
            for watch_dir in watch_dirs:
                for root, _, filenames in os.walk(watch_dir):
                    for fname in filenames:
                        ext = Path(fname).suffix.lower()
                        if ext not in WATCH_SUPPORTED_EXTENSIONS:
                            continue

                        fpath = os.path.join(root, fname)

                        try:
                            mtime = os.path.getmtime(fpath)
                        except:
                            continue

                        # New file or modified?
                        old_mtime = file_mtimes.get(fpath)
                        if old_mtime is None:
                            # New file
                            file_mtimes[fpath] = mtime
                            convert_file_if_needed(fpath)
                        elif mtime > old_mtime + 1:  # 1s tolerance
                            # Modified file - reconvert
                            file_mtimes[fpath] = mtime
                            logger.info(f"[watcher] Modified: {os.path.basename(fpath)}")
                            convert_file_if_needed(fpath)

        except Exception as e:
            logger.error(f"[watcher] Scan error: {e}")

        # Poll every 5 seconds
        watcher_stop_event.wait(5)


def start_watcher():
    """Start the file watcher thread."""
    global watcher_thread

    if not WATCH_ENABLED:
        logger.info("[watcher] File watching disabled")
        return

    watcher_thread = threading.Thread(target=watcher_loop, daemon=True)
    watcher_thread.start()
    logger.info("[watcher] Started")


def stop_watcher():
    """Stop the file watcher thread."""
    global watcher_thread

    if watcher_thread is None:
        return

    logger.info("[watcher] Stopping...")
    watcher_stop_event.set()
    watcher_thread.join(timeout=5)
    watcher_thread = None
    logger.info("[watcher] Stopped")


@app.on_event("startup")
async def startup_event():
    global startup_scan_thread, startup_scan_complete

    init_converter()

    # Run startup scan in background thread FIRST (non-blocking)
    # so the service can accept requests while converting
    import threading
    startup_scan_complete.clear()  # 标记未完成
    startup_scan_thread = threading.Thread(target=scan_and_convert_all_wrapper, daemon=True)
    startup_scan_thread.start()
    logger.info("[startup] Service ready, background scan started, watcher will start after scan completes")


@app.on_event("shutdown")
async def shutdown_event():
    # Wait for startup-scan to complete (max 5 seconds)
    if startup_scan_thread and startup_scan_thread.is_alive():
        logger.info("[shutdown] Waiting for startup-scan to complete...")
        startup_scan_thread.join(timeout=5)
    stop_watcher()


# =====================================================================
# Health Check
# =====================================================================
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mimo_configured": bool(MIMO_API_KEY),
        "default_method": DEFAULT_IMAGE_DESC_METHOD
    }


@app.post("/rescan")
async def rescan():
    """Manually trigger a rescan for unconverted files.

    This is useful when .md files were deleted and you want to reconvert
    without restarting the service.
    """
    import threading

    def run_scan():
        logger.info("[rescan] Manual rescan triggered")
        scan_and_convert_all()

    # Run in background thread to not block the request
    scan_thread = threading.Thread(target=run_scan, daemon=True)
    scan_thread.start()

    return {"status": "ok", "message": "Rescan started in background"}


# =====================================================================
# Core Conversion Logic
# =====================================================================
def get_context_text(items: List, picture_idx: int, max_length: int = 300) -> Tuple[str, str]:
    """Get text context before and after a picture."""
    context_before = ""
    context_after = ""

    # Get context before (search backwards for text items)
    for i in range(picture_idx - 1, max(-1, picture_idx - 5), -1):
        item = items[i][0]
        if isinstance(item, TextItem) and hasattr(item, 'text'):
            text = item.text.strip()
            if text and len(text) > 10:  # Skip very short texts
                context_before = text[:max_length]
                break

    # Get context after (search forwards for text items)
    for i in range(picture_idx + 1, min(len(items), picture_idx + 5)):
        item = items[i][0]
        if isinstance(item, TextItem) and hasattr(item, 'text'):
            text = item.text.strip()
            if text and len(text) > 10:
                context_after = text[:max_length]
                break

    return context_before, context_after


def fix_missing_spaces(text: str) -> str:
    """Fix missing spaces in text extracted from PDFs.

    Some PDFs lose spaces during extraction, producing text like:
    "Itisstillunclarified" -> "It is still unclarified"

    Also removes control characters (like SOH 0x01) that may appear.

    Uses wordninja for word segmentation on long tokens that appear
    to be concatenated words. Falls back to simple camelCase splitting
    if wordninja is unavailable.
    """
    if not text:
        return text

    # Step 1: Remove control characters (SOH, STX, etc.)
    # Keep newlines (\x0a), tabs (\x09), and carriage returns (\x0d)
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)

    try:
        import wordninja
        _split = wordninja.split
    except ImportError:
        _split = None

    lines = text.split('\n')
    fixed_lines = []

    for line in lines:
        # Skip code blocks, headings, image descriptions, URLs, markdown syntax
        stripped = line.strip()
        if (stripped.startswith('```') or stripped.startswith('#') or
            stripped.startswith('[Image') or stripped.startswith('|') or
            stripped.startswith('http') or stripped.startswith('![') or
            stripped.startswith('<!-- ')):
            fixed_lines.append(line)
            continue

        # Detect: if a line has long "words" (>15 chars) that are mostly
        # ASCII letters, they are likely concatenated words
        # Lowered threshold from 25 to 15 for better detection
        tokens = re.split(r'(\s+)', line)  # Split preserving whitespace
        needs_fix = False
        for token in tokens:
            # Remove punctuation at edges to check the core word
            core = re.sub(r'^[^a-zA-Z0-9]*|[^a-zA-Z0-9]*$', '', token)
            # Check for concatenated words: >15 chars with lowercase letters
            if len(core) > 15 and re.search(r'[a-z]{3,}', core):
                needs_fix = True
                break

        if not needs_fix:
            fixed_lines.append(line)
            continue

        # Fix each long token - once we know the line needs fixing,
        # use a lower threshold (8) for individual segments after punctuation split
        fixed_tokens = []
        for token in tokens:
            # Split token into segments by punctuation, fix each segment
            # This preserves commas, semicolons, parentheses etc.
            segments = re.split(r'([,;:!?()\[\]{}])', token)
            fixed_segments = []
            for seg in segments:
                core = re.sub(r'^[^a-zA-Z0-9]*|[^a-zA-Z0-9]*$', '', seg)
                # Lowered threshold from 10 to 8 for better detection
                if len(core) > 8 and re.search(r'[a-z]{3,}', core) and _split:
                    words = _split(core)
                    # Preserve leading/trailing non-alnum chars from segment
                    prefix_match = re.match(r'^([^a-zA-Z0-9]*)', seg)
                    suffix_match = re.search(r'([^a-zA-Z0-9]*)$', seg)
                    prefix = prefix_match.group(1) if prefix_match else ''
                    suffix = suffix_match.group(1) if suffix_match else ''
                    fixed_segments.append(prefix + ' '.join(words) + suffix)
                else:
                    fixed_segments.append(seg)
            fixed_tokens.append(''.join(fixed_segments))

        fixed_lines.append(''.join(fixed_tokens))

    return '\n'.join(fixed_lines)


def insert_descriptions_into_markdown(md: str, descriptions: List[str]) -> str:
    """Insert image descriptions at placeholder positions in markdown.

    Docling uses '<!-- image -->' as placeholder for images.
    We replace each placeholder with the corresponding description.
    """
    placeholder = "<!-- image -->"
    parts = md.split(placeholder)

    if len(parts) - 1 != len(descriptions):
        logger.warning(f"Placeholder count ({len(parts) - 1}) != description count ({len(descriptions)})")
        # If mismatch, just append descriptions at the end
        if descriptions:
            md += "\n\n---\n\n## Image Descriptions\n\n"
            for i, desc in enumerate(descriptions):
                if desc:
                    md += f"### Image {i + 1}\n\n{desc}\n\n"
        return md

    # Insert descriptions at placeholder positions
    result = parts[0]
    for i, desc in enumerate(descriptions):
        if desc:
            result += f"\n\n[Image Description: {desc}]\n\n"
        else:
            result += f"\n\n[Image {i + 1}: No description generated]\n\n"
        result += parts[i + 1]

    return result


def convert_with_image_description(
    filepath: str,
    method: DescriptionMethod = DescriptionMethod.SMOLVLM
) -> dict:
    """Convert document and generate image descriptions with context.

    Args:
        filepath: PDF file path
        method: Description method
            - smolvlm: Use SmolVLM
            - mimo: Use mimo API
            - auto: Try mimo first, fallback to smolvlm
            - none: No description
    """
    start_time = time.time()

    logger.info(f"Starting conversion: {filepath}, method: {method}")
    result = doc_converter.convert(filepath)
    doc = result.document

    # Export markdown with image placeholders
    md_output = doc.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)

    # Collect all items with their indices
    items = list(doc.iterate_items())

    # Extract pictures with context
    pictures = []
    descriptions = []  # Ordered list of descriptions for markdown insertion

    for idx, (item, level) in enumerate(items):
        if isinstance(item, PictureItem):
            context_before, context_after = get_context_text(items, idx)

            pic_info = {
                'index': len(pictures),
                'label': str(item.label),
                'page': item.prov[0].page_no if item.prov else None,
                'description': None,
                'method': None,
                'base64': None,
                'mime_type': None,
                'context_before': context_before,
                'context_after': context_after,
            }

            # Extract image data
            if item.image:
                uri = str(item.image.uri)
                if uri.startswith('data:'):
                    header, base64_data = uri.split(',', 1)
                    pic_info['base64'] = base64_data
                    pic_info['mime_type'] = header.split(':')[1].split(';')[0]

            pictures.append(pic_info)

    logger.info(f"Found {len(pictures)} pictures")

    # Generate descriptions based on method
    method_used = "none"

    # Batch processing configuration
    BATCH_SIZE = 5  # 并行处理的图片数量
    BATCH_DELAY = 0.5  # 批次之间的延迟（秒），防止 API 限流

    def describe_image_sync(pic: dict, index: int, method: DescriptionMethod) -> Tuple[int, Optional[str], str]:
        """同步描述单张图片（线程安全）"""
        if not pic['base64']:
            return index, None, 'no_image'

        if method == DescriptionMethod.MIMO:
            success, desc = describe_image_with_mimo(
                pic['base64'],
                pic['mime_type'],
                pic['context_before'],
                pic['context_after']
            )
            if success:
                return index, desc, 'mimo'
            else:
                logger.warning(f"Mimo description failed for pic {index}: {desc}")
                return index, None, 'mimo_failed'

        elif method == DescriptionMethod.SMOLVLM:
            try:
                image_data = base64.b64decode(pic['base64'])
                image = Image.open(io.BytesIO(image_data))
                desc = describe_image_with_smolvlm(
                    image,
                    pic['context_before'],
                    pic['context_after']
                )
                return index, desc, 'smolvlm'
            except Exception as e:
                logger.warning(f"SmolVLM description failed for pic {index}: {e}")
                return index, None, 'smolvlm_failed'

        elif method == DescriptionMethod.AUTO:
            success, desc = describe_image_with_mimo(
                pic['base64'],
                pic['mime_type'],
                pic['context_before'],
                pic['context_after']
            )
            if success:
                return index, desc, 'mimo'
            else:
                # Fallback to SmolVLM
                logger.warning(f"Mimo failed for pic {index}, trying SmolVLM: {desc}")
                try:
                    image_data = base64.b64decode(pic['base64'])
                    image = Image.open(io.BytesIO(image_data))
                    desc = describe_image_with_smolvlm(
                        image,
                        pic['context_before'],
                        pic['context_after']
                    )
                    return index, desc, 'smolvlm_fallback'
                except Exception as e:
                    logger.warning(f"SmolVLM fallback also failed for pic {index}: {e}")
                    return index, None, 'failed'

        return index, None, 'unknown_method'

    if pictures and method != DescriptionMethod.NONE:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        # 初始化结果列表
        results = [None] * len(pictures)
        methods = [None] * len(pictures)

        # 分批处理 - 使用同步方式避免async问题
        total_batches = (len(pictures) + BATCH_SIZE - 1) // BATCH_SIZE
        logger.info(f"Processing {len(pictures)} pictures in {total_batches} batches (batch_size={BATCH_SIZE})")

        # 使用线程池并行处理
        with ThreadPoolExecutor(max_workers=BATCH_SIZE) as executor:
            for batch_idx in range(total_batches):
                start_idx = batch_idx * BATCH_SIZE
                end_idx = min(start_idx + BATCH_SIZE, len(pictures))
                batch_pics = pictures[start_idx:end_idx]

                logger.info(f"Processing batch {batch_idx + 1}/{total_batches} (pics {start_idx + 1}-{end_idx})")

                # 提交当前批次的所有任务
                futures = []
                for i, pic in enumerate(batch_pics):
                    future = executor.submit(
                        describe_image_sync,
                        pic,
                        start_idx + i,
                        method
                    )
                    futures.append(future)

                # 等待当前批次完成
                for future in futures:
                    try:
                        idx, desc, mtd = future.result(timeout=300)  # 5分钟超时
                        results[idx] = desc
                        methods[idx] = mtd
                        pictures[idx]['description'] = desc
                        pictures[idx]['method'] = mtd
                    except Exception as e:
                        logger.error(f"Batch processing error: {e}")

                # 批次间延迟（最后一批不延迟）
                if batch_idx < total_batches - 1:
                    time.sleep(BATCH_DELAY)

        descriptions = results

        # 统计成功/失败数量
        success_count = sum(1 for m in methods if m and not m.endswith('_failed') and m != 'no_image')
        failed_count = sum(1 for m in methods if m and m.endswith('_failed'))

        if method == DescriptionMethod.MIMO:
            method_used = f"mimo({success_count}/{len(pictures)})"
        elif method == DescriptionMethod.SMOLVLM:
            method_used = f"smolvlm({success_count}/{len(pictures)})"
        elif method == DescriptionMethod.AUTO:
            mimo_count = sum(1 for m in methods if m and m.startswith('mimo'))
            smolvlm_count = sum(1 for m in methods if m and 'smolvlm' in m)
            method_used = f"mimo({mimo_count})+smolvlm({smolvlm_count})"
    else:
        # No descriptions, fill with None
        descriptions = [None] * len(pictures)

    # Insert descriptions into markdown at placeholder positions
    md_output = insert_descriptions_into_markdown(md_output, descriptions)

    # Post-process: fix missing spaces in extracted text
    md_output = fix_missing_spaces(md_output)

    # Remove control characters (SOH, STX, etc.) that can appear in PDF extraction
    md_output = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', md_output)

    processing_time = time.time() - start_time
    logger.info(f"Conversion completed, time: {processing_time:.2f}s, method: {method_used}")

    return {
        'markdown': md_output,
        'pictures': pictures,
        'method_used': method_used,
        'processing_time': processing_time
    }


# =====================================================================
# API Endpoints
# =====================================================================
@app.post("/v1/convert/file")
@app.post("/convert")
async def docling_serve_convert(request: Request):
    """File upload conversion endpoint."""
    tmp_path = None
    try:
        logger.info(f"Received conversion request...")

        content_type = request.headers.get("content-type", "")
        if "multipart/form-data" in content_type:
            form = await request.form()
            file_obj = None
            for key, value in form.items():
                if hasattr(value, "filename") and value.filename:
                    file_obj = value
                    break
            if not file_obj:
                file_obj = form.get("file") or form.get("doc")

            if not file_obj:
                return JSONResponse({"status": "failure", "error": "No file uploaded"}, status_code=400)

            suffix = os.path.splitext(file_obj.filename)[1] or ".pdf"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                shutil.copyfileobj(file_obj.file, tmp)
                tmp_path = tmp.name
        else:
            return JSONResponse({"status": "failure", "error": "Unsupported Content-Type"}, status_code=400)

        # Get parameters
        try:
            params = await request.json() if "application/json" in content_type else {}
        except:
            params = {}

        method = params.get("image_desc_method", DEFAULT_IMAGE_DESC_METHOD)

        # Execute conversion
        logger.info(f"Converting file: {tmp_path}, image description method: {method}")
        result = convert_with_image_description(tmp_path, DescriptionMethod(method))

        response_data = {
            "status": "success",
            "document": {
                "md_content": result['markdown'],
                "text_content": result['markdown'],
            },
            "pictures": result['pictures'],
            "image_desc_method": result['method_used'],
            "processing_time": result['processing_time']
        }

        logger.info(f"Conversion successful! Markdown length: {len(result['markdown'])}, pictures: {len(result['pictures'])}")
        return JSONResponse(content=response_data)

    except Exception as e:
        logger.error(f"Processing error: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"status": "failure", "error": str(e)}
        )

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


@app.post("/convert-path")
async def convert_path(request: Request):
    """Convert by file path endpoint (commonly used by agents)."""
    try:
        data = await request.json()
        filepath = data.get("path", "")
        method = data.get("image_desc_method", DEFAULT_IMAGE_DESC_METHOD)

        if not filepath:
            return JSONResponse({"error": "Path parameter required"}, status_code=400)

        if not os.path.exists(filepath):
            return JSONResponse({"error": f"File not found: {filepath}"}, status_code=404)

        logger.info(f"Converting file: {filepath}, image description method: {method}")
        result = convert_with_image_description(filepath, DescriptionMethod(method))

        return JSONResponse({
            "status": "success",
            "markdown": result['markdown'],
            "pictures": result['pictures'],
            "image_desc_method": result['method_used'],
            "filename": os.path.basename(filepath),
            "processing_time": result['processing_time']
        })

    except Exception as e:
        logger.error(f"Processing error: {str(e)}")
        import traceback
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    logger.info(f"Docling service starting, port: {PORT}, default image description method: {DEFAULT_IMAGE_DESC_METHOD}")
    uvicorn.run(app, host="0.0.0.0", port=PORT)
