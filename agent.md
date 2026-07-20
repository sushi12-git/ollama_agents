# agent.md — ollama-websearch

Project documentation for AI agents (or humans) landing in this repo.
Audience: an agent that needs to understand the project fast, run it, and
extend it. Read this top to bottom; everything you need is below.

---

## 1. What this project is

A single-file Python CLI that wraps a local Ollama model with web search,
RAG over local files, and a small set of file-editing tools. You talk to
it at a Rich-rendered REPL; it calls Ollama at `http://localhost:11434`,
streams the response, and lets the model call tools (search the web,
read/write local files, search a vector index) inside an agentic loop.
It auto-detects whether the chosen model supports native tool-calling
and falls back to a prompt-injection loop (`SEARCH: ...` lines) if not.

The whole project currently lives in one file: `ollama_web.py`.

---

## 2. Quick start

Run from the project root:

```
python ollama_web.py                 # interactive, auto-pick a model
python ollama_web.py -m qwen3.5:9b   # explicit model
python ollama_web.py -m gemma4:12b -n 8   # 8 search results per query
python ollama_web.py --list          # list local Ollama models and exit
python ollama_web.py --base-url http://localhost:11434   # override host
```

Flags:

- `-m / --model` — Ollama model tag. If omitted, the script auto-picks:
  prefers `qwen3.5:9b`, else any `:9b` or `:12b`, else first available.
- `-n / --num-results` — search results per query (default `5`).
- `--list` — print a Rich table of local models and exit.
- `--base-url` — Ollama API base URL (default `http://localhost:11434`).

In the REPL: type a message and hit Enter. `Ctrl+C` or `exit` / `quit` /
`bye` / `q` to leave. See section 6 for slash commands.

---

## 3. File layout

This project is intentionally minimal — one source file plus this doc.

| File              | Purpose                                                   |
|-------------------|-----------------------------------------------------------|
| `ollama_web.py`   | Entire application: CLI, REPL, search, RAG, tool loop.   |
| `agent.md`        | This file. Project documentation for AI agents.          |
| `AGENT.md`        | User-level agent rules (Windows, India, free-tier only).  |

Inside `ollama_web.py`, top-to-bottom:

1. Imports + UTF-8 stdout reconfigure (so Rich doesn't crash cp1252).
2. Optional imports: `rich` (Console, Markdown, Panel, Prompt, Live, etc.),
   `duckduckgo-search` (`DDGS`).
3. Constants: `OLLAMA_BASE`, `DEFAULT_MODEL`, `DEFAULT_N_RESULTS`,
   ASCII `BANNER`.
4. Helpers: `cprint`, `ollama_request` (urllib, no extra deps),
   `list_models`.
5. Web search: `web_search(query, n)`.
6. Tool definitions: `TOOLS` list (Ollama function-calling schema),
   `SYSTEM_PROMPT`.
7. Streaming: `chat_stream(model, messages, tools)` generator.
8. Prompt-injection fallback: `INJECTION_SYSTEM`, `extract_search_queries`.
9. Tool-support detection: `check_tool_support(model)`.
10. Two agentic loops: `run_agent_native`, `run_agent_fallback`.
11. REPL: `run_chat(model, n_results)`.
12. Entry point: `main()` with argparse.

---

## 4. The tool surface

The model sees a list of tools in Ollama's function-calling format and
calls them by name. The current `TOOLS` list contains `web_search`.
File/RAG tools (`search_docs`, `read_file`, `write_file`, `edit_file`)
are described in section 10 (How to extend) — they are extension points,
not yet wired into the `TOOLS` list.

### `web_search` (implemented)

- **What it does:** runs a DuckDuckGo text search and returns numbered
  results with title, URL, and snippet.
- **Args:** `query` (string, required), `num_results` (int, default 5).
- **Backed by:** `duckduckgo_search.DDGS().text(...)`.
- **Output format:** `Web search results for: '<query>' (retrieved
  YYYY-MM-DD HH:MM)` followed by `[i] Title / URL / snippet` blocks.
- **Caveats:**
  - If `duckduckgo-search` is not installed, the tool returns
    `"Error: duckduckgo-search package not installed."` — install it.
  - DuckDuckGo rate-limits; back-to-back queries may return empty or
    raise. The tool catches exceptions and returns `"Search error: ..."`
    so the loop continues.
  - The number of results actually returned is computed in `run_agent_native`
    by counting lines starting with `[`; non-standard snippets can throw
    that count off (cosmetic only).

### `search_docs` (extension point)

- **What it should do:** semantic search over an ingested RAG index
  (chroma collection built by `--rag`).
- **Args:** `query` (string), `top_k` (int, default 5).
- **Caveats:** only available after `--rag` has been run; the agent
  should fall back to `web_search` if the index is empty or missing.

### `read_file` (extension point)

- **What it should do:** return the contents of a local file.
- **Args:** `path` (string), `max_bytes` (int, optional).
- **Caveats:** path must be inside an allow-list (default: cwd). Don't
  pass absolute paths outside the project without an explicit flag.

### `write_file` (extension point)

- **What it should do:** create or overwrite a local file.
- **Args:** `path` (string), `content` (string).
- **Caveats:** destructive — must respect `--yes` (auto-confirm) and
  prompt the user before overwriting existing files in interactive mode.

### `edit_file` (extension point)

- **What it should do:** apply a targeted edit (find/replace or unified
  diff) to an existing file.
- **Args:** `path` (string), `old_text` (string), `new_text` (string).
- **Caveats:** must verify `old_text` appears exactly once. If zero or
  multiple matches, return an error and let the model retry with a more
  specific snippet. Never silently apply ambiguous edits.

---

## 5. RAG

RAG is a planned extension to `ollama_web.py`. The expected design:

- **Ingest flag:** `python ollama_web.py --rag <path>` (file or folder).
  Re-runs chunk + embed + upsert into a local chroma collection.
- **Storage:** chromadb (persistent, on disk under `.rag/` or similar).
  Required package: `chromadb`.
- **Embedding model:** an Ollama embedding model, e.g.
  `nomic-embed-text` (free, local). Configurable via `--embed-model`.
- **Supported file types:** `.txt`, `.md`, `.py`, `.json`, `.csv`, `.html`,
  and any other UTF-8 text format. Binary files (PDF, DOCX, images) are
  out of scope until a parser is added.
- **Chunking:** simple fixed-size chunking with overlap (e.g. 800 chars
  with 100 char overlap) is fine for v1. Keep chunks small enough that
  `read_file` can return them inside the model's context.
- **Retrieval tool:** `search_docs` (see section 4). Returns the top-k
  chunks with their source path so the model can cite them.

Until `--rag` is implemented, the tool surface only contains `web_search`.

---

## 6. Slash commands

The REPL accepts plain text as a chat message. Slash commands (typed at
the `You:` prompt) are reserved for meta-actions. The current set:

- `/exit`, `/quit`, `/bye`, `/q` — leave the REPL.
- `/clear` — clear the in-memory message history (keep system prompt).
- `/history` — print the current conversation as a Rich table.
- `/model <name>` — switch the active model mid-session.
- `/tools` — list the tools currently exposed to the model.
- `/help` — print a one-screen usage summary.

(`exit`, `quit`, `bye`, `q` without a slash are also accepted.)

---

## 7. Known gotchas

- **Windows cp1252 terminal.** Python on Windows defaults to cp1252.
  The script calls `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
  on startup, but if you run it from a tool that re-wraps stdout, Rich
  emoji and box-drawing characters can still crash. Stick to ASCII in
  any user-facing string. The `BANNER` is hand-drawn ASCII for this
  reason.
- **Streaming output.** `chat_stream` yields `("text", delta)` chunks.
  `run_agent_native` and `run_agent_fallback` collect them into
  `display_text` and call `Live.update(Markdown(display_text))` once
  per chunk. If you add a new tool path, do not call `print()` from
  inside the loop body — it will interleave with the Live panel and
  corrupt the render. Use `console.print()` outside the `with Live(...)`
  block, or stop the Live context first.
- **Tool-support detection.** `check_tool_support` posts the `TOOLS`
  list with a trivial `"hi"` prompt. It only proves the API accepts the
  payload — it does NOT prove the model actually emits a `tool_calls`
  field. Some models silently ignore tools. To force a real test, send a
  prompt that requires a tool (e.g. "What's the weather in Mumbai?") and
  inspect `msg.get("tool_calls")`. If empty, the model isn't using tools
  even though `check_tool_support` returned True.
- **Auto-confirm with `--yes`.** File-mutating tools (`write_file`,
  `edit_file`) must accept a `--yes` flag at the CLI that suppresses the
  "overwrite?" confirmation. Default behavior: prompt the user for any
  write/edit that targets an existing file. `--yes` is for scripted /
  batch runs; do not enable it by default.
- **Ollama not running.** `ollama_request` catches `URLError`, prints a
  red error, and `sys.exit(1)`. Always start `ollama serve` (or the
  Ollama desktop app) before launching the CLI.
- **Auto model pick.** With no `-m`, the script picks the first model
  whose name contains `qwen3.5:9b`, then any `:9b` / `:12b`, then the
  first available. If you want a specific model, pass `-m` explicitly.

---

## 8. The system prompt

- **Location:** `ollama_web.py`, near the top — the `SYSTEM_PROMPT`
  constant (used in native tool-calling mode) and `INJECTION_SYSTEM`
  (used in prompt-injection fallback mode).
- **Current text (native):** "You are a helpful assistant with access
  to real-time web search. When you need current information — news,
  prices, weather, recent events, or anything after your knowledge
  cutoff — call the web_search tool. After receiving search results,
  synthesize a clear, accurate answer. Always cite the source URLs you
  used."
- **Current text (fallback):** instructs the model to emit
  `SEARCH: <query>` on its own line.
- **How to customize:** edit the constants in place. Keep the
  fallback-mode prompt in sync if you change tone or add new tool names
  — it must list every tool the fallback is expected to invoke. ASCII
  only, no emoji.

---

## 9. Environment

- **Python:** 3.14 (the project uses modern features; 3.10+ should also
  work but 3.14 is the tested target).
- **Ollama:** running locally at `http://localhost:11434`. Override with
  `--base-url` if it's elsewhere.
- **Required packages:**
  - `requests` — HTTP client (the current code uses `urllib`, but
    `requests` is the documented dependency for future HTTP work and
    for any extension that needs connection pooling / retries).
  - `rich` — terminal rendering (Console, Markdown, Panel, Prompt,
    Live, Table, Rule, box). The script degrades gracefully if Rich is
    missing (`HAS_RICH = False` branch) but you really want it.
  - `duckduckgo-search` — provides `DDGS` for `web_search`. Without it,
    the tool returns an error string.
  - `chromadb` — required for the `--rag` ingestion path. Not used by
    the current `web_search` code.
- **Optional / future:** `numpy`, `pypdf` (for PDF ingestion in RAG),
  `python-dotenv` (if you want a `.env` for `OLLAMA_BASE`).
- **Install:** `pip install rich duckduckgo-search chromadb requests`.

---

## 10. How to extend

### Add a new tool

Two edits in `ollama_web.py`:

1. **Add a tool spec to the `TOOLS` list** (Ollama function-calling
   schema, JSON-Schema-ish). Example shape:

   ```
   TOOLS = [
       { ... web_search ... },
       {
           "type": "function",
           "function": {
               "name": "read_file",
               "description": "Read a local UTF-8 text file and return its contents.",
               "parameters": {
                   "type": "object",
                   "properties": {
                       "path": {"type": "string"},
                       "max_bytes": {"type": "integer", "default": 65536},
                   },
                   "required": ["path"],
               },
           },
       },
   ]
   ```

2. **Wire the handler inside `run_agent_native`.** The relevant block is
   the `for tc in final_tool_calls:` loop. Each iteration pulls
   `fname = fn.get("name", "")` and `args = fn.get("arguments", {})`
   (args may be a JSON string — the existing code already parses it),
   then dispatches. Add a new `elif fname == "read_file":` branch,
   call your handler, and append `{"role": "tool", "content": result}`
   to `local_messages`. If the tool name is unknown, the existing
   `else` branch already appends `f"Unknown tool: {fname}"`.

3. **Mirror it in `run_agent_fallback`** only if you want the same tool
   in non-tool-calling models. Otherwise, document the tool as
   "native-only" in `SYSTEM_PROMPT` and accept that fallback users
   won't get it.

4. **Update `SYSTEM_PROMPT`** so the model knows the new tool exists
   and when to call it.

### Add a new slash command

Two edits in `ollama_web.py`:

1. **Add the command name and handler to a `COMMANDS` dict** (or
   extend the existing `if user_input.lower() in {"exit", ...}` block
   in `run_chat`). Pattern:

   ```
   COMMANDS = {
       "/clear":   lambda m: m.clear() or [sys_msg],
       "/history": lambda m: print_history(m),
       "/model":   switch_model,
       "/tools":   print_tools,
       "/help":    print_help,
   }
   ```

   The handler receives the current `messages` list (and, for `/model`,
   the rest of the user input after the command). Return value, if any,
   replaces `messages`.

2. **In `run_chat`, before the chat dispatch**, check
   `if user_input.startswith("/"): cmd, *rest = user_input.split(maxsplit=1); ...`.
   If the command is in `COMMANDS`, call its handler and `continue`.
   Otherwise, fall through to the normal chat path.

3. **Update section 6** of this file so the next agent knows the
   command exists.

### Add a new RAG file type

Edit the ingestion code (when `--rag` is implemented) to:

1. Detect the extension.
2. Pick a parser — `.txt`/`.md`/`.py`/`.json`/`.csv`/`.html` are plain
   UTF-8 reads; binary formats need a parser (`pypdf` for PDF, etc.).
3. Chunk, embed, and upsert identically to the text path.
4. Record the source path in the chunk metadata so `search_docs` can
   return it for citation.

### Add a new embedding model

Pass `--embed-model <name>` (when `--rag` exists) and use
`OLLAMA_BASE/api/embeddings` with `{"model": <name>, "prompt": <text>}`.
Default: `nomic-embed-text`. Keep it local and free.

---

## 11. Quick reference

- Default model: `qwen3.5:9b`
- Default search results per query: `5`
- Default Ollama URL: `http://localhost:11434`
- Max tool rounds per turn: `8` (in both agentic loops)
- Streaming: `chat_stream` generator, `Live` panel for rendering
- Tool format: Ollama function-calling JSON (not OpenAI — same shape,
  different endpoint)
- Fallback mode: prompt injection via `SEARCH: <query>` lines
- Exit the REPL: `exit`, `quit`, `bye`, `q`, or `Ctrl+C`

---

## 12. When in doubt

1. Re-read this file.
2. Read `ollama_web.py` — it's one file, ~500 lines, and the comments
   flag every section.
3. Run `python ollama_web.py --list` to confirm Ollama is reachable and
   see what models you have.
4. Run `python ollama_web.py -m <known-good-model> -n 3` with a prompt
   that requires a tool (e.g. "What's the weather in Delhi right now?")
   to confirm the tool loop works end-to-end.
