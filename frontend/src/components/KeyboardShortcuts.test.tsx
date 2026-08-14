import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ModalShell } from './ModalShell'
import {
  comboParts,
  eventCombos,
  formatCombo,
  KeyboardShortcutProvider,
  useKeyboardShortcut,
  useShortcutDocs,
  useShortcutOverlay,
} from './KeyboardShortcuts'

function setPlatform(value: string) {
  Object.defineProperty(navigator, 'userAgent', { value, configurable: true })
  Object.defineProperty(navigator, 'platform', { value, configurable: true })
}

const ORIGINAL_UA = navigator.userAgent
const ORIGINAL_PLATFORM = navigator.platform

afterEach(() => {
  setPlatform(ORIGINAL_PLATFORM || ORIGINAL_UA)
  vi.useRealTimers()
})

function press(target: Element | Document, init: KeyboardEventInit) {
  return fireEvent.keyDown(target, { bubbles: true, ...init })
}

describe('combo labels', () => {
  it('renders the platform the viewer is actually on', () => {
    setPlatform('Windows NT 10.0')
    expect(formatCombo('mod+shift+o')).toBe('Ctrl+Shift+O')
    expect(formatCombo('alt+arrowup')).toBe('Alt+↑')
    expect(formatCombo('escape')).toBe('Esc')

    setPlatform('MacIntel')
    expect(formatCombo('mod+shift+o')).toBe('⌘⇧O')
    expect(formatCombo('alt+arrowup')).toBe('⌥↑')
    expect(formatCombo('escape')).toBe('Esc')
  })

  it('exposes the same labels as caps, so the overlay and call sites cannot drift', () => {
    setPlatform('MacIntel')
    expect(comboParts('mod+shift+o')).toEqual(['⌘', '⇧', 'O'])
    expect(formatCombo('mod+shift+o')).toBe(comboParts('mod+shift+o').join(''))
  })
})

describe('event → combo', () => {
  it('treats shift as a modifier for letters but as part of a symbol', () => {
    expect(
      eventCombos({ key: 'O', code: 'KeyO', ctrlKey: true, shiftKey: true } as never),
    ).toContain('mod+shift+o')
    // '?' is Shift+/ — nobody calls it "shift question mark".
    expect(eventCombos({ key: '?', code: 'Slash', shiftKey: true } as never)).toContain('?')
  })

  it('offers the physical key as well, so layouts that remap it still match', () => {
    // Physical KeyO on a layout where it does not produce "o". The pre-registry
    // handler matched on e.code for exactly this reason.
    const combos = eventCombos({
      key: 'R',
      code: 'KeyO',
      ctrlKey: true,
      shiftKey: true,
    } as never)
    expect(combos).toContain('mod+shift+o')
    expect(combos).toContain('mod+shift+r')
  })

  it('ignores a bare modifier press', () => {
    expect(eventCombos({ key: 'Shift', code: 'ShiftLeft', shiftKey: true } as never)).toEqual([])
  })
})

function Harness({ onFire = () => {} }: { onFire?: (name: string) => void }) {
  useKeyboardShortcut(
    {
      combo: 'mod+shift+o',
      description: 'Start a new chat',
      category: 'Chat',
      allowInInputs: true,
    },
    (e) => {
      e.preventDefault()
      onFire('new-chat')
    },
  )
  useKeyboardShortcut(
    { combo: 'escape', description: 'Abort the streaming turn', category: 'Chat' },
    (e) => {
      e.preventDefault()
      onFire('escape')
    },
  )
  useShortcutDocs('Composer', [{ combo: 'enter', description: 'Send the message' }])
  return <textarea data-testid="composer" />
}

describe('dispatch guards', () => {
  it('fires a document shortcut and respects allowInInputs', () => {
    const fired: string[] = []
    render(
      <KeyboardShortcutProvider>
        <Harness onFire={(n) => fired.push(n)} />
      </KeyboardShortcutProvider>,
    )
    const composer = screen.getByTestId('composer')

    press(document, { key: 'O', code: 'KeyO', ctrlKey: true, shiftKey: true })
    expect(fired).toEqual(['new-chat'])

    // New chat opts into editable targets; Escape does not, because the
    // composer runs its own Escape chain.
    press(composer, { key: 'O', code: 'KeyO', ctrlKey: true, shiftKey: true })
    press(composer, { key: 'Escape', code: 'Escape' })
    expect(fired).toEqual(['new-chat', 'new-chat'])

    press(document, { key: 'Escape', code: 'Escape' })
    expect(fired).toEqual(['new-chat', 'new-chat', 'escape'])
  })

  it('never dispatches a documentation-only entry', () => {
    const fired: string[] = []
    render(
      <KeyboardShortcutProvider>
        <Harness onFire={(n) => fired.push(n)} />
      </KeyboardShortcutProvider>,
    )
    press(document, { key: 'Enter', code: 'Enter' })
    expect(fired).toEqual([])
  })

  it('stands down while an overlay layer is mounted', async () => {
    const fired: string[] = []
    function WithDialog() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <Harness onFire={(n) => fired.push(n)} />
          <button type="button" onClick={() => setOpen(true)}>
            open dialog
          </button>
          {open ? (
            <ModalShell
              role="dialog"
              labelledBy="t"
              onClose={() => setOpen(false)}
              overlayClassName="x"
            >
              <h2 id="t">A dialog</h2>
            </ModalShell>
          ) : null}
        </>
      )
    }
    render(
      <KeyboardShortcutProvider>
        <WithDialog />
      </KeyboardShortcutProvider>,
    )

    fireEvent.click(screen.getByRole('button', { name: 'open dialog' }))
    await screen.findByText('A dialog')

    press(document, { key: 'O', code: 'KeyO', ctrlKey: true, shiftKey: true })
    expect(fired).toEqual([])
  })
})

describe('the ? overlay', () => {
  function renderOverlayHarness() {
    function Chrome() {
      const overlay = useShortcutOverlay()
      return (
        <>
          <Harness />
          <button type="button" onClick={overlay.open}>
            Keyboard shortcuts
          </button>
        </>
      )
    }
    return render(
      <KeyboardShortcutProvider>
        <Chrome />
      </KeyboardShortcutProvider>,
    )
  }

  it('toggles in both directions from "?"', async () => {
    renderOverlayHarness()
    press(document, { key: '?', code: 'Slash', shiftKey: true })
    await screen.findByText('Keyboard shortcuts', { selector: 'h2' })

    // The overlay is itself a layer, so closing has to be handled before the
    // open-guard — this is the case that silently regressed once already.
    press(document, { key: '?', code: 'Slash', shiftKey: true })
    await waitFor(() =>
      expect(screen.queryByText('Keyboard shortcuts', { selector: 'h2' })).toBeNull(),
    )
  })

  it('opens from the UI even when focus is in the composer', async () => {
    renderOverlayHarness()
    const composer = screen.getByTestId('composer')
    composer.focus()

    // '?' is deliberately inert here — the composer autofocuses on desktop, so
    // this is the state a first-time operator is actually in.
    press(composer, { key: '?', code: 'Slash', shiftKey: true })
    expect(screen.queryByText('Keyboard shortcuts', { selector: 'h2' })).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: 'Keyboard shortcuts' }))
    expect(await screen.findByText('Keyboard shortcuts', { selector: 'h2' })).toBeInTheDocument()
  })

  it('does not open on top of a dialog that is already up', async () => {
    function WithDialog() {
      const [open, setOpen] = useState(true)
      return (
        <ModalShell
          role="dialog"
          labelledBy="t"
          onClose={() => setOpen(!open)}
          overlayClassName="x"
        >
          <h2 id="t">A dialog</h2>
        </ModalShell>
      )
    }
    render(
      <KeyboardShortcutProvider>
        <WithDialog />
      </KeyboardShortcutProvider>,
    )
    await screen.findByText('A dialog')
    press(document, { key: '?', code: 'Slash', shiftKey: true })
    expect(screen.queryByText('Keyboard shortcuts', { selector: 'h2' })).toBeNull()
  })

  it('lists every registered key, grouped, with platform-aware caps', async () => {
    setPlatform('Windows NT 10.0')
    renderOverlayHarness()
    press(document, { key: '?', code: 'Slash', shiftKey: true })
    await screen.findByText('Keyboard shortcuts', { selector: 'h2' })

    const rows = Array.from(document.querySelectorAll('.shortcut-sheet__row')).map(
      (row) => row.textContent,
    )
    expect(rows).toEqual([
      'Show this list?',
      'Start a new chatCtrl+Shift+O',
      'Abort the streaming turnEsc',
      'Send the messageEnter',
    ])
    const groups = Array.from(document.querySelectorAll('.shortcut-sheet__group-title')).map(
      (el) => el.textContent,
    )
    expect(groups).toEqual(['Global', 'Chat', 'Composer'])
  })

  it('drops a shortcut from the list when its owner unmounts', async () => {
    function Toggling() {
      const [mounted, setMounted] = useState(true)
      return (
        <>
          {mounted ? <Harness /> : null}
          <button type="button" onClick={() => setMounted(false)}>
            unmount
          </button>
        </>
      )
    }
    render(
      <KeyboardShortcutProvider>
        <Toggling />
      </KeyboardShortcutProvider>,
    )
    fireEvent.click(screen.getByRole('button', { name: 'unmount' }))
    press(document, { key: '?', code: 'Slash', shiftKey: true })
    await screen.findByText('Keyboard shortcuts', { selector: 'h2' })

    expect(screen.queryByText('Start a new chat')).toBeNull()
    expect(screen.getByText('Show this list')).toBeInTheDocument()
  })
})

describe('chords and prefix state', () => {
  it('supports two-step chords', async () => {
    const fired: string[] = []
    function ChordHarness() {
      useKeyboardShortcut(
        {
          combo: 'g c',
          description: 'Go to Chat',
          category: 'Navigation',
        },
        (e) => {
          e.preventDefault()
          fired.push('chat')
        },
      )
      return <div />
    }

    render(
      <KeyboardShortcutProvider>
        <ChordHarness />
      </KeyboardShortcutProvider>,
    )

    press(document, { key: 'g', code: 'KeyG' })
    expect(fired).toEqual([])

    press(document, { key: 'c', code: 'KeyC' })
    expect(fired).toEqual(['chat'])
  })

  it('times out after 1.5 seconds', async () => {
    vi.useFakeTimers()
    const fired: string[] = []
    function ChordHarness() {
      useKeyboardShortcut(
        {
          combo: 'g c',
          description: 'Go to Chat',
          category: 'Navigation',
        },
        (e) => {
          e.preventDefault()
          fired.push('chat')
        },
      )
      return <div />
    }

    render(
      <KeyboardShortcutProvider>
        <ChordHarness />
      </KeyboardShortcutProvider>,
    )

    press(document, { key: 'g', code: 'KeyG' })

    act(() => {
      vi.advanceTimersByTime(1500)
    })

    press(document, { key: 'c', code: 'KeyC' })
    expect(fired).toEqual([])

    vi.useRealTimers()
  })

  it('re-arms on repeated prefix key', async () => {
    vi.useFakeTimers()
    const fired: string[] = []
    function ChordHarness() {
      useKeyboardShortcut(
        {
          combo: 'g c',
          description: 'Go to Chat',
          category: 'Navigation',
        },
        (e) => {
          e.preventDefault()
          fired.push('chat')
        },
      )
      return <div />
    }

    render(
      <KeyboardShortcutProvider>
        <ChordHarness />
      </KeyboardShortcutProvider>,
    )

    press(document, { key: 'g', code: 'KeyG' })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    press(document, { key: 'g', code: 'KeyG' })

    act(() => {
      vi.advanceTimersByTime(1000)
    })

    press(document, { key: 'c', code: 'KeyC' })
    expect(fired).toEqual(['chat'])

    vi.useRealTimers()
  })

  it('is cancelled by Escape', async () => {
    const fired: string[] = []
    function ChordHarness() {
      useKeyboardShortcut(
        {
          combo: 'g c',
          description: 'Go to Chat',
          category: 'Navigation',
        },
        (e) => {
          e.preventDefault()
          fired.push('chat')
        },
      )
      return <div />
    }

    render(
      <KeyboardShortcutProvider>
        <ChordHarness />
      </KeyboardShortcutProvider>,
    )

    press(document, { key: 'g', code: 'KeyG' })
    press(document, { key: 'Escape', code: 'Escape' })
    press(document, { key: 'c', code: 'KeyC' })
    expect(fired).toEqual([])
  })

  it('is cancelled by any modifier key being held', async () => {
    const fired: string[] = []
    function ChordHarness() {
      useKeyboardShortcut(
        {
          combo: 'g c',
          description: 'Go to Chat',
          category: 'Navigation',
        },
        (e) => {
          e.preventDefault()
          fired.push('chat')
        },
      )
      return <div />
    }

    render(
      <KeyboardShortcutProvider>
        <ChordHarness />
      </KeyboardShortcutProvider>,
    )

    press(document, { key: 'g', code: 'KeyG' })
    press(document, { key: 'c', code: 'KeyC', ctrlKey: true })
    expect(fired).toEqual([])
  })
})

describe('outside a provider', () => {
  it('renders without a registry rather than throwing', () => {
    // Views are rendered bare in their own unit tests; a missing cheat-sheet
    // must not take them down.
    expect(() => render(<Harness />)).not.toThrow()
  })
})
