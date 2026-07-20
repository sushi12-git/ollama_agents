---
name: video-to-action
description: >-
  Turn a tutorial video into actions that actually get done. Use this skill
  whenever the user shares a YouTube link or a local video file and wants the
  steps followed, reproduced, or done for them — phrases like "do what this
  video says", "follow this tutorial", "watch this and set it up", "I want to
  try what this guy is doing", or any "how to make money / build / install X
  with AI" video. It sends the video to Gemini for understanding, extracts a
  structured step list, then carries out the technical steps automatically and
  hands back the parts only a human can do. Trigger even if the user doesn't say
  the word "skill" — a shared video plus an intent to act is enough.
---

# Video-to-Action

Take a video the user shares (YouTube URL or local file), understand it via
Gemini, turn it into a concrete step list, and then **do** the steps that can be
safely automated — stopping for the parts that genuinely need a human.

The point is to collapse "watch this 20-minute tutorial and replicate it" into a
single request. Many tutorials — especially "make money with AI" videos — mix
real, automatable steps (install this, run that, create this file) with steps
that need a person (sign up, pay, pick a niche, record your voice). Your job is
to separate the two: execute the first kind, and clearly hand back the second.

## Workflow

### 1. Get the video source and the goal
Confirm what you're working with:
- A **YouTube URL**, or a **local file path** (e.g. `C:\Users\...\clip.mp4`).
- The user's **goal** in their words, if they gave one ("I want the chatbot from
  this", "just get the part where he sets up the API"). This sharpens extraction.

If they pasted a link with no instruction, assume they want it reproduced.

### 2. Extract structured steps with Gemini
Run the bundled script. It reads `GEMINI_API_KEY` from the environment and writes
a JSON file of steps.

```powershell
python "$env:USERPROFILE\.claude\skills\video-to-action\scripts\extract_steps.py" "<URL or path>" --goal "<user goal>" --out video_steps.json
```

- For large local files the upload takes a while — that's expected.
- If it errors with `GEMINI_API_KEY is not set`, walk the user through **Setup**
  below, then retry.
- If it errors with `google-genai not installed`, run `pip install google-genai`.

Then read `video_steps.json`. Each step has: `n`, `timestamp`, `action`, `type`,
`details`, `command`, `requires_human`, `caution`.

### 3. Show the plan, then act
Briefly summarize for the user: the title, what it produces, prerequisites, and
the full step list with each step's type. This is their window to redirect you.

Then **auto-execute** — the user chose this. Don't ask permission step by step.
Map each step's `type` to a tool:

| `type`       | How to do it                                                        |
|--------------|---------------------------------------------------------------------|
| `terminal`   | Run `command` with the shell (PowerShell on this machine).          |
| `file_edit`  | Create/edit the file with Write/Edit.                               |
| `browser`    | Use the Chrome MCP if available; otherwise describe and hand back.  |
| `gui`        | Use computer-use if available and the app is granted; else hand back.|
| `account`    | **Hand back** — never create accounts or log in as the user.        |
| `payment`    | **Hand back** — never spend money or enter payment details.         |
| `manual`     | **Hand back** — creative/judgment work (pick niche, record audio).  |
| `info`       | No action; use as context.                                          |

Work top to bottom. If a step depends on a handed-back step (e.g. it needs an API
key from an account the user must create), do everything up to that point, then
pause and tell the user exactly what you need from them to continue.

### 4. The safety floor (non-negotiable, even in auto-execute)
Auto-execute means you don't ask before *ordinary* steps. It does **not** mean
acting blindly. Before running any step, stop and confirm with the user if it:
- spends money, enters payment info, or starts a paid subscription,
- deletes or overwrites files you didn't create, or wipes data,
- posts/publishes/sends something public or to other people,
- changes system-wide settings or security/credentials,
- or has a non-empty `caution` field.

For these, say what the step is, why it's flagged, and let the user decide. This
protects the user from a video that casually says "now just buy the $97 course"
or "delete your old project folder."

### 5. Report
When done, give a short rundown: what you executed and the result, what you
skipped and why, and the exact handed-back items the user needs to do themselves
(numbered, in order). Be honest about steps the video glossed over or claims that
look unrealistic — surface anything in the `notes` field.

## A note on "make money with AI" videos
Treat them with healthy realism. Extract and do the genuinely useful technical
setup (scaffolding a site, wiring up an API, generating content), but don't
oversell the outcome. If the real "value" of the video is an affiliate signup, a
paid tool, or vague hustle advice, say so plainly in your report rather than
pretending you automated a money machine.

## Setup: saving your Gemini API key safely (one time)
The script needs a free Gemini API key. **Do not paste the key into the chat** —
it would be stored in the conversation. Instead the user sets it as a Windows
user environment variable from their own terminal:

1. Get a key at https://aistudio.google.com/apikey (free tier works).
2. In a PowerShell window, run (replacing the placeholder):
   ```powershell
   [Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "PASTE_KEY_HERE", "User")
   ```
3. **Open a new terminal/Claude session** so the variable is loaded. It persists
   across reboots and is scoped to the user account.

To check it's set without revealing it: `if ($env:GEMINI_API_KEY) { "set" }`.
