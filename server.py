#!/usr/bin/env python3
"""
Bilibili Transcript MCP Server
==============================
A lightweight MCP server that extracts English transcript from Bilibili videos.
- Tries Bilibili CC subtitles first (via API)
- Falls back to yt-dlp audio download + faster-whisper ASR
- Returns plain English text only

Usage:
    ./venv/bin/python server.py

Then mount via Claude Code:
    /mcp add bilibili-transcript stdio /absolute/path/to/venv/bin/python server.py
"""

import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).parent.resolve()
MODELS_DIR = PROJECT_DIR / "models"
TEMP_DIR = PROJECT_DIR / "temp"
MODELS_DIR.mkdir(exist_ok=True)
TEMP_DIR.mkdir(exist_ok=True)

# Faster-Whisper model size: "base" or "small".  "small" is default for better
# accuracy with mathematical terminology while keeping memory reasonable.
DEFAULT_WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")

# yt-dlp needs these headers to avoid Bilibili anti-bot (HTTP 412).
YTDLP_HEADERS = [
    "--add-header",
    "User-Agent:Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "--add-header",
    "Referer:https://www.bilibili.com",
]

# ---------------------------------------------------------------------------
# MCP Server Setup
# ---------------------------------------------------------------------------
mcp = FastMCP("bilibili-transcript")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_bilibili_url(url: str) -> tuple[str, int]:
    """Extract BV id and page number from a Bilibili URL."""
    # Match BV号
    bv_match = re.search(r"BV[0-9A-Za-z]+", url)
    if not bv_match:
        raise ValueError(f"Cannot extract BV id from URL: {url}")
    bvid = bv_match.group(0)

    # Match page number (p=2, etc.)
    page_match = re.search(r"[?&]p=(\d+)", url)
    page = int(page_match.group(1)) if page_match else 1

    return bvid, page


def fetch_video_metadata(bvid: str) -> dict:
    """Fetch video metadata from Bilibili API."""
    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    req = urllib.request.Request(
        api_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://www.bilibili.com",
        },
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("code") != 0:
        raise RuntimeError(f"Bilibili API error: {data}")
    return data["data"]


def fetch_subtitle_list(metadata: dict, page: int) -> list[dict]:
    """Extract subtitle list for the given page from metadata."""
    # For multi-page videos, subtitles are in pages[] array
    pages = metadata.get("pages", [])
    if not pages:
        # Single page video
        return metadata.get("subtitle", {}).get("list", [])

    # Find matching cid for the requested page
    target_cid = None
    for p in pages:
        if p.get("page") == page:
            target_cid = p.get("cid")
            break

    if target_cid is None:
        # Fallback to first page
        target_cid = pages[0].get("cid")

    # Bilibili's view API returns subtitle info for the *first* page in the
    # top-level subtitle field.  For anthology videos we may need to call
    # another endpoint, but often the subtitles are the same across pages.
    # We'll try the top-level subtitle list first.
    subs = metadata.get("subtitle", {}).get("list", [])

    # If top-level is empty and it's an anthology, try fetching page-specific
    # subtitle via player API
    if not subs and target_cid:
        try:
            player_url = (
                f"https://api.bilibili.com/x/player/wbi/v2?cid={target_cid}&bvid={metadata.get('bvid')}"
            )
            req = urllib.request.Request(
                player_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://www.bilibili.com",
                },
            )
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                pdata = json.loads(resp.read().decode("utf-8"))
            if pdata.get("code") == 0:
                subs = pdata.get("data", {}).get("subtitle", {}).get("subtitles", [])
        except Exception:
            pass

    return subs


def download_subtitle_text(subtitle_url: str) -> str:
    """Download and return the plain text from a Bilibili subtitle JSON URL."""
    req = urllib.request.Request(
        subtitle_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com",
        },
    )
    ctx = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    # Bilibili subtitle format: {"body": [{"from": 0.0, "to": 1.0, "content": "..."}, ...]}
    body = data.get("body", [])
    texts = [item.get("content", "").strip() for item in body if item.get("content")]
    return "\n".join(texts)


def run_ytdlp_audio_download(video_url: str, output_path: Path) -> Path:
    """Download best audio from Bilibili using yt-dlp with anti-bot headers."""
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-check-certificate",
        *YTDLP_HEADERS,
        "-f",
        "bestaudio",
        "-o",
        str(output_path),
        video_url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    # yt-dlp may add extension automatically
    if output_path.exists():
        return output_path
    # Try common extensions
    for ext in [".m4a", ".webm", ".opus", ".mp4", ".mkv"]:
        candidate = output_path.with_suffix(ext)
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Audio file not found after download: {output_path}")


def transcribe_with_whisper(audio_path: Path, model_size: str = DEFAULT_WHISPER_MODEL) -> str:
    """Transcribe audio to English text using faster-whisper."""
    from faster_whisper import WhisperModel

    # Load model (will auto-download to MODELS_DIR on first run)
    model = WhisperModel(
        model_size,
        device="auto",
        compute_type="int8",
        download_root=str(MODELS_DIR),
    )

    segments, _info = model.transcribe(
        str(audio_path),
        language="en",
        task="transcribe",
        beam_size=5,
        condition_on_previous_text=True,
    )

    texts = [segment.text.strip() for segment in segments if segment.text.strip()]
    return "\n".join(texts)


# ---------------------------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------------------------
@mcp.tool()
def get_video_transcript(url: str) -> str:
    """
    Extract English transcript from a Bilibili video URL.

    Strategy:
        1. Query Bilibili API for official CC subtitles (prefer English).
        2. If no subtitles, download audio via yt-dlp and transcribe with
           faster-whisper (default "small" model).

    Args:
        url: Full Bilibili video URL, e.g.
             https://www.bilibili.com/video/BV1aJ411w74i/?p=2

    Returns:
        Plain English transcript text.
    """
    bvid, page = parse_bilibili_url(url)
    print(f"[bilibili-transcript] Processing {bvid} page {page}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Step 1: Try official subtitles via Bilibili API
    # ------------------------------------------------------------------
    try:
        metadata = fetch_video_metadata(bvid)
        title = metadata.get("title", "Unknown")
        print(f"[bilibili-transcript] Video title: {title}", file=sys.stderr)

        subs = fetch_subtitle_list(metadata, page)
        if subs:
            print(f"[bilibili-transcript] Found {len(subs)} subtitle track(s)", file=sys.stderr)
            # Prefer English, then any available
            chosen = None
            for s in subs:
                lan = s.get("lan", "").lower()
                if "en" in lan:
                    chosen = s
                    break
            if chosen is None:
                chosen = subs[0]

            sub_url = chosen.get("subtitle_url", "")
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            elif sub_url.startswith("/"):
                sub_url = "https://" + sub_url

            if sub_url:
                text = download_subtitle_text(sub_url)
                print(f"[bilibili-transcript] Subtitle downloaded ({len(text)} chars)", file=sys.stderr)
                return text
    except Exception as e:
        print(f"[bilibili-transcript] Subtitle fetch failed: {e}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Step 2: Fallback — download audio + faster-whisper ASR
    # ------------------------------------------------------------------
    print("[bilibili-transcript] No CC subtitles. Falling back to audio transcription...", file=sys.stderr)

    # Determine exact video URL (include page param if needed)
    video_url = f"https://www.bilibili.com/video/{bvid}"
    if page > 1:
        video_url += f"/?p={page}"

    # Temporary audio file
    temp_audio = TEMP_DIR / f"{bvid}_p{page}_audio"

    try:
        audio_path = run_ytdlp_audio_download(video_url, temp_audio)
        print(f"[bilibili-transcript] Audio downloaded: {audio_path}", file=sys.stderr)

        text = transcribe_with_whisper(audio_path)
        print(f"[bilibili-transcript] Transcription complete ({len(text)} chars)", file=sys.stderr)
        return text
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {e}") from e
    finally:
        # Clean up temp audio files
        for f in TEMP_DIR.glob(f"{bvid}_p{page}_audio*"):
            try:
                f.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    mcp.run(transport="stdio")
