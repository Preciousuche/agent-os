import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { SessionChip } from './SessionChip'
import type { SessionListItem } from './logic'

vi.mock('sonner', () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn(), info: vi.fn() },
}))

const CURRENT = 'agent:main:webchat:default'

const SESSIONS: SessionListItem[] = [
  'agent:main:webchat:default',
  'agent:main:webchat:abc123',
  { key: 'agent:trader:cli:default', run_status: 'running' },
  'sess-legacy',
]

function renderChip(overrides: Partial<Parameters<typeof SessionChip>[0]> = {}) {
  const onSwitch = vi.fn()
  const onReset = vi.fn()
  const onCopy = vi.fn().mockResolvedValue(undefined)
  const fetchSessions = vi.fn().mockResolvedValue(SESSIONS)
  render(
    <SessionChip
      sessionKey={CURRENT}
      onSwitch={onSwitch}
      onReset={onReset}
      onCopy={onCopy}
      fetchSessions={fetchSessions}
      {...overrides}
    />,
  )
  return { onSwitch, onReset, onCopy, fetchSessions }
}

afterEach(() => {
  sessionStorage.clear()
  vi.clearAllMocks()
  vi.unstubAllGlobals()
})

describe('SessionChip', () => {
  it('renders the current session key on the chip (chat.js:1223)', () => {
    renderChip()
    const chip = screen.getByRole('button', { name: /switch chat session/i })
    expect(chip).toHaveTextContent(CURRENT)
  })

  it('opens the switcher popover on click and lists the fetched sessions (chat.js:2026/2071)', async () => {
    renderChip()
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    // The popover dialog appears; the fetched session keys are listed.
    expect(await screen.findByRole('dialog', { name: /switch session/i })).toBeInTheDocument()
    expect(await screen.findByText('agent:main:webchat:abc123')).toBeInTheDocument()
    expect(screen.getByText('agent:trader:cli:default')).toBeInTheDocument()
  })

  it('authenticates the default session-list request with the per-tab gateway token', async () => {
    sessionStorage.setItem('agentos.wsToken', 'session-token')
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ sessions: SESSIONS }),
    } as Response)
    vi.stubGlobal('fetch', fetchSpy)
    renderChip({ fetchSessions: undefined })

    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    expect(await screen.findByText('agent:main:webchat:abc123')).toBeInTheDocument()
    expect(fetchSpy).toHaveBeenCalledWith('/api/sessions', {
      headers: { Authorization: 'Bearer session-token' },
      credentials: 'same-origin',
    })
  })

  it('closes the switcher on Escape and restores focus to its trigger', async () => {
    renderChip()
    const trigger = screen.getByRole('button', { name: /switch chat session/i })
    fireEvent.click(trigger)
    expect(await screen.findByRole('dialog', { name: /switch session/i })).toBeInTheDocument()

    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('dialog', { name: /switch session/i })).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('groups sessions and tags a running one with its run status (chat.js:1862/1611)', async () => {
    renderChip()
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    // The webchat group label + the CLI group label both render.
    expect(await screen.findByText('Web chat')).toBeInTheDocument()
    expect(screen.getByText('CLI')).toBeInTheDocument()
    // The running CLI session shows a Running run-status tag (chat.js:1934).
    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('marks the current session and switching to it is a no-op (chat.js:1938/1946)', async () => {
    const { onSwitch } = renderChip()
    const trigger = screen.getByRole('button', { name: /switch chat session/i })
    fireEvent.click(trigger)
    // The current row carries the "current" tag.
    expect(await screen.findByText('current')).toBeInTheDocument()
    // Clicking the current session must NOT fire onSwitch (chat.js:1946 `k !== current`).
    fireEvent.click(screen.getByText(CURRENT, { selector: '.chat-session-popover-item-key' }))
    expect(onSwitch).not.toHaveBeenCalled()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('switching to a different session fires onSwitch with its key (chat.js:1946)', async () => {
    const { onSwitch } = renderChip()
    const trigger = screen.getByRole('button', { name: /switch chat session/i })
    fireEvent.click(trigger)
    fireEvent.click(await screen.findByText('agent:main:webchat:abc123'))
    expect(onSwitch).toHaveBeenCalledWith('agent:main:webchat:abc123')
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('filters the list by the search input (chat.js:1911/2072)', async () => {
    renderChip()
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    await screen.findByText('agent:main:webchat:abc123')
    const search = screen.getByRole('searchbox', { name: /search sessions/i })
    fireEvent.change(search, { target: { value: 'abc' } })
    await waitFor(() => {
      expect(screen.getByText('agent:main:webchat:abc123')).toBeInTheDocument()
      expect(screen.queryByText('agent:trader:cli:default')).not.toBeInTheDocument()
    })
  })

  it('copies the session key and toasts (chat.js:1782/1848)', async () => {
    const { onCopy } = renderChip()
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Copy session key' }))
    await waitFor(() => {
      expect(onCopy).toHaveBeenCalledWith(CURRENT)
      expect(toast.info).toHaveBeenCalledWith('Session key copied')
    })
  })

  it('resets the current session via onReset (chat.js:2723)', () => {
    const { onReset } = renderChip()
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Reset session' }))
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it('exports from the compact Chat actions menu', () => {
    const onExport = vi.fn()
    renderChip({ onExport })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Export chat as Markdown' }))
    expect(onExport).toHaveBeenCalledTimes(1)
  })

  it('moves the session into a project from the actions menu', () => {
    const onMoveToProject = vi.fn()
    renderChip({
      onMoveToProject,
      projectsById: new Map([
        ['p2', 'Zulu docs'],
        ['p1', 'Alpha research'],
      ]),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Move this session to a project' }))
    // The picker swaps in: "No project" first, then projects sorted by name.
    const items = screen.getAllByRole('menuitem').map((el) => el.textContent)
    expect(items).toEqual(['No project', 'Alpha research', 'Zulu docs'])
    fireEvent.click(screen.getByRole('menuitem', { name: 'Alpha research' }))
    expect(onMoveToProject).toHaveBeenCalledWith('p1')
    expect(screen.queryByRole('menu', { name: 'Chat actions' })).not.toBeInTheDocument()
  })

  it('detaches via "No project" and treats the current choice as a no-op', () => {
    const onMoveToProject = vi.fn()
    renderChip({
      onMoveToProject,
      projectId: 'p1',
      projectsById: new Map([['p1', 'Alpha research']]),
    })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Move this session to a project' }))
    // Selecting the project the session is already in changes nothing.
    fireEvent.click(screen.getByRole('menuitem', { name: 'Alpha research' }))
    expect(onMoveToProject).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Move this session to a project' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'No project' }))
    expect(onMoveToProject).toHaveBeenCalledWith(null)
  })

  it('hides the move action without projects, unless the session is in one', () => {
    renderChip({ onMoveToProject: vi.fn(), projectsById: new Map() })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    expect(
      screen.queryByRole('menuitem', { name: 'Move this session to a project' }),
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' })) // close

    // A session already in a (stale) project can still detach.
    renderChip({ onMoveToProject: vi.fn(), projectId: 'p9', projectsById: new Map() })
    fireEvent.click(screen.getAllByRole('button', { name: 'Chat actions' })[1]!)
    expect(
      screen.getByRole('menuitem', { name: 'Move this session to a project' }),
    ).toBeInTheDocument()
  })

  it('anchors the actions menu to the actions trigger wrapper', () => {
    renderChip({ onExport: vi.fn() })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    const menu = screen.getByRole('menu', { name: 'Chat actions' })
    expect(menu.parentElement).toHaveClass('chat-session-actions')
    expect(menu.parentElement).toContainElement(
      screen.getByRole('button', { name: 'Chat actions' }),
    )
  })

  it('keeps action-menu focus keyboard-friendly without fetching sessions', async () => {
    const { fetchSessions } = renderChip({ onExport: vi.fn() })
    const trigger = screen.getByRole('button', { name: 'Chat actions' })
    fireEvent.click(trigger)

    const copy = screen.getByRole('menuitem', { name: 'Copy session key' })
    const reset = screen.getByRole('menuitem', { name: 'Reset session' })
    await waitFor(() => expect(copy).toHaveFocus())
    expect(screen.getAllByRole('menuitem').every((item) => item.tabIndex === -1)).toBe(true)
    expect(fetchSessions).not.toHaveBeenCalled()

    fireEvent.keyDown(copy, { key: 'ArrowDown' })
    expect(reset).toHaveFocus()
    fireEvent.keyDown(reset, { key: 'End' })
    expect(screen.getByRole('menuitem', { name: 'Export chat as Markdown' })).toHaveFocus()

    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('menu', { name: 'Chat actions' })).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())

    fireEvent.click(trigger)
    const reopenedCopy = screen.getByRole('menuitem', { name: 'Copy session key' })
    await waitFor(() => expect(reopenedCopy).toHaveFocus())
    fireEvent.keyDown(reopenedCopy, { key: 'Tab' })
    expect(screen.queryByRole('menu', { name: 'Chat actions' })).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('degrades to manual key entry when the session list fetch fails (chat.js:2038-2069)', async () => {
    const { onSwitch } = renderChip({
      fetchSessions: vi.fn().mockRejectedValue(new Error('offline')),
    })
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    // The manual-entry note + a key field pre-filled to the current key.
    expect(await screen.findByText(/Session list unavailable/i)).toBeInTheDocument()
    const field = screen.getByRole('searchbox', { name: /session key/i }) as HTMLInputElement
    expect(field.value).toBe(CURRENT)
    fireEvent.change(field, { target: { value: 'agent:main:webchat:typed' } })
    fireEvent.keyDown(field, { key: 'Enter' })
    expect(onSwitch).toHaveBeenCalledWith('agent:main:webchat:typed')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /switch chat session/i })).toHaveFocus(),
    )
  })

  it('keeps a short visible run-status label for narrow headers', () => {
    renderChip({
      runState: { status: 'approval_pending', label: 'Waiting for approval', task: null },
    })
    expect(document.querySelector('.chat-session-run-status__full')).toHaveTextContent(
      'Waiting for approval',
    )
    expect(document.querySelector('.chat-session-run-status__compact')).toHaveTextContent('Wait')
  })

  it('shows an empty-state when no sessions come back (chat.js:1955)', async () => {
    renderChip({ fetchSessions: vi.fn().mockResolvedValue([]) })
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    expect(await screen.findByText('No sessions found.')).toBeInTheDocument()
  })
})

// ── Session naming (issue #248 follow-up) ────────────────────────────────────

const NAMED_SESSIONS: SessionListItem[] = [
  { key: CURRENT, display_name: 'Speeding ticket report' },
  { key: 'agent:main:webchat:abc123', display_name: 'Tax filing notes' },
  { key: 'agent:trader:cli:default', derived_title: 'trader-fallback' },
]

describe('SessionChip naming', () => {
  it('labels the chip with the session name and keeps the key in the tooltip', () => {
    renderChip({ sessionName: 'Speeding ticket report' })
    const chip = screen.getByRole('button', { name: /switch chat session/i })
    expect(chip).toHaveTextContent('Speeding ticket report')
    expect(chip.querySelector('.chat-session-chip-key')).toHaveAttribute('title', CURRENT)
  })

  it('falls back to the key when the session has no name', () => {
    renderChip()
    expect(screen.getByRole('button', { name: /switch chat session/i })).toHaveTextContent(CURRENT)
  })

  it('lists a renamed session by name with its key underneath', async () => {
    renderChip({ fetchSessions: vi.fn().mockResolvedValue(NAMED_SESSIONS) })
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    expect(await screen.findByText('Tax filing notes')).toBeInTheDocument()
    expect(screen.getByText('agent:main:webchat:abc123')).toBeInTheDocument()
  })

  it('never renders the derived title as a name', async () => {
    renderChip({ fetchSessions: vi.fn().mockResolvedValue(NAMED_SESSIONS) })
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    await screen.findByText('Tax filing notes')
    expect(screen.queryByText('trader-fallback')).not.toBeInTheDocument()
  })

  it('searches by session name as well as by key', async () => {
    renderChip({ fetchSessions: vi.fn().mockResolvedValue(NAMED_SESSIONS) })
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    await screen.findByText('Tax filing notes')
    const search = screen.getByRole('searchbox', { name: /search sessions/i })

    fireEvent.change(search, { target: { value: 'tax filing' } })
    await waitFor(() => {
      expect(screen.getByText('agent:main:webchat:abc123')).toBeInTheDocument()
      expect(screen.queryByText('agent:trader:cli:default')).not.toBeInTheDocument()
    })

    // The key still matches — renaming must not cost the old search path.
    fireEvent.change(search, { target: { value: 'trader' } })
    await waitFor(() => {
      expect(screen.getByText('agent:trader:cli:default')).toBeInTheDocument()
      expect(screen.queryByText('Tax filing notes')).not.toBeInTheDocument()
    })
  })

  it('matches the derived title so an unrenamed session stays findable', async () => {
    renderChip({ fetchSessions: vi.fn().mockResolvedValue(NAMED_SESSIONS) })
    fireEvent.click(screen.getByRole('button', { name: /switch chat session/i }))
    await screen.findByText('Tax filing notes')
    fireEvent.change(screen.getByRole('searchbox', { name: /search sessions/i }), {
      target: { value: 'fallback' },
    })
    await waitFor(() => expect(screen.getByText('agent:trader:cli:default')).toBeInTheDocument())
  })

  it('hides the rename action when no rename handler is wired', () => {
    renderChip()
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    expect(screen.queryByRole('menuitem', { name: 'Rename session' })).not.toBeInTheDocument()
  })

  it('renames the session from the actions menu, prefilled with the current name', async () => {
    const onRename = vi.fn()
    renderChip({ onRename, sessionName: 'Old name' })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Rename session' }))

    const input = screen.getByRole('textbox', { name: 'Session name' }) as HTMLInputElement
    expect(input.value).toBe('Old name')
    expect(input.maxLength).toBe(120)

    fireEvent.change(input, { target: { value: '  New name  ' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)

    expect(onRename).toHaveBeenCalledWith('New name')
    // The menu closes and focus returns to its trigger.
    expect(screen.queryByRole('menu', { name: 'Chat actions' })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Chat actions' })).toHaveFocus())
  })

  it('clears the name when the field is emptied', () => {
    const onRename = vi.fn()
    renderChip({ onRename, sessionName: 'Old name' })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Rename session' }))
    const input = screen.getByRole('textbox', { name: 'Session name' })
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.submit(input.closest('form') as HTMLFormElement)
    expect(onRename).toHaveBeenCalledWith('')
  })

  it('skips the round-trip when the name is unchanged', () => {
    const onRename = vi.fn()
    renderChip({ onRename, sessionName: 'Same name' })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Rename session' }))
    const input = screen.getByRole('textbox', { name: 'Session name' })
    fireEvent.submit(input.closest('form') as HTMLFormElement)
    expect(onRename).not.toHaveBeenCalled()
  })

  it('cancels the edit on Escape without closing the actions menu', () => {
    const onRename = vi.fn()
    renderChip({ onRename, sessionName: 'Old name' })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Rename session' }))
    const input = screen.getByRole('textbox', { name: 'Session name' })
    fireEvent.change(input, { target: { value: 'Discarded' } })
    fireEvent.keyDown(input, { key: 'Escape' })

    expect(onRename).not.toHaveBeenCalled()
    expect(screen.getByRole('menu', { name: 'Chat actions' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Rename session' })).toBeInTheDocument()
  })

  it('leaves arrow keys to the caret while the rename field is open', () => {
    const onRename = vi.fn()
    renderChip({ onRename, onExport: vi.fn() })
    fireEvent.click(screen.getByRole('button', { name: 'Chat actions' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Rename session' }))
    const input = screen.getByRole('textbox', { name: 'Session name' })
    input.focus()
    fireEvent.keyDown(input, { key: 'ArrowDown' })
    expect(input).toHaveFocus()
  })
})
