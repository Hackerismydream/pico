// SPDX-License-Identifier: MIT
// Copyright (c) 2026 EverMind.
// See NOTICES.md.
//
// Production TUI client over the Python-owned JSON-RPC socket.

import { EventEmitter } from 'node:events'

import type { GatewayEvent } from './gatewayTypes.js'

import { RpcClient } from './rpc/index.js'

const CLIENT_VERSION = '0.0.2'
// Mirrors the negotiated capability list sent during `system.hello`.
// Server-side does not yet enforce these, but we send the canonical set
// so future capability negotiation has a stable baseline.
const CLIENT_CAPABILITIES: string[] = ['chat', 'config', 'confirm', 'attachments', 'sessions']

export interface TuiRpcClientOptions {
  /** Unix socket path. Defaults to env `PICO_RPC_SOCKET`. */
  socketPath?: string
  /** Injected RpcClient (test seam). Owns its own lifecycle when supplied. */
  rpcClient?: RpcClient
}

export class TuiRpcClient extends EventEmitter {
  // Chat streaming subscribes through this same client while server
  // notifications flow through the EventEmitter adapter. Sharing one client
  // keeps the socket count at one and avoids handshake races.
  public readonly rpcClient: RpcClient
  private bufferedEvents: GatewayEvent[] = []
  private subscribed = false
  private startPromise: Promise<void> | null = null
  private killed = false

  constructor(opts: TuiRpcClientOptions = {}) {
    super()
    this.setMaxListeners(0)
    this.rpcClient =
      opts.rpcClient ??
      new RpcClient({
        // Bridge first-class top-level notifications (confirm.request and
        // clarify.request) onto the
        // `'event'` bus that `createGatewayEventHandler` consumes. Subscription
        // -stream `event` notifications keep flowing through the typed registry.
        onNotification: (method, params) => this.publishServerNotification(method, params),
        socketPath: opts.socketPath
      })
  }

  /**
   * Map a top-level server notification (`{method, params}`) to a
   * `GatewayEvent` (`{type, payload}`) and publish it. `createGatewayEventHandler`
   * switches on `type` and ignores unknown ones, so this is forward-compatible.
   */
  private publishServerNotification(method: string, params: unknown): void {
    this.publish({ payload: params, type: method } as GatewayEvent)
  }

  /**
   * Boot sequence:
   *   1. await `system.hello` (5s server-side timeout per Phase 2 RpcServer).
   *   2. synthesize the transport-ready event.
   *   3. buffer (or emit, if `drain()` already called) the event.
   *
   * Repeated calls return the same promise.
   */
  start(): Promise<void> {
    if (this.startPromise) {
      return this.startPromise
    }

    this.startPromise = (async () => {
      await this.rpcClient.rpc('system.hello', {
        client_version: CLIENT_VERSION,
        client_capabilities: CLIENT_CAPABILITIES
      })
      setTimeout(() => {
        if (this.killed) {
          return
        }

        const ready: GatewayEvent = { payload: { skin: {} }, type: 'gateway.ready' }
        this.publish(ready)
      }, 0)
    })()

    return this.startPromise
  }

  /**
   * Switch to direct event delivery and replay boot-time buffered events.
   */
  drain(): void {
    this.subscribed = true
    const queued = this.bufferedEvents
    this.bufferedEvents = []

    for (const ev of queued) {
      this.emit('event', ev)
    }
  }

  /** Invoke an RPC method. Pure delegate to `RpcClient.rpc()`. */
  async request<T = unknown>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    return this.rpcClient.rpc<T>(method, params)
  }

  /**
   * Tear down: close the RPC socket, emit `exit` so `useMainApp.ts` clears
   * UI state. Safe to call multiple times.
   */
  kill(): void {
    if (this.killed) {
      return
    }

    this.killed = true
    this.bufferedEvents = []
    this.subscribed = false
    try {
      this.rpcClient.close()
    } finally {
      this.emit('exit', 0)
    }
  }

  /**
   * The RPC transport has no buffered child-process stdout to tail; server
   * logs are written by Python `loguru` to its own files.
   */
  getLogTail(_limit = 20): string {
    return '(RPC server logs are available through the Python loguru sink)'
  }

  private publish(ev: GatewayEvent): void {
    if (this.subscribed) {
      this.emit('event', ev)
    } else {
      this.bufferedEvents.push(ev)
    }
  }
}
