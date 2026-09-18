# UI Design & Modern Discord Bot Views

A research-backed design proposal for modernizing Alfred's Discord UI components, embeds, and interactive player views.

| | |
|---|---|
| **Status** | **Shipped.** Option A and all four blueprint steps are implemented |
| **Written** | 2026-08 |
| **Kept for** | the research and the rejected options, which are the part worth not re-deriving |

Read this as a record of a decision, not as a plan. What it proposed is what the
bot now draws: the shipped card is described in [the README](../README.md#the-now-playing-view),
and how it is built is [design.md](design.md). The module paths below were
written before the package was split into `music/` and `ui/` and have been
corrected, but nothing else here has been rewritten to match what shipped -
where the two differ, the code is right.

---

## 1. Competitor & Ecosystem Research

We analyzed top-tier Discord music and media bots (Hydra, Green-bot, Jockie Music, Uzox, Soul, Tempo, and Spotify's Discord Rich Presence) to identify what makes a modern, visually stunning music view.

| Bot / System | Layout Strengths | Component Strengths | Weaknesses |
|---|---|---|---|
| **Green-bot** | Dynamic brand colors, clean mini-thumbnails, author source tags | 2-row button layout (Playback + Audio tools), volume sliders | Can feel cluttered with too many buttons |
| **Hydra** | Dedicated fixed control channel, large banner artwork | Reaction / Button toggle highlights | Huge vertical footprint, pushes chat off-screen |
| **Jockie Music** | Highly readable queue formatting, compact embed height | Simple 5-button primary row | Plain monochrome embeds without source branding |
| **Uzox / Soul** | Neon cyberpunk accent colors, sleek custom Unicode progress bars | Interactive loop & filter state buttons with dynamic style colors | Requires custom emoji support on some self-hosts |
| **Spotify Rich Presence** | Flanked timestamps (`01:23 ━━●━━━━ 03:45`), album thumbnail right-aligned | Clean metadata hierarchy (Title -> Artist -> Album) | Fixed format, no controls |

---

## 2. Modern Discord Formatting Arsenal

Discord's modern markdown renderer (Markdown v2) supports features rarely utilized in older music bots:

1. **Subtext (`-# `)**:
   - Renders muted, smaller typography.
   - Ideal for auxiliary metadata: requester tags, queue length, source provider, loop state.
   - Keeps the main card clean while retaining full information density.
2. **Header Hierarchy (`### `)**:
   - `### [Track Title](url)` creates bold, clickable title text that pops out instantly without blowing up embed height.
3. **Flanked Progress Bars (`───●──────`)**:
   - Time stamps at the edges (`01:42 ━━━━●━━━━━━━━ 04:15`) instead of stacked text.
   - Matches universal streaming UX (Spotify, Apple Music, YouTube Music).
4. **Dynamic Discord Relative Timestamps (`<t:unix:R>`)**:
   - Useful for queue views (e.g. `Ends <t:1724123456:R>`).
5. **Component Button Styles (hikari / lightbulb)**:
   - `ButtonStyle.PRIMARY` (Blurple): Active toggles (e.g. Loop Active, Paused).
   - `ButtonStyle.SECONDARY` (Charcoal Grey): Default neutral playback controls.
   - `ButtonStyle.SUCCESS` (Emerald Green): Active playback / Resume.
   - `ButtonStyle.DANGER` (Ruby Red): Stop / Disconnect.
   - `ButtonStyle.LINK` (URL): Direct zero-interaction link to track on YouTube / Spotify.

---

## 3. Brand Theme & Accent Color

Embeds uniformly use Alfred's signature brand teal color from the landing page:

| Token | Hex Color | Usage |
|---|---|---|
| **Alfred Accent** (`--accent`) | `#3A7582` | All player cards, queue embeds, status replies |
| **Alfred Soft** (`--highlight`) | `#BCE5EC` | Secondary highlights & badges |

---

## 4. Proposed View Designs

### Option A: The "Modern Streaming Card" (Recommended)

Compact, high-contrast, perfectly balanced between desktop and mobile.

#### Visual Mockup:
```
┌─────────────────────────────────────────────────────────────┐
│ Now Playing                                    [Thumbnail]  │
│ ### [Starboy (feat. Daft Punk)](https://youtube.com/...)     │
│ by **The Weeknd**                                           │
│                                                             │
│ `01:42` ▬▬▬▬▬▬▬🔘▬▬▬▬▬▬▬▬▬▬ `03:50`                       │
│                                                             │
│ -# 👤 Requested by @nauqh • 📑 Playlist: Starboy           │
└─────────────────────────────────────────────────────────────┘
[ ⏸️ Pause ] [ ⏭️ Skip ] [ 🔁 Loop: off ] [ 🔗 Link ]
```

#### Key Elements:
- **Title**: `### [Title](URL)` bold hyperlinked header.
- **Artist**: `by **Artist**` under title.
- **Progress Line**: Flanked timestamps with solid unbroken bar (18 chars): `` `01:42` ▬▬▬▬▬▬▬🔘▬▬▬▬▬▬▬▬▬▬ `03:50` `` (or `🔴 LIVE` for livestreams).
- **Subtext (`-#`)**: Requester and playlist info in small muted text.
- **Action Row (4 buttons)**:
  1. `Pause / Resume`: Secondary when playing (`⏸️ Pause`), Success Green when paused (`▶️ Resume`).
  2. `Skip`: Secondary (`⏭️ Skip`).
  3. `Loop`: Secondary when Off (`🔁 Loop: off`), Primary Blurple when Track (`🔂 Loop: track`) or Queue (`🔁 Loop: queue`).
  4. `Track Link`: Link button (`🔗 Link`) pointing directly to track URI.

---

### Option B: The "Compact Cyber Deck"

Minimal vertical height, maximum information density.

#### Visual Mockup:
```
┌─────────────────────────────────────────────────────────────┐
│ 🎶 Now Playing                                 [Thumbnail]  │
│                                                             │
│ **[Interstellar Main Theme](https://...)**                   │
│ `Hans Zimmer`                                               │
│                                                             │
│ ▶ `02:15 / 04:30` ▰▰▰▰▰▱▱▱▱▱ [ 48% ]                        │
│                                                             │
│ -# 🎧 Playlist: OST Masterpieces • Req: @user               │
└─────────────────────────────────────────────────────────────┘
[ ⏯️ Play/Pause ] [ ⏭️ Skip ] [ 🔁 Loop ] [ ⏹️ Stop ]
```

---

### Option C: The Modern `/queue` Embed

Pairs with the Now Playing view for clean queue inspection.

#### Visual Mockup:
```
┌─────────────────────────────────────────────────────────────┐
│ Queue                                                       │
│                                                             │
│ **Currently Playing:**                                      │
│ [Starboy](https://...) `03:50` • The Weeknd                 │
│                                                             │
│ **Up Next:**                                                │
│ `1.` [Blinding Lights](https://...) `03:20` • <@user>       │
│ `2.` [Save Your Tears](https://...) `03:35` • <@user>       │
│ `3.` [After Hours](https://...) `06:01` • <@user>           │
│ `4.` [Die For You](https://...) `03:53` • <@user>           │
│                                                             │
│ -# Total: 5 tracks                                          │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Progress Bar Comparison & Glyph Recommendations

Different unicode glyph sets render differently across iOS, Android, and Desktop Discord:

| Style | Rendering | Cross-Platform Stability | Recommended |
|---|---|---|---|
| **Box Pill** | `01:23 ▰▰▰▰▰▱▱▱▱▱ 03:45` | High (Standard Unicode Geometric) | ⭐⭐⭐ |
| **Thin Dot Line** | `01:23 ━━━━●━━━━━━━━ 03:45` | High (Heavy Box Lines `━` + Black Circle `●`) | ⭐⭐⭐⭐⭐ (Best) |
| **Emoji Classic** | `▶️ ▬🔘▬▬▬▬▬▬▬▬ `0:15 | 3:45`` | Medium (Emoji height differences on mobile) | ⭐⭐ (Outdated) |
| **Braille Smooth** | `01:23 ⣿⣿⣿⣿⣀⣀⣀⣀ 03:45` | Low (Variable font widths) | ⭐ |

---

## 6. Implementation Blueprint

### Step 1: Source Theme Colors (`alfred/music/sources.py` or `alfred/constants.py`)
Add color constants mapping `track.source_name` or `source.display_name` to hex codes (`hikari.Color`).

### Step 2: Modern Progress Bar Formatter (`alfred/ui/formatting.py`)
Upgrade `player_bar()` to flanked layout `01:23 ━━━━●━━━━━━━━ 03:45` with customizable width.

### Step 3: Embed Redesign (`alfred/ui/embeds.py`)
Implement Option A with dynamic color, `-# ` subtext, source header, and album art thumbnail.

### Step 4: Enhanced Menu Buttons (`alfred/ui/menus.py`)
- Native Discord Twemoji vector icons (`⏸️ Pause` / `▶️ Resume`, `⏭️ Skip`, `🔁 Loop: ...`).
- Dynamic button styles (`ButtonStyle.SUCCESS` on Resume, `ButtonStyle.PRIMARY` on Active Loop).
- Direct link button (`🔗 Link`) to `current.uri` (native Discord URL button).
