// SPDX-License-Identifier: MIT
// Copyright (c) 2026 EverMind.
// See NOTICES.md.
//
// Bridges `RpcClient.subscribe<TurnEvent>('turn.subscribe', ...)` notifications
// onto the existing `turnController`. The factory
// returns a thin handle with `attach / detach / send / cancel / isTurnActive`
// so it can be unit-tested against a fake RpcClient (no socket required) and
// wired into `useMainApp.ts` as a per-session lifecycle object.

import { randomUUID } from 'node:crypto'

import type { Msg } from '../types.js'

import {
  RpcError,
  type ErrorEvent,
  type MessageCompleteEvent,
  type MessageStartEvent,
  type TokenDeltaEvent,
  type ToolCompleteEvent,
  type ToolStartEvent,
  type TurnEvent,
  type TurnSendParams,
  type TurnSendResult,
  type TurnSubscribeParams
} from '../rpc/index.js'
import { turnController } from './turnController.js'
import { patchTurnState } from './turnStore.js'
import { getUiState, patchUiState } from './uiStore.js'

/**
 * Minimal RpcClient surface the chat path needs. Defining this locally lets
 * tests inject a fake without touching the real socket-backed RpcClient.
 * The shape mirrors the public methods of `src/rpc/client.ts::RpcClient`,
 * including the `subscribe` return shape `{subscription_id, unsubscribe}`.
 */
export interface ChatStreamRpcClient {
  rpc<R = unknown, P = unknown>(method: string, params: P): Promise<R>
  subscribe<E = unknown, P = unknown>(
    method: string,
    params: P,
    handler: (event: E) => void,
    opts?: { unsubscribeMethod?: string }
  ): Promise<{ subscription_id: string; unsubscribe: () => Promise<void> }>
}

export interface ChatStreamOptions {
  rpcClient: ChatStreamRpcClient
  sessionKey: string
  releaseSessionImages?: (sessionId: string, claimId?: string) => void
  rollbackSessionImages?: (sessionId: string, claimId?: string) => void
  submissionIdFactory?: () => string
  /** Optional sys-message hook for surfacing non-cancellation errors. */
  sys?: (msg: string) => void
  /**
   * Append a finished message to the React history list. Required for
   * `message.complete` to persist the assistant turn's final text + tool
   * trail in the UI — without this the streamed tokens vanish on completion.
   * Mirrors the legacy `createGatewayEventHandler.ts:675` pattern.
   */
  appendMessage?: (msg: Msg) => void
  /**
   * Server-ack watchdog window (ms). Armed when `send` starts; if NO server
   * event of any kind arrives within this window the turn is treated as wedged
   * (events lost / subscription not delivering / turn.send hung) and the input
   * is restored instead of freezing. It measures server-ack liveness only — the
   * first inbound event disarms it — never LLM first-token latency. Defaults to
   * {@link DEFAULT_WATCHDOG_MS}.
   */
  watchdogMs?: number
}

/** Default server-ack watchdog window — see {@link ChatStreamOptions.watchdogMs}. */
export const DEFAULT_WATCHDOG_MS = 10_000

export interface ChatStreamHandle {
  attach: () => Promise<void>
  detach: () => Promise<void>
  send: (content: string, imageClaimId?: string) => Promise<TurnSendResult>
  cancel: () => Promise<void>
  isTurnActive: () => boolean
  sessionKey: string
  /**
   * Local hard reset: drop the active turn and restore the prompt WITHOUT a
   * server round-trip. Backs the Ctrl+C escape hatch and the watchdog so a
   * turn that produces no terminal event can never wedge the UI.
   */
  forceReset: () => void
}

type AttemptInvalidation = 'detach' | 'force_reset' | 'transport_error' | 'watchdog'

interface SendAttempt {
  imageClaimId?: string
  invalidated: AttemptInvalidation | null
  imagesSettled: boolean
  rpcSettled: boolean
  started: boolean
  submissionId: string
  terminal: boolean
  turnId: string | null
  watchdog: null | ReturnType<typeof setTimeout>
}

interface InternalState {
  attached: boolean
  attempts: Map<string, SendAttempt>
  current: SendAttempt | null
  subscriptionEpoch: number
  unsubscribe: (() => Promise<void>) | null
  turnId: string | null
}

const dispatch = (
  state: InternalState,
  event: TurnEvent,
  sys?: (msg: string) => void,
  appendMessage?: (msg: Msg) => void,
  releaseSessionImages?: (claimId?: string) => void,
  invalidateTransport?: () => void
): void => {
  switch (event.type) {
    case 'message.start':
      onMessageStart(state, event)
      return
    case 'token.delta':
      if (acceptsTurnPayload(state)) {
        onTokenDelta(event)
      }
      return
    case 'thinking.delta':
      if (acceptsTurnPayload(state)) {
        turnController.recordReasoningDelta(event.payload.text)
      }
      return
    case 'tool.start':
      if (acceptsTurnPayload(state)) {
        onToolStart(event)
      }
      return
    case 'tool.progress':
      return
    case 'tool.complete':
      if (acceptsTurnPayload(state)) {
        onToolComplete(event)
      }
      return
    case 'message.complete':
      onMessageComplete(state, event, appendMessage, releaseSessionImages)
      return
    case 'error':
      onError(state, event, sys, appendMessage, releaseSessionImages, invalidateTransport)
      return
    case 'subagent.delivered':
      appendMessage?.({ role: 'assistant', text: event.payload.text })
      return
    case 'cron.delivered': {
      if (sys) {
        const { name, text, fired_at } = event.payload
        const tag = fired_at ? `${name} @ ${fired_at}` : name
        sys(`─── ⏰ ${tag} ───\n${text}\n${'─'.repeat(40)}`)
      }
      return
    }
    default: {
      // Exhaustiveness — if a new TurnEvent variant lands the type-checker
      // will complain here, forcing this file to be updated.
      const exhaustive: never = event
      void exhaustive
    }
  }
}

const acceptsTurnPayload = (state: InternalState): boolean => {
  const attempt = state.current

  return Boolean(attempt?.started && !attempt.invalidated && !attempt.terminal)
}

const onMessageStart = (state: InternalState, ev: MessageStartEvent): void => {
  const attempt = state.attempts.get(ev.payload.submission_id)

  if (!attempt) {
    return
  }

  attempt.turnId = ev.payload.turn_id
  attempt.started = true
  if (attempt.watchdog !== null) {
    clearTimeout(attempt.watchdog)
    attempt.watchdog = null
  }
  if (state.current !== attempt || attempt.invalidated || attempt.terminal) {
    return
  }

  state.turnId = attempt.turnId
  turnController.startMessage()
  patchUiState({ status: 'running…' })
}

const onTokenDelta = (ev: TokenDeltaEvent): void => {
  turnController.recordMessageDelta({ text: ev.payload.text })
}

const onToolStart = (ev: ToolStartEvent): void => {
  const { tool_call_id, name, arguments: args } = ev.payload
  // Render a short context line from the first scalar argument value so the
  // active-tool list shows useful preview text without leaking the full
  // argument blob into the UI.
  const previewKey = Object.keys(args)[0]
  const previewVal = previewKey !== undefined ? args[previewKey] : undefined
  const context =
    typeof previewVal === 'string' ? previewVal : previewVal !== undefined ? JSON.stringify(previewVal) : ''
  turnController.recordToolStart(tool_call_id, name, context)
}

const onToolComplete = (ev: ToolCompleteEvent): void => {
  const { tool_call_id, result_preview, failed, truncated } = ev.payload
  const summary = truncated ? `${result_preview} (truncated)` : result_preview
  turnController.recordToolComplete(
    tool_call_id,
    undefined,
    failed ? summary : undefined,
    failed ? undefined : summary
  )
}

const releaseAttemptImages = (attempt: SendAttempt, releaseSessionImages?: (claimId?: string) => void): void => {
  if (attempt.imagesSettled) {
    return
  }

  if (attempt.imageClaimId) {
    releaseSessionImages?.(attempt.imageClaimId)
  }
  attempt.imagesSettled = true
}

const onMessageComplete = (
  state: InternalState,
  ev: MessageCompleteEvent,
  appendMessage?: (msg: Msg) => void,
  releaseSessionImages?: (claimId?: string) => void
): void => {
  const attempt = state.attempts.get(ev.payload.submission_id)

  if (!attempt || attempt.terminal) {
    return
  }

  attempt.terminal = true
  attempt.turnId = ev.payload.turn_id
  if (attempt.watchdog !== null) {
    clearTimeout(attempt.watchdog)
    attempt.watchdog = null
  }
  releaseAttemptImages(attempt, releaseSessionImages)
  state.attempts.delete(attempt.submissionId)
  if (state.current !== attempt || attempt.invalidated) {
    return
  }

  state.current = null
  state.turnId = null
  // The typed message.complete carries `{turn_id, usage}` per CAP-CHAT-1
  // wire shape (B1 fix); the assistant content is reconstructed from the
  // `bufRef` accumulated via token.delta. recordMessageComplete reads bufRef
  // when payload.text is omitted and returns the final message list that
  // the caller must commit into history — without this the streamed tokens
  // appear during the turn but vanish when the turn closes.
  if (ev.payload.usage) {
    patchUiState(s => ({ ...s, usage: { ...s.usage, ...ev.payload.usage } }))
  }
  const { finalMessages, finalText, wasInterrupted } = turnController.recordMessageComplete({})
  if (!wasInterrupted && appendMessage) {
    const msgs: Msg[] = finalMessages.length > 0 ? finalMessages : [{ role: 'assistant', text: finalText }]
    msgs.forEach(appendMessage)
  }
  patchUiState({ status: 'ready' })
}

const onError = (
  state: InternalState,
  ev: ErrorEvent,
  sys?: (msg: string) => void,
  appendMessage?: (msg: Msg) => void,
  releaseSessionImages?: (claimId?: string) => void,
  invalidateTransport?: () => void
): void => {
  const { attachments_discarded: attachmentsDiscarded, submission_id: submissionId, reason, message, code } = ev.payload
  const attempt = submissionId ? state.attempts.get(submissionId) : undefined

  if (submissionId && !attempt) {
    return
  }

  if (!attempt) {
    const hadActiveAttempt = state.current !== null
    if (attachmentsDiscarded) {
      releaseSessionImages?.()
      sys?.('pending image attachment discarded; attach it again before retrying')
    }
    sys?.(`error: ${message} (code=${code})`)
    invalidateTransport?.()
    if (hadActiveAttempt) {
      turnController.finalizeInterruptedTurn({ appendMessage, sys })
      turnController.clearStatusTimer()
    } else {
      turnController.recordError()
    }
    patchUiState({ busy: false, status: `error: ${message.slice(0, 80)}` })
    patchTurnState({ activity: [], outcome: '' })
    return
  }
  if (attempt.terminal) {
    return
  }

  attempt.terminal = true
  attempt.turnId = ev.payload.turn_id ?? attempt.turnId
  if (attempt.watchdog !== null) {
    clearTimeout(attempt.watchdog)
    attempt.watchdog = null
  }
  releaseAttemptImages(attempt, releaseSessionImages)
  state.attempts.delete(attempt.submissionId)
  if (attachmentsDiscarded && sys) {
    sys('pending image attachment discarded; attach it again before retrying')
  }
  if (state.current !== attempt || attempt.invalidated) {
    return
  }

  state.current = null
  state.turnId = null
  if (reason === 'cancelled_by_client') {
    restoreInputPrompt(appendMessage, sys)
    return
  }
  // Non-cancellation error: surface a sys note, idle the turn, and reset
  // the live anchor so the user can submit again.
  if (sys) {
    sys(`error: ${message} (code=${code})`)
  }
  turnController.recordError()
  patchUiState({ busy: false, status: `error: ${message.slice(0, 80)}` })
  patchTurnState({ activity: [], outcome: '' })
}

const restoreInputPrompt = (appendMessage?: (msg: Msg) => void, sys?: (msg: string) => void): void => {
  // Preserve streamed content, drop streaming state, release `busy`, and
  // settle the visible status after a cancelled turn.
  turnController.finalizeInterruptedTurn({ appendMessage, sys })
  turnController.clearStatusTimer()
  patchUiState({ busy: false, status: 'interrupted' })
  turnController.statusTimer = setTimeout(() => {
    turnController.statusTimer = null
    if (!getUiState().busy) {
      patchUiState({ status: 'ready' })
    }
  }, 800)
}

const isAuthoritativeRpcRejection = (error: unknown): error is RpcError => error instanceof RpcError

export const createChatStream = (opts: ChatStreamOptions): ChatStreamHandle => {
  const state: InternalState = {
    attached: false,
    attempts: new Map(),
    current: null,
    subscriptionEpoch: 0,
    unsubscribe: null,
    turnId: null
  }

  const watchdogMs = opts.watchdogMs ?? DEFAULT_WATCHDOG_MS

  const clearAttemptWatchdog = (attempt: SendAttempt): void => {
    if (attempt.watchdog !== null) {
      clearTimeout(attempt.watchdog)
      attempt.watchdog = null
    }
  }

  const rollbackImageClaim = (imageClaimId?: string): void => {
    if (!imageClaimId) {
      return
    }

    if (opts.rollbackSessionImages) {
      opts.rollbackSessionImages(opts.sessionKey, imageClaimId)
    } else {
      opts.releaseSessionImages?.(opts.sessionKey, imageClaimId)
    }
  }

  const rollbackAttemptImages = (attempt: SendAttempt): void => {
    if (attempt.imagesSettled) {
      return
    }

    rollbackImageClaim(attempt.imageClaimId)
    attempt.imagesSettled = true
  }

  const invalidateAttempt = (attempt: SendAttempt, reason: AttemptInvalidation): void => {
    attempt.invalidated ??= reason
    clearAttemptWatchdog(attempt)
    if (state.current === attempt) {
      state.current = null
    }
  }

  const invalidateCurrent = (reason: AttemptInvalidation): void => {
    const attempt = state.current

    if (attempt) {
      invalidateAttempt(attempt, reason)
    }
    state.turnId = null
  }

  const invalidateSubscription = (): void => {
    invalidateCurrent('transport_error')
    state.subscriptionEpoch += 1
    state.attached = false
    const unsubscribe = state.unsubscribe
    state.unsubscribe = null
    if (unsubscribe) {
      void unsubscribe().catch(() => undefined)
    }
  }

  const forceReset = (): void => {
    invalidateCurrent('force_reset')
    restoreInputPrompt(opts.appendMessage, opts.sys)
  }

  const armAckWatchdog = (attempt: SendAttempt): void => {
    clearAttemptWatchdog(attempt)
    attempt.watchdog = setTimeout(() => {
      if (state.current !== attempt || attempt.invalidated || attempt.terminal || attempt.started) {
        return
      }

      opts.sys?.('turn produced no response — input restored (press Enter to retry)')
      invalidateCurrent('watchdog')
      restoreInputPrompt(opts.appendMessage, opts.sys)
    }, watchdogMs)
  }

  async function attach(): Promise<void> {
    if (state.attached) {
      return
    }

    const subscriptionEpoch = ++state.subscriptionEpoch
    const params: TurnSubscribeParams = { session_key: opts.sessionKey }
    const result = await opts.rpcClient.subscribe<TurnEvent, TurnSubscribeParams>(
      'turn.subscribe',
      params,
      event => {
        if (subscriptionEpoch !== state.subscriptionEpoch) {
          return
        }
        dispatch(
          state,
          event,
          opts.sys,
          opts.appendMessage,
          opts.releaseSessionImages
            ? claimId =>
                claimId
                  ? opts.releaseSessionImages?.(opts.sessionKey, claimId)
                  : opts.releaseSessionImages?.(opts.sessionKey)
            : undefined,
          invalidateSubscription
        )
      },
      { unsubscribeMethod: 'turn.unsubscribe' }
    )

    if (subscriptionEpoch !== state.subscriptionEpoch) {
      await result.unsubscribe()
      return
    }

    state.unsubscribe = result.unsubscribe
    state.attached = true
  }

  const detach = async (): Promise<void> => {
    state.subscriptionEpoch += 1
    for (const attempt of [...state.attempts.values()]) {
      invalidateAttempt(attempt, 'detach')
    }
    state.current = null
    state.turnId = null
    const u = state.unsubscribe
    state.unsubscribe = null
    state.attached = false
    if (u) {
      await u()
    }
  }

  const send = async (content: string, imageClaimId?: string): Promise<TurnSendResult> => {
    if (!state.attached) {
      try {
        await attach()
      } catch (error) {
        rollbackImageClaim(imageClaimId)
        throw error
      }
    }

    if (!state.attached) {
      rollbackImageClaim(imageClaimId)
      throw new Error('turn subscription is not attached')
    }

    if (state.current) {
      rollbackImageClaim(imageClaimId)
      throw new Error('turn already in progress — wait for message.complete or cancel first')
    }

    const submissionId = opts.submissionIdFactory?.() ?? randomUUID()
    const attempt: SendAttempt = {
      imageClaimId,
      imagesSettled: false,
      invalidated: null,
      rpcSettled: false,
      started: false,
      submissionId,
      terminal: false,
      turnId: null,
      watchdog: null
    }
    const params: TurnSendParams = {
      session_key: opts.sessionKey,
      content,
      submission_id: submissionId
    }

    state.attempts.set(submissionId, attempt)
    state.current = attempt
    armAckWatchdog(attempt)

    let result: TurnSendResult
    try {
      result = await opts.rpcClient.rpc<TurnSendResult, TurnSendParams>('turn.send', params)
    } catch (err) {
      attempt.rpcSettled = true
      clearAttemptWatchdog(attempt)
      if (attempt.terminal) {
        return { accepted: true, turn_id: attempt.turnId ?? '' }
      }
      if (isAuthoritativeRpcRejection(err)) {
        state.attempts.delete(submissionId)
        rollbackAttemptImages(attempt)
        if (state.current === attempt) {
          state.current = null
          state.turnId = null
        }
        if (attempt.invalidated) {
          return { accepted: true, turn_id: attempt.turnId ?? '' }
        }
        throw err
      }
      if (attempt.invalidated) {
        return { accepted: true, turn_id: attempt.turnId ?? '' }
      }

      invalidateSubscription()
      opts.sys?.('turn delivery status is unknown; input restored while awaiting server settlement')
      restoreInputPrompt(opts.appendMessage, opts.sys)

      return { accepted: true, turn_id: attempt.turnId ?? '' }
    }

    attempt.rpcSettled = true
    attempt.turnId ??= result.turn_id
    if (attempt.terminal) {
      return { accepted: true, turn_id: attempt.turnId ?? result.turn_id }
    }
    if (!result.accepted) {
      clearAttemptWatchdog(attempt)
      state.attempts.delete(submissionId)
      rollbackAttemptImages(attempt)
      if (state.current === attempt) {
        state.current = null
        state.turnId = null
      }
      if (attempt.invalidated) {
        return { accepted: true, turn_id: attempt.turnId ?? result.turn_id }
      }
      return result
    }
    clearAttemptWatchdog(attempt)
    if (state.current === attempt && !attempt.invalidated && !attempt.terminal) {
      state.turnId = attempt.turnId
    }

    return result
  }

  const cancel = async (): Promise<void> => {
    if (!state.turnId) {
      return
    }
    await opts.rpcClient.rpc<{ cancelled: boolean }, { session_key: string }>('turn.cancel', {
      session_key: opts.sessionKey
    })
    // We do NOT clear state.turnId here — the server is expected to emit an
    // `error(reason=cancelled_by_client)` event that drives the actual
    // UI-state reset via dispatch(). Clearing locally would race with the
    // event delivery and leave the turn-active guard inconsistent.
  }

  const isTurnActive = (): boolean => state.attempts.size > 0

  return { attach, detach, send, cancel, isTurnActive, forceReset, sessionKey: opts.sessionKey }
}
