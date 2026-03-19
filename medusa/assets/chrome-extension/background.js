/**
 * Medusa Browser Relay — Chrome Extension Service Worker
 *
 * The extension auto-connects to the local Medusa relay server and waits
 * for commands.  The agent creates its OWN new tabs (never touches user
 * tabs) which are grouped under a visible "Medusa" tab group.  All CDP
 * commands are forwarded via chrome.debugger on agent-created tabs only.
 *
 * Flow:
 *   1. Extension polls relay server every few seconds until it's up.
 *   2. Once connected, relay can send Target.createTarget → extension
 *      creates a new tab, adds it to the "Medusa" tab group, attaches
 *      chrome.debugger, and reports back.
 *   3. All further CDP commands operate on agent-created tabs only.
 *   4. When relay disconnects, agent tabs are cleaned up.
 */

const DEFAULT_PORT = 18792
const TAB_GROUP_TITLE = 'Medusa'
const TAB_GROUP_COLOR = 'green'
const AUTO_CONNECT_INTERVAL_MS = 3000

const BADGE = {
  on:         { text: 'ON',  color: '#4CAF50' },
  off:        { text: '',    color: '#000000' },
  connecting: { text: '...', color: '#F59E0B' },
  error:      { text: '!',   color: '#B91C1C' },
}

// ── Relay WebSocket state ───────────────────────────────────────────

/** @type {WebSocket|null} */
let relayWs = null

/** @type {Promise<void>|null} */
let relayConnectPromise = null

let debuggerListenersInstalled = false

let nextSession = 1

/** @type {number|null} Auto-connect polling timer */
let autoConnectTimer = null

/** @type {boolean} Whether auto-connect polling is active */
let autoConnectEnabled = true

/**
 * Per-tab state for tabs created and attached by the agent.
 * Only agent-created tabs go in here — never user tabs.
 * @type {Map<number, {state:'connecting'|'connected', sessionId?:string, targetId?:string}>}
 */
const tabs = new Map()

/** @type {Map<string, number>} sessionId → tabId */
const tabBySession = new Map()

/** @type {Map<string, number>} child sessionId → parent tabId */
const childSessionToTab = new Map()

/** @type {Map<number, {resolve:(v:any)=>void, reject:(e:Error)=>void}>} */
const pending = new Map()

/** @type {number|null} Chrome tab group ID for agent tabs */
let medusaGroupId = null


// ── Helpers ─────────────────────────────────────────────────────────

async function getRelayPort() {
  const stored = await chrome.storage.local.get(['relayPort'])
  const raw = stored.relayPort
  const n = Number.parseInt(String(raw || ''), 10)
  if (!Number.isFinite(n) || n <= 0 || n > 65535) return DEFAULT_PORT
  return n
}

function setGlobalBadge(kind) {
  const cfg = BADGE[kind]
  void chrome.action.setBadgeText({ text: cfg.text })
  void chrome.action.setBadgeBackgroundColor({ color: cfg.color })
  void chrome.action.setBadgeTextColor({ color: '#FFFFFF' }).catch(() => {})
}


// ── Tab group management ────────────────────────────────────────────

async function ensureMedusaTabGroup(tabId) {
  /**
   * Add a tab to the "Medusa" tab group.  Creates the group on first use.
   */
  try {
    if (medusaGroupId !== null) {
      // Verify group still exists
      try {
        await chrome.tabGroups.get(medusaGroupId)
      } catch {
        medusaGroupId = null
      }
    }

    if (medusaGroupId === null) {
      // Create a new group with this tab
      medusaGroupId = await chrome.tabs.group({ tabIds: [tabId] })
      await chrome.tabGroups.update(medusaGroupId, {
        title: TAB_GROUP_TITLE,
        color: TAB_GROUP_COLOR,
        collapsed: false,
      })
    } else {
      // Add tab to existing group
      await chrome.tabs.group({ tabIds: [tabId], groupId: medusaGroupId })
    }
  } catch (err) {
    // Tab grouping is best-effort — don't fail the attach
    console.warn('Failed to add tab to Medusa group:', err)
  }
}


// ── Auto-connect polling ────────────────────────────────────────────

function startAutoConnect() {
  if (autoConnectTimer !== null) return
  autoConnectEnabled = true
  autoConnectTimer = setInterval(() => void tryAutoConnect(), AUTO_CONNECT_INTERVAL_MS)
  // Also try immediately
  void tryAutoConnect()
}

function stopAutoConnect() {
  autoConnectEnabled = false
  if (autoConnectTimer !== null) {
    clearInterval(autoConnectTimer)
    autoConnectTimer = null
  }
}

async function tryAutoConnect() {
  if (!autoConnectEnabled) return
  if (relayWs && relayWs.readyState === WebSocket.OPEN) return

  try {
    await ensureRelayConnection()
    // Connected! Stop polling.
    stopAutoConnect()
    setGlobalBadge('on')
    void chrome.action.setTitle({ title: 'Medusa Browser Relay: connected' })
  } catch {
    // Relay not up yet — keep polling
  }
}


// ── Relay connection ────────────────────────────────────────────────

async function ensureRelayConnection() {
  if (relayWs && relayWs.readyState === WebSocket.OPEN) return
  if (relayConnectPromise) return await relayConnectPromise

  relayConnectPromise = (async () => {
    const port = await getRelayPort()
    const httpBase = `http://127.0.0.1:${port}`
    const wsUrl = `ws://127.0.0.1:${port}/extension`

    // Fast preflight — is the relay server up?
    try {
      await fetch(`${httpBase}/`, { method: 'HEAD', signal: AbortSignal.timeout(2000) })
    } catch (err) {
      throw new Error(`Relay server not reachable at ${httpBase} (${String(err)})`)
    }

    const ws = new WebSocket(wsUrl)
    relayWs = ws

    await new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('WebSocket connect timeout')), 5000)
      ws.onopen = () => { clearTimeout(t); resolve() }
      ws.onerror = () => { clearTimeout(t); reject(new Error('WebSocket connect failed')) }
      ws.onclose = (ev) => {
        clearTimeout(t)
        reject(new Error(`WebSocket closed (${ev.code} ${ev.reason || 'no reason'})`))
      }
    })

    ws.onmessage = (event) => void onRelayMessage(String(event.data || ''))
    ws.onclose = () => onRelayClosed('closed')
    ws.onerror = () => onRelayClosed('error')

    if (!debuggerListenersInstalled) {
      debuggerListenersInstalled = true
      chrome.debugger.onEvent.addListener(onDebuggerEvent)
      chrome.debugger.onDetach.addListener(onDebuggerDetach)
    }
  })()

  try {
    await relayConnectPromise
  } finally {
    relayConnectPromise = null
  }
}

function onRelayClosed(reason) {
  relayWs = null
  for (const [id, p] of pending.entries()) {
    pending.delete(id)
    p.reject(new Error(`Relay disconnected (${reason})`))
  }

  // Detach and close all agent-created tabs
  for (const tabId of tabs.keys()) {
    void chrome.debugger.detach({ tabId }).catch(() => {})
    // Optionally close agent tabs when relay disconnects
    // void chrome.tabs.remove(tabId).catch(() => {})
  }
  tabs.clear()
  tabBySession.clear()
  childSessionToTab.clear()
  medusaGroupId = null

  setGlobalBadge('off')
  void chrome.action.setTitle({ title: 'Medusa Browser Relay: disconnected' })

  // Resume auto-connect polling so we reconnect when relay comes back
  startAutoConnect()
}

function sendToRelay(payload) {
  const ws = relayWs
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    throw new Error('Relay not connected')
  }
  ws.send(JSON.stringify(payload))
}


// ── Tab attach / detach (agent-created tabs only) ───────────────────

async function attachTab(tabId, opts = {}) {
  const debuggee = { tabId }
  await chrome.debugger.attach(debuggee, '1.3')
  await chrome.debugger.sendCommand(debuggee, 'Page.enable').catch(() => {})

  const info = /** @type {any} */ (
    await chrome.debugger.sendCommand(debuggee, 'Target.getTargetInfo')
  )
  const targetInfo = info?.targetInfo
  const targetId = String(targetInfo?.targetId || '').trim()
  if (!targetId) {
    throw new Error('Target.getTargetInfo returned no targetId')
  }

  const sessionId = `cb-tab-${nextSession++}`

  tabs.set(tabId, { state: 'connected', sessionId, targetId })
  tabBySession.set(sessionId, tabId)

  // Add to Medusa tab group
  await ensureMedusaTabGroup(tabId)

  if (!opts.skipAttachedEvent) {
    sendToRelay({
      method: 'forwardCDPEvent',
      params: {
        method: 'Target.attachedToTarget',
        params: {
          sessionId,
          targetInfo: { ...targetInfo, attached: true },
          waitingForDebugger: false,
        },
      },
    })
  }

  return { sessionId, targetId }
}

async function detachTab(tabId, reason) {
  const tab = tabs.get(tabId)
  if (tab?.sessionId && tab?.targetId) {
    try {
      sendToRelay({
        method: 'forwardCDPEvent',
        params: {
          method: 'Target.detachedFromTarget',
          params: { sessionId: tab.sessionId, targetId: tab.targetId, reason },
        },
      })
    } catch {
      // ignore
    }
  }

  if (tab?.sessionId) tabBySession.delete(tab.sessionId)
  tabs.delete(tabId)

  for (const [childSessionId, parentTabId] of childSessionToTab.entries()) {
    if (parentTabId === tabId) childSessionToTab.delete(childSessionId)
  }

  try {
    await chrome.debugger.detach({ tabId })
  } catch {
    // ignore
  }
}


// ── CDP command forwarding ──────────────────────────────────────────

function getTabBySessionId(sessionId) {
  const direct = tabBySession.get(sessionId)
  if (direct) return { tabId: direct, kind: 'main' }
  const child = childSessionToTab.get(sessionId)
  if (child) return { tabId: child, kind: 'child' }
  return null
}

function getTabByTargetId(targetId) {
  for (const [tabId, tab] of tabs.entries()) {
    if (tab.targetId === targetId) return tabId
  }
  return null
}

async function handleForwardCdpCommand(msg) {
  const method = String(msg?.params?.method || '').trim()
  const params = msg?.params?.params || undefined
  const sessionId = typeof msg?.params?.sessionId === 'string' ? msg.params.sessionId : undefined

  // Map command to an agent-owned tab
  const bySession = sessionId ? getTabBySessionId(sessionId) : null
  const targetId = typeof params?.targetId === 'string' ? params.targetId : undefined
  const tabId =
    bySession?.tabId ||
    (targetId ? getTabByTargetId(targetId) : null) ||
    (() => {
      // No sessionId: pick the first connected agent tab
      for (const [id, tab] of tabs.entries()) {
        if (tab.state === 'connected') return id
      }
      return null
    })()

  // ── Special commands handled via Chrome extension APIs ─────────

  // Runtime.enable needs a reset workaround
  if (method === 'Runtime.enable' && tabId) {
    const debuggee = { tabId }
    try {
      await chrome.debugger.sendCommand(debuggee, 'Runtime.disable')
      await new Promise((r) => setTimeout(r, 50))
    } catch {
      // ignore
    }
    return await chrome.debugger.sendCommand(debuggee, 'Runtime.enable', params)
  }

  // Agent creates a new tab → we create it, group it, and attach debugger
  if (method === 'Target.createTarget') {
    const url = typeof params?.url === 'string' ? params.url : 'about:blank'
    const newTab = await chrome.tabs.create({ url, active: true })
    if (!newTab.id) throw new Error('Failed to create tab')
    await new Promise((r) => setTimeout(r, 150))
    const attached = await attachTab(newTab.id)
    return { targetId: attached.targetId }
  }

  // Agent closes a tab
  if (method === 'Target.closeTarget') {
    const target = typeof params?.targetId === 'string' ? params.targetId : ''
    const toClose = target ? getTabByTargetId(target) : tabId
    if (!toClose) return { success: false }
    // Only close agent-owned tabs
    if (!tabs.has(toClose)) return { success: false }
    try {
      await chrome.tabs.remove(toClose)
    } catch {
      return { success: false }
    }
    return { success: true }
  }

  // Agent activates (focuses) a tab
  if (method === 'Target.activateTarget') {
    const target = typeof params?.targetId === 'string' ? params.targetId : ''
    const toActivate = target ? getTabByTargetId(target) : tabId
    if (!toActivate) return {}
    const tab = await chrome.tabs.get(toActivate).catch(() => null)
    if (!tab) return {}
    if (tab.windowId) {
      await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {})
    }
    await chrome.tabs.update(toActivate, { active: true }).catch(() => {})
    return {}
  }

  // All other commands require an attached tab
  if (!tabId) throw new Error(`No attached agent tab for method ${method}`)

  const debuggee = { tabId }
  const tabState = tabs.get(tabId)
  const mainSessionId = tabState?.sessionId
  const debuggerSession =
    sessionId && mainSessionId && sessionId !== mainSessionId
      ? { ...debuggee, sessionId }
      : debuggee

  return await chrome.debugger.sendCommand(debuggerSession, method, params)
}


// ── Relay message handling ──────────────────────────────────────────

async function onRelayMessage(text) {
  /** @type {any} */
  let msg
  try {
    msg = JSON.parse(text)
  } catch {
    return
  }

  // Ping / pong keepalive
  if (msg && msg.method === 'ping') {
    try { sendToRelay({ method: 'pong' }) } catch { /* ignore */ }
    return
  }

  // Response to a request we sent
  if (msg && typeof msg.id === 'number' && (msg.result !== undefined || msg.error !== undefined)) {
    const p = pending.get(msg.id)
    if (!p) return
    pending.delete(msg.id)
    if (msg.error) p.reject(new Error(String(msg.error)))
    else p.resolve(msg.result)
    return
  }

  // Forward CDP command from relay → chrome.debugger
  if (msg && typeof msg.id === 'number' && msg.method === 'forwardCDPCommand') {
    try {
      const result = await handleForwardCdpCommand(msg)
      sendToRelay({ id: msg.id, result })
    } catch (err) {
      sendToRelay({ id: msg.id, error: err instanceof Error ? err.message : String(err) })
    }
  }
}


// ── Debugger event forwarding ───────────────────────────────────────

function onDebuggerEvent(source, method, params) {
  const tabId = source.tabId
  if (!tabId) return
  // Only forward events from agent-owned tabs
  const tab = tabs.get(tabId)
  if (!tab?.sessionId) return

  if (method === 'Target.attachedToTarget' && params?.sessionId) {
    childSessionToTab.set(String(params.sessionId), tabId)
  }
  if (method === 'Target.detachedFromTarget' && params?.sessionId) {
    childSessionToTab.delete(String(params.sessionId))
  }

  try {
    sendToRelay({
      method: 'forwardCDPEvent',
      params: {
        sessionId: source.sessionId || tab.sessionId,
        method,
        params,
      },
    })
  } catch {
    // ignore
  }
}

function onDebuggerDetach(source, reason) {
  const tabId = source.tabId
  if (!tabId) return
  if (!tabs.has(tabId)) return
  void detachTab(tabId, reason)
}


// ── Extension lifecycle ─────────────────────────────────────────────

// Toolbar icon click: toggle auto-connect or show status
chrome.action.onClicked.addListener(() => {
  if (relayWs && relayWs.readyState === WebSocket.OPEN) {
    // Already connected — show options page
    void chrome.runtime.openOptionsPage()
  } else {
    // Try to connect now
    void tryAutoConnect()
  }
})

chrome.runtime.onInstalled.addListener(() => {
  void chrome.runtime.openOptionsPage()
})

// Start auto-connect polling on service worker startup
startAutoConnect()
