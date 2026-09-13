"""Render this repo's Claude Code session transcripts (JSONL) into log.txt at the repo root.

    python code/build_transcript.py              # find sessions, render, redact, rewrite log.txt
    python code/build_transcript.py --dry-run    # print stats only

Claude Code stores sessions at ~/.claude/projects/<encoded path>/<session-id>.jsonl, where the encoded path is the
directory the session was opened in with every non-alphanumeric character replaced by '-'. The repo root and each of
its parents are tried, because a session opened in a parent folder is stored under the parent's name.

User and assistant text is kept in full. Tool calls and tool results are one line each, truncated to 500 characters.
Existing agent summary entries in log.txt are preserved and moved under "=== AGENT SUMMARIES ===" at the end.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
ROOT = CODE_DIR.parent
LOG_PATH = ROOT / "log.txt"
SUMMARY_MARKER = "=== AGENT SUMMARIES ==="
MAX_TOOL_CHARS = 500

SECRET_PATTERNS = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}")),
    ("openai_style_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{20,}")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("aws_secret_access_key", re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{30,}")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{30,}")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("secret_assignment", re.compile(r"(?i)\b(?:[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD|PASSWD))\s*[=:]\s*['\"]?(?!set\b|unset\b|\[REDACTED)[A-Za-z0-9_\-./+=]{12,}")),
]


def encode_project_dir(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def find_session_files(projects_dir: Path) -> tuple[list[Path], list[Path]]:
    tried, found = [], []
    for candidate in [ROOT, *ROOT.parents]:
        folder = projects_dir / encode_project_dir(candidate)
        tried.append(folder)
        if folder.is_dir():
            found.extend(sorted(folder.glob("*.jsonl")))
    return tried, found


def first_timestamp(path: Path) -> str:
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                ts = json.loads(line).get("timestamp")
            except json.JSONDecodeError:
                continue
            if ts:
                return ts
    return ""


def one_line(text: str, limit: int = MAX_TOOL_CHARS) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[:limit] + f" ...[{len(flat) - limit} more chars]"


def summarize_tool_use(block: dict) -> str:
    name, args = block.get("name", "?"), block.get("input") or {}
    if name in ("Bash", "PowerShell"):
        detail = f"{args.get('description', '')} :: {args.get('command', '')}"
    elif name in ("Read", "Write", "Edit", "NotebookEdit"):
        detail = str(args.get("file_path", ""))
        if name == "Write":
            detail += f" ({len(args.get('content', ''))} chars)"
        if name == "Read" and (args.get("offset") or args.get("limit")):
            detail += f" (offset {args.get('offset')}, limit {args.get('limit')})"
    elif name == "Grep":
        detail = f"pattern {args.get('pattern')!r} in {args.get('path', '.')}"
    elif name == "Glob":
        detail = f"pattern {args.get('pattern')!r}"
    elif name == "Skill":
        detail = f"skill {args.get('skill')}"
    else:
        detail = json.dumps(args, ensure_ascii=False)
    return f"[TOOL] {name} — {one_line(detail)}"


def result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    parts = []
    for item in content or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif isinstance(item, dict) and item.get("type") == "image":
            parts.append("[image]")
    return " ".join(parts)


def render_session(path: Path, number: int) -> list[str]:
    lines = [f"=== SESSION {number} — {first_timestamp(path)} — {path.stem} ==="]
    tool_names: dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = rec.get("type")
            if kind == "queue-operation" and rec.get("operation") == "enqueue" and rec.get("content"):
                lines.append(f"[USER] (sent while the agent was working) {rec['content']}")
                continue
            msg = rec.get("message")
            if kind not in ("user", "assistant") or not isinstance(msg, dict):
                continue
            content = msg.get("content")
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if kind == "assistant" and btype == "text" and block.get("text", "").strip():
                    lines.append(f"[ASSISTANT] {block['text']}")
                elif kind == "assistant" and btype == "tool_use":
                    tool_names[block.get("id", "")] = block.get("name", "?")
                    lines.append(summarize_tool_use(block))
                elif kind == "user" and btype == "text" and block.get("text", "").strip():
                    tag = "[META]" if rec.get("isMeta") else "[USER]"
                    text = one_line(block["text"]) if rec.get("isMeta") else block["text"]
                    lines.append(f"{tag} {text}")
                elif kind == "user" and btype == "tool_result":
                    name = tool_names.get(block.get("tool_use_id", ""), "?")
                    status = " (error)" if block.get("is_error") else ""
                    lines.append(f"[TOOL] {name} result{status} — {one_line(result_text(block))}")
    return lines


def redact(text: str) -> tuple[str, dict[str, int]]:
    found: dict[str, int] = {}
    for kind, pattern in SECRET_PATTERNS:
        text, n = pattern.subn(f"[REDACTED:{kind}]", text)
        if n:
            found[kind] = n
    return text, found


def existing_summaries() -> str:
    """Text after the LAST line that consists solely of the marker. The transcript itself can quote the marker
    (for example inside a user prompt), so a plain substring split would copy transcript text into the summaries."""
    if not LOG_PATH.exists():
        return ""
    current = LOG_PATH.read_text(encoding="utf-8")
    markers = list(re.finditer(rf"^{re.escape(SUMMARY_MARKER)}[ \t]*$", current, flags=re.M))
    if markers:
        return current[markers[-1].end():].lstrip("\n")
    return current


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects-dir", type=Path, default=Path.home() / ".claude" / "projects")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tried, files = find_session_files(args.projects_dir)
    if not files:
        print("NO SESSION FILES FOUND. Tried:")
        for t in tried:
            print("  ", t)
        raise SystemExit(1)
    files.sort(key=first_timestamp)
    print("session files (chronological):")
    for f in files:
        st = f.stat()
        print(f"  {f}  {st.st_size / 1024:,.1f} KB  modified {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M:%S}")

    body = []
    for n, f in enumerate(files, 1):
        body.extend(render_session(f, n))
        body.append("")
    transcript, secrets = redact("\n".join(body))
    note = (f"# Rendered from Claude Code session JSONL by code/build_transcript.py on "
            f"{datetime.now().astimezone():%Y-%m-%dT%H:%M:%S%z}. Sessions: {len(files)}. "
            f"User/assistant text in full; tool calls/results one line, max {MAX_TOOL_CHARS} chars.")
    output = transcript.rstrip("\n") + f"\n\n{note}\n\n{SUMMARY_MARKER}\n\n" + existing_summaries()
    print("secrets redacted:", secrets or "none found")
    if args.dry_run:
        print(f"(dry run) would write {len(output.splitlines())} lines, {len(output.encode('utf-8')) / 1024:,.1f} KB")
        return
    LOG_PATH.write_text(output, encoding="utf-8", newline="\n")
    print(f"wrote {LOG_PATH}: {len(output.splitlines())} lines, {LOG_PATH.stat().st_size / 1024:,.1f} KB")


if __name__ == "__main__":
    main()
