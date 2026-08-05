// SPDX-License-Identifier: MIT
// Portions Copyright (c) 2025 Nous Research (hermes-agent, MIT).
// Modifications Copyright (c) 2026 EverMind.
// See NOTICES.md and LICENSES/MIT-hermes-agent.txt.

const RICH_RE = /\[(?:bold\s+)?(?:dim\s+)?(#(?:[0-9a-fA-F]{3,8}))\]([\s\S]*?)(\[\/\])/g

export function parseRichMarkup(markup: string): Line[] {
  const lines: Line[] = []

  for (const raw of markup.split('\n')) {
    const trimmed = raw.trimEnd()

    if (!trimmed) {
      lines.push(['', ' '])

      continue
    }

    const matches = [...trimmed.matchAll(RICH_RE)]

    if (!matches.length) {
      lines.push(['', trimmed])

      continue
    }

    let cursor = 0

    for (const m of matches) {
      const before = trimmed.slice(cursor, m.index)

      if (before) {
        lines.push(['', before])
      }

      lines.push([m[1]!, m[2]!])
      cursor = m.index! + m[0].length
    }

    if (cursor < trimmed.length) {
      lines.push(['', trimmed.slice(cursor)])
    }
  }

  return lines
}

const PICO_WORD_ART = [
  '██████╗ ██╗ ██████╗  ██████╗ ',
  '██╔══██╗██║██╔════╝ ██╔═══██╗',
  '██████╔╝██║██║      ██║   ██║',
  '██╔═══╝ ██║██║      ██║   ██║',
  '██║     ██║╚██████╗ ╚██████╔╝',
  '╚═╝     ╚═╝ ╚═════╝  ╚═════╝ '
] as const

const AGENT_WORD_ART = [
  ' █████╗  ██████╗ ███████╗███╗   ██╗████████╗',
  '██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝',
  '███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   ',
  '██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   ',
  '██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   ',
  '╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   '
] as const

const PICO_LOGO_ART = PICO_WORD_ART.map((row, index) => `${row}   ${AGENT_WORD_ART[index]}`)

const PICO_HERO_ART = [
  '         ╱╲         ',
  '        ╱  ╲        ',
  '       ╱ ◆  ╲       ',
  '      ╱      ╲      ',
  '     ╱  PICO  ╲     ',
  '    ╰──────────╯    '
] as const

export const PICO_LOGO_WIDTH = PICO_LOGO_ART.reduce((width, row) => Math.max(width, [...row].length), 0)
export const PICO_HERO_WIDTH = PICO_HERO_ART.reduce((width, row) => Math.max(width, [...row].length), 0)

// How many art rows share one ramp colour in the title (vertical bands).
const LOGO_ROWS_PER_BAND = 2
// How many vertical colour bands the hero is split into (horizontal gradient).
const HERO_BANDS = 5

const bandColor = (ramp: readonly string[], row: number) =>
  ramp[Math.floor(row / LOGO_ROWS_PER_BAND)] ?? ramp[ramp.length - 1]!

// Title (wordmark): one ramp colour per LOGO_ROWS_PER_BAND rows, top → bottom,
// using the first ceil(rows / band) ramp entries.
export const picoLogo = (ramp: readonly string[], customLogo?: string): Line[] =>
  customLogo ? parseRichMarkup(customLogo) : PICO_LOGO_ART.map((text, i) => [bandColor(ramp, i), text])

// Width of the "PICO" word — the minimum the short form needs.
export const PICO_WORD_WIDTH = PICO_WORD_ART.reduce((width, row) => Math.max(width, [...row].length), 0)

// Just the "PICO" word, with the per-word top → bottom ramp gradient.
export const picoLogoWord = (ramp: readonly string[]): Line[] =>
  PICO_WORD_ART.map((text, i) => [bandColor(ramp, i), text])

// Hero (pico): a horizontal gradient split into HERO_BANDS column bands,
// coloured right → left so the highlight (ramp[0]) lands on the right and it
// deepens toward the left (ramp[HERO_BANDS-1]). Each row is returned as an
// array of `[color, segment]` pairs rendered inline.
export const picoHero = (ramp: readonly string[], customHero?: string): Line[][] => {
  if (customHero) {
    return parseRichMarkup(customHero).map(line => [line])
  }

  return PICO_HERO_ART.map(row => {
    const chars = [...row]
    const bandWidth = Math.ceil(chars.length / HERO_BANDS)
    const segments: Line[] = []

    for (let band = 0; band < HERO_BANDS; band++) {
      const text = chars.slice(band * bandWidth, (band + 1) * bandWidth).join('')

      if (!text) {
        continue
      }

      const color = ramp[HERO_BANDS - 1 - band] ?? ramp[ramp.length - 1]!
      segments.push([color, text])
    }

    return segments
  })
}

export const artWidth = (lines: Line[]) => lines.reduce((m, [, t]) => Math.max(m, [...t].length), 0)

// Width of a segmented art (hero): max over rows of the summed segment widths.
export const rowsWidth = (rows: Line[][]) =>
  rows.reduce(
    (m, segs) =>
      Math.max(
        m,
        segs.reduce((a, [, t]) => a + [...t].length, 0)
      ),
    0
  )

type Line = [string, string]
