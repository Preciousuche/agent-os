import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
  useId,
  useMemo,
} from 'react'
import { AnimatePresence } from 'motion/react'
import { X } from 'lucide-react'
import { ModalShell } from '@/components/ModalShell'
import './KeyboardShortcuts.css'

export interface KeyboardShortcut {
  key: string // e.g. "mod+shift+o"
  description: string
  category: string // e.g. "Global", "Composer"
  allowInInputs?: boolean
  allowWithOverlays?: boolean
  documentationOnly?: boolean
}

interface ShortcutRegistryItem {
  id: string
  config: KeyboardShortcut
  handler: (e: KeyboardEvent) => void
}

interface KeyboardShortcutContextType {
  register: (
    id: string,
    config: KeyboardShortcut,
    handler: (e: KeyboardEvent) => void,
  ) => () => void
  shortcuts: ShortcutRegistryItem[]
  isHelpOpen: boolean
  setIsHelpOpen: (open: boolean) => void
}

const KeyboardShortcutContext = createContext<KeyboardShortcutContextType | null>(null)

export function isMac(): boolean {
  if (typeof navigator === 'undefined') return false
  return /mac/i.test(navigator.userAgent)
}

export function formatShortcutKey(keyCombo: string): string {
  const parts = keyCombo.toLowerCase().split('+')
  const mac = isMac()

  return parts
    .map((part) => {
      if (part === 'mod') {
        return mac ? '⌘' : 'Ctrl'
      }
      if (part === 'shift') {
        return mac ? '⇧' : 'Shift'
      }
      if (part === 'alt') {
        return mac ? '⌥' : 'Alt'
      }
      if (part === 'arrowup' || part === 'up') {
        return '↑'
      }
      if (part === 'arrowdown' || part === 'down') {
        return '↓'
      }
      if (part === 'enter') {
        return 'Enter'
      }
      if (part === 'escape' || part === 'esc') {
        return 'Esc'
      }
      if (part.length === 1) {
        return part.toUpperCase()
      }
      return part.charAt(0).toUpperCase() + part.slice(1)
    })
    .join(mac ? '' : '+')
}

export function getEventCombo(e: KeyboardEvent | React.KeyboardEvent): string {
  const parts: string[] = []

  let key = (e.key || '').toLowerCase()
  if (!key || key === 'unidentified') {
    if (e.code) {
      if (e.code.startsWith('Key') && e.code.length === 4) {
        key = e.code.charAt(3).toLowerCase()
      } else if (e.code.startsWith('Digit') && e.code.length === 6) {
        key = e.code.charAt(5)
      } else {
        key = e.code.toLowerCase()
      }
    }
  }

  if (e.metaKey || e.ctrlKey) {
    parts.push('mod')
  }
  if (e.altKey) {
    parts.push('alt')
  }

  // Only add 'shift' modifier if key itself isn't a symbol produced by shift (like '?')
  // and key itself isn't 'shift'.
  if (e.shiftKey && key !== '?' && key !== 'shift') {
    parts.push('shift')
  }

  if (key !== 'control' && key !== 'meta' && key !== 'alt' && key !== 'shift') {
    parts.push(key)
  }

  return parts.join('+')
}

export function KeyboardShortcutProvider({ children }: { children: React.ReactNode }) {
  const [shortcuts, setShortcuts] = useState<ShortcutRegistryItem[]>([])
  const [isHelpOpen, setIsHelpOpen] = useState(false)

  const shortcutsRef = useRef<ShortcutRegistryItem[]>([])

  useEffect(() => {
    shortcutsRef.current = shortcuts
  }, [shortcuts])

  const register = useCallback(
    (id: string, config: KeyboardShortcut, handler: (e: KeyboardEvent) => void) => {
      setShortcuts((prev) => [...prev, { id, config, handler }])
      return () => {
        setShortcuts((prev) => prev.filter((item) => item.id !== id))
      }
    },
    [],
  )

  // Handle global shortcuts dispatching
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return

      const combo = getEventCombo(e)
      if (!combo) return

      const hasOverlay = !!document.querySelector(
        '.modal-backdrop, .chat-session-popover, .chat-session-actions-menu, .help-modal__overlay, .ag-modal__overlay, .sess-modal__overlay, .sk-modal__overlay, .cron-modal__overlay',
      )

      const target = e.target as HTMLElement | null
      const isEditable =
        !!target &&
        (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)

      // Handle the helper shortcut "?" statically
      if (combo === '?' && !isEditable && !hasOverlay) {
        e.preventDefault()
        setIsHelpOpen((prev) => !prev)
        return
      }

      const matches = shortcutsRef.current.filter((item) => {
        return (
          !item.config.documentationOnly && item.config.key.toLowerCase() === combo.toLowerCase()
        )
      })

      if (matches.length === 0) return

      // Evaluate matches in reverse order of registration (latest first - stack behavior)
      for (let i = matches.length - 1; i >= 0; i--) {
        const match = matches[i]!

        if (hasOverlay && !match.config.allowWithOverlays) {
          continue
        }

        if (isEditable && !match.config.allowInInputs) {
          continue
        }

        match.handler(e)

        if (e.defaultPrevented) {
          break
        }
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])

  const contextValue = useMemo(
    () => ({
      register,
      shortcuts,
      isHelpOpen,
      setIsHelpOpen,
    }),
    [register, shortcuts, isHelpOpen],
  )

  return (
    <KeyboardShortcutContext.Provider value={contextValue}>
      {children}
      <AnimatePresence>
        {isHelpOpen && (
          <KeyboardShortcutHelpModal onClose={() => setIsHelpOpen(false)} shortcuts={shortcuts} />
        )}
      </AnimatePresence>
    </KeyboardShortcutContext.Provider>
  )
}

export function useKeyboardShortcut(config: KeyboardShortcut, handler: (e: KeyboardEvent) => void) {
  const context = useContext(KeyboardShortcutContext)

  const id = useId()
  const handlerRef = useRef(handler)

  useEffect(() => {
    handlerRef.current = handler
  }, [handler])

  const { key, description, category, allowInInputs, allowWithOverlays, documentationOnly } = config
  const register = context?.register

  useEffect(() => {
    if (!register) return

    const stableHandler = (e: KeyboardEvent) => {
      handlerRef.current(e)
    }

    return register(
      id,
      { key, description, category, allowInInputs, allowWithOverlays, documentationOnly },
      stableHandler,
    )
  }, [
    register,
    id,
    key,
    description,
    category,
    allowInInputs,
    allowWithOverlays,
    documentationOnly,
  ])
}

function KeyboardShortcutHelpModal({
  onClose,
  shortcuts,
}: {
  onClose: () => void
  shortcuts: ShortcutRegistryItem[]
}) {
  const categories: Record<string, ShortcutRegistryItem[]> = {}

  // Initialize with helper shortcut
  categories['Global'] = [
    {
      id: 'global-help-shortcut',
      config: {
        key: '?',
        description: 'Show keyboard shortcuts',
        category: 'Global',
      },
      handler: () => {},
    },
  ]

  shortcuts.forEach((item) => {
    const cat = item.config.category || 'Other'
    if (!categories[cat]) {
      categories[cat] = []
    }
    const exists = categories[cat].some(
      (existing) =>
        existing.config.key.toLowerCase() === item.config.key.toLowerCase() &&
        existing.config.description === item.config.description,
    )
    if (!exists) {
      categories[cat].push(item)
    }
  })

  const renderKbdParts = (keyCombo: string) => {
    const parts = keyCombo.toLowerCase().split('+')
    const mac = isMac()

    return parts.map((part, idx) => {
      let label = part
      if (part === 'mod') {
        label = mac ? '⌘' : 'Ctrl'
      } else if (part === 'shift') {
        label = mac ? '⇧' : 'Shift'
      } else if (part === 'alt') {
        label = mac ? '⌥' : 'Alt'
      } else if (part === 'arrowup' || part === 'up') {
        label = '↑'
      } else if (part === 'arrowdown' || part === 'down') {
        label = '↓'
      } else if (part === 'enter') {
        label = 'Enter'
      } else if (part === 'escape' || part === 'esc') {
        label = 'Esc'
      } else if (part.length === 1) {
        label = part.toUpperCase()
      } else {
        label = part.charAt(0).toUpperCase() + part.slice(1)
      }

      return (
        <React.Fragment key={idx}>
          {idx > 0 && !mac && <span className="help-modal__plus">+</span>}
          <kbd className="help-modal__kbd">{label}</kbd>
        </React.Fragment>
      )
    })
  }

  return (
    <ModalShell
      role="dialog"
      labelledBy="help-modal-title"
      onClose={onClose}
      overlayClassName="help-modal__overlay"
      className="help-modal"
    >
      <div className="help-modal__head">
        <h2 id="help-modal-title" className="help-modal__title">
          Keyboard Shortcuts
        </h2>
        <button
          type="button"
          className="help-modal__close"
          onClick={onClose}
          aria-label="Close dialog"
        >
          <X size={18} />
        </button>
      </div>
      <div className="help-modal__body">
        {Object.entries(categories).map(([category, items]) => (
          <div key={category} className="help-modal__section">
            <h3 className="help-modal__section-title">{category}</h3>
            {items.map((item) => (
              <div key={item.id} className="help-modal__shortcut-row">
                <span className="help-modal__shortcut-desc">{item.config.description}</span>
                <div className="help-modal__kbd-list">{renderKbdParts(item.config.key)}</div>
              </div>
            ))}
          </div>
        ))}
      </div>
    </ModalShell>
  )
}
