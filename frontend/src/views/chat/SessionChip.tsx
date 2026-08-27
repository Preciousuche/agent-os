import { useCallback, useEffect, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent } from 'react'
import { toast } from 'sonner'
import {
  Check,
  ChevronDown,
  Copy,
  FileDown,
  FolderKanban,
  MoreHorizontal,
  Pencil,
  RotateCcw,
} from 'lucide-react'
import { authenticatedHeaders } from '@/lib/http-auth'
import {
  classifySessionKey,
  groupSessionsByProject,
  runStatusChipClass,
  sessionItemKey,
  sessionItemName,
  sessionItemSearchText,
  sessionRunStatus,
  type RunStatusResult,
  type SessionGroup,
  type SessionListItem,
} from './logic'
import { useShortcutDocs } from '@/components/KeyboardShortcuts'
import { useOverlayLayer } from '@/components/overlay-layer'
import { t } from '@/i18n'
import '@/i18n/en/chat'

// #137 — the switcher popover and the actions menu bind these to their own
// elements (`onKey` / `onActionsKeyDown` below), so they are documented here.
const SESSION_SHORTCUTS = [
  { combo: 'arrowdown', description: 'Move to the next action' },
  { combo: 'arrowup', description: 'Move to the previous action' },
  { combo: 'escape', description: 'Close the switcher and restore focus' },
] as const

/**
 * Session chip + switcher (React) — ported from the legacy topbar-center chip
 * (chat.js:1219-1229 render, 1836-2089 `_bindSessionChip`).
 *
 * One chip acts as the switcher trigger; a compact actions menu keeps copy,
 * reset, and export available inside the Chat-only floating workspace header.
 * Opening the chip fetches the session list from `/api/sessions` (chat.js:2026), grouping items via
 * `classifySessionKey` (chat.js:1862) and tagging each with its run status
 * (chat.js:1611). Selecting a session calls `onSwitch(key)` — the transcript
 * owner (ChatPage) re-points `useTranscript` at the new key, which parks the old
 * session's stream, re-subscribes, and reloads history. When the list fetch
 * fails, the popover degrades to a manual key-entry field (chat.js:2038-2069).
 */

// chat.js:1903 — the switcher group order (empty groups are skipped).
const GROUP_ORDER: SessionGroup[] = ['Web chat', 'CLI', 'Sub-agents', 'Agents', 'Sessions', 'Other']

/**
 * `SessionGroup` is a stable token set — it is both a type and the bucket key
 * `classifySessionKey` returns — so only the rendered label is translated.
 */
function groupLabel(group: SessionGroup): string {
  const labels: Record<SessionGroup, string> = {
    'Web chat': t('chat.groupWebChat'),
    CLI: t('chat.groupCli'),
    'Sub-agents': t('chat.groupSubagents'),
    Agents: t('chat.groupAgents'),
    Sessions: t('chat.groupSessions'),
    Other: t('chat.groupOther'),
  }
  return labels[group]
}

const COMPACT_RUN_LABEL: Record<RunStatusResult['status'], string> = {
  idle: 'Idle',
  queued: 'Queue',
  running: 'Run',
  approval_pending: 'Wait',
  interrupted: 'Stop',
  failed: 'Fail',
  timeout: 'Time',
  cancelled: 'Done',
}

// Mirrors MAX_SESSION_NAME_LENGTH in src/agentos/session/naming.py — the
// gateway truncates past this, so stop the input there instead of silently
// dropping the tail on save.
const SESSION_NAME_MAX = 120

export interface SessionChipProps {
  /** The current (canonical) session key (chat.js:1223). */
  sessionKey: string
  /**
   * The current session's user-set name (`display_name`), '' when it has never
   * been renamed. Drives the chip label and prefills the rename input.
   */
  sessionName?: string
  /**
   * Persist a new name for the current session (`sessions.rename`). Omit and
   * the rename action is hidden — same contract as `onExport`. An empty string
   * clears the name.
   */
  onRename?: (name: string) => void
  /** Live current-session run state (chat.js:1767 `_applySessionRunState`). */
  runState?: RunStatusResult
  /** Switch to a different session (chat.js:1809 `_switchToSession`). */
  onSwitch: (key: string) => void
  /** Reset the current session (chat.js:2723 `sessions.reset`). */
  onReset: () => void
  /** Export the current transcript as Markdown. */
  onExport?: () => void
  /**
   * Copy the current key to the clipboard (chat.js:1782
   * `_copySessionKeyToClipboard`). Injected so the component stays pure of the
   * clipboard/execCommand fallback; defaults to `navigator.clipboard`.
   */
  onCopy?: (key: string) => Promise<void>
  /**
   * Fetch the session list (chat.js:2026 `GET /api/sessions`). Injected for
   * testability; defaults to the real `fetch`. Resolves the raw items, or throws
   * → the popover degrades to manual entry.
   */
  fetchSessions?: () => Promise<SessionListItem[]>
  /**
   * Project id → name map. When provided, sessions in a project render under
   * a per-project tier above the kind groups; omit and the switcher keeps its
   * legacy kind-only grouping.
   */
  projectsById?: Map<string, string>
  /** The current session's project id ('' when project-less). */
  projectId?: string
  /**
   * Move the current session into a project (`sessions.patch`); `null`
   * detaches. Omit and the "Move to project" action is hidden — same
   * contract as `onExport`.
   */
  onMoveToProject?: (projectId: string | null) => void
}

function defaultCopy(key: string): Promise<void> {
  // chat.js:1784-1806 — clipboard API with an execCommand fallback.
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    return navigator.clipboard.writeText(key)
  }
  const textarea = document.createElement('textarea')
  textarea.value = key
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.left = '-9999px'
  textarea.style.top = '0'
  document.body.appendChild(textarea)
  textarea.focus()
  textarea.select()
  let copied = false
  try {
    copied = document.execCommand('copy')
  } finally {
    textarea.remove()
  }
  return copied ? Promise.resolve() : Promise.reject(new Error('Copy command failed'))
}

async function defaultFetchSessions(): Promise<SessionListItem[]> {
  // chat.js:2026-2032 — GET /api/sessions → data.sessions || data.keys, filtered
  // to items that actually carry a key. A non-OK response throws → manual entry.
  const resp = await fetch('/api/sessions', {
    headers: authenticatedHeaders(),
    credentials: 'same-origin',
  })
  if (!resp.ok) throw new Error('Session list unavailable')
  const data = (await resp.json()) as { sessions?: SessionListItem[]; keys?: SessionListItem[] }
  const raw = data.sessions || data.keys || []
  return raw.filter((s) => !!sessionItemKey(s))
}

export function SessionChip({
  sessionKey,
  sessionName = '',
  runState = sessionRunStatus(undefined),
  onSwitch,
  onReset,
  onExport,
  onRename,
  onCopy = defaultCopy,
  fetchSessions = defaultFetchSessions,
  projectsById,
  projectId = '',
  onMoveToProject,
}: SessionChipProps) {
  const [open, setOpen] = useState(false)
  const [filter, setFilter] = useState('')
  // null = not fetched yet / in-flight; [] = fetched-empty. `failed` degrades
  // the popover to manual key entry (chat.js:2038).
  const [sessions, setSessions] = useState<SessionListItem[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [manualKey, setManualKey] = useState('')
  const [actionsOpen, setActionsOpen] = useState(false)
  // The actions menu swaps its item list for an inline name editor rather than
  // opening a modal — renaming is a one-field edit and the menu is already an
  // Escape-owning layer, so a second layer would only add focus bookkeeping.
  const [renaming, setRenaming] = useState(false)
  // Like renaming, the project picker swaps the menu's item list in place.
  const [moving, setMoving] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  const actionsTriggerRef = useRef<HTMLButtonElement>(null)
  const actionsMenuRef = useRef<HTMLDivElement>(null)

  useShortcutDocs('Session switcher', SESSION_SHORTCUTS)
  // Neither of these is a ModalShell, but both are dismissible layers that own
  // Escape while they are up — so document-level shortcuts must stand down for
  // them, exactly as they did for the old `.chat-session-popover` selector.
  useOverlayLayer(open || actionsOpen)

  const getSessionTrigger = useCallback(
    () => document.querySelector<HTMLButtonElement>('#chat-session-switcher-trigger'),
    [],
  )
  const getActionsTrigger = useCallback(
    () => document.querySelector<HTMLButtonElement>('#chat-session-actions-trigger'),
    [],
  )

  const focusBeforeDismiss = useCallback((target: () => HTMLElement | null) => {
    target()?.focus()
  }, [])

  const copy = useCallback(() => {
    if (!sessionKey) return
    onCopy(sessionKey)
      .then(() => toast.info('Session key copied'))
      .catch((err: unknown) =>
        toast.error('Copy failed: ' + (err instanceof Error ? err.message : String(err))),
      )
  }, [sessionKey, onCopy])

  const dismiss = useCallback(() => {
    setOpen(false)
    setActionsOpen(false)
    setRenaming(false)
    setMoving(false)
    setFilter('')
    setSessions(null)
    setFailed(false)
    setManualKey(sessionKey)
  }, [sessionKey])

  const toggle = useCallback(() => {
    setActionsOpen(false)
    setOpen((wasOpen) => {
      if (wasOpen) {
        setFilter('')
        setSessions(null)
        setFailed(false)
        setManualKey(sessionKey)
      }
      return !wasOpen
    })
  }, [sessionKey])

  const toggleActions = useCallback(() => {
    setOpen(false)
    setFilter('')
    setSessions(null)
    setFailed(false)
    setManualKey(sessionKey)
    setRenaming(false)
    setMoving(false)
    setActionsOpen((wasOpen) => !wasOpen)
  }, [sessionKey])

  // Rename opens in place inside the menu, prefilled with the current name so
  // the common edit ("fix a typo") does not start from an empty field.
  const startRename = useCallback(() => {
    setNameDraft(sessionName)
    setRenaming(true)
  }, [sessionName])

  const submitRename = useCallback(() => {
    const next = nameDraft.trim()
    focusBeforeDismiss(getActionsTrigger)
    // Skip the round-trip when nothing actually changed.
    if (onRename && next !== sessionName.trim()) onRename(next)
    dismiss()
  }, [dismiss, focusBeforeDismiss, getActionsTrigger, nameDraft, onRename, sessionName])

  const runHeaderAction = useCallback(
    (action: () => void) => {
      focusBeforeDismiss(getActionsTrigger)
      action()
      dismiss()
    },
    [dismiss, focusBeforeDismiss, getActionsTrigger],
  )

  const switchTo = useCallback(
    (key: string) => {
      focusBeforeDismiss(getSessionTrigger)
      dismiss()
      if (key && key !== sessionKey) onSwitch(key)
    },
    [dismiss, focusBeforeDismiss, getSessionTrigger, onSwitch, sessionKey],
  )

  // chat.js:1960-2076 — opening the chip fetches the session list (the close-time
  // reset lives in `toggle`/`dismiss`, so this effect only synchronizes the
  // external fetch while open — no setState-in-effect cascade). Refetch each open
  // so a freshly-created session shows up.
  useEffect(() => {
    if (!open) return
    let cancelled = false
    fetchSessions()
      .then((list) => {
        if (!cancelled) setSessions(list)
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true)
          setManualKey(sessionKey)
        }
      })
    return () => {
      cancelled = true
    }
  }, [open, fetchSessions, sessionKey])

  useEffect(() => {
    // While the inline rename editor is up the input owns focus (autoFocus),
    // so don't yank it back to the first menu item. `moving` is a dep so the
    // first project-picker item receives focus when the list swaps in.
    if (!actionsOpen || renaming) return
    actionsMenuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
  }, [actionsOpen, renaming, moving])

  // chat.js:2004-2020 — dismiss on outside click / Escape while open.
  useEffect(() => {
    if (!open && !actionsOpen) return
    const onDocClick = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) dismiss()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        e.stopPropagation()
        const restoreTarget = actionsOpen ? getActionsTrigger : getSessionTrigger
        focusBeforeDismiss(restoreTarget)
        dismiss()
      }
    }
    // Defer registration so the click that opened us isn't picked up.
    const id = window.setTimeout(() => {
      document.addEventListener('mousedown', onDocClick, true)
      document.addEventListener('keydown', onKey)
    }, 0)
    return () => {
      window.clearTimeout(id)
      document.removeEventListener('mousedown', onDocClick, true)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, actionsOpen, dismiss, focusBeforeDismiss, getActionsTrigger, getSessionTrigger])

  const onActionsKeyDown = useCallback(
    (event: ReactKeyboardEvent<HTMLDivElement>) => {
      // The rename editor is a text field: arrow keys move the caret, and Tab
      // should leave the layer through the browser's own order. Escape still
      // closes it via the document-level handler below.
      if (renaming) return
      const items = Array.from(
        actionsMenuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [],
      )
      if (!items.length) return

      if (event.key === 'Tab') {
        event.preventDefault()
        const trigger = actionsTriggerRef.current
        const contextButtons = Array.from(
          trigger
            ?.closest('[data-chat-session-context]')
            ?.querySelectorAll<HTMLButtonElement>('button:not([disabled])') ?? [],
        ).filter((button) => !actionsMenuRef.current?.contains(button))
        const triggerIndex = trigger ? contextButtons.indexOf(trigger) : -1
        const target = event.shiftKey ? trigger : contextButtons[triggerIndex + 1] || trigger
        focusBeforeDismiss(() => target)
        dismiss()
        return
      }

      const current = items.indexOf(document.activeElement as HTMLButtonElement)
      let next = current
      if (event.key === 'ArrowDown') next = (current + 1) % items.length
      else if (event.key === 'ArrowUp') next = (current - 1 + items.length) % items.length
      else if (event.key === 'Home') next = 0
      else if (event.key === 'End') next = items.length - 1
      else return

      event.preventDefault()
      items[next]?.focus()
    },
    [dismiss, focusBeforeDismiss, renaming],
  )

  // chat.js:1901-1957 — group the fetched sessions, apply the filter. Project
  // tiers (named by the project) render above the legacy kind groups.
  const groups: Array<{ key: string; label: string; items: SessionListItem[] }> = []
  if (sessions) {
    const f = filter.trim().toLowerCase()
    const { projectTiers, rest } = groupSessionsByProject(
      sessions,
      projectsById ?? new Map<string, string>(),
    )
    for (const tier of projectTiers) {
      const visible = f
        ? tier.items.filter((it) => sessionItemSearchText(it).includes(f))
        : tier.items
      if (visible.length)
        groups.push({ key: `project:${tier.id}`, label: tier.name, items: visible })
    }
    const bucket: Record<SessionGroup, SessionListItem[]> = {
      'Web chat': [],
      CLI: [],
      'Sub-agents': [],
      Agents: [],
      Sessions: [],
      Other: [],
    }
    for (const item of rest) {
      const g = classifySessionKey(item)
      if (g) bucket[g].push(item)
    }
    for (const label of GROUP_ORDER) {
      const visible = f
        ? bucket[label].filter((it) => sessionItemSearchText(it).includes(f))
        : bucket[label]
      if (visible.length)
        groups.push({ key: `kind:${label}`, label: groupLabel(label), items: visible })
    }
  }
  const total = groups.reduce((n, g) => n + g.items.length, 0)

  return (
    <div className="chat-session" ref={rootRef}>
      <span className="chat-session-label">{t('chat.sessionLabel')}</span>
      <button
        id="chat-session-switcher-trigger"
        type="button"
        className={`chat-session-chip${open ? ' is-active' : ''}`}
        aria-label={t('chat.sessionSwitchAria')}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={toggle}
      >
        {/* A renamed session shows its name; the key stays reachable through
            the tooltip and "Copy session key". */}
        <span className="chat-session-chip-key" title={sessionKey}>
          {sessionName || sessionKey}
        </span>
        <ChevronDown className="chat-session-chip-caret" aria-hidden="true" />
      </button>
      <span
        id="chat-run-status"
        className={`chip chat-session-run-status ${runStatusChipClass(runState.status)}`.trim()}
        title={[
          runState.label,
          runState.task?.task_id,
          runState.task?.queue_position ? `queue #${runState.task.queue_position}` : '',
          runState.task?.terminal_reason || runState.task?.terminalReason,
        ]
          .filter(Boolean)
          .join(' - ')}
        data-status={runState.status}
      >
        <span className="chat-session-run-status__full">{runState.label}</span>
        <span className="chat-session-run-status__compact" aria-hidden="true">
          {COMPACT_RUN_LABEL[runState.status]}
        </span>
      </span>
      <div className="chat-session-actions">
        <button
          id="chat-session-actions-trigger"
          ref={actionsTriggerRef}
          type="button"
          className="chat-session-actions-trigger"
          title={t('chat.sessionActions')}
          aria-label={t('chat.sessionActions')}
          aria-haspopup="menu"
          aria-expanded={actionsOpen}
          onClick={toggleActions}
        >
          <MoreHorizontal aria-hidden="true" />
        </button>

        {actionsOpen && (
          <div
            ref={actionsMenuRef}
            className="chat-session-actions-menu"
            role="menu"
            aria-label={t('chat.sessionActions')}
            onKeyDown={onActionsKeyDown}
          >
            {renaming ? (
              <form
                className="chat-session-rename"
                onSubmit={(event) => {
                  event.preventDefault()
                  submitRename()
                }}
              >
                <input
                  className="chat-session-rename__input"
                  autoFocus
                  value={nameDraft}
                  maxLength={SESSION_NAME_MAX}
                  placeholder={t('chat.sessionRenamePlaceholder')}
                  aria-label={t('chat.sessionRenameInput')}
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(event) => setNameDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') {
                      // Cancel the edit only — the menu stays up, so Escape
                      // reads as "undo this field", not "close everything".
                      event.preventDefault()
                      event.stopPropagation()
                      setRenaming(false)
                    }
                  }}
                />
                <span className="chat-session-rename__hint">{t('chat.sessionRenameHint')}</span>
              </form>
            ) : null}
            {moving ? (
              // In-place project picker (mirrors the inline rename swap):
              // "No project" detaches, a project entry moves. The current
              // choice is marked and selecting it is a no-op close.
              <>
                <div className="chat-session-actions-menu__label t-label">
                  {t('chat.sessionMoveToProject')}
                </div>
                {[
                  { id: '', label: t('chat.sessionMoveNoProject') },
                  ...[...(projectsById ?? new Map<string, string>()).entries()]
                    .map(([id, label]) => ({ id, label }))
                    .sort((a, b) => a.label.localeCompare(b.label)),
                ].map((option) => {
                  const isCurrent = option.id === (projectId || '')
                  return (
                    <button
                      key={option.id || 'none'}
                      type="button"
                      className={`chat-session-actions-menu__item${isCurrent ? ' is-current' : ''}`}
                      role="menuitem"
                      tabIndex={-1}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() =>
                        runHeaderAction(() => {
                          if (!isCurrent && onMoveToProject)
                            onMoveToProject(option.id === '' ? null : option.id)
                        })
                      }
                    >
                      {isCurrent ? (
                        <Check aria-hidden="true" />
                      ) : (
                        <FolderKanban aria-hidden="true" />
                      )}
                      <span>{option.label}</span>
                    </button>
                  )
                })}
              </>
            ) : null}
            {!renaming && !moving && onRename ? (
              <button
                type="button"
                className="chat-session-actions-menu__item"
                role="menuitem"
                tabIndex={-1}
                aria-label={t('chat.sessionRenameAria')}
                onMouseDown={(event) => event.preventDefault()}
                onClick={startRename}
              >
                <Pencil aria-hidden="true" />
                <span>{t('chat.sessionRename')}</span>
              </button>
            ) : null}
            {!moving && onMoveToProject && ((projectsById?.size ?? 0) > 0 || projectId) ? (
              <button
                type="button"
                className="chat-session-actions-menu__item"
                role="menuitem"
                tabIndex={-1}
                aria-label={t('chat.sessionMoveToProjectAria')}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => setMoving(true)}
              >
                <FolderKanban aria-hidden="true" />
                <span>{t('chat.sessionMoveToProject')}</span>
              </button>
            ) : null}
            {!moving ? (
              <button
                type="button"
                className="chat-session-actions-menu__item"
                role="menuitem"
                tabIndex={-1}
                aria-label={t('chat.sessionCopyKeyAria')}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => runHeaderAction(copy)}
              >
                <Copy aria-hidden="true" />
                <span>{t('chat.sessionCopyKey')}</span>
              </button>
            ) : null}
            {!moving ? (
              <button
                type="button"
                className="chat-session-actions-menu__item"
                role="menuitem"
                tabIndex={-1}
                aria-label={t('chat.sessionResetAria')}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => runHeaderAction(onReset)}
              >
                <RotateCcw aria-hidden="true" />
                <span>{t('chat.sessionReset')}</span>
              </button>
            ) : null}
            {!moving && onExport ? (
              <button
                type="button"
                className="chat-session-actions-menu__item"
                role="menuitem"
                tabIndex={-1}
                aria-label={t('chat.sessionExportAria')}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => runHeaderAction(onExport)}
              >
                <FileDown aria-hidden="true" />
                <span>{t('chat.sessionExport')}</span>
              </button>
            ) : null}
          </div>
        )}
      </div>

      {open && (
        <div
          className="chat-session-popover"
          role="dialog"
          aria-label={t('chat.sessionSwitchDialog')}
        >
          {failed ? (
            <>
              <input
                type="search"
                className="chat-session-popover-search"
                placeholder={t('chat.sessionKeyPlaceholder')}
                aria-label={t('chat.sessionKeyLabel')}
                autoComplete="off"
                spellCheck={false}
                value={manualKey}
                onChange={(e) => setManualKey(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    switchTo(manualKey.trim())
                  }
                }}
                autoFocus
              />
              <div className="chat-session-popover-list">
                <div className="chat-session-popover-empty">{t('chat.sessionListUnavailable')}</div>
                <button
                  type="button"
                  className="chat-session-popover-item"
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => switchTo(manualKey.trim())}
                >
                  <span className="chat-session-popover-item-key">
                    {t('chat.sessionSwitchTyped')}
                  </span>
                </button>
              </div>
            </>
          ) : (
            <>
              <input
                type="search"
                className="chat-session-popover-search"
                placeholder={t('chat.sessionSearchPlaceholder')}
                aria-label={t('chat.sessionSearchLabel')}
                autoComplete="off"
                spellCheck={false}
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                autoFocus
              />
              <div className="chat-session-popover-list">
                {sessions === null ? (
                  <div className="chat-session-popover-empty">{t('chat.sessionLoading')}</div>
                ) : total === 0 ? (
                  <div className="chat-session-popover-empty">
                    {filter.trim() ? t('chat.sessionNoMatches') : t('chat.sessionNoSessions')}
                  </div>
                ) : (
                  groups.map((group) => (
                    <div className="chat-session-popover-group" key={group.key}>
                      <div className="chat-session-popover-group-label">{group.label}</div>
                      {group.items.map((item) => {
                        const k = sessionItemKey(item)
                        const name = sessionItemName(item)
                        const run = sessionRunStatus(typeof item === 'object' ? item : {})
                        const isCurrent = k === sessionKey
                        return (
                          <button
                            type="button"
                            key={k}
                            className={`chat-session-popover-item${isCurrent ? ' is-current' : ''}`}
                            onMouseDown={(event) => event.preventDefault()}
                            onClick={() => switchTo(k)}
                          >
                            {/* A renamed session leads with its name and keeps
                                the key on a second line — the key is still how
                                a session is identified everywhere else. */}
                            <span className="chat-session-popover-item-labels">
                              {name ? (
                                <span className="chat-session-popover-item-name" title={name}>
                                  {name}
                                </span>
                              ) : null}
                              <span
                                className={`chat-session-popover-item-key${name ? ' is-secondary' : ''}`}
                                title={k}
                              >
                                {k}
                              </span>
                            </span>
                            {run.status !== 'idle' && (
                              <span
                                className={`chat-session-popover-item-run chat-session-popover-item-run--${run.status}`}
                              >
                                {run.label}
                              </span>
                            )}
                            {isCurrent && (
                              <span className="chat-session-popover-item-tag">
                                {t('chat.sessionCurrent')}
                              </span>
                            )}
                          </button>
                        )
                      })}
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
