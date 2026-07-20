---
name: skill-finder
description: >-
  Search for, download, and apply AI agent skills or plugins that would
  improve the output for a specific task. Trigger this whenever the user
  asks for something and you suspect a purpose-built skill exists that
  would help — or when the user explicitly says "find a skill for this",
  "is there a plugin for this?", "search for a better way to do this",
  or similar. Also trigger proactively when a task is complex and a
  specialized skill could meaningfully improve quality (e.g. frontend
  design, code review, deployment, testing, documentation).
---

# Skill Finder

Search GitHub and the web for AI agent skills/plugins that match the
current task, download the best match to the local skills folder, read
its instructions, and apply them to produce better output.

## When to trigger

- The user explicitly asks to find a skill or plugin.
- You're about to tackle a complex or specialized task (frontend design,
  writing tests, code review, deployment, docs, data analysis, etc.) and
  a purpose-built skill could meaningfully improve quality.
- The user says things like "there must be a better way", "find a plugin
  for this", "search for skills", "is there a prompt for this?", etc.

**Don't trigger** for trivial tasks where your baseline ability is fine
(fixing a typo, answering a quick question, simple file edits).

## Workflow

### 1. Identify what kind of skill would help

Before searching, figure out what you need:
- What is the task category? (frontend, backend, testing, devops, writing,
  design, data, deployment, code review, etc.)
- What tool/agent format would be useful? (Claude Code CLAUDE.md, Cursor
  rules, Windsurf rules, generic agent skills, prompt templates)
- What would a good skill add that you can't do baseline? (specialized
  workflow, checklist, domain expertise, style guide, etc.)

### 2. Search for skills on GitHub

Search GitHub for relevant repositories. Use queries like:

```
claude code skills [task category]
cursor rules [task category]
AI agent skills [task category]
CLAUDE.md [specific topic]
awesome claude code
```

Good search terms by task type:

| Task | Search queries |
|------|---------------|
| Frontend/UI | `claude code frontend design skill`, `cursor rules frontend`, `AI agent UI design guide` |
| Testing | `claude code testing skill`, `cursor rules testing`, `AI agent test writing` |
| Code review | `claude code review skill`, `AI agent code review guide` |
| DevOps/deploy | `claude code deployment skill`, `cursor rules devops` |
| Documentation | `claude code documentation skill`, `AI agent docs writing` |
| API design | `claude code API design skill`, `cursor rules API` |
| Performance | `claude code performance optimization skill` |
| Security | `claude code security audit skill` |
| Game dev | `claude code game development skill`, `AI agent game design` |
| General | `awesome-claude-code`, `claude-code-skills`, `cursor-rules-collection` |

### 3. Evaluate candidates

For each candidate repo, check:
- **Relevance** — Does it actually match the task?
- **Quality** — Is the content substantive or just filler?
- **Format** — Is it a SKILL.md, CLAUDE.md, .cursorrules, or similar
  that you can read and follow?
- **Recency** — Is it maintained or abandoned?
- **Stars/forks** — Some signal of community validation (but don't
  over-weight this — new skills can be excellent).

Pick the **single best match**. If nothing good exists, say so honestly
and proceed with your baseline ability.

### 4. Download the skill

Clone or download just the skill files (not the entire repo if it's huge)
into the local skills folder:

```powershell
# Clone the whole repo (simplest)
git clone <repo-url> "$env:USERPROFILE\Desktop\AI Agent SKILLS\<skill-name>"

# Or for a single file, use curl/Invoke-WebRequest
Invoke-WebRequest -Uri "<raw-github-url>" -OutFile "$env:USERPROFILE\Desktop\AI Agent SKILLS\<skill-name>\SKILL.md"
```

**Target directory:** `C:\Users\SUSHRUT\Desktop\AI Agent SKILLS\<skill-name>\`

### 5. Read and apply the skill

- Read the downloaded SKILL.md / CLAUDE.md / rules file.
- Follow its instructions for the current task.
- If it has a workflow or checklist, work through it step by step.
- Combine its guidance with the user's AGENT.md rules — AGENT.md takes
  precedence on any conflicts (e.g. no spending money, no account creation).

### 6. Report what you used

After completing the task, briefly tell the user:
- What skill you found and where it came from (repo URL).
- Whether it meaningfully improved the output.
- Whether they should keep it in their skills folder for future use.

If the skill was useful, **update the skills inventory** in
`C:\Users\SUSHRUT\Desktop\AGENT.md` (the "Available AI Agent Skills"
section) so other agents can find it too.

## Safety rules

- **Never install paid tools or dependencies.** Only free, open-source
  skills and plugins.
- **Never run untrusted scripts** from downloaded skills without reading
  them first and confirming they're safe.
- **Never clone repos larger than ~50 MB** without asking the user. Most
  skill repos are tiny (a few markdown files).
- **AGENT.md rules override skill rules.** If a downloaded skill says
  "use Stripe" but AGENT.md says "use Razorpay", use Razorpay.
- **Don't hoard skills.** Only download what's actually useful for the
  current task. The user can always ask for more later.
