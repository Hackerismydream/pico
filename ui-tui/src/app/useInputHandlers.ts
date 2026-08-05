// SPDX-License-Identifier: MIT
// Portions Copyright (c) 2025 Nous Research (hermes-agent, MIT).
// Modifications Copyright (c) 2026 EverMind.
// See NOTICES.md and LICENSES/MIT-hermes-agent.txt.

import { forceRedraw, useInput } from '@hermes/ink'
import { useStore } from '@nanostores/react'
import { useEffect, useRef } from 'react'

import type { InputHandlerContext, InputHandlerResult } from './interfaces.js'

import { TYPING_IDLE_MS } from '../config/timing.js'
import { isAction, isCopyShortcut, isMac } from '../lib/platform.js'
import { computePrecisionWheelStep, initPrecisionWheel } from '../lib/precisionWheel.js'
import { computeWheelStep, initWheelAccelForHost } from '../lib/wheelAccel.js'
import { answerConfirmFromInput, cancelConfirmRequest } from './confirmResponse.js'
import { getInputSelection } from './inputSelectionStore.js'
import { $isBlocked, $overlayState, patchOverlayState } from './overlayStore.js'
import { turnController } from './turnController.js'
import { getUiState, patchUiState } from './uiStore.js'
import { dispatchNextQueuedSubmission } from './useSubmission.js'

const isCtrl = (key: { ctrl: boolean }, ch: string, target: string) => key.ctrl && ch.toLowerCase() === target

export function useInputHandlers(ctx: InputHandlerContext): InputHandlerResult {
  const { actions, chatStreamRef, composer, gateway, terminal, wheelStep } = ctx
  const { actions: cActions, refs: cRefs, state: cState } = composer

  const overlay = useStore($overlayState)
  const isBlocked = useStore($isBlocked)
  const pagerPageSize = Math.max(5, (terminal.stdout?.rows ?? 24) - 6)
  const scrollIdleTimer = useRef<null | ReturnType<typeof setTimeout>>(null)

  // Wheel accel ported from claude-code: inter-event timing drives step size,
  // direction flips reset. wheelStep (WHEEL_SCROLL_STEP) is the base; final
  // rows = wheelStep × accelMult. State mutates in place across renders.
  const wheelAccelRef = useRef(initWheelAccelForHost())

  const precisionWheelRef = useRef(initPrecisionWheel())

  useEffect(() => () => clearTimeout(scrollIdleTimer.current ?? undefined), [])

  const scrollTranscript = (delta: number) => {
    if (getUiState().busy) {
      turnController.boostStreamingForScroll()
      clearTimeout(scrollIdleTimer.current ?? undefined)
      scrollIdleTimer.current = setTimeout(() => {
        scrollIdleTimer.current = null
        turnController.relaxStreaming()
      }, TYPING_IDLE_MS)
    }

    terminal.scrollWithSelection(delta)
  }

  const copySelection = () => {
    // ink's copySelection() already calls setClipboard() which handles
    // pbcopy (macOS), wl-copy/xclip (Linux), tmux, and OSC 52 fallback.
    terminal.selection.copySelection()
  }

  const clearSelection = () => {
    terminal.selection.clearSelection()
  }

  const cancelOverlayFromCtrlC = () => {
    if (overlay.clarify) {
      return actions.answerClarify('')
    }

    if (overlay.confirm) {
      const requestId = overlay.confirm.requestId
      if (!requestId) {
        return patchOverlayState({ confirm: null })
      }

      return cancelConfirmRequest(gateway.rpc, requestId)
    }

    if (overlay.modelPicker) {
      return patchOverlayState({ modelPicker: false })
    }

    if (overlay.picker) {
      return patchOverlayState({ picker: false })
    }

    if (overlay.agents) {
      return patchOverlayState({ agents: false })
    }
  }

  const cycleQueue = (dir: 1 | -1) => {
    const len = cRefs.queueRef.current.length

    if (!len) {
      return false
    }

    const index = cState.queueEditIdx === null ? (dir > 0 ? 0 : len - 1) : (cState.queueEditIdx + dir + len) % len
    const entry = cActions.getQueueEntry(index)

    cActions.setQueueEdit(index)
    cActions.setHistoryIdx(null)
    cActions.setInput(entry?.text ?? '')
    cActions.setPasteSnips(entry?.pasteSnips ?? [])

    return true
  }

  const cycleHistory = (dir: 1 | -1) => {
    const h = cRefs.historyRef.current
    const cur = cState.historyIdx

    if (dir < 0) {
      if (!h.length) {
        return
      }

      if (cur === null) {
        cRefs.historyDraftRef.current = cState.input
      }

      const index = cur === null ? h.length - 1 : Math.max(0, cur - 1)

      cActions.setHistoryIdx(index)
      cActions.setQueueEdit(null)
      cActions.setInput(h[index] ?? '')

      return
    }

    if (cur === null) {
      return
    }

    const next = cur + 1

    if (next >= h.length) {
      cActions.setHistoryIdx(null)
      cActions.setInput(cRefs.historyDraftRef.current)
    } else {
      cActions.setHistoryIdx(next)
      cActions.setInput(h[next] ?? '')
    }
  }

  useInput((ch, key, event) => {
    const live = getUiState()

    if (isBlocked) {
      // When clarify/confirm overlays are active, their own useInput
      // handlers must receive keystrokes (arrow keys, numbers, Enter).  Only
      // intercept Ctrl+C here so the user can deny/dismiss — all other keys
      // fall through to the component-level handlers.
      if (overlay.clarify || overlay.confirm) {
        if (isCtrl(key, ch, 'c')) {
          if (overlay.confirm) {
            return answerConfirmFromInput(event, cancelOverlayFromCtrlC)
          }

          cancelOverlayFromCtrlC()
        }

        return
      }

      if (overlay.pager) {
        if (key.escape || isCtrl(key, ch, 'c') || ch === 'q') {
          return patchOverlayState({ pager: null })
        }

        const move = (delta: number | 'top' | 'bottom') =>
          patchOverlayState(prev => {
            if (!prev.pager) {
              return prev
            }

            const { lines, offset } = prev.pager
            const max = Math.max(0, lines.length - pagerPageSize)
            const step = delta === 'top' ? -lines.length : delta === 'bottom' ? lines.length : delta
            const next = Math.max(0, Math.min(offset + step, max))

            return next === offset ? prev : { ...prev, pager: { ...prev.pager, offset: next } }
          })

        if (key.upArrow || ch === 'k') {
          return move(-1)
        }

        if (key.downArrow || ch === 'j') {
          return move(1)
        }

        if (key.pageUp || ch === 'b') {
          return move(-pagerPageSize)
        }

        if (ch === 'g') {
          return move('top')
        }

        if (ch === 'G') {
          return move('bottom')
        }

        if (key.return || ch === ' ' || key.pageDown) {
          patchOverlayState(prev => {
            if (!prev.pager) {
              return prev
            }

            const { lines, offset } = prev.pager
            const max = Math.max(0, lines.length - pagerPageSize)

            // Auto-close only when already at the last page — otherwise clamp
            // to `max` so the offset matches what the line/page-back handlers
            // can reach (prevents a snap-back jump on the next ↑/↓/PgUp).
            return offset >= max
              ? { ...prev, pager: null }
              : { ...prev, pager: { ...prev.pager, offset: Math.min(offset + pagerPageSize, max) } }
          })
        }

        return
      }

      if (isCtrl(key, ch, 'c')) {
        cancelOverlayFromCtrlC()
      } else if (key.escape && overlay.picker) {
        patchOverlayState({ picker: false })
      }

      return
    }

    if (cState.completions.length && cState.input && cState.historyIdx === null && (key.upArrow || key.downArrow)) {
      const len = cState.completions.length

      cActions.setCompIdx(i => (key.upArrow ? (i - 1 + len) % len : (i + 1) % len))

      return
    }

    if (key.wheelUp || key.wheelDown) {
      const dir: -1 | 1 = key.wheelUp ? -1 : 1
      const now = Date.now()
      // Modifier-held wheel = precision mode: one row per frame, no accel.
      // Smooth mice / trackpads emit tiny same-frame bursts; coalesce those
      // without the old 80ms throttle that made opt-scroll feel stepped.
      // SGR/X10 mouse encoding only carries shift/meta/ctrl bits; Cmd on
      // macOS is intercepted by the terminal, so we honor Option (meta) on
      // Mac / Alt (meta) on Win+Linux / Ctrl as a portable fallback. Shift
      // is reserved for selection extension.
      const hasModifier = key.meta || key.ctrl
      const precision = computePrecisionWheelStep(precisionWheelRef.current, dir, hasModifier, now)

      if (precision.active) {
        // Entering precision mode must discard any accelerated wheel state;
        // otherwise the next normal wheel event inherits stale momentum.
        if (precision.entered) {
          wheelAccelRef.current = initWheelAccelForHost()
        }

        return precision.rows ? scrollTranscript(dir * wheelStep) : undefined
      }

      // 0 = direction-flip bounce deferred; skip the no-op scroll.
      const rows = computeWheelStep(wheelAccelRef.current, dir, now)

      return rows ? scrollTranscript(dir * rows * wheelStep) : undefined
    }

    if (key.shift && key.upArrow) {
      return scrollTranscript(-1)
    }

    if (key.shift && key.downArrow) {
      return scrollTranscript(1)
    }

    if (key.pageUp || key.pageDown) {
      // Half-viewport keeps 50% continuity and stays under Ink's
      // `delta < innerHeight` DECSTBM fast-path threshold.
      const viewport = terminal.scrollRef.current?.getViewportHeight() ?? Math.max(6, (terminal.stdout?.rows ?? 24) - 8)
      const step = Math.max(4, Math.floor(viewport / 2))

      return scrollTranscript(key.pageUp ? -step : step)
    }

    // Queue-edit cancel beats selection-clear for plain Esc: the queue header
    // explicitly promises "Esc cancel", so honoring it takes priority over the
    // implicit selection-dismissal convention. Without an active edit, fall through.
    if (key.escape && cState.queueEditIdx !== null) {
      return cActions.clearIn()
    }

    if (key.escape && terminal.hasSelection) {
      return clearSelection()
    }

    if (key.upArrow && !cState.inputBuf.length) {
      const inputSel = getInputSelection()
      const cursor = inputSel && inputSel.start === inputSel.end ? inputSel.start : null

      const noLineAbove =
        !cState.input || (cursor !== null && cState.input.lastIndexOf('\n', Math.max(0, cursor - 1)) < 0)

      if (noLineAbove) {
        cycleQueue(1) || cycleHistory(-1)

        return
      }
    }

    if (key.downArrow && !cState.inputBuf.length) {
      const inputSel = getInputSelection()
      const cursor = inputSel && inputSel.start === inputSel.end ? inputSel.start : null
      const noLineBelow = !cState.input || (cursor !== null && cState.input.indexOf('\n', cursor) < 0)

      if (noLineBelow || cState.historyIdx !== null) {
        cycleQueue(-1) || cycleHistory(1)

        return
      }
    }

    if (isCopyShortcut(key, ch)) {
      if (terminal.hasSelection) {
        return copySelection()
      }

      const inputSel = getInputSelection()

      if (inputSel && inputSel.end > inputSel.start) {
        inputSel.clear()

        return
      }

      // On macOS, Cmd+C with no selection is a no-op (Ctrl+C below handles interrupt).
      // On non-macOS, isAction uses Ctrl, so fall through to interrupt/clear/exit.
      if (isMac) {
        return
      }
    }

    if (isCtrl(key, ch, 'x') && cState.queueEditIdx !== null) {
      cActions.removeQueue(cState.queueEditIdx)

      return cActions.clearIn()
    }

    if (key.ctrl && ch.toLowerCase() === 'c') {
      if (live.busy && live.sid) {
        const chat = chatStreamRef?.current ?? null

        if (chat?.isTurnActive()) {
          if (live.escapeArmed) {
            // Second Ctrl+C while the turn is still in flight — the first
            // cancel produced no terminal event (events lost / server
            // wedged). Hard-reset the prompt locally so the user is never
            // stuck waiting on a response that can't arrive.
            patchUiState({ escapeArmed: false })
            chat.forceReset()

            return
          }

          // First Ctrl+C: issue the normal server cancel and arm the escape
          // hatch — the busy placeholder flips to the force-quit hint and a
          // second Ctrl+C falls back to the local reset above.
          patchUiState({ escapeArmed: true })
          chat.cancel().catch((err: Error) => actions.sys(`cancel failed: ${err.message}`))

          return
        }

        if (chat) {
          chat.cancel().catch((err: Error) => actions.sys(`cancel failed: ${err.message}`))
        }
        return
      }

      if (cState.input || cState.inputBuf.length) {
        return cActions.clearIn()
      }

      return actions.die()
    }

    if (isAction(key, ch, 'd')) {
      return actions.die()
    }

    if (isAction(key, ch, 'l')) {
      clearSelection()
      forceRedraw(terminal.stdout ?? process.stdout)

      return
    }

    // Cmd/Ctrl+G, plus Alt+G fallback for VSCode/Cursor (they bind the
    // primary keystroke to "Find Next" before the TUI sees it; Alt+G
    // arrives as meta+g across platforms).
    if (ch.toLowerCase() === 'g' && (isAction(key, ch, 'g') || key.meta)) {
      return void cActions.openEditor().catch((err: unknown) => {
        actions.sys(err instanceof Error ? `failed to open editor: ${err.message}` : 'failed to open editor')
      })
    }

    if (key.tab && cState.completions.length) {
      const row = cState.completions[cState.compIdx]

      if (row?.text) {
        const text =
          cState.input.startsWith('/') && row.text.startsWith('/') && cState.compReplace > 0
            ? row.text.slice(1)
            : row.text

        cActions.setInput(cState.input.slice(0, cState.compReplace) + text)
      }

      return
    }

    if (isAction(key, ch, 'k') && cRefs.queueRef.current.length && live.sid) {
      dispatchNextQueuedSubmission(cActions, actions.dispatchSubmission)
    }
  })

  return { pagerPageSize }
}
