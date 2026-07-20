#!/usr/bin/env python3
"""
extract_steps.py — Send a video (YouTube URL or local file) to Gemini and get
back a structured, machine-readable list of steps that Claude can then act on.

Usage:
    python extract_steps.py "https://www.youtube.com/watch?v=..."   [options]
    python extract_steps.py "C:\\path\\to\\video.mp4"                 [options]

Options:
    --goal "..."     What the user wants to accomplish (sharpens extraction).
    --model NAME     Gemini model (default: gemini-2.5-flash).
    --out PATH       Where to write the JSON (default: ./video_steps.json).

Requires the GEMINI_API_KEY environment variable and the `google-genai` package
(`pip install google-genai`). Prints the path to the JSON file on success.
"""

import argparse
import json
import os
import sys
import time

PROMPT = """You are analyzing a tutorial/how-to video so that an autonomous agent can REPRODUCE what it teaches. Watch the whole video and extract a precise, ordered action plan.

Return ONLY a JSON object (no markdown fences, no prose) with this shape:

{
  "title": "short title of what the video teaches",
  "summary": "2-3 sentence plain-English summary of the end result",
  "prerequisites": ["tools/accounts/files needed before starting"],
  "steps": [
    {
      "n": 1,
      "timestamp": "mm:ss where this step starts in the video",
      "action": "imperative one-line instruction",
      "type": "terminal | file_edit | gui | browser | account | payment | manual | info",
      "details": "everything an agent needs to do this WITHOUT rewatching: exact values, settings, file names, what success looks like",
      "command": "exact shell command if type is terminal, else null",
      "requires_human": true/false,
      "caution": "null, or a warning if this step costs money, is irreversible, posts publicly, or needs personal credentials"
    }
  ],
  "notes": "caveats, things the video glosses over, or claims that seem unrealistic"
}

Rules for the `type` field — be honest, this drives what the agent can automate:
- "terminal": a command to run in a shell. Put the literal command in `command`.
- "file_edit": create or edit a file with specific content.
- "gui": click/type inside a desktop app.
- "browser": navigate/click on a website.
- "account": sign up for or log into a service. Set requires_human=true.
- "payment": anything that spends money or enters payment details. Set requires_human=true and fill `caution`.
- "manual": a creative/judgment step a human must do (record voiceover, pick a niche, write copy).
- "info": background explanation, not an action.

Be concrete. If the video says "now just deploy it", expand that into the actual commands shown on screen. If a value is shown on screen (an API endpoint, a config flag, a prompt template), capture it verbatim in `details`. Do not invent steps that are not in the video.
"""

YOUTUBE_HINTS = ("youtube.com/", "youtu.be/")


def is_youtube(src: str) -> bool:
    return any(h in src for h in YOUTUBE_HINTS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="YouTube URL or path to a local video file")
    ap.add_argument("--goal", default="", help="What the user wants to accomplish")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--out", default="video_steps.json")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY is not set. See the skill's setup section.", file=sys.stderr)
        return 2

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("ERROR: google-genai not installed. Run: pip install google-genai", file=sys.stderr)
        return 2

    client = genai.Client(api_key=api_key)
    prompt = PROMPT
    if args.goal:
        prompt += f"\n\nThe user's specific goal: {args.goal}\nPrioritize steps that serve this goal."

    if is_youtube(args.source):
        print(f"Analyzing YouTube video: {args.source}", file=sys.stderr)
        contents = types.Content(parts=[
            types.Part(file_data=types.FileData(file_uri=args.source)),
            types.Part(text=prompt),
        ])
    else:
        path = args.source
        if not os.path.isfile(path):
            print(f"ERROR: file not found: {path}", file=sys.stderr)
            return 2
        print(f"Uploading local video (this can take a bit for large files): {path}", file=sys.stderr)
        f = client.files.upload(file=path)
        # Gemini must finish processing the upload before we can reference it.
        while getattr(f.state, "name", str(f.state)) == "PROCESSING":
            time.sleep(3)
            f = client.files.get(name=f.name)
        state = getattr(f.state, "name", str(f.state))
        if state == "FAILED":
            print("ERROR: Gemini failed to process the uploaded video.", file=sys.stderr)
            return 1
        contents = [f, prompt]

    print(f"Asking {args.model} to extract steps...", file=sys.stderr)
    resp = client.models.generate_content(
        model=args.model,
        contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    text = (resp.text or "").strip()
    # Be forgiving if the model wraps output in code fences despite instructions.
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print("ERROR: Gemini did not return valid JSON. Raw output below:", file=sys.stderr)
        print(text, file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)

    n_steps = len(data.get("steps", []))
    print(f"OK: wrote {n_steps} steps to {os.path.abspath(args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
