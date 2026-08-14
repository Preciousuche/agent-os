// Combos and their labels — the pure half of the shortcut registry (#137).
//
// Kept apart from the provider and the overlay so that the eagerly-loaded
// shell can format a keycap (the New chat tooltip) without pulling in the
// overlay's ModalShell / motion dependencies.

export interface ShortcutSpec {
  /**
   * Canonical combo: lowercase, '+'-joined, modifiers first in the order
   * mod → alt → shift. `mod` is Cmd on macOS and Ctrl elsewhere.
   * e.g. 'mod+shift+o', 'alt+arrowup', 'escape', '?'.
   */
  combo: string
  description: string
  category: string
  /** Fire even when focus is in an input / textarea / contenteditable. */
  allowInInputs?: boolean
  /** Fire even while a modal or popover layer is open. */
  allowWithOverlays?: boolean
  /**
   * Documented here, handled elsewhere. The composer, slash menu and session
   * switcher bind their keys to their own element (they need the event before
   * it reaches the document, and they need to consume it). Registering the spec
   * keeps the overlay complete without relocating the behaviour.
   */
  documentationOnly?: boolean
}

export interface RegisteredShortcut {
  id: string
  spec: ShortcutSpec
  handler: (e: KeyboardEvent) => void
}

/** The combo that opens the overlay. Shift+/ on a US layout. */
export const HELP_COMBO = '?'

export const HELP_SHORTCUT: RegisteredShortcut = {
  id: 'help-overlay',
  spec: {
    combo: HELP_COMBO,
    description: 'Show this list',
    category: 'Global',
    documentationOnly: true,
  },
  handler: () => {},
}

/** Categories render in this order; anything else falls in after it. */
export const CATEGORY_ORDER = [
  'Global',
  'Navigation',
  'Chat',
  'Composer',
  'Slash commands',
  'Session switcher',
  'Dialogs',
]

export function isMac(): boolean {
  if (typeof navigator === 'undefined') return false
  const platform =
    (navigator as { userAgentData?: { platform?: string } }).userAgentData?.platform ||
    navigator.platform ||
    navigator.userAgent
  return /mac/i.test(platform)
}

const KEY_LABELS: Record<string, string> = {
  enter: 'Enter',
  escape: 'Esc',
  esc: 'Esc',
  tab: 'Tab',
  space: 'Space',
  arrowup: '↑',
  arrowdown: '↓',
  arrowleft: '←',
  arrowright: '→',
  up: '↑',
  down: '↓',
  home: 'Home',
  end: 'End',
}

/**
 * A combo as the caps that should be drawn for it, on this platform. The single
 * source of truth for shortcut labels — `formatCombo` joins these and the
 * overlay renders one `<kbd>` per entry, so the two cannot drift. #131
 * hardcoded '⌘⇧O' at the call site, which was wrong on Windows and Linux.
 */
export function comboParts(combo: string): string[] {
  const mac = isMac()
  return combo
    .toLowerCase()
    .split('+')
    .map((part) => {
      if (part === 'mod') return mac ? '⌘' : 'Ctrl'
      if (part === 'shift') return mac ? '⇧' : 'Shift'
      if (part === 'alt') return mac ? '⌥' : 'Alt'
      const known = KEY_LABELS[part]
      if (known) return known
      if (part.length === 1) return part.toUpperCase()
      return part.charAt(0).toUpperCase() + part.slice(1)
    })
}

/** The same caps as one string: '⌘⇧O' on macOS, 'Ctrl+Shift+O' elsewhere. */
export function formatCombo(combo: string): string {
  return comboParts(combo).join(isMac() ? '' : '+')
}

/**
 * Shift is a modifier for letters and digits ('shift+enter', 'mod+shift+o') but
 * part of the character itself for the symbols it produces — '?' is Shift+/ on
 * a US layout and nobody thinks of it as "shift question mark".
 */
function shiftBelongsToKey(key: string): boolean {
  return key.length === 1 && !/[a-z0-9]/i.test(key)
}

function keyFromCode(code: string): string {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3).toLowerCase()
  if (/^Digit[0-9]$/.test(code)) return code.slice(5)
  return code.toLowerCase()
}

/**
 * Every combo an event can be said to be.
 *
 * Two candidates, because the two readings disagree on non-US layouts and both
 * matter: `e.key` is what the user typed (so '?' stays '?' wherever it lives),
 * `e.code` is the physical key (so Cmd+Shift+O keeps working where KeyO does
 * not produce "o" — the behaviour the pre-registry handler had via
 * `e.code === 'KeyO'`). A spec matches if it equals either.
 */
export function eventCombos(
  e: Pick<KeyboardEvent, 'key' | 'code' | 'ctrlKey' | 'metaKey' | 'altKey' | 'shiftKey'>,
): string[] {
  const rawKey = (e.key || '').toLowerCase()
  // Holding a modifier down is not a shortcut. Checked on e.key, before the
  // code candidate is built — 'ShiftLeft' would otherwise read as a key named
  // "shiftleft" and produce a combo nothing can ever match.
  if (rawKey === 'control' || rawKey === 'meta' || rawKey === 'alt' || rawKey === 'shift') {
    return []
  }

  const candidates: string[] = []
  if (rawKey && rawKey !== 'unidentified') candidates.push(rawKey)
  if (e.code) {
    const fromCode = keyFromCode(e.code)
    if (fromCode && !candidates.includes(fromCode)) candidates.push(fromCode)
  }

  const combos: string[] = []
  for (const key of candidates) {
    const parts: string[] = []
    if (e.metaKey || e.ctrlKey) parts.push('mod')
    if (e.altKey) parts.push('alt')
    if (e.shiftKey && !shiftBelongsToKey(key)) parts.push('shift')
    parts.push(key)
    const combo = parts.join('+')
    if (!combos.includes(combo)) combos.push(combo)
  }
  return combos
}

/** Group for display, preferring CATEGORY_ORDER. */
export function groupByCategory(
  shortcuts: RegisteredShortcut[],
): Array<[string, RegisteredShortcut[]]> {
  const groups = new Map<string, RegisteredShortcut[]>()
  for (const item of [HELP_SHORTCUT, ...shortcuts]) {
    const category = item.spec.category || 'Other'
    const bucket = groups.get(category) ?? []
    // The same key can legitimately appear in two categories (Esc means
    // something different in the composer than it does globally); a repeat
    // within one category is a duplicate registration.
    if (bucket.some((existing) => existing.spec.combo === item.spec.combo)) continue
    bucket.push(item)
    groups.set(category, bucket)
  }
  return [...groups.entries()].sort(([a], [b]) => {
    const ai = CATEGORY_ORDER.indexOf(a)
    const bi = CATEGORY_ORDER.indexOf(b)
    return (ai === -1 ? CATEGORY_ORDER.length : ai) - (bi === -1 ? CATEGORY_ORDER.length : bi)
  })
}
