// The `?` cheat-sheet (#137).
//
// Split from the registry and loaded lazily: it is the only part that needs
// ModalShell and `motion`, and the registry provider mounts at app boot. Pulling
// those into the eager tree moved the whole animation runtime into the initial
// bundle (+44 KiB gzip) for a panel most sessions never open.
import { Fragment } from 'react'
import { AnimatePresence } from 'motion/react'
import { X } from 'lucide-react'
import { ModalShell } from '@/components/ModalShell'
import { t } from '@/i18n'
import { comboParts, groupByCategory, isMac, type RegisteredShortcut } from './shortcut-combo'
import './KeyboardShortcuts.css'

/**
 * Stays mounted once the sheet has been opened, so `AnimatePresence` can play
 * the exit as well as the enter.
 */
export default function ShortcutOverlay({
  open,
  shortcuts,
  onClose,
}: {
  open: boolean
  shortcuts: RegisteredShortcut[]
  onClose: () => void
}) {
  return (
    <AnimatePresence>
      {open ? <Sheet shortcuts={shortcuts} onClose={onClose} /> : null}
    </AnimatePresence>
  )
}

function Sheet({ shortcuts, onClose }: { shortcuts: RegisteredShortcut[]; onClose: () => void }) {
  const groups = groupByCategory(shortcuts)
  const mac = isMac()

  return (
    <ModalShell
      role="dialog"
      labelledBy="shortcut-overlay-title"
      onClose={onClose}
      overlayClassName="shortcut-overlay"
      className="shortcut-sheet panel"
    >
      <div className="panel__head shortcut-sheet__head">
        <h2 id="shortcut-overlay-title" className="shortcut-sheet__title">
          {t('shell.shortcutsLabel')}
        </h2>
        <button
          type="button"
          className="shortcut-sheet__close"
          onClick={onClose}
          aria-label={t('shell.shortcutClose')}
        >
          <X size={18} />
        </button>
      </div>
      <div className="panel__body shortcut-sheet__body">
        {groups.map(([category, items]) => (
          <section key={category} className="shortcut-sheet__group">
            <h3 className="shortcut-sheet__group-title">{category}</h3>
            {items.map((item) => (
              <div key={item.id} className="shortcut-sheet__row">
                <span className="shortcut-sheet__desc">{item.spec.description}</span>
                <span className="shortcut-sheet__keys">
                  {item.spec.combo.split(' ').map((chord, chordIdx) => (
                    <Fragment key={`${item.id}-${chordIdx}`}>
                      {chordIdx > 0 && (
                        <span className="shortcut-sheet__then">{t('shell.shortcutSeparator')}</span>
                      )}
                      {comboParts(chord).map((part, idx) => (
                        <Fragment key={`${item.id}-${chordIdx}-${idx}`}>
                          {idx > 0 && !mac ? <span className="shortcut-sheet__plus">+</span> : null}
                          <kbd className="shortcut-sheet__kbd">{part}</kbd>
                        </Fragment>
                      ))}
                    </Fragment>
                  ))}
                </span>
              </div>
            ))}
          </section>
        ))}
      </div>
    </ModalShell>
  )
}
