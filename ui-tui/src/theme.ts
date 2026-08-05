// SPDX-License-Identifier: MIT
// Portions Copyright (c) 2025 Nous Research (hermes-agent, MIT).
// Modifications Copyright (c) 2026 EverMind.
// See NOTICES.md and LICENSES/MIT-hermes-agent.txt.

import { activeColorTier } from '@hermes/ink'

export interface ThemeColors {
  primary: string
  accent: string
  border: string
  text: string
  muted: string
  surface: string
  surfaceRaised: string
  heading: string
  info: string
  path: string
  thinking: string
  completionBg: string
  completionCurrentBg: string
  completionMetaBg: string
  completionMetaCurrentBg: string

  label: string
  ok: string
  error: string
  warn: string

  prompt: string
  sessionLabel: string
  sessionBorder: string

  statusBg: string
  statusFg: string
  statusGood: string
  statusWarn: string
  statusBad: string
  statusCritical: string
  selectionBg: string

  diffAdded: string
  diffRemoved: string
  diffAddedWord: string
  diffRemovedWord: string

  shellDollar: string
}

export interface ThemeBrand {
  name: string
  icon: string
  prompt: string
  welcome: string
  goodbye: string
  tool: string
  helpHeader: string
}

export interface Theme {
  color: ThemeColors
  brand: ThemeBrand
  bannerLogo: string
  bannerHero: string
  // Brand yellow ramp (light → dark), resolved for the active tier. Used for
  // the gradient banner art.
  yellow: readonly string[]
}

export type ColorScheme = 'dark' | 'light'

// ── Color math ───────────────────────────────────────────────────────
//
// Only the helpers the truecolor palettes themselves need. There is NO
// RGB->ANSI conversion at runtime: the reduced-tier palettes below are
// pre-derived literals (see scripts/gen-color-palettes.mjs), so a level-2
// terminal gets curated `ansi256(N)` values instead of chalk's lossy hex
// downsample (which collapsed the dark-green border onto an olive cube cell).

function parseHex(h: string): [number, number, number] | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(h)

  if (!m) {
    return null
  }

  const n = parseInt(m[1]!, 16)

  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff]
}

function mix(a: string, b: string, t: number) {
  const pa = parseHex(a)
  const pb = parseHex(b)

  if (!pa || !pb) {
    return a
  }

  const lerp = (i: 0 | 1 | 2) => Math.round(pa[i] + (pb[i] - pa[i]) * t)

  return '#' + ((1 << 24) | (lerp(0) << 16) | (lerp(1) << 8) | lerp(2)).toString(16).slice(1)
}

// ── Brand ────────────────────────────────────────────────────────────

const BRAND: ThemeBrand = {
  name: 'Pico',
  icon: '◆',
  prompt: '❯',
  welcome: 'Type your message or /help for commands.',
  goodbye: 'Goodbye!',
  tool: '·',
  helpHeader: 'Commands'
}

const cleanPromptSymbol = (s: string | undefined, fallback: string) => {
  const cleaned = String(s ?? '')
    .replace(/\s+/g, ' ')
    .trim()

  return cleaned || fallback
}

// ── Brand yellow ramp (gradient logo / 3D shadow) ────────────────────
//
// A brand asset (pico-tui-design-system, "Brand ramp"), ordered light → dark.
// Used for the gradient banner art. The .50/.300/.500/.700/.900 stops are the
// documented title bands (docs/tui-color-problem/title-gradient-table.md);
// other stops are interpolated. The banner only reads the first few entries
// (hero bands) and falls back to the last, so ramp length isn't load-bearing.
//
// Truecolor carries an extra .600 stop for a smoother hero gradient (9 entries:
// [.50,.100,.300,.500,.600,.700,.900,.950,.990]); the reduced 256/16 tiers keep
// the 8-stop set ([.50,.100,.300,.500,.700,.900,.950,.990]) — the doc defines
// no .600 there. Dark and light carry DISTINCT scales at truecolor and 256
// (light re-derived around #B87900, not a dimmed dark scale); 16 is `yellow`.

const YELLOW_RAMP_TC_DARK: readonly string[] = [
  '#fff7c2', // 50
  '#fff0a4', // 100
  '#FFE573', // 300
  '#fbe23f', // 500
  '#e1c405', // 600
  '#c8a900', // 700
  '#8a6d00', // 900
  '#594600', // 950
  '#2d2300' // 990
]

const YELLOW_RAMP_TC_LIGHT: readonly string[] = [
  '#F6DA8B',
  '#EBC76C',
  '#D9A83A',
  '#B87900', // 500
  '#935F00', // 600
  '#935F00', // 700
  '#684300',
  '#432B00',
  '#221600'
]

const YELLOW_RAMP_256_DARK: readonly string[] = [
  'ansi256(229)',
  'ansi256(229)',
  'ansi256(228)',
  'ansi256(220)', // 500
  'ansi256(178)',
  'ansi256(94)',
  'ansi256(58)',
  'ansi256(234)'
]

const YELLOW_RAMP_256_LIGHT: readonly string[] = [
  'ansi256(222)',
  'ansi256(222)',
  'ansi256(179)',
  'ansi256(136)',
  'ansi256(94)',
  'ansi256(58)',
  'ansi256(58)',
  'ansi256(234)'
]

const YELLOW_RAMP_16: readonly string[] = [
  'ansi:yellow',
  'ansi:yellow',
  'ansi:yellow',
  'ansi:yellow',
  'ansi:yellow',
  'ansi:yellow',
  'ansi:yellow',
  'ansi:yellow'
]

function yellowRamp(tier: 0 | 1 | 2 | 3, scheme: ColorScheme): readonly string[] {
  if (tier === 2) {
    return scheme === 'light' ? YELLOW_RAMP_256_LIGHT : YELLOW_RAMP_256_DARK
  }
  if (tier === 1) {
    return YELLOW_RAMP_16
  }
  return scheme === 'light' ? YELLOW_RAMP_TC_LIGHT : YELLOW_RAMP_TC_DARK
}

// ── Tier 3: truecolor (source of truth) ──────────────────────────────

export const DARK_THEME: Theme = {
  color: {
    primary: '#c8c8c8',
    accent: '#7aa2f7',
    border: '#323237',
    text: '#e1e1e1',
    muted: '#6c6c6c',
    surface: '#141414',
    surfaceRaised: '#242424',
    heading: '#73daca',
    info: '#7aa2f7',
    path: '#ff9e64',
    thinking: '#bb9af7',
    completionBg: '#242424',
    completionCurrentBg: '#363636',
    completionMetaBg: '#242424',
    completionMetaCurrentBg: '#363636',

    label: '#c8c8c8',
    ok: '#9ece6a',
    error: '#f7768e',
    warn: '#e0af68',

    prompt: '#c8c8c8',
    sessionLabel: '#6c6c6c',
    sessionBorder: '#505058',

    statusBg: '#141414',
    statusFg: '#6c6c6c',
    statusGood: '#9ece6a',
    statusWarn: '#e0af68',
    statusBad: '#f7768e',
    statusCritical: '#f7768e',
    selectionBg: '#363636',

    diffAdded: '#063806',
    diffRemoved: '#420e14',
    diffAddedWord: '#9ece6a',
    diffRemovedWord: '#f7768e',
    shellDollar: '#e0af68'
  },

  brand: BRAND,

  bannerLogo: '',
  bannerHero: '',
  yellow: YELLOW_RAMP_TC_DARK
}

// Light-terminal palette: darker, higher-contrast values that stay legible on
// white backgrounds. Same shape as DARK_THEME so `fromSkin` still layers on
// top cleanly (#11300).
export const LIGHT_THEME: Theme = {
  color: {
    primary: '#444444',
    accent: '#2f64d2',
    border: '#c8c8cd',
    text: '#262626',
    muted: '#767676',
    surface: '#eeeeee',
    surfaceRaised: '#dedede',
    heading: '#0c947c',
    info: '#2f64d2',
    path: '#c3691e',
    thinking: '#7d4bc6',
    completionBg: '#dedede',
    completionCurrentBg: '#c6c6c6',
    completionMetaBg: '#dedede',
    completionMetaCurrentBg: '#c6c6c6',

    label: '#444444',
    ok: '#378e23',
    error: '#cd3048',
    warn: '#a27612',

    prompt: '#444444',
    sessionLabel: '#767676',
    sessionBorder: '#a5a5af',

    statusBg: '#eeeeee',
    statusFg: '#767676',
    statusGood: '#378e23',
    statusWarn: '#a27612',
    statusBad: '#cd3048',
    statusCritical: '#cd3048',
    selectionBg: '#c6c6c6',

    diffAdded: '#daf2dc',
    diffRemoved: '#f5dade',
    diffAddedWord: '#378e23',
    diffRemovedWord: '#cd3048',
    shellDollar: '#a27612'
  },

  brand: BRAND,

  bannerLogo: '',
  bannerHero: '',
  yellow: YELLOW_RAMP_TC_LIGHT
}

// ── Tier 2: 256-color (per design tokens, docs/tui-color-problem/tokens.md) ──

const DARK_256_COLORS: ThemeColors = {
  primary: 'ansi256(251)',
  accent: 'ansi256(111)',
  border: 'ansi256(236)',
  text: 'ansi256(254)',
  muted: 'ansi256(242)',
  surface: 'ansi256(233)',
  surfaceRaised: 'ansi256(235)',
  heading: 'ansi256(79)',
  info: 'ansi256(111)',
  path: 'ansi256(209)',
  thinking: 'ansi256(141)',
  completionBg: 'ansi256(235)',
  completionCurrentBg: 'ansi256(237)',
  completionMetaBg: 'ansi256(235)',
  completionMetaCurrentBg: 'ansi256(237)',
  label: 'ansi256(251)',
  ok: 'ansi256(149)',
  error: 'ansi256(210)',
  warn: 'ansi256(179)',
  prompt: 'ansi256(251)',
  sessionLabel: 'ansi256(242)',
  sessionBorder: 'ansi256(240)',
  statusBg: 'ansi256(233)',
  statusFg: 'ansi256(242)',
  statusGood: 'ansi256(149)',
  statusWarn: 'ansi256(179)',
  statusBad: 'ansi256(210)',
  statusCritical: 'ansi256(210)',
  selectionBg: 'ansi256(237)',
  diffAdded: 'ansi256(22)',
  diffRemoved: 'ansi256(52)',
  diffAddedWord: 'ansi256(149)',
  diffRemovedWord: 'ansi256(210)',
  shellDollar: 'ansi256(179)'
}

const LIGHT_256_COLORS: ThemeColors = {
  primary: 'ansi256(238)',
  accent: 'ansi256(26)',
  border: 'ansi256(251)',
  text: 'ansi256(234)',
  muted: 'ansi256(243)',
  surface: 'ansi256(255)',
  surfaceRaised: 'ansi256(253)',
  heading: 'ansi256(29)',
  info: 'ansi256(26)',
  path: 'ansi256(166)',
  thinking: 'ansi256(98)',
  completionBg: 'ansi256(253)',
  completionCurrentBg: 'ansi256(251)',
  completionMetaBg: 'ansi256(253)',
  completionMetaCurrentBg: 'ansi256(251)',
  label: 'ansi256(238)',
  ok: 'ansi256(28)',
  error: 'ansi256(161)',
  warn: 'ansi256(136)',
  prompt: 'ansi256(238)',
  sessionLabel: 'ansi256(243)',
  sessionBorder: 'ansi256(248)',
  statusBg: 'ansi256(255)',
  statusFg: 'ansi256(243)',
  statusGood: 'ansi256(28)',
  statusWarn: 'ansi256(136)',
  statusBad: 'ansi256(161)',
  statusCritical: 'ansi256(161)',
  selectionBg: 'ansi256(251)',
  diffAdded: 'ansi256(194)',
  diffRemoved: 'ansi256(224)',
  diffAddedWord: 'ansi256(28)',
  diffRemovedWord: 'ansi256(161)',
  shellDollar: 'ansi256(136)'
}

// ── Tier 1: 16-color (per design tokens, docs/tui-color-problem/tokens.md) ──
//
// Two caveats vs the token spec, which a single color string can't encode:
//   - `reverse` highlights (completionCurrentBg/completionMetaCurrentBg/
//     selectionBg) fall back to brightBlack — the spec's stated alternative.
//   - statusCritical's `+ bold` is dropped (bold is a text style, not a
//     color), leaving it `red` like the spec's base.

const DARK_16_COLORS: ThemeColors = {
  primary: 'ansi:white',
  accent: 'ansi:blueBright',
  border: 'ansi:blackBright',
  text: 'ansi:white',
  muted: 'ansi:blackBright',
  surface: 'ansi:black',
  surfaceRaised: 'ansi:blackBright',
  heading: 'ansi:cyanBright',
  info: 'ansi:blueBright',
  path: 'ansi:yellow',
  thinking: 'ansi:magentaBright',
  completionBg: 'ansi:black',
  completionCurrentBg: 'ansi:blackBright',
  completionMetaBg: 'ansi:black',
  completionMetaCurrentBg: 'ansi:blackBright',
  label: 'ansi:blackBright',
  ok: 'ansi:greenBright',
  error: 'ansi:redBright',
  warn: 'ansi:yellow',
  prompt: 'ansi:white',
  sessionLabel: 'ansi:blackBright',
  sessionBorder: 'ansi:blackBright',
  statusBg: 'ansi:black',
  statusFg: 'ansi:blackBright',
  statusGood: 'ansi:greenBright',
  statusWarn: 'ansi:yellow',
  statusBad: 'ansi:redBright',
  statusCritical: 'ansi:red',
  selectionBg: 'ansi:blackBright',
  diffAdded: 'ansi:blackBright',
  diffRemoved: 'ansi:blackBright',
  diffAddedWord: 'ansi:green',
  diffRemovedWord: 'ansi:red',
  shellDollar: 'ansi:yellow'
}

const LIGHT_16_COLORS: ThemeColors = {
  primary: 'ansi:black',
  accent: 'ansi:blue',
  border: 'ansi:blackBright',
  text: 'ansi:black',
  muted: 'ansi:blackBright',
  surface: 'ansi:white',
  surfaceRaised: 'ansi:whiteBright',
  heading: 'ansi:cyan',
  info: 'ansi:blue',
  path: 'ansi:yellow',
  thinking: 'ansi:magenta',
  completionBg: 'ansi:white',
  completionCurrentBg: 'ansi:blackBright',
  completionMetaBg: 'ansi:white',
  completionMetaCurrentBg: 'ansi:blackBright',
  label: 'ansi:blackBright',
  ok: 'ansi:green',
  error: 'ansi:red',
  warn: 'ansi:yellow',
  prompt: 'ansi:black',
  sessionLabel: 'ansi:blackBright',
  sessionBorder: 'ansi:blackBright',
  statusBg: 'ansi:white',
  statusFg: 'ansi:blackBright',
  statusGood: 'ansi:green',
  statusWarn: 'ansi:yellow',
  statusBad: 'ansi:red',
  statusCritical: 'ansi:red',
  selectionBg: 'ansi:blackBright',
  diffAdded: 'ansi:blackBright',
  diffRemoved: 'ansi:blackBright',
  diffAddedWord: 'ansi:green',
  diffRemovedWord: 'ansi:red',
  shellDollar: 'ansi:yellow'
}

const DARK_256: Theme = { ...DARK_THEME, color: DARK_256_COLORS, yellow: YELLOW_RAMP_256_DARK }
const DARK_16: Theme = { ...DARK_THEME, color: DARK_16_COLORS, yellow: YELLOW_RAMP_16 }
const LIGHT_256: Theme = { ...LIGHT_THEME, color: LIGHT_256_COLORS, yellow: YELLOW_RAMP_256_LIGHT }
const LIGHT_16: Theme = { ...LIGHT_THEME, color: LIGHT_16_COLORS, yellow: YELLOW_RAMP_16 }

/**
 * Pick the palette for a scheme + color tier. Tier 3 (truecolor) and tier 0
 * (no color — chalk strips the codes anyway) both use the hex palette, so the
 * truecolor `Theme` reference is returned unchanged for identity checks.
 */
export function resolveTheme(scheme: ColorScheme, tier: 0 | 1 | 2 | 3): Theme {
  if (scheme === 'light') {
    if (tier === 2) {
      return LIGHT_256
    }
    if (tier === 1) {
      return LIGHT_16
    }
    return LIGHT_THEME
  }

  if (tier === 2) {
    return DARK_256
  }
  if (tier === 1) {
    return DARK_16
  }
  return DARK_THEME
}

// ── Light/dark detection ─────────────────────────────────────────────

const TRUE_RE = /^(?:1|true|yes|on)$/
const FALSE_RE = /^(?:0|false|no|off)$/

// TERM_PROGRAM fallback allow-list for terminals whose default profile is
// light and which may not expose COLORFGBG. Empty by default: a TERM_PROGRAM
// alone can't tell a light profile from a dark one (Terminal.app ships both
// and emits no COLORFGBG either way), and dark profiles are common, so an
// undetectable terminal stays dark unless an explicit signal (PICO_TUI_THEME
// / PICO_TUI_LIGHT / PICO_TUI_BACKGROUND / COLORFGBG) says light. Still
// injectable so tests can exercise the precedence rules.
const LIGHT_DEFAULT_TERM_PROGRAMS = new Set<string>([])

// Best-effort RGB → luminance check.  Currently only accepts a 3- or
// 6-digit hex value (with or without a leading `#`); the env var name
// `PICO_TUI_BACKGROUND` is intentionally generic so a future OSC11
// query helper can cache its answer there too, but additional formats
// (rgb()/hsl()/named colours) would need explicit parsing here first.
const LUMA_LIGHT_THRESHOLD = 0.6

// Strict allow-list: parseInt(..., 16) silently truncates at the first
// non-hex character (e.g. `fffgff` would parse as `fff` and yield a
// false-positive "white" reading), so reject anything that doesn't match
// the canonical 3- or 6-digit shape up front.
const HEX_3_RE = /^[0-9a-f]{3}$/
const HEX_6_RE = /^[0-9a-f]{6}$/

function backgroundLuminance(raw: string): null | number {
  const v = raw.trim().toLowerCase()

  if (!v) {
    return null
  }

  const hex = v.startsWith('#') ? v.slice(1) : v

  const rgb = HEX_6_RE.test(hex)
    ? [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)]
    : HEX_3_RE.test(hex)
      ? [parseInt(hex[0]! + hex[0]!, 16), parseInt(hex[1]! + hex[1]!, 16), parseInt(hex[2]! + hex[2]!, 16)]
      : null

  if (!rgb) {
    return null
  }

  // Rec. 709 luma — close enough for "is this background bright".
  return (0.2126 * rgb[0]! + 0.7152 * rgb[1]! + 0.0722 * rgb[2]!) / 255
}

// Pick light vs dark with ordered, explainable signals (#11300):
//
//   1. `PICO_TUI_LIGHT` boolean — `1`/`true`/`yes`/`on` → light;
//      `0`/`false`/`no`/`off` → dark.  Either explicit value wins
//      regardless of any later signal.
//   2. `PICO_TUI_THEME` named override — `light` / `dark` win over
//      every signal below.
//   3. `PICO_TUI_BACKGROUND` hex hint (3- or 6-digit) — luminance
//      ≥ LUMA_LIGHT_THRESHOLD → light.
//   4. `COLORFGBG` last field — XFCE / rxvt / Terminal.app emit
//      slot 7 or 15 on light profiles; 0–15 ranges are otherwise
//      treated as authoritatively dark so the TERM_PROGRAM
//      allow-list below cannot override an explicit dark profile.
//   5. `TERM_PROGRAM` light-default allow-list (empty by default; see
//      LIGHT_DEFAULT_TERM_PROGRAMS).
//
// Anything we can't decide stays dark — the default Pico palette
// is the dark one.
export function detectLightMode(
  env: NodeJS.ProcessEnv = process.env,
  // Injectable so tests can prove the COLORFGBG-over-TERM_PROGRAM
  // precedence rule even though the production allow-list is empty.
  lightDefaultTermPrograms: ReadonlySet<string> = LIGHT_DEFAULT_TERM_PROGRAMS
): boolean {
  const lightFlag = (env.PICO_TUI_LIGHT ?? '').trim().toLowerCase()

  if (TRUE_RE.test(lightFlag)) {
    return true
  }

  if (FALSE_RE.test(lightFlag)) {
    return false
  }

  const themeFlag = (env.PICO_TUI_THEME ?? '').trim().toLowerCase()

  if (themeFlag === 'light') {
    return true
  }

  if (themeFlag === 'dark') {
    return false
  }

  const bgHint = backgroundLuminance(env.PICO_TUI_BACKGROUND ?? '')

  if (bgHint !== null) {
    return bgHint >= LUMA_LIGHT_THRESHOLD
  }

  const colorfgbg = (env.COLORFGBG ?? '').trim()

  if (colorfgbg) {
    // Validate as a decimal integer before coercing — `Number('')` is 0,
    // so a malformed `COLORFGBG='15;'` would otherwise look like an
    // authoritative dark slot and incorrectly block the TERM_PROGRAM
    // allow-list.  Anything that isn't pure digits falls through.
    const lastField = colorfgbg.split(';').at(-1) ?? ''

    if (/^\d+$/.test(lastField)) {
      const bg = Number(lastField)

      if (bg === 7 || bg === 15) {
        return true
      }

      // Slots 0–6 and 8–14 are the dark half of the 0–15 ANSI range.
      // When COLORFGBG is set we trust it as authoritative — a non-light
      // value here shouldn't get overridden by the TERM_PROGRAM allow-list.
      if (bg >= 0 && bg < 16) {
        return false
      }
    }
  }

  const termProgram = (env.TERM_PROGRAM ?? '').trim()

  return lightDefaultTermPrograms.has(termProgram)
}

const DEFAULT_LIGHT_MODE = detectLightMode()
const DEFAULT_SCHEME: ColorScheme = DEFAULT_LIGHT_MODE ? 'light' : 'dark'

export const DEFAULT_THEME: Theme = resolveTheme(DEFAULT_SCHEME, activeColorTier())

// Scheme detected at runtime by the OSC 11 background-color probe (see
// applyDetectedBackground). Null until — or unless — the terminal answers the
// query. When set it wins over the env-sniffed DEFAULT_SCHEME for every theme
// built afterwards, so a late reply re-themes the whole app.
let detectedScheme: ColorScheme | null = null

/** Effective light/dark scheme: the OSC 11 probe result if we have one, else
 *  the env-sniffed default. Theme builders read this (not DEFAULT_SCHEME) so a
 *  late probe reply takes effect when the theme is rebuilt. */
export function currentScheme(): ColorScheme {
  return detectedScheme ?? DEFAULT_SCHEME
}

/** Curated per-scheme palette for the current scheme + color tier, with no
 *  skin applied. Used to rebuild the theme when the probe flips the scheme
 *  before any gateway skin has arrived. */
export function resolveCurrentDefaultTheme(): Theme {
  return resolveTheme(currentScheme(), activeColorTier())
}

/** Truecolor hex for the OSC 12 hardware-cursor color. OSC 12 takes an RGB
 *  value, so we use the hex primary regardless of the text color tier — a
 *  256/16 terminal still renders its cursor in truecolor. A skin's hex primary
 *  (tier 3) is honored; otherwise the curated per-scheme title color. */
export function cursorColorHex(theme: Theme): string {
  const p = theme.color.primary

  return p.startsWith('#') ? p : currentScheme() === 'light' ? LIGHT_THEME.color.primary : DARK_THEME.color.primary
}

// Parse an OSC 11 background reply payload into a #rrggbb hex string.
// xterm-class terminals answer `rgb:RRRR/GGGG/BBBB` (1-4 hex digits per
// channel, scaled to that channel's max); a few reply `#RRGGBB`. Anything
// else returns null so the caller keeps the env-based scheme.
function oscColorToHex(data: string): null | string {
  const s = data.trim().toLowerCase()
  const m = /^rgba?:([0-9a-f]{1,4})\/([0-9a-f]{1,4})\/([0-9a-f]{1,4})/.exec(s)

  if (m) {
    const scale = (h: string) => Math.round((parseInt(h, 16) / (16 ** h.length - 1)) * 255)

    return '#' + [m[1]!, m[2]!, m[3]!].map(h => scale(h).toString(16).padStart(2, '0')).join('')
  }

  const hex = s.startsWith('#') ? s.slice(1) : s

  if (HEX_6_RE.test(hex)) {
    return '#' + hex
  }

  if (HEX_3_RE.test(hex)) {
    return '#' + [...hex].map(c => c + c).join('')
  }

  return null
}

/**
 * Fold an OSC 11 background-color reply into light/dark detection.
 *
 * Caches the parsed color into PICO_TUI_BACKGROUND and re-runs
 * detectLightMode() so the existing precedence rules apply unchanged — an
 * explicit PICO_TUI_THEME / PICO_TUI_LIGHT still wins over the measured
 * background. Returns the resolved scheme and whether it differs from the
 * scheme that was in effect (so the caller knows whether to re-theme), or
 * null when the reply isn't a color we can parse.
 */
export function applyDetectedBackground(oscData: string): { changed: boolean; scheme: ColorScheme } | null {
  const hex = oscColorToHex(oscData)

  if (!hex) {
    return null
  }

  process.env.PICO_TUI_BACKGROUND = hex
  const scheme: ColorScheme = detectLightMode() ? 'light' : 'dark'
  const changed = scheme !== currentScheme()
  detectedScheme = scheme

  return { changed, scheme }
}

// ── Skin → Theme ─────────────────────────────────────────────────────

function skinColors(colors: Record<string, string>): ThemeColors {
  const base = (currentScheme() === 'light' ? LIGHT_THEME : DARK_THEME).color
  const c = (k: string) => colors[k]
  const hasSkinColors = Object.keys(colors).length > 0

  const accent = c('ui_accent') ?? c('banner_accent') ?? base.accent
  const bannerAccent = c('banner_accent') ?? c('banner_title') ?? base.accent
  const muted = c('banner_dim') ?? base.muted
  const completionBg = c('completion_menu_bg') ?? base.completionBg

  const completionCurrentBg =
    c('completion_menu_current_bg') ??
    (hasSkinColors ? mix(completionBg, bannerAccent, 0.25) : base.completionCurrentBg)

  // Meta columns cascade off the matching skin key, then fall back to the
  // palette's own (distinct) meta value — so an empty skin reproduces the
  // default theme exactly while a skin that sets only the main completion bg
  // still carries it into the meta column.
  const completionMetaBg = c('completion_menu_meta_bg') ?? c('completion_menu_bg') ?? base.completionMetaBg
  const completionMetaCurrentBg =
    c('completion_menu_meta_current_bg') ??
    c('completion_menu_current_bg') ??
    (hasSkinColors ? completionCurrentBg : base.completionMetaCurrentBg)

  return {
    primary: c('ui_primary') ?? c('banner_title') ?? base.primary,
    accent,
    border: c('ui_border') ?? c('banner_border') ?? base.border,
    text: c('ui_text') ?? c('banner_text') ?? base.text,
    muted,
    surface: base.surface,
    surfaceRaised: base.surfaceRaised,
    heading: base.heading,
    info: base.info,
    path: base.path,
    thinking: base.thinking,
    completionBg,
    completionCurrentBg,
    completionMetaBg,
    completionMetaCurrentBg,

    label: c('ui_label') ?? base.label,
    ok: c('ui_ok') ?? base.ok,
    error: c('ui_error') ?? base.error,
    warn: c('ui_warn') ?? base.warn,

    prompt: c('prompt') ?? c('banner_text') ?? base.prompt,
    sessionLabel: c('session_label') ?? base.sessionLabel,
    sessionBorder: c('session_border') ?? base.sessionBorder,

    statusBg: base.statusBg,
    statusFg: base.statusFg,
    statusGood: c('ui_ok') ?? base.statusGood,
    statusWarn: c('ui_warn') ?? base.statusWarn,
    statusBad: base.statusBad,
    statusCritical: base.statusCritical,
    selectionBg:
      c('selection_bg') ?? c('completion_menu_current_bg') ?? (hasSkinColors ? completionCurrentBg : base.selectionBg),

    diffAdded: base.diffAdded,
    diffRemoved: base.diffRemoved,
    diffAddedWord: base.diffAddedWord,
    diffRemovedWord: base.diffRemovedWord,
    shellDollar: c('shell_dollar') ?? base.shellDollar
  }
}

export function fromSkin(
  colors: Record<string, string>,
  branding: Record<string, string>,
  bannerLogo = '',
  bannerHero = '',
  toolPrefix = '',
  helpHeader = ''
): Theme {
  const d = DEFAULT_THEME

  const brand: ThemeBrand = {
    name: branding.agent_name ?? d.brand.name,
    icon: d.brand.icon,
    prompt: cleanPromptSymbol(branding.prompt_symbol, d.brand.prompt),
    welcome: branding.welcome ?? d.brand.welcome,
    goodbye: branding.goodbye ?? d.brand.goodbye,
    tool: toolPrefix || d.brand.tool,
    helpHeader: branding.help_header ?? (helpHeader || d.brand.helpHeader)
  }

  // Skins are authored in truecolor hex. The reduced tiers can't represent
  // arbitrary hex, so fall back to the curated built-in palette for that tier
  // (per product decision) — only branding + banner art carry over. The hex
  // path covers tier 3 and, harmlessly, tier 0 (codes are stripped anyway).
  const tier = activeColorTier()
  const color = tier === 1 || tier === 2 ? resolveTheme(currentScheme(), tier).color : skinColors(colors)

  return { color, brand, bannerLogo, bannerHero, yellow: yellowRamp(tier, currentScheme()) }
}
