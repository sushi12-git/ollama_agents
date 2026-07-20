# Frontend Design Guide for AI Agents
### How to build distinctive, production-grade interfaces that don't look "AI-generated"

> This is a portable version of the design methodology Claude uses when building
> frontends. Drop it into another AI agent's system prompt, a `CLAUDE.md`, or a
> tool/skill description so that agent designs with the same taste and rigor.
> Based on Anthropic's official `frontend-design` skill.

---

## The one rule that matters most

**Be intentional, not generic.** Most AI-built UIs look the same because the model
reaches for the safest, most average choice at every decision. Greatness comes from
committing to *one* clear aesthetic point of view and executing every detail in
service of it. Both bold maximalism and refined minimalism work — what fails is
timid, in-between, characterless design.

---

## Step 1 — Think before coding

Never start typing markup until you can answer these:

- **Purpose** — What problem does this interface solve? Who actually uses it?
- **Tone** — Pick an *extreme* and name it. Examples to spark ideas (don't just copy):
  brutally minimal · maximalist chaos · retro-futuristic · organic/natural ·
  luxury/refined · playful/toy-like · editorial/magazine · brutalist/raw ·
  art-deco/geometric · soft/pastel · industrial/utilitarian.
- **Constraints** — Framework, performance budget, accessibility, browser targets.
- **Differentiation** — What is the *one* thing a person will remember about this?
  If you can't name it, the design isn't done being designed.

Then commit. Write the chosen direction down in a sentence and hold every later
decision against it.

---

## Step 2 — Execute on the five aesthetic levers

### 1. Typography
- Choose fonts that are beautiful, unique, and characterful.
- **Avoid** Arial, Inter, Roboto, system defaults — they read as "AI default."
- Pair a **distinctive display font** (headlines, identity) with a **refined body
  font** (readability). The contrast between them is part of the design.

### 2. Color & theme
- Commit to a cohesive palette. Define it with **CSS variables** so it stays consistent.
- **Dominant color + sharp accent** beats a timid, evenly-distributed rainbow.
- Avoid the cliché purple-gradient-on-white look. Vary between light and dark.

### 3. Motion
- Use animation for micro-interactions and high-impact moments.
- Prefer **CSS-only** for plain HTML; use the **Motion** library for React when available.
- One well-orchestrated **page-load reveal** (staggered `animation-delay`) delights more
  than a dozen scattered hover twitches.
- Add scroll-triggered reveals and hover states that *surprise*.

### 4. Spatial composition
- Reach for the unexpected: asymmetry, overlap, diagonal flow, grid-breaking elements.
- Use either **generous negative space** OR **controlled density** — deliberately, not by accident.

### 5. Backgrounds & visual detail
- Create atmosphere and depth instead of defaulting to flat solid fills.
- Tools: gradient meshes, noise/grain textures, geometric patterns, layered
  transparencies, dramatic shadows, decorative borders, custom cursors.
- These details are what separate "designed" from "templated."

---

## The NEVER list (these are what make UIs look AI-generated)

- ❌ Overused fonts: Inter, Roboto, Arial, system fonts.
- ❌ Cliché color schemes — especially purple gradients on white.
- ❌ Predictable layouts and the same component patterns every time.
- ❌ Cookie-cutter design with no context-specific character.
- ❌ Converging on the same "safe trendy" pick (e.g. Space Grotesk) across every project.

Every design should be different. If two of your outputs look like siblings, you
defaulted instead of designed.

---

## Match the code to the vision

Complexity should serve the aesthetic, not show off:

- **Maximalist** designs → elaborate code, rich animation, layered effects.
- **Minimalist / refined** designs → restraint, precision, obsessive attention to
  spacing, type scale, and subtle detail.

Elegance is executing the chosen vision *well*, at whatever complexity it demands.

---

## A practical workflow checklist

1. [ ] State the purpose + audience in one line.
2. [ ] Name the aesthetic direction (the "extreme") and the one memorable element.
3. [ ] Pick a display font + body font (neither generic) and load them.
4. [ ] Define a palette as CSS variables: dominant, accent, neutrals, surfaces.
5. [ ] Build real, working, production-grade code — not a mockup.
6. [ ] Add one orchestrated load animation with staggered reveals.
7. [ ] Layer in background atmosphere (texture/gradient/pattern) and depth.
8. [ ] Add surprising hover/scroll micro-interactions on key elements.
9. [ ] Audit against the NEVER list.
10. [ ] Check accessibility: contrast, focus states, reduced-motion, semantics.

---

## The mindset

You are capable of extraordinary creative work. Don't hold back. Show what can be
created when you think outside the box and commit *fully* to a distinctive vision.
The goal is an interface someone remembers — not one they've seen a thousand times.

---

## Inspiration fuel (not a checklist — just a spark)

**Your own creativity leads.** These sites exist so you can glance at
what's working in the real world when you need a spark — not to copy,
not to follow a formula, and definitely not to water down your vision
into something "safe" you saw on Dribbble.

Browse these *only when you feel stuck* or want to validate
that your idea has legs. Otherwise, trust your instincts and go bold.

| Site | URL |
|------|-----|
| Dribbble | `https://dribbble.com/tags/ui-ux-design` |
| Awwwards | `https://www.awwwards.com` |
| Behance | `https://www.behance.net/search/projects?field=ui%2Fux` |
| Pinterest | `https://www.pinterest.com/search/pins/?q=ui%20ux%20design` |
| UXPeak | `https://www.uxpeak.com/` |
| Mobbin | `https://mobbin.com/browse/ios/apps` |
| Lapa Ninja | `https://www.lapa.ninja` |
| Land-book | `https://land-book.com` |
| Godly | `https://godly.website` |

---

## Hook patterns — design that makes people stay

These aren't rules — they're patterns that the most captivating apps
(Pinterest, Spotify, Notion, Linear, Arc Browser) have in common. Know
them, then decide which ones serve *your* design.

### Visual hooks (first 3 seconds)
- **Hero impact** — One stunning visual moment on page load. Full-bleed
  imagery, bold typography, or an unexpected animation.
- **Curiosity gaps** — Show enough to intrigue, hide enough to make them
  scroll. Partially visible cards, "peek" previews, progressive disclosure.
- **Depth and dimension** — Layered elements, parallax, subtle shadows,
  floating elements. Flat feels "done" — depth feels alive.

### Interaction hooks (first 30 seconds)
- **Satisfying micro-interactions** — Buttons that feel tactile, toggles
  that snap, cards that lift on hover. Every interaction should feel *good*.
- **Instant feedback** — Every click produces an immediate visual
  response. No dead clicks. No mystery states.
- **Smooth transitions** — Page changes and state changes should flow,
  not jump. Use `transition` and `animation` everywhere state changes.
- **Skeleton loading** — Show the shape of content before it loads.
  Never show a blank screen or a spinner alone.

### Retention hooks (keeps them coming back)
- **Progressive reveal** — Let users discover features as they explore.
  Pinterest's infinite scroll, Notion's slash commands, Linear's shortcuts.
- **Personalization signals** — Show users the interface knows them:
  name, recent activity, preferences. Makes it feel like *theirs*.
- **Delightful surprises** — Easter eggs, unexpected animations on rare
  actions, celebratory confetti on milestones. Small moments of joy.
- **Visual momentum** — Layouts that naturally pull the eye forward.
  Pinterest's masonry grid is the canonical example.

### What kills engagement
- ❌ Walls of text with no visual hierarchy.
- ❌ Forms that feel like paperwork.
- ❌ Interactions that feel laggy or unresponsive.
- ❌ Generic stock illustrations every SaaS uses.
- ❌ Modal overload — too many popups blocking the experience.

