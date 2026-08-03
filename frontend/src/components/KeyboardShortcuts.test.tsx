import { render, screen, fireEvent } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import {
  formatShortcutKey,
  getEventCombo,
  KeyboardShortcutProvider,
  useKeyboardShortcut,
} from './KeyboardShortcuts'

describe('KeyboardShortcuts Utilities', () => {
  it('formats shortcut keys platform-awarely', () => {
    // Mock userAgent for non-mac
    const originalUserAgent = navigator.userAgent
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Windows NT 10.0',
      configurable: true,
    })

    expect(formatShortcutKey('mod+shift+o')).toBe('Ctrl+Shift+O')
    expect(formatShortcutKey('alt+arrowup')).toBe('Alt+↑')
    expect(formatShortcutKey('escape')).toBe('Esc')

    // Mock userAgent for mac
    Object.defineProperty(navigator, 'userAgent', {
      value: 'Macintosh; Intel Mac OS X 10_15_7',
      configurable: true,
    })

    expect(formatShortcutKey('mod+shift+o')).toBe('⌘⇧O')
    expect(formatShortcutKey('alt+arrowup')).toBe('⌥↑')
    expect(formatShortcutKey('escape')).toBe('Esc')

    // Restore
    Object.defineProperty(navigator, 'userAgent', {
      value: originalUserAgent,
      configurable: true,
    })
  })

  it('determines the correct event combo key', () => {
    const e1 = {
      key: 'o',
      code: 'KeyO',
      ctrlKey: true,
      shiftKey: true,
      metaKey: false,
      altKey: false,
    } as KeyboardEvent
    expect(getEventCombo(e1)).toBe('mod+shift+o')

    const e2 = {
      key: 'ArrowUp',
      ctrlKey: false,
      shiftKey: false,
      metaKey: false,
      altKey: true,
    } as KeyboardEvent
    expect(getEventCombo(e2)).toBe('alt+arrowup')

    const e3 = {
      key: '?',
      ctrlKey: false,
      shiftKey: true,
      metaKey: false,
      altKey: false,
    } as KeyboardEvent
    expect(getEventCombo(e3)).toBe('?')
  })
})

function TestComponent() {
  const [pressed, setPressed] = useState(false)

  useKeyboardShortcut(
    {
      key: 'mod+k',
      description: 'Test shortcut description',
      category: 'Test Category',
    },
    (e) => {
      e.preventDefault()
      setPressed(true)
    },
  )

  return <div>{pressed ? 'Pressed' : 'Not Pressed'}</div>
}

describe('KeyboardShortcutProvider', () => {
  it('registers and triggers a global shortcut', () => {
    render(
      <KeyboardShortcutProvider>
        <TestComponent />
      </KeyboardShortcutProvider>,
    )

    expect(screen.getByText('Not Pressed')).toBeInTheDocument()

    // Trigger Mod+K (Ctrl+K or Cmd+K)
    const event = new KeyboardEvent('keydown', {
      key: 'k',
      ctrlKey: true,
      bubbles: true,
    })
    document.dispatchEvent(event)

    expect(screen.getByText('Pressed')).toBeInTheDocument()
  })

  it('toggles the help modal on "?" keydown', () => {
    render(
      <KeyboardShortcutProvider>
        <TestComponent />
      </KeyboardShortcutProvider>,
    )

    // Initially modal is not open
    expect(screen.queryByText('Keyboard Shortcuts')).not.toBeInTheDocument()

    // Dispatch "?" keydown
    const event = new KeyboardEvent('keydown', {
      key: '?',
      bubbles: true,
    })
    document.dispatchEvent(event)

    // Modal should be open and display the title and test description
    expect(screen.getByText('Keyboard Shortcuts')).toBeInTheDocument()
    expect(screen.getByText('Test shortcut description')).toBeInTheDocument()
    expect(screen.getByText('Test Category')).toBeInTheDocument()

    // Close the modal
    const closeBtn = screen.getByRole('button', { name: 'Close dialog' })
    fireEvent.click(closeBtn)

    // Modal should be closed
    expect(screen.queryByText('Keyboard Shortcuts')).not.toBeInTheDocument()
  })
})
