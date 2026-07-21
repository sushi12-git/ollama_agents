#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ollama-websearch: a local Ollama-powered CLI agent.

Capabilities:
  * Streams tokens from any local Ollama model (qwen3.5, gemma4, ornith, ...)
  * web_search       - DuckDuckGo search
  * search_docs      - RAG over local files (ChromaDB + nomic-embed-text)
  * read_file        - read a file
  * write_file       - create/overwrite a file (with confirmation)
  * edit_file        - find-and-replace patch (with confirmation)
  * Slash commands   - /model, /clear, /tools, /help, /rag, /history, /save, ...
  * Pluggable skills - drop .py files in ./skills/ to add new commands

Usage:
    python ollama_web.py
    python ollama_web.py -m qwen3.5:9b -n 5
    python ollama_web.py --rag ./docs --rag-top-k 4
    python ollama_web.py --list
"""

import argparse
import html
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import urllib.parse

# Force UTF-8 on Windows so Rich markup never crashes cp1252 terminals.
# (Belt-and-braces: nothing in this file uses non-ASCII anyway.)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import difflib
import shutil
import urllib.error
import urllib.request
from datetime import datetime

# --- Optional / installed packages ------------------------------------------

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.rule import Rule
    from rich import box
    from rich.table import Table
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

try:
    from ddgs import DDGS
    HAS_DDG = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDG = True
    except ImportError:
        HAS_DDG = False

try:
    import chromadb
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False


# --- Constants ---------------------------------------------------------------

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_N_RESULTS = 5
DEFAULT_EMBED_MODEL = "nomic-embed-text:latest"
MAX_TOOL_ROUNDS = 8
MAX_HISTORY = 50  # messages retained per session

console = Console() if HAS_RICH else None

# All-ASCII banner -- works on cp1252, no Unicode/emoji needed.
BANNER = r"""
   ____  __    __    ___    __  ______ 
  / __ \/ /   / /   /   |  /  |/  /   |
 / / / / /   / /   / /| | / /|_/ / /| |
/ /_/ / /___/ /___/ ___ |/ /  / / ___ |
\____/_____/_____/_/  |_/_/  /_/_/  |_|

    ___   _____________   _____________
   /   | / ____/ ____/ | / /_  __/ ___/
  / /| |/ / __/ __/ /  |/ / / /  \__ \ 
 / ___ / /_/ / /___/ /|  / / /  ___/ / 
/_/  |_\____/_____/_/ |_/ /_/  /____/  

          web  *  RAG  *  files  *  plugins
"""


# --- Small printing helpers -------------------------------------------------

def cprint(msg, style=""):
    if HAS_RICH and console is not None:
        console.print(msg, style=style)
    else:
        # Strip Rich markup tags if no Rich available.
        import re
        clean = re.sub(r"\[/?[^\]]+\]", "", str(msg))
        print(clean)


def strip_emoji(text):
    """Remove emoji and other Unicode pictographs (cp1252 safety)."""
    import re
    pattern = re.compile(
        '[\U0001F600-\U0001F64F'
        '\U0001F300-\U0001F5FF'
        '\U0001F680-\U0001F6FF'
        '\U0001F1E0-\U0001F1FF'
        '\U00002702-\U000027B0'
        '\U000024C2-\U0001F251'
        '\U0001F900-\U0001F9FF'
        '\U0001FA00-\U0001FA6F'
        '\U0001FA70-\U0001FAFF'
        '\U00002600-\U000026FF'
        '\U0000FE00-\U0000FE0F'
        '\U0000200D-\U0000200F'
        ']+', flags=re.UNICODE)
    return pattern.sub('', text)


def info(msg):
    cprint(f"[cyan]{msg}[/cyan]")


def ok(msg):
    cprint(f"[green]{msg}[/green]")


def warn(msg):
    cprint(f"[yellow]{msg}[/yellow]")


def err(msg):
    cprint(f"[bold red]{msg}[/bold red]")


def header(label):
    if HAS_RICH and console is not None:
        console.print()
        console.rule(f"[bold cyan] {label} [/bold cyan]", style="cyan")
    else:
        print(f"\n--- {label} ---")


def status_panel(title, lines):
    """Render a multi-line status panel; falls back to plain print."""
    if HAS_RICH and console is not None:
        body = "\n".join(lines)
        console.print(Panel(body, title=f"[bold magenta]{title}[/bold magenta]",
                            border_style="magenta", padding=(0, 2)))
    else:
        print(f"=== {title} ===")
        for line in lines:
            print(f"  {line}")


def banner_panel(ctx):
    """Startup banner showing session status."""
    lines = [
        f"[bold green]Model:[/bold green]      {ctx.get('model', DEFAULT_MODEL)}",
        f"[bold green]Search:[/bold green]     DuckDuckGo ({ctx.get('n_results', DEFAULT_N_RESULTS)} results/query)",
        f"[bold green]Backend:[/bold green]    Ollama @ {OLLAMA_BASE}",
        f"[bold green]RAG:[/bold green]        {_rag_status_line()}",
        f"[bold green]File tools:[/bold green] {'on' if ctx.get('enable_file_tools', True) else 'off'}",
        f"[bold green]Auto-yes:[/bold green]   {'on' if ctx.get('auto_confirm', False) else 'off (will prompt)'}",
        "",
        "[dim]Type a message and press Enter. Ctrl+C or 'exit' to leave.[/dim]",
        "[dim]Type /help for slash commands. Type /model to switch model.[/dim]",
    ]
    if HAS_RICH and console is not None:
        console.print(BANNER, style="bold cyan")
        status_panel("Session", lines)
    else:
        print(BANNER)
        print(f"=== {title} ===" if False else "")
        for line in lines:
            import re
            print("  " + re.sub(r"\[/?[^\]]+\]", "", line))


# --- HTTP / Ollama ----------------------------------------------------------

def ollama_request(path, payload=None, stream=False, timeout=180):
    """Low-level HTTP call to Ollama (pure urllib, no extra deps)."""
    url = f"{OLLAMA_BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        err(f"Cannot reach Ollama at {OLLAMA_BASE}")
        err(f"  Make sure `ollama serve` is running.  ({e})")
        sys.exit(1)
    if stream:
        return resp
    raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def list_models():
    data = ollama_request("/api/tags")
    models = data.get("models", [])
    if HAS_RICH and console is not None:
        tbl = Table(title="Local Ollama Models", box=box.ROUNDED,
                    style="bold cyan", header_style="bold magenta")
        tbl.add_column("Model", style="green")
        tbl.add_column("Size", style="yellow", justify="right")
        tbl.add_column("Family", style="dim")
        tbl.add_column("Modified", style="dim")
        for m in models:
            size_gb = m.get("size", 0) / 1e9
            mod = m.get("modified_at", "")[:10]
            fam = (m.get("details", {}) or {}).get("family", "")
            tbl.add_row(m["name"], f"{size_gb:.1f} GB", fam, mod)
        console.print(tbl)
    else:
        for m in models:
            print(m["name"])
    return [m["name"] for m in models]


# --- Web search -------------------------------------------------------------

def run_command(command, cwd=None, timeout=120):
    """Run a local shell command and return stdout/stderr."""
    if not command:
        return "Error: no command provided."
    if isinstance(command, str):
        try:
            parts = shlex.split(command)
        except ValueError as e:
            return f"Error parsing command: {e}"
    else:
        parts = list(command)
    if not parts:
        return "Error: no command provided."
    try:
        completed = subprocess.run(
            parts,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
        output_parts = []
        if completed.stdout.strip():
            output_parts.append(completed.stdout.strip())
        if completed.stderr.strip():
            output_parts.append(completed.stderr.strip())
        body = "\n\n".join(output_parts).strip()
        if body:
            return f"Exit code: {completed.returncode}\n\n{body}"
        return f"Exit code: {completed.returncode}"
    except FileNotFoundError:
        return f"Error: command not found: {parts[0]}"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout} seconds."
    except Exception as e:
        return f"Error running command: {e}"


def fetch_url(url, timeout=30):
    """Fetch a URL and return readable text content."""
    if not url:
        return "Error: missing URL."
    cleaned = str(url).strip()
    if not cleaned:
        return "Error: missing URL."
    if not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    req = urllib.request.Request(cleaned, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error fetching {cleaned}: {e}"
    text = re.sub(r"<script[\s\S]*?</script>", " ", content, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    if not text:
        return f"Fetched {cleaned}\n\n(no readable text found)"
    preview = text[:4000]
    return f"Fetched {cleaned}\n\n{preview}"


def web_search(query: str, n: int = DEFAULT_N_RESULTS) -> str:
    """Search the web, or fetch a direct URL when the query is a link."""
    q = (query or "").strip()
    if not q:
        return "Error: empty search query."
    if q.startswith(("http://", "https://")):
        return fetch_url(q)
    if not HAS_DDG:
        try:
            search_url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote(q)
            req = urllib.request.Request(search_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html_text = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            return f"Search error: {e}"
        matches = re.findall(r'<a rel="nofollow" class="result__a" href="(.*?)".*?>(.*?)</a>', html_text, flags=re.S)
        results = []
        for href, title in matches[:n]:
            cleaned_href = html.unescape(re.sub(r"^/l/\?uddg=", "", href))
            cleaned_title = html.unescape(re.sub(r"<[^>]+>", " ", title))
            results.append({"title": re.sub(r"\s+", " ", cleaned_title).strip(), "href": cleaned_href})
        if not results:
            return f"No results found for: {q}"
        lines = [f"Web search results for: '{q}'", f"Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title', 'No title')}")
            lines.append(f"    URL: {r.get('href', '')}")
            lines.append("")
        return "\n".join(lines)
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(q, max_results=n))
        if not results:
            return f"No results found for: {q}"
        lines = [
            f"Web search results for: '{q}'",
            f"Retrieved: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title', 'No title')}")
            lines.append(f"    URL: {r.get('href', '')}")
            lines.append(f"    {r.get('body', '')}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"


def repair_self(path, old_string, new_string, auto_confirm=False):
    """Safely patch a project file in place using the same write logic.

    This is intentionally narrow: it can only edit files inside the project root
    and only when the old text is found exactly once.
    """
    repo_root = os.path.abspath(os.path.dirname(__file__))
    abs_path = os.path.abspath(os.path.join(repo_root, path))
    if os.path.commonpath([repo_root, abs_path]) != repo_root:
        return f"Error: refusing to edit outside project root: {path}"
    if not os.path.exists(abs_path):
        return f"Error: file not found: {abs_path}"
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except Exception as e:
        return f"Error reading {abs_path}: {e}"
    if old_string not in content:
        return f"Error: old_string not found in {abs_path}"
    if content.count(old_string) > 1:
        return f"Error: old_string found multiple times in {abs_path}"
    new_content = content.replace(old_string, new_string, 1)
    return tool_write_file(abs_path, new_content, auto_confirm=auto_confirm)


# --- RAG (ChromaDB + nomic-embed-text) --------------------------------------

_rag_client = None
_rag_collection = None
_rag_meta = {"enabled": False, "chunks": 0, "embed_model": None,
             "top_k": 4, "chunk_size": 500, "sources": []}


def _rag_status_line():
    if not _rag_meta["enabled"]:
        return "off (pass --rag PATH to enable)"
    return (f"on ({_rag_meta['chunks']} chunks, "
            f"embed={_rag_meta['embed_model']}, "
            f"top_k={_rag_meta['top_k']})")


def init_rag(paths, top_k=4, chunk_size=500, persist_dir=None, embed_model="nomic"):
    """Initialize RAG: load files, chunk, embed, store in ChromaDB.
    Shows progress for file discovery, chunking, and embedding phases.
    """
    global _rag_client, _rag_collection
    if not HAS_CHROMA:
        err("chromadb not installed. Run: pip install chromadb")
        return False
    if persist_dir:
        os.makedirs(persist_dir, exist_ok=True)
        _rag_client = chromadb.PersistentClient(path=persist_dir)
    else:
        _rag_client = chromadb.EphemeralClient()
    _rag_collection = _rag_client.get_or_create_collection("docs")

    if embed_model == "nomic":
        model_name = DEFAULT_EMBED_MODEL
    else:
        model_name = embed_model  # treated as ollama model name

    all_chunks = []
    all_ids = []
    all_meta = []
    sources = []

    supported = {".txt", ".md", ".py", ".js", ".ts", ".json", ".yaml",
                 ".yml", ".csv", ".html", ".css", ".xml", ".ini", ".cfg",
                 ".toml", ".sh", ".bat", ".sql", ".log", ".rst"}

    # Phase 1: discover and read files
    info("Scanning files...")
    file_count = 0
    total_bytes = 0
    for p in paths:
        p = os.path.abspath(p)
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    if ext in supported:
                        full = os.path.join(root, f)
                        try:
                            text = open(full, encoding="utf-8", errors="replace").read()
                        except Exception:
                            continue
                        chunks = chunk_text(text, chunk_size)
                        for i, c in enumerate(chunks):
                            all_chunks.append(c)
                            all_ids.append(f"{full}::{i}")
                            all_meta.append({"source": full, "chunk": i})
                        if chunks:
                            sources.append(full)
                            file_count += 1
                            total_bytes += len(text)
        elif os.path.isfile(p):
            ext = os.path.splitext(p)[1].lower()
            if ext in supported:
                try:
                    text = open(p, encoding="utf-8", errors="replace").read()
                except Exception as e:
                    warn(f"Could not read {p}: {e}")
                    continue
                chunks = chunk_text(text, chunk_size)
                for i, c in enumerate(chunks):
                    all_chunks.append(c)
                    all_ids.append(f"{p}::{i}")
                    all_meta.append({"source": p, "chunk": i})
                if chunks:
                    sources.append(p)
                    file_count += 1
                    total_bytes += len(text)
            else:
                warn(f"Skipping unsupported file type: {p}")

    if not all_chunks:
        err("No chunks were produced. Check file types and paths.")
        return False

    info(f"Found {file_count} file(s) ({total_bytes/1024:.1f} KB) -> {len(all_chunks)} chunks")

    # Phase 2: embed with progress
    info(f"Embedding {len(all_chunks)} chunks with {model_name} (via Ollama)...")
    embeddings = []
    BATCH = 50  # embed in smaller batches so we can show progress
    for i in range(0, len(all_chunks), BATCH):
        batch = all_chunks[i:i + BATCH]
        if HAS_RICH and console is not None:
            console.print(f"  [dim]Embedding {i+1}-{min(i+BATCH, len(all_chunks))} / {len(all_chunks)}[/dim]")
        else:
            print(f"  Embedding {i+1}-{min(i+BATCH, len(all_chunks))} / {len(all_chunks)}")
        batch_emb = embed_texts(batch, model_name=model_name)
        embeddings.extend(batch_emb)

    if len(embeddings) != len(all_chunks):
        err(f"Embedding mismatch: got {len(embeddings)} for {len(all_chunks)} chunks.")
        return False

    # Phase 3: store in ChromaDB
    info("Storing in vector database...")
    BATCH = 100
    for i in range(0, len(all_chunks), BATCH):
        _rag_collection.add(
            documents=all_chunks[i:i + BATCH],
            embeddings=embeddings[i:i + BATCH],
            ids=all_ids[i:i + BATCH],
            metadatas=all_meta[i:i + BATCH],
        )

    _rag_meta.update({
        "enabled": True,
        "chunks": len(all_chunks),
        "embed_model": model_name,
        "top_k": top_k,
        "chunk_size": chunk_size,
        "sources": sources,
    })
    ok(f"RAG ready: {len(all_chunks)} chunks from {len(sources)} files.")
    return True


def chunk_text(text, chunk_size=500, overlap=50):
    """Simple character-level sliding-window chunker."""
    if chunk_size <= 0:
        return [text]
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + chunk_size)
        chunks.append(text[start:end])
        if end >= n:
            break
        start += chunk_size - overlap
        if start < 0:
            start = 0
    return [c.strip() for c in chunks if c.strip()]


def embed_texts(texts, model_name=DEFAULT_EMBED_MODEL):
    """Embed a list of strings via Ollama /api/embeddings."""
    out = []
    for t in texts:
        resp = ollama_request("/api/embeddings", payload={"model": model_name, "prompt": t})
        emb = resp.get("embedding")
        if emb is None:
            raise RuntimeError(f"No embedding returned for text of length {len(t)}")
        out.append(emb)
    return out


def search_docs(query, top_k=None):
    """Tool handler: search the RAG index and return formatted excerpts."""
    if not _rag_meta["enabled"] or _rag_collection is None:
        return "No documents have been ingested. Use --rag PATH to load files."
    k = int(top_k) if top_k else _rag_meta["top_k"]
    try:
        q_emb = embed_texts([query], model_name=_rag_meta["embed_model"])[0]
        results = _rag_collection.query(query_embeddings=[q_emb], n_results=k)
    except Exception as e:
        return f"search_docs error: {e}"
    docs = results.get("documents", [[]])[0] if results else []
    metas = results.get("metadatas", [[]])[0] if results else []
    if not docs:
        return f"No relevant documents found for: '{query}'"
    lines = [f"Relevant document excerpts for: '{query}'", ""]
    for i, (doc, meta) in enumerate(zip(docs, metas), 1):
        src = (meta or {}).get("source", "unknown")
        lines.append(f"[Excerpt {i}] (source: {src})")
        lines.append(doc)
        lines.append("")
    return "\n".join(lines)


# --- File tools -------------------------------------------------------------

def _resolve_path(path):
    """Resolve a path; expand home and normalize Windows placeholder users."""
    if not path:
        return os.path.abspath("")

    resolved = os.path.expanduser(path)
    if os.name == "nt":
        user_home = os.path.expanduser("~")
        current_user = os.path.basename(user_home)
        resolved = resolved.replace("YOUR_USER", current_user)
        resolved = resolved.replace("your_user", current_user)
        resolved = resolved.replace("C:\\Users\\" + current_user, user_home)
        resolved = resolved.replace("C:/Users/" + current_user, user_home)

    return os.path.abspath(resolved)


def tool_read_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
        # Truncate very large files in the response.
        if len(content) > 20000:
            content = content[:20000] + f"\n\n... [truncated, file is {len(content)}+ chars]"
        return content
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except PermissionError:
        return f"Error: permission denied: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


def tool_list_dir(path="."):
    abs_path = _resolve_path(path)
    try:
        entries = sorted(os.listdir(abs_path))
        if not entries:
            return f"Directory is empty: {abs_path}"
        preview = "\n".join(entries[:200])
        return f"Directory: {abs_path}\n\n{preview}"
    except FileNotFoundError:
        return f"Error: directory not found: {abs_path}"
    except PermissionError:
        return f"Error: permission denied: {abs_path}"
    except Exception as e:
        return f"Error listing {abs_path}: {e}"


def tool_write_file(path, content, auto_confirm=False):
    abs_path = _resolve_path(path)
    action = "create" if not os.path.exists(abs_path) else "overwrite"
    if action == "overwrite":
        try:
            old = open(abs_path, encoding="utf-8", errors="replace").read()
        except Exception:
            old = ""
        diff = list(difflib.unified_diff(
            old.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"{abs_path} (current)",
            tofile=f"{abs_path} (new)",
            n=2,
        ))
        if diff:
            shown = "".join(diff[:80])
            if HAS_RICH and console is not None:
                console.print(Panel(shown, title=f"[bold yellow]Diff: {action} {abs_path}[/bold yellow]",
                                    border_style="yellow"))
            else:
                print(shown)
        if not auto_confirm:
            try:
                ans = input(f"  Write to {abs_path}? [y/N] ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return "Write cancelled (interrupted)."
            if ans not in {"y", "yes"}:
                return "Write cancelled by user."
        # Backup existing file.
        try:
            shutil.copy2(abs_path, abs_path + ".bak")
        except Exception:
            pass
    try:
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"OK: {action} {abs_path} ({len(content)} chars)"
    except Exception as e:
        return f"Error writing {abs_path}: {e}"


def tool_edit_file(path, old_string, new_string, auto_confirm=False):
    abs_path = _resolve_path(path)
    if not os.path.exists(abs_path):
        return f"Error: file not found: {abs_path}"
    try:
        content = open(abs_path, encoding="utf-8", errors="replace").read()
    except Exception as e:
        return f"Error reading {abs_path}: {e}"
    if old_string not in content:
        return f"Error: old_string not found in {abs_path} (check whitespace/indentation)"
    new_content = content.replace(old_string, new_string, 1)
    return tool_write_file(abs_path, new_content, auto_confirm=auto_confirm)


# --- Streaming chat ---------------------------------------------------------

def chat_stream(model, messages, tools=None, think=False):
    """
    Call /api/chat with stream=True.

    Yields:
      ("text",    delta)        - regular content token
      ("think",   delta)        - chain-of-thought token (only when think=True
                                   and the model emits a "thinking" field)
      ("done",    (full_text, tool_calls))
    """
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    if think:
        payload["think"] = True

    # No timeout on streaming -- the model generates at its own pace
    # and urllib's timeout counts from request start to ANY data arrival,
    # which can be 3+ minutes on a cold/large model with a verbose prompt.
    resp = ollama_request("/api/chat", payload=payload, stream=True, timeout=None)
    full_text = ""
    full_thinking = ""
    tool_calls = []
    try:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = chunk.get("message", {}) or {}
            delta = msg.get("content", "")
            if delta:
                full_text += delta
                yield "text", delta
            thinking_delta = msg.get("thinking", "")
            if thinking_delta:
                full_thinking += thinking_delta
                yield "think", thinking_delta
            # Tool calls can appear in ANY chunk, not just the done chunk.
            tc = msg.get("tool_calls") or []
            if tc:
                tool_calls = tc
            if chunk.get("done"):
                yield "done", (full_text, tool_calls, full_thinking)
                return
    finally:
        try:
            resp.close()
        except Exception:
            pass
    yield "done", (full_text, tool_calls, full_thinking)


# --- Tool-support detection -------------------------------------------------

def check_tool_support(model):
    """
    Probe for native tool-calling by sending a prompt that *requires* a
    tool call. The probe itself acts as a model warmup -- the single
    /api/chat call loads a cold model into memory.
    """
    probe_tools = [{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }]
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": ("What is the current weather in Mumbai right now? "
                        "You MUST call the web_search tool to answer. "
                        "Do not answer from memory."),
        }],
        "tools": probe_tools,
        "stream": False,
    }
    saved_exit = sys.exit
    sys.exit = lambda *a, **k: (_ for _ in ()).throw(SystemExit())
    try:
        try:
            result = ollama_request("/api/chat", payload=payload, timeout=120)
        except SystemExit:
            return False
        except Exception:
            return False
        msg = (result or {}).get("message", {}) or {}
        tc = msg.get("tool_calls") or []
        return bool(tc)
    finally:
        sys.exit = saved_exit


# --- Tool definitions (Ollama tool-calling format) ---------------------------

def build_tools(enable_rag=True, enable_file_tools=True):
    tools = [
        {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the public internet for current information, or fetch a direct URL "
                    "when the user gives a link."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The search query or full URL."},
                        "num_results": {"type": "integer",
                                        "description": "How many results to return (default 5).",
                                        "default": 5},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Open and read a specific URL directly, returning the fetched text content.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The full URL to fetch."},
                    },
                    "required": ["url"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a local shell command and return the output. Use this for git clone, pip install, python scripts, and other CLI tasks.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": ["string", "array"],
                            "description": "Shell command as a string or argv list.",
                        },
                        "cwd": {"type": "string", "description": "Optional working directory for the command."},
                        "timeout": {"type": "integer", "description": "Timeout in seconds.", "default": 120},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "repair_self",
                "description": "Patch this project file in place to fix or improve the agent implementation. Use only for scoped changes inside the repository.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to edit, relative to the project root."},
                        "old_string": {"type": "string", "description": "Exact existing text to replace."},
                        "new_string": {"type": "string", "description": "Replacement text."},
                    },
                    "required": ["path", "old_string", "new_string"],
                },
            },
        },
    ]
    if enable_rag:
        tools.append({
            "type": "function",
            "function": {
                "name": "search_docs",
                "description": (
                    "Search the user's locally-ingested documents (RAG index) for "
                    "relevant passages. Use this whenever the user asks about their "
                    "own files, codebase, notes, or uploaded documents."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string",
                                  "description": "What to search for in the documents."},
                        "top_k": {"type": "integer",
                                  "description": "Number of chunks to retrieve (default 4).",
                                  "default": 4},
                    },
                    "required": ["query"],
                },
            },
        })
    if enable_file_tools:
        tools.extend([
            {
                "type": "function",
                "function": {
                    "name": "list_dir",
                    "description": "List the contents of a directory so the agent can inspect or organize files on the machine.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Directory path to list."},
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": ("Read the contents of a text file. Use this before "
                                    "editing to confirm current content."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string",
                                     "description": "Absolute or relative file path."},
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": ("Create or overwrite a file. The user will be "
                                    "shown a diff and asked to confirm before the "
                                    "write happens, unless auto-confirm is on."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to write to."},
                            "content": {"type": "string",
                                        "description": "Full new contents of the file."},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "edit_file",
                    "description": ("Edit a file by replacing an exact string with new text. "
                                    "Use this for precise find-and-replace patches."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path to edit."},
                            "old_string": {"type": "string",
                                           "description": "Exact text to find (must appear exactly once)."},
                            "new_string": {"type": "string",
                                           "description": "Replacement text."},
                        },
                        "required": ["path", "old_string", "new_string"],
                    },
                },
            },
        ])
    return tools


TOOLS = build_tools(enable_rag=True, enable_file_tools=True)


# --- System prompt ----------------------------------------------------------


SYSTEM_PROMPT_BASE = """\
You are an expert assistant in a local CLI. You have tools -- they are listed \
below and are ready to use. Call them whenever the user asks for current \
information, web searches, file operations, or anything requiring external data.

Rules:
- When the user asks you to search, call web_search immediately.
- When the user is given a URL, call fetch_url directly to read it.
- When the user asks to run commands, install packages, clone repos, or execute scripts, call run_command.
- When the user asks the agent to improve or repair itself, call repair_self for scoped edits to project files.
- When the user asks about their files or code, call search_docs.
- Do not refuse to use tools. Do not say tools are unavailable.
- Be direct and concise. Use markdown, no emoji.
- Cite source URLs when using web search.
- For write_file / edit_file, the user will be prompted to confirm.
"""

SYSTEM_PROMPT_SHORT = """\
You are a helpful assistant in a CLI. Use your tools when needed. Be concise.
"""


def build_system_prompt(ctx):
    """Compose the system prompt."""
    parts = [SYSTEM_PROMPT_BASE]
    if ctx.get("auto_confirm"):
        parts.append(
            "\n## Note\n"
            "Auto-confirm is ON for this session. File write/edit operations "
            "will be applied immediately without asking the user. Be careful."
        )
    return "\n".join(parts)


# --- Prompt-injection fallback ---------------------------------------------

INJECTION_SYSTEM = """\
You are a CLI assistant without native tool-calling. To use a tool, emit ONE of \
these tags in your output then STOP and wait for the result:

  SEARCH: <query>
  SEARCH_DOCS: <query>
  FETCH_URL: <url>
  RUN_COMMAND: <command>
  REPAIR_SELF: <path>
  LIST_DIR: <path>
  READ_FILE: <path>
  WRITE_FILE: <path>
  ...content...
  END_WRITE_FILE
  EDIT_FILE: <path>
  <old>
  ---
  <new>
  END_EDIT_FILE

Do NOT guess results. After I return the tool output, continue your answer.
"""


def _read_block(text, start_idx, end_marker):
    """Helper: starting at line index `start_idx` (after a tag line), collect
    subsequent lines until `end_marker` or end of text. Returns (block, next_idx).
    """
    lines = text.splitlines()
    block_lines = []
    i = start_idx
    while i < len(lines):
        if lines[i].strip() == end_marker:
            i += 1
            break
        block_lines.append(lines[i])
        i += 1
    return "\n".join(block_lines), i


def extract_tool_calls(text):
    """Parse the model's text output for any of the supported injection tags.

    Returns a list of (tool_name, args_dict) tuples in document order.
    """
    calls = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        upper = s.upper()
        if upper.startswith("SEARCH:"):
            q = s[7:].strip()
            if q:
                calls.append(("web_search", {"query": q}))
            i += 1
        elif upper.startswith("SEARCH_DOCS:"):
            q = s[len("SEARCH_DOCS:"):].strip()
            if q:
                calls.append(("search_docs", {"query": q}))
            i += 1
        elif upper.startswith("FETCH_URL:"):
            u = s[len("FETCH_URL:"):].strip()
            if u:
                calls.append(("fetch_url", {"url": u}))
            i += 1
        elif upper.startswith("RUN_COMMAND:"):
            cmd = s[len("RUN_COMMAND:"):].strip()
            if cmd:
                calls.append(("run_command", {"command": cmd}))
            i += 1
        elif upper.startswith("REPAIR_SELF:"):
            p = s[len("REPAIR_SELF:"):].strip()
            if p:
                rest, end_i = _read_block(text, i + 1, "END_REPAIR_SELF")
                if "---" in rest:
                    old, new = rest.split("---", 1)
                    calls.append(("repair_self", {
                        "path": p,
                        "old_string": old.strip("\n"),
                        "new_string": new.strip("\n"),
                    }))
                else:
                    calls.append(("repair_self", {"path": p}))
                i = end_i
            else:
                i += 1
        elif upper.startswith("READ_FILE:"):
            p = s[len("READ_FILE:"):].strip()
            if p:
                calls.append(("read_file", {"path": p}))
            i += 1
        elif upper.startswith("LIST_DIR:"):
            p = s[len("LIST_DIR:"):].strip()
            calls.append(("list_dir", {"path": p or "."}))
            i += 1
        elif upper.startswith("WRITE_FILE:"):
            p = s[len("WRITE_FILE:"):].strip()
            if p:
                content, next_i = _read_block(text, i + 1, "END_WRITE_FILE")
                calls.append(("write_file", {"path": p, "content": content}))
                # Advance to the line after END_WRITE_FILE (or EOF).
                i = i + 1 + content.count("\n") + 1
            else:
                i += 1
        elif upper.startswith("EDIT_FILE:"):
            p = s[len("EDIT_FILE:"):].strip()
            if p:
                # Format:  EDIT_FILE: <path>\n<old>\n---\n<new>\nEND_EDIT_FILE
                rest, end_i = _read_block(text, i + 1, "END_EDIT_FILE")
                if "---" in rest:
                    old, new = rest.split("---", 1)
                    calls.append(("edit_file", {
                        "path": p,
                        "old_string": old.rstrip("\n"),
                        "new_string": new.rstrip("\n"),
                    }))
                i = end_i
            else:
                i += 1
        else:
            i += 1
    return calls


# Backward-compat alias used elsewhere in the module.
def extract_search_queries(text):
    return [args["query"] for name, args in extract_tool_calls(text)
            if name == "web_search" and args.get("query")]


# --- Tool dispatch ---------------------------------------------------------

def dispatch_tool_call(name, args, ctx):
    """Run a single tool call. Returns the tool's result as a string."""
    auto = bool(ctx.get("auto_confirm", False))
    enable_files = bool(ctx.get("enable_file_tools", True))
    enable_rag = bool(ctx.get("enable_rag", True))

    if name == "web_search":
        q = args.get("query", "")
        n = int(args.get("num_results", ctx.get("n_results", DEFAULT_N_RESULTS)))
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold yellow]web_search[/bold yellow]  {q}",
                border_style="yellow", padding=(0, 1)))
        else:
            print(f"\n>> web_search: {q}")
        result = web_search(q, n)
        if HAS_RICH and console is not None:
            count = sum(1 for line in result.splitlines() if line.startswith("["))
            console.print(f"[dim]  -> {count} result(s)[/dim]")
        return result

    if name == "search_docs":
        if not enable_rag:
            return "RAG is disabled in this session."
        q = args.get("query", "")
        k = args.get("top_k")
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold cyan]search_docs[/bold cyan]  {q}",
                border_style="cyan", padding=(0, 1)))
        else:
            print(f"\n>> search_docs: {q}")
        return search_docs(q, k)

    if name == "fetch_url":
        url = args.get("url", "")
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold blue]fetch_url[/bold blue]  {url}",
                border_style="blue", padding=(0, 1)))
        else:
            print(f"\n>> fetch_url: {url}")
        return fetch_url(url)

    if name == "run_command":
        command = args.get("command", "")
        cwd = args.get("cwd")
        timeout = args.get("timeout", 120)
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold magenta]run_command[/bold magenta]  {command}",
                border_style="magenta", padding=(0, 1)))
        else:
            print(f"\n>> run_command: {command}")
        return run_command(command, cwd=cwd, timeout=int(timeout))

    if name == "repair_self":
        path = args.get("path", "")
        old_string = args.get("old_string", "")
        new_string = args.get("new_string", "")
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold red]repair_self[/bold red]  {path}",
                border_style="red", padding=(0, 1)))
        else:
            print(f"\n>> repair_self: {path}")
        return repair_self(path, old_string, new_string, auto_confirm=auto)

    if name == "list_dir":
        if not enable_files:
            return "File tools are disabled in this session."
        path = args.get("path", ".")
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold green]list_dir[/bold green]  {path}",
                border_style="green", padding=(0, 1)))
        else:
            print(f"\n>> list_dir: {path}")
        return tool_list_dir(path)

    if name == "read_file":
        if not enable_files:
            return "File tools are disabled in this session."
        path = args.get("path", "")
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold green]read_file[/bold green]  {path}",
                border_style="green", padding=(0, 1)))
        else:
            print(f"\n>> read_file: {path}")
        return tool_read_file(path)

    if name == "write_file":
        if not enable_files:
            return "File tools are disabled in this session."
        path = args.get("path", "")
        content = args.get("content", "")
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold red]write_file[/bold red]  {path} ({len(content)} chars)",
                border_style="red", padding=(0, 1)))
        else:
            print(f"\n>> write_file: {path}")
        return tool_write_file(path, content, auto_confirm=auto)

    if name == "edit_file":
        if not enable_files:
            return "File tools are disabled in this session."
        path = args.get("path", "")
        old = args.get("old_string", "")
        new = args.get("new_string", "")
        if HAS_RICH and console is not None:
            console.print(Panel(
                f"[bold red]edit_file[/bold red]  {path}",
                border_style="red", padding=(0, 1)))
        else:
            print(f"\n>> edit_file: {path}")
        return tool_edit_file(path, old, new, auto_confirm=auto)

    return f"Unknown tool: {name}"


# --- Agent loops ------------------------------------------------------------

def run_agent_native(model, messages, ctx):
    """Agentic loop using Ollama's native tool-calling API."""
    local_messages = messages[:]
    tools = build_tools(enable_rag=ctx.get("enable_rag", True),
                        enable_file_tools=ctx.get("enable_file_tools", True))
    collected_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        header(f"{model}")

        # Stream tokens directly to stdout (NO rich.live.Live - that buffers and
        # can deadlock on Windows cp1252). Then render as Markdown after.
        collected_text = ""
        final_tool_calls = []
        think = bool(ctx.get("think", False))
        for event, data in chat_stream(model, local_messages, tools=tools, think=think):
            if event == "text":
                cleaned = strip_emoji(data)
                print(cleaned, end="", flush=True)
                collected_text += data
            elif event == "think":
                cleaned = strip_emoji(data)
                if HAS_RICH and console is not None:
                    console.print(cleaned, end="", style="dim")
                else:
                    print(f"\033[2m{data}\033[0m", end="", flush=True)
            elif event == "done":
                collected_text, final_tool_calls, _thinking = data

        # Final newline after the streamed tokens.
        print()

        if not final_tool_calls:
            local_messages.append({"role": "assistant", "content": collected_text})
            break

        # Record the assistant turn (including any tool_calls it made).
        local_messages.append({
            "role": "assistant",
            "content": collected_text,
            "tool_calls": final_tool_calls,
        })

        # Execute each tool call, append the tool result.
        for tc in final_tool_calls:
            fn = (tc or {}).get("function", {}) or {}
            fname = fn.get("name", "")
            args = fn.get("arguments", {}) or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args.strip() else {}
                except Exception:
                    args = {}
            try:
                result = dispatch_tool_call(fname, args, ctx)
            except Exception as e:
                result = f"Tool error in {fname}: {e}"
            local_messages.append({"role": "tool", "content": result})

    messages.clear()
    messages.extend(local_messages)
    return collected_text


def run_agent_fallback(model, messages, ctx):
    """Agentic loop via tagged-line prompt injection.

    Recognises SEARCH, SEARCH_DOCS, READ_FILE, WRITE_FILE, EDIT_FILE tags
    in the model's text output and dispatches them through the same
    handlers the native tool-calling loop uses.
    """
    local_messages = messages[:]
    collected_text = ""

    for _ in range(MAX_TOOL_ROUNDS):
        header(f"{model} (fallback)")

        collected_text = ""
        think = bool(ctx.get("think", False))
        for event, data in chat_stream(model, local_messages, tools=None, think=think):
            if event == "text":
                cleaned = strip_emoji(data)
                print(cleaned, end="", flush=True)
                collected_text += data
            elif event == "think":
                cleaned = strip_emoji(data)
                if HAS_RICH and console is not None:
                    console.print(cleaned, end="", style="dim")
                else:
                    print(f"\033[2m{data}\033[0m", end="", flush=True)
            elif event == "done":
                # data = (full_text, [], thinking) - tools are empty in fallback.
                collected_text, _, _ = data
        # Final newline after streaming completes.
        print()

        tool_calls = extract_tool_calls(collected_text)
        if not tool_calls:
            local_messages.append({"role": "assistant", "content": collected_text})
            break

        local_messages.append({"role": "assistant", "content": collected_text})
        for name, args in tool_calls:
            try:
                result = dispatch_tool_call(name, args, ctx)
            except Exception as e:
                result = f"Tool error in {name}: {e}"
            local_messages.append({
                "role": "user",
                "content": f"Tool `{name}` returned:\n\n{result}\n\nContinue your answer.",
            })

    messages.clear()
    messages.extend(local_messages)
    return collected_text


# --- Slash commands / skills ------------------------------------------------

class Skill:
    """A slash command. Subclass or use the (name, desc, handler) tuple form."""
    def __init__(self, name, description, handler, aliases=None):
        self.name = name
        self.description = description
        self.handler = handler  # signature: (args: str, ctx: dict) -> str | None
        self.aliases = aliases or []

    def matches(self, line):
        parts = line.strip().split(None, 1)
        if not parts:
            return False
        cmd = parts[0].lower().lstrip("/")
        return cmd == self.name.lower() or cmd in [a.lower() for a in self.aliases]


def _models_command(args, ctx):
    rows = list_models()
    return f"{len(rows)} model(s) available."


def _model_command(args, ctx):
    name = args.strip()
    if not name:
        return f"Current model: {ctx.get('model')}"
    # Verify model exists.
    try:
        available = [m["name"] for m in ollama_request("/api/tags").get("models", [])]
    except Exception as e:
        return f"Could not list models: {e}"
    if name not in available:
        # Allow common short forms.
        candidates = [m for m in available if name in m]
        if len(candidates) == 1:
            name = candidates[0]
        elif len(candidates) > 1:
            return f"Ambiguous model '{name}'. Candidates: {candidates}"
        else:
            return f"Model '{name}' not found. Available: {available}"
    ctx["model"] = name
    ok(f"Model switched to: {name}")
    return None  # do not feed to LLM


def _tools_command(args, ctx):
    tools = build_tools(enable_rag=ctx.get("enable_rag", True),
                        enable_file_tools=ctx.get("enable_file_tools", True))
    if HAS_RICH and console is not None:
        tbl = Table(title="Registered Tools", box=box.ROUNDED, style="bold cyan")
        tbl.add_column("Tool", style="green")
        tbl.add_column("Description", style="white")
        for t in tools:
            fn = t.get("function", {})
            tbl.add_row(fn.get("name", "?"), fn.get("description", "")[:80])
        console.print(tbl)
    else:
        for t in tools:
            fn = t.get("function", {})
            print(f"  {fn.get('name', '?')}: {fn.get('description', '')[:80]}")
    return None


def _clear_command(args, ctx):
    if "messages" in ctx and ctx["messages"]:
        ctx["messages"][:] = [ctx["messages"][0]]  # keep system prompt
        ok("Conversation cleared (system prompt retained).")
    return None


def _system_command(args, ctx):
    msgs = ctx.get("messages", [])
    if msgs and msgs[0].get("role") == "system":
        print(msgs[0]["content"])
    else:
        print("(no system prompt set)")
    return None


def _reset_command(args, ctx):
    # Re-initialize the system prompt from the current config.
    sys_prompt = build_system_prompt(ctx)
    if "messages" in ctx:
        if ctx["messages"] and ctx["messages"][0].get("role") == "system":
            ctx["messages"][0] = {"role": "system", "content": sys_prompt}
        else:
            ctx["messages"].insert(0, {"role": "system", "content": sys_prompt})
    ok("System prompt reset.")
    return None


def _yes_command(args, ctx):
    ctx["auto_confirm"] = True
    ok("Auto-confirm ON. File writes will apply without prompting.")
    return None


def _no_command(args, ctx):
    ctx["auto_confirm"] = False
    warn("Auto-confirm OFF. File writes will prompt for confirmation.")
    return None


def _rag_command(args, ctx):
    status_panel("RAG", [
        f"Enabled:    {_rag_meta['enabled']}",
        f"Chunks:     {_rag_meta['chunks']}",
        f"Embed:      {_rag_meta['embed_model']}",
        f"Top-K:      {_rag_meta['top_k']}",
        f"Chunk size: {_rag_meta['chunk_size']}",
        f"Sources:    {len(_rag_meta['sources'])} file(s)",
    ])
    if args.strip() == "off":
        _rag_meta["enabled"] = False
        ctx["enable_rag"] = False
        warn("RAG disabled for this session.")
    elif args.strip() == "on":
        if _rag_collection is not None:
            _rag_meta["enabled"] = True
            ctx["enable_rag"] = True
            ok("RAG re-enabled.")
        else:
            warn("RAG was never initialized. Pass --rag PATH at startup.")
    return None


def _web_command(args, ctx):
    """Run a one-off web search and show results."""
    q = args.strip()
    if not q:
        warn("Usage: /web <query>")
        return None
    n = ctx.get("n_results", DEFAULT_N_RESULTS)
    info(f"Searching web for: {q}")
    result = web_search(q, n)
    if HAS_RICH and console is not None:
        console.print(Panel(result, title="[bold yellow]Web Search Results[/bold yellow]", border_style="yellow"))
    else:
        print(f"\n=== Web Search: {q} ===\n{result}")
    return None


def _history_command(args, ctx):
    msgs = ctx.get("messages", [])
    if HAS_RICH and console is not None:
        tbl = Table(title=f"Conversation History ({len(msgs)} messages)",
                    box=box.ROUNDED, style="bold cyan")
        tbl.add_column("#", style="dim")
        tbl.add_column("Role", style="green")
        tbl.add_column("Preview", style="white")
        for i, m in enumerate(msgs):
            role = m.get("role", "?")
            content = (m.get("content") or "")
            if isinstance(content, list):
                content = json.dumps(content)
            preview = (content[:100] + "...") if len(content) > 100 else content
            preview = preview.replace("\n", " ")
            tbl.add_row(str(i), role, preview)
        console.print(tbl)
    else:
        for i, m in enumerate(msgs):
            print(f"{i:3} {m.get('role'):10} {(m.get('content') or '')[:80]}")
    return None


def _save_command(args, ctx):
    path = args.strip() or f"ollama_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    try:
        msgs = ctx.get("messages", [])
        model = ctx.get("model", "unknown")
        is_md = path.lower().endswith((".md", ".markdown"))
        with open(path, "w", encoding="utf-8") as f:
            if is_md:
                f.write(f"# Session: {model}\n\n")
                f.write(f"_Saved: {datetime.now().strftime('%Y-%m-%d %H:%M')}_\n\n")
                f.write("---\n\n")
                for m in msgs:
                    role = m.get("role", "?")
                    content = m.get("content", "")
                    if role == "system":
                        f.write(f"## System\n\n{content}\n\n---\n\n")
                    elif role == "user":
                        f.write(f"## You\n\n{content}\n\n---\n\n")
                    elif role == "assistant":
                        f.write(f"## {model}\n\n{content}\n\n---\n\n")
                    elif role == "tool":
                        f.write(f"### Tool result\n\n{content}\n\n---\n\n")
            else:
                json.dump({"model": model, "messages": msgs}, f, indent=2, ensure_ascii=False)
        ok(f"Saved session to {path}")
    except Exception as e:
        err(f"Save failed: {e}")
    return None


def _load_command(args, ctx):
    path = args.strip()
    if not path:
        warn("Usage: /load <path>")
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ctx["messages"] = data.get("messages", [])
        if data.get("model"):
            ctx["model"] = data["model"]
        ok(f"Loaded session from {path}")
    except Exception as e:
        err(f"Load failed: {e}")
    return None


def _split_task_for_agents(task, count):
    import re
    text = (task or "").strip()
    if not text:
        return [f"Subtask {i + 1} of {count}: continue the task." for i in range(count)]

    sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text) if s.strip()]
    if not sentences:
        words = text.split()
        if len(words) <= count:
            return [w for w in words] or [text]
        parts = []
        for i in range(count):
            start = i * len(words) // count
            end = (i + 1) * len(words) // count
            parts.append(" ".join(words[start:end]).strip())
        return parts

    if len(sentences) <= count:
        return sentences[:count] + [f"Subtask {len(sentences) + 1} of {count}: continue the task." for _ in range(count - len(sentences))]

    per_agent = len(sentences) // count
    remainder = len(sentences) % count
    chunks = []
    start = 0
    for i in range(count):
        size = per_agent + (1 if i < remainder else 0)
        end = start + size
        chunks.append(" ".join(sentences[start:end]).strip())
        start = end
    return chunks


def _extract_model_size(model_name):
    import re
    match = re.search(r"(\d+(?:\.\d+)?)\s*b", (model_name or "").lower())
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _resolve_spawn_model(model, ctx):
    requested_size = _extract_model_size(model)
    if requested_size is not None and requested_size <= 2.0:
        return model

    try:
        available = ollama_request("/api/tags").get("models", [])
    except Exception as e:
        warn(f"Could not list available models for spawn: {e}")
        return None

    candidates = []
    for entry in available:
        name = (entry or {}).get("name") or ""
        size = _extract_model_size(name)
        if size is None or size > 2.0:
            continue
        candidates.append(name)

    if not candidates:
        warn("Spawn requires a 2B-or-smaller model, but none are currently available.")
        return None

    preferred = [n for n in candidates if "qwen3.5:2b" in n.lower() or "qwen3.5:1b" in n.lower()]
    return preferred[0] if preferred else candidates[0]


def _synthesize_spawn_results(model, task, results, ctx):
    synthesis_messages = [{"role": "system", "content": build_system_prompt(ctx)}]
    synthesis_messages.append({
        "role": "user",
        "content": (
            "You are the final synthesis agent. Combine the subagent outputs below into one "
            "brief, structured summary. Keep the answer concise, readable, and action-oriented.\n\n"
            f"Original task: {task}\n\n"
            "Subagent outputs:\n"
            + "\n\n".join(results)
        ),
    })

    try:
        if ctx.get("_supports_tools"):
            return run_agent_native(model, synthesis_messages, ctx).strip()
        return run_agent_fallback(model, synthesis_messages, ctx).strip()
    except Exception as e:
        return f"Synthesis error: {e}"


def run_spawn_agents(model, task, ctx, count=1):
    count = max(1, min(int(count), 5))
    spawn_model = _resolve_spawn_model(model, ctx)
    if not spawn_model:
        return "Spawn aborted: no 2B-or-smaller model is available for subagents."

    info(f"Spawning {count} subagent(s) to divide the work with {spawn_model}...")
    parts = _split_task_for_agents(task, count)
    results = []

    for idx, part in enumerate(parts, 1):
        submessages = [{"role": "system", "content": build_system_prompt(ctx)}]
        submessages.append({
            "role": "user",
            "content": (
                f"You are subagent {idx}/{count}. Focus only on the following subtask and "
                f"return a concise, actionable result. Do not repeat the full task.\n\n"
                f"Subtask: {part}"
            ),
        })

        try:
            if ctx.get("_supports_tools"):
                output = run_agent_native(spawn_model, submessages, ctx)
            else:
                output = run_agent_fallback(spawn_model, submessages, ctx)
        except Exception as e:
            output = f"Subagent {idx} error: {e}"

        cleaned = output.strip()
        results.append(f"Subagent {idx}/{count}: {cleaned}")

    synthesized = _synthesize_spawn_results(spawn_model, task, results, ctx)
    return "\n\n".join([
        "Spawn plan:",
        "\n\n".join(results),
        "\n\nFinal synthesis:",
        synthesized,
    ])


def _spawn_command(args, ctx):
    parts = args.strip().split(None, 1)
    if not parts:
        warn("Usage: /spawn <n> [task]")
        return None
    try:
        count = int(parts[0])
    except ValueError:
        warn("Usage: /spawn <n> [task]")
        return None
    task = parts[1].strip() if len(parts) > 1 else ""
    if not task:
        task = "Please break this request into N parts and work on the most important first steps."
    result = run_spawn_agents(ctx.get("model"), task, ctx, count=count)
    print(result)
    return None


def _exit_command(args, ctx):
    raise SystemExit(0)


def _help_command(args, ctx):
    if HAS_RICH and console is not None:
        tbl = Table(title="Slash Commands", box=box.ROUNDED,
                    style="bold cyan", header_style="bold magenta")
        tbl.add_column("Command", style="green")
        tbl.add_column("Description", style="white")
        for s in ctx["_skills"]:
            tbl.add_row("/" + s.name, s.description)
        console.print(tbl)
    else:
        for s in ctx["_skills"]:
            print(f"  /{s.name:14} {s.description}")
    return None


SKILLS = [
    Skill("help",      "Show this help table.",                                 _help_command,      aliases=["?"]),
    Skill("exit",      "Exit the REPL.",                                       _exit_command,      aliases=["quit", "q", "bye"]),
    Skill("clear",     "Clear conversation (keeps system prompt).",             _clear_command),
    Skill("reset",     "Rebuild the system prompt from current config.",       _reset_command),
    Skill("model",     "Show or switch model: /model [name].",                 _model_command),
    Skill("models",    "List local Ollama models.",                            _models_command),
    Skill("tools",     "List tools the model can call.",                       _tools_command),
    Skill("system",    "Print the current system prompt.",                     _system_command),
    Skill("history",   "Show conversation history.",                          _history_command),
    Skill("rag",       "Show RAG status.  /rag on | /rag off",                 _rag_command),
    Skill("web",       "Run a one-off web search: /web <query>",               _web_command),
    Skill("yes",       "Auto-confirm file writes for the rest of the session.",_yes_command),
    Skill("no",        "Turn off auto-confirm.",                               _no_command),
    Skill("save",      "Save session to Markdown/JSON: /save [path]",          _save_command),
    Skill("load",      "Load session from JSON: /load <path>",                 _load_command),
    Skill("spawn",     "Spawn N subagents to divide a task: /spawn 3 <goal>", _spawn_command),
]


def load_external_skills(skills_dir):
    """Load .py files in skills/ - each should expose a `register()` function
    that returns a list of (name, description, handler) tuples or Skill objects."""
    if not os.path.isdir(skills_dir):
        return []
    loaded = []
    import importlib.util
    for fname in sorted(os.listdir(skills_dir)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(skills_dir, fname)
        try:
            spec = importlib.util.spec_from_file_location(f"skill_{fname[:-3]}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            reg = getattr(mod, "register", None)
            if reg is None:
                continue
            result = reg()
            for item in result:
                if isinstance(item, Skill):
                    loaded.append(item)
                else:
                    name, desc, handler = item
                    loaded.append(Skill(name, desc, handler))
        except Exception as e:
            warn(f"Failed to load skill {fname}: {e}")
    return loaded


def handle_command(line, ctx):
    """If line is a slash command, run it and return True."""
    stripped = line.strip()
    if not stripped.startswith("/"):
        return False
    for s in ctx["_skills"]:
        if s.matches(stripped):
            args = stripped.split(None, 1)
            args_str = args[1] if len(args) > 1 else ""
            try:
                s.handler(args_str, ctx)
            except SystemExit:
                raise
            except Exception as e:
                err(f"Command /{s.name} failed: {e}")
            return True
    warn(f"Unknown command: {stripped.split(None,1)[0]}.  Type /help.")
    return True


def parse_spawn_request(line):
    import re
    match = re.search(
        r"\bspawn\s+(\d+)\s+(?:agents?|subagents?)\b",
        line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    count = int(match.group(1))
    task = line[match.end():].strip()
    return count, task


# --- REPL -------------------------------------------------------------------

def prompt_user(ctx):
    if HAS_RICH and console is not None:
        console.print()
        try:
            line = Prompt.ask(f"[bold blue][[/bold blue][bold magenta]{ctx.get('model','?').split(':')[0]}[/bold magenta][bold blue]] You[/bold blue]").strip()
        except (KeyboardInterrupt, EOFError):
            raise
    else:
        try:
            line = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            raise
    return line


def run_chat(ctx):
    model = ctx["model"]
    sys_prompt = build_system_prompt(ctx)  # noqa
    messages = [{"role": "system", "content": sys_prompt}]
    ctx["messages"] = messages
    ctx["_skills"] = SKILLS + ctx.get("_extra_skills", [])

    # If we're resuming a saved session, splice its history in (after the
    # freshly-built system prompt). The old system message is dropped.
    if ctx.get("initial_messages"):
        old_msgs = ctx["initial_messages"]
        # Drop any system messages from the saved file; we have a fresh one.
        user_msgs = [m for m in old_msgs if m.get("role") != "system"]
        messages.extend(user_msgs)
        info(f"Resumed {len(user_msgs)} prior message(s).")

    # Banner + status.
    banner_panel(ctx)

    # Tool-support check (also acts as model warmup).
    info("Probing model for native tool-calling support...")
    supports = check_tool_support(model)
    if supports:
        ok("Native tool-calling ENABLED.")
    else:
        warn("Native tool-calling not detected. Falling back to prompt-injection mode.")
    ctx["_supports_tools"] = supports

    # Auto-save hook for /session.
    def _auto_save_session():
        path = ctx.get("session_path")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({
                    "model": ctx.get("model"),
                    "messages": ctx.get("messages", []),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            warn(f"Auto-save to {path} failed: {e}")

    while True:
        try:
            user_input = prompt_user(ctx)
        except (KeyboardInterrupt, EOFError):
            print()
            ok("Goodbye.")
            _auto_save_session()
            break

        if not user_input:
            continue

        spawn_count, spawn_task = parse_spawn_request(user_input)
        if spawn_count is not None:
            task = spawn_task or user_input
            result = run_spawn_agents(model, task, ctx, count=spawn_count)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": result})
            _auto_save_session()
            continue

        # Slash commands.
        if user_input.startswith("/"):
            try:
                handle_command(user_input, ctx)
            except SystemExit:
                _auto_save_session()
                ok("Goodbye.")
                break
            _auto_save_session()  # also save after state-changing commands
            continue

        messages.append({"role": "user", "content": user_input})

        # Keep history bounded.
        if len(messages) > MAX_HISTORY + 1:
            sys_msg = messages[0]
            messages[:] = [sys_msg] + messages[-(MAX_HISTORY):]

        try:
            if ctx.get("_supports_tools"):
                run_agent_native(ctx["model"], messages, ctx)
            else:
                run_agent_fallback(ctx["model"], messages, ctx)
        except KeyboardInterrupt:
            warn("(interrupted - starting a new turn)")
            if messages and messages[-1].get("role") == "user":
                messages.pop()


# --- Entry point ------------------------------------------------------------

def main():
    global OLLAMA_BASE
    parser = argparse.ArgumentParser(
        description="Local Ollama CLI agent with web search, RAG, and file tools.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python ollama_web.py
              python ollama_web.py -m qwen3.5:9b
              python ollama_web.py -m gemma4:12b -n 8
              python ollama_web.py --rag ./docs --rag-persist ./rag_db
              python ollama_web.py --list
        """),
    )
    parser.add_argument("-m", "--model", default=None,
                        help="Ollama model to use (default: auto-detect).")
    parser.add_argument("-n", "--num-results", type=int, default=DEFAULT_N_RESULTS,
                        dest="num_results",
                        help=f"Number of search results per query (default: {DEFAULT_N_RESULTS}).")
    parser.add_argument("--list", action="store_true",
                        help="List all available local models and exit.")
    parser.add_argument("--base-url", default=OLLAMA_BASE,
                        help=f"Ollama API base URL (default: {OLLAMA_BASE}).")
    # RAG flags
    parser.add_argument("--rag", action="append", default=[],
                        metavar="PATH",
                        help="Ingest file or folder for RAG (repeatable).")
    parser.add_argument("--rag-top-k", type=int, default=4, dest="rag_top_k",
                        help="Chunks to retrieve (default: 4).")
    parser.add_argument("--rag-chunk-size", type=int, default=500, dest="rag_chunk_size",
                        help="Chars per chunk (default: 500).")
    parser.add_argument("--rag-persist", default=None, dest="rag_persist",
                        help="Persist ChromaDB to this directory.")
    parser.add_argument("--rag-embed-model", default="nomic", dest="rag_embed_model",
                        help="Embedding model (default: nomic-embed-text via Ollama).")
    # File / behavior flags
    parser.add_argument("--no-file-tools", action="store_true", dest="no_file_tools",
                        help="Disable read/write/edit tools.")
    parser.add_argument("--no-rag", action="store_true", dest="no_rag",
                        help="Disable RAG even if --rag is passed.")
    parser.add_argument("--no-search", action="store_true", dest="no_search",
                        help="Disable web_search tool.")
    parser.add_argument("--yes", action="store_true", dest="yes",
                        help="Auto-confirm all file writes (dangerous).")
    parser.add_argument("--skills-dir", default=None, dest="skills_dir",
                        help="Directory of plugin .py files (default: ./skills).")
    # Feature flags from the continuation doc.
    parser.add_argument("--think", action="store_true", dest="think",
                        help="Enable chain-of-thought / thinking mode (if the model supports it).")
    parser.add_argument("--session", default=None, dest="session",
                        help="Auto-save session to this path on exit; resume from it on startup if it exists.")

    args = parser.parse_args()

    # Assign globals AFTER argparse to keep the global declaration at the top
    # of main() but the values applied here.
    OLLAMA_BASE = args.base_url.rstrip("/")

    if args.list:
        list_models()
        return

    # Resolve model.
    model = args.model
    if model is None:
        try:
            available = [m["name"] for m in ollama_request("/api/tags").get("models", [])]
            if available:
                preferred = [m for m in available if "qwen3.5:9b" in m]
                if not preferred:
                    preferred = [m for m in available if ":9b" in m or ":12b" in m]
                model = preferred[0] if preferred else available[0]
            else:
                model = DEFAULT_MODEL
        except Exception:
            model = DEFAULT_MODEL

    # Build tool list: --no-search, --no-rag, --no-file-tools
    enable_search = not args.no_search
    enable_rag = not args.no_rag and bool(args.rag)
    enable_file_tools = not args.no_file_tools
    global TOOLS
    TOOLS = build_tools(enable_rag=enable_rag, enable_file_tools=enable_file_tools)
    if not enable_search:
        TOOLS = [t for t in TOOLS if t["function"]["name"] != "web_search"]

    # Initialize RAG if requested.
    if enable_rag and args.rag:
        init_rag(args.rag, top_k=args.rag_top_k, chunk_size=args.rag_chunk_size,
                 persist_dir=args.rag_persist, embed_model=args.rag_embed_model)

    # Load external skills.
    skills_dir = args.skills_dir or os.path.join(os.getcwd(), "skills")
    extra_skills = load_external_skills(skills_dir)

    # If --session is given and the file exists, load it (resume prior session).
    initial_messages = None
    if args.session and os.path.exists(args.session):
        try:
            with open(args.session, "r", encoding="utf-8") as f:
                _sess = json.load(f)
            initial_messages = _sess.get("messages", [])
            if _sess.get("model") and not args.model:
                model = _sess["model"]
            ok(f"Resumed session from {args.session} ({len(initial_messages)} messages)")
        except Exception as e:
            warn(f"Could not load session {args.session}: {e}")

    ctx = {
        "model": model,
        "n_results": args.num_results,
        "enable_rag": enable_rag,
        "enable_file_tools": enable_file_tools,
        "auto_confirm": bool(args.yes),
        "think": bool(args.think),
        "session_path": args.session,
        "initial_messages": initial_messages,
        "_extra_skills": extra_skills,
    }

    # If we resumed a session, preserve the system prompt from it (it has the
    # right tool list / RAG state) but use the current ctx config for everything
    # else. The simplest behavior: just pass the messages through run_chat.
    run_chat(ctx)


if __name__ == "__main__":
    main()
