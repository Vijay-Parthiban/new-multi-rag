---
name: new-multi-rag
description: "An instrumented control room for enterprise RAG: ingest, retrieve, chat, measure."
colors:
  canvas: "#0b0e14"
  panel: "rgba(17, 21, 30, 0.85)"
  panel-subtle: "rgba(22, 27, 38, 0.7)"
  surface-inset: "rgba(28, 34, 48, 0.6)"
  sidebar: "rgba(13, 16, 23, 0.95)"
  border-default: "rgba(56, 68, 100, 0.45)"
  border-muted: "rgba(56, 68, 100, 0.25)"
  border-glow: "rgba(88, 166, 255, 0.2)"
  text-primary: "#e6edf3"
  text-secondary: "#8b949e"
  link: "#58a6ff"
  accent: "#58a6ff"
  accent-emphasis: "#79c0ff"
  accent-subtle: "rgba(56, 139, 253, 0.12)"
  accent-glow: "rgba(56, 139, 253, 0.35)"
  danger: "#f85149"
  success: "#3fb950"
  warn: "#d29922"
  canvas-light: "#f5f7fa"
  panel-light: "rgba(255, 255, 255, 0.92)"
  text-primary-light: "#1a1d23"
  text-secondary-light: "#5a6270"
  accent-light: "#2563eb"
  border-default-light: "rgba(209, 218, 233, 0.7)"
typography:
  display:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "1.625rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0em"
  body:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "0em"
  button:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.25
    letterSpacing: "0em"
  label:
    fontFamily: "Inter, system-ui, -apple-system, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.04em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
rounded:
  sm: "8px"
  md: "12px"
  lg: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "28px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "7px 16px"
    typography: "{typography.button}"
  button-secondary:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "7px 16px"
    typography: "{typography.button}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.sm}"
    padding: "7px 16px"
    typography: "{typography.button}"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.sm}"
    padding: "8px 14px"
    typography: "{typography.body}"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text-primary}"
    rounded: "{rounded.md}"
    padding: "14px 18px"
  chip-status:
    backgroundColor: "{colors.panel-subtle}"
    textColor: "{colors.text-secondary}"
    rounded: "{rounded.pill}"
    padding: "2px 8px"
    typography: "{typography.label}"
---

# Design System: new-multi-rag

## Overview

**Creative North Star: "The Control Room"**

The interface is an instrument panel in a dark room. A Knowledge Product is the machine; the sidebar is the console; every page is one reading on it. Surfaces sit a layer above a deep slate field, lit only where something carries state: the active route, a running job, a failing check. Nothing glows that does not mean something.

The voice is **instrumented and quiet**. Counts, timestamps, identifiers and metric tables are content, not clutter, and they stay on screen. Decoration is the thing that gets cut. A page earns its space by what it lets an operator verify, not by how it introduces itself.

Interaction is **tactile and confident**: a primary control lifts a pixel and gains a blue halo, navigation slides two pixels toward the reader, focus rings are always visible. These are small, consistent acknowledgements that the console heard you. They are never large motion, never one identical entrance on every panel.

**Key Characteristics:**
- Dark-first with a full light theme; both themes are maintained, never one over the other.
- Glass panels over a fixed two-tone radial wash; depth comes from translucency plus an offset shadow.
- One chromatic accent, used for the active route, the primary action, links and focus.
- Status colours are semantic only: pass green, hold amber, signal red.
- Dense 14 px base type; tables and badges drop to 11 px uppercase with tracked labels.
- Sidebar 256 px, collapsing to a 72 px icon rail.

## Colors

A single blue signal over a deep slate field, with three status colours that must never be reused as decoration.

### Primary
- **Electric Signal Blue** (`#58a6ff` dark, `#2563eb` light): the active sidebar route, links, focus rings, and the primary button's gradient base. Its lighter companion **Signal Highlight** (`#79c0ff`) is used for the active route label and for the top of the page-title gradient.
- **Accent Wash** (`rgba(56, 139, 253, 0.12)`): the selected row, the active nav background, and any chip that marks a chosen item. It reads as light spill, not as a fill.

### Neutral
- **Deep Instrument Slate** (`#0b0e14`): the canvas. It never appears as a card colour; cards are lighter.
- **Frosted Panel** (`rgba(17, 21, 30, 0.85)`): the panel surface, always over the canvas, always with `backdrop-filter: blur(16px)`.
- **Recessed Slate** (`rgba(22, 27, 38, 0.7)`): panel headers, table headers, inset strips.
- **Sunken Well** (`rgba(28, 34, 48, 0.6)`): inputs at rest, code blocks, empty-state wells.
- **Cool Paper** (`#e6edf3`): primary text.
- **Muted Steel** (`#8b949e`): secondary text, labels, table headers, metadata.
- **Hull Line** (`rgba(56, 68, 100, 0.45)`) and **Hull Line Faint** (`rgba(56, 68, 100, 0.25)`): the two border weights. Default for panels and inputs, faint for internal dividers.

### Tertiary
- **Pass Green** (`#3fb950`): a completed run, a passing check.
- **Hold Amber** (`#d29922`): queued, processing, a warning that does not block.
- **Signal Red** (`#f85149`): a failed run, a blocked guardrail, a destructive action.

### Named Rules
**The One Light Rule.** The accent is the only chromatic light. A screen may spend it on the active route, the primary action, links and focus, and nothing else. If a surface needs attention and is not one of those four, use weight, position or a status colour.

**The Status Is Not Decoration Rule.** Pass green, hold amber and signal red mean outcome. They never style a neutral chip, a brand mark or a hover.

## Typography

**Display Font:** Inter (with `system-ui`)
**Body Font:** Inter (with `system-ui`)
**Label/Mono Font:** `ui-monospace` stack, reserved for identifiers, JSON, scores and keys.

**Character:** One family carries everything, and hierarchy comes from size and weight alone. The result reads like an instrument legend: quiet, exact, with numbers that line up.

### Hierarchy
- **Display** (700, `1.625rem`, line-height `1.2`, tracking `-0.02em`): the page title only, one per page. It carries the product's single gradient treatment.
- **Title** (600, `0.875rem`): panel titles and section headers inside a page.
- **Body** (400, `0.875rem`, line-height `1.5`): prose, table cells, form values. Keep measure to about 52ch for descriptions.
- **Label** (600, `0.6875rem`, tracking `0.04em`, uppercase): table headers, status badges, field labels above inputs, metadata rows.
- **Mono** (`0.8125rem`): IDs, metric keys, JSON payloads, token counts.

### Named Rules
**The One Gradient Rule.** The blue-to-cyan text gradient exists on the page title and nowhere else. New emphasis comes from weight, size or the accent colour as a solid.

## Layout

A fixed console on the left and a working field on the right.

- The sidebar is `256px` expanded and `72px` collapsed; the width lives in `--sidebar-width` and `--sidebar-width-collapsed` so both states are one token apart.
- Page content sits in a single column with `1.75rem` below the header. A header is a breadcrumb, a title, one description line capped at `52ch`, and the page's actions on the right.
- Dense pages use a two-pane grid of `340px + minmax(0, 1fr)` with `1rem` gap: list on the left, detail on the right. Below `1100px` it stacks.
- Panels stack with `1rem` gaps and never nest inside another panel.
- Tables are the primary data surface: `0.65rem 0.85rem` cells, a sticky header at `0.68rem` uppercase, and no outer scrollbar where the page already scrolls.
- Breakpoints in use: `1100px`, `900px`, `720px`, `560px`. Two-column forms drop to one at `900px`.

## Elevation & Depth

**Layered glass.** Depth is translucency plus an offset shadow: a panel is a sheet of frosted glass held above the canvas, and the shadow says how far. The canvas itself is never flat black; a fixed radial wash of accent at `8%` in the top centre and cyan at `6%` in the bottom right gives the room a light source.

Every surface at rest already has its shadow. Hover raises the border, not the elevation, except for the primary button, which lifts `1px` and gains a wider halo.

### Shadow Vocabulary
- **Rest** (`0 1px 3px rgba(0,0,0,.3), 0 1px 2px rgba(0,0,0,.2)`): rows, badges, small controls.
- **Panel** (`0 4px 12px rgba(0,0,0,.4), 0 2px 4px rgba(0,0,0,.3)`): every card and panel at rest.
- **Overlay** (`0 8px 32px rgba(0,0,0,.5), 0 4px 12px rgba(0,0,0,.3)`): dialogs, drawers, floating menus.
- **Signal Halo** (`0 0 20px rgba(56,139,253,.15)`): a running job or a focused accent surface. Only where state is meant.
- **Primary Lift** (`0 4px 16px rgba(37,99,235,.4)`): the primary button on hover, paired with `translateY(-1px)`.

### Named Rules
**The Glass Is Depth Rule.** Blur marks a surface that floats. Do not blur an inline element or a row, and do not add glass to a surface that already sits on the canvas without a shadow.

## Shapes

Geometry is rounded but not soft: `8px` for controls, `12px` for panels, `16px` for dialogs and large containers, `999px` for pills and status badges.

Borders are `1px` and always come from the two hull weights; a translucent fill plus a `1px` line does the work that a heavier stroke would. The active sidebar route is the one exception in the system: a `3px` inset accent bar on its left edge, with the radius squared off on that side. Nothing else draws a bar shadow.

## Components

### Buttons
- **Shape:** `8px` radius, `1px` transparent border, inline-flex with `6px` gap, `7px 16px` padding at `0.875rem/500`.
- **Primary:** the blue-to-cyan gradient, white label, and a blue shadow. One per surface; it is the action the page exists for.
- **Secondary:** frosted panel fill, `1px` hull border, `blur(8px)`. Hover raises the border to the glow weight and lifts `1px`.
- **Ghost:** transparent with secondary text; hover fills with the glass tone. Used for row actions and dismiss.
- **Small:** `0.8125rem` with `0.3rem 0.625rem` padding, for table rows and panel headers.
- **Disabled:** `opacity: 0.4`, no transform, cursor not-allowed.

### Chips
- **Style:** `999px`, `2px 8px` padding, `0.6875rem/600` uppercase with `0.04em` tracking, `1px` border from the hull weight.
- **State:** neutral chips sit on the recessed tone with secondary text. Status chips take the semantic colour for both text and border; they never fill.

### Cards / Containers
- **Corner Style:** `12px`.
- **Background:** frosted panel over the canvas, never a solid grey.
- **Shadow Strategy:** Panel at rest; Overlay only when it floats above the page.
- **Border:** `1px` hull line, raised to the glow weight on focus-within.
- **Internal Padding:** `14px 18px` body, `0.875rem 1.125rem` header with a faint bottom divider.

### Inputs / Fields
- **Style:** sunken well, `1px` hull border, `8px` radius, `8px 14px` padding.
- **Focus:** border switches to the accent and a `3px` accent-glow ring appears; no outline.
- **Labels:** above the field, `0.72rem` secondary, with an `id` and a matching `htmlFor`. Never a placeholder standing in for a label.

### Navigation
- **Style:** sidebar rows `0.5rem 0.75rem`, `8px` radius, secondary text at `0.9rem/500`, `16px` icon at `70%` opacity.
- **Default / Hover / Active:** hover raises the glass tone, brightens the text and slides `2px` right. Active takes the accent wash, the accent label at `600`, an accent icon and the inset bar.
- **Collapsed:** a `72px` icon rail; labels leave, titles remain as tooltips, the active bar stays.

### Tables
- **Style:** full width, sticky header on the recessed tone, `0.68rem` uppercase header labels, faint row dividers, no zebra except in the Fabric tables.
- **Numbers:** right or centred in a narrow numeric column, mono where the value is an identifier or a score.

### Progress
- **Style:** a `4px` track on the hull line with an accent fill that animates width over `0.3s`. It appears only while a job runs, next to its phase label and counters, and it respects reduced motion.

## Do's and Don'ts

### Do:
- **Do** put visible counts, IDs, timestamps and scores on screen. Density is the product voice.
- **Do** keep one primary action per surface, and make the remaining actions secondary or ghost.
- **Do** use `127.0.0.1` in every example URL and dev instruction.
- **Do** give every input a label with `htmlFor`, and every interactive control a `type`.
- **Do** keep both themes working when you add a colour: add it to `:root` and `[data-theme="light"]`.
- **Do** name a control after its action ("Create dataset version", "Delete"), and an error after the problem and the fix.

### Don't:
- **Don't** add a second accent hue. Status colours are not accents.
- **Don't** place the text gradient anywhere except the page title.
- **Don't** nest a panel inside a panel, and don't use a card grid as a page structure.
- **Don't** add an eyebrow, kicker or label above a heading. The heading carries itself.
- **Don't** reach for a modal when a panel, drawer or inline form does the job.
- **Don't** use mono for prose. It marks identifiers, keys, payloads and scores only.
- **Don't** add motion beyond the `1–2px` lift, the `0.2s` colour transition and the progress fill, and always honour `prefers-reduced-motion`.
