import './sessions.css'
import { useEffect, useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import {
  ActivityIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  CopyIcon,
  FolderKanbanIcon,
  MessageSquareIcon,
  PlusIcon,
  PencilIcon,
  RefreshCwIcon,
  SearchIcon,
  Trash2Icon,
} from 'lucide-react'
import { toast } from 'sonner'
import { copyWithFallback } from '@/lib/clipboard'
import { listItemVariants, SUBTLE_EASE } from '@/lib/motion'
import { ModalShell } from '@/components/ModalShell'
import { Button } from '@/components/ui/button'
import { useRpc } from '@/app/providers'
import { t, tPlural } from '@/i18n'
import '@/i18n/en/sessions'
import {
  agentIdFromKey,
  agentSubline,
  buildDeleteParams,
  dotTone,
  filterSessions,
  parseBulkDeleteResult,
  parseSingleDeleteResult,
  relTimeLabel,
  runStatusBadge,
  sessionStats,
  sessionStatusChip,
  sessionStatusLabel,
  sessionName,
  sessionVisualStatus,
  sortSessions,
  type AgentEntry,
  type RawSession,
  type SortColumn,
  type Tone,
} from './logic'
import {
  filterSessionsByProject,
  projectId as projectIdOf,
  projectName,
  sessionProjectId,
  type RawProject,
} from '@/views/projects/logic'

interface SessionsList {
  sessions?: RawSession[]
}
interface ProjectsList {
  projects?: RawProject[]
}
interface AgentsList {
  agents?: (AgentEntry & { model?: string; type?: string; isBuiltin?: boolean })[]
}
interface RpcError {
  code?: string
  message?: string
}

const PAGE_SIZES = [10, 25, 50, 100]

// Mirrors MAX_SESSION_NAME_LENGTH in src/agentos/session/naming.py — the
// gateway truncates past this, so stop the input there instead of silently
// dropping the tail on save.
const SESSION_NAME_MAX = 120

// ── Reusable destructive confirmation (alertdialog) ──────────────────────────
function ConfirmDialog({
  title,
  body,
  confirmLabel,
  cancelLabel = t('common.cancel'),
  busy = false,
  onCancel,
  onConfirm,
}: {
  title: string
  body: React.ReactNode
  confirmLabel: string
  cancelLabel?: string
  busy?: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const titleId = useId()
  const bodyId = useId()
  return (
    <ModalShell
      role="alertdialog"
      labelledBy={titleId}
      describedBy={bodyId}
      onClose={busy ? () => {} : onCancel}
      overlayClassName="sess-modal__overlay"
      className="sess-modal panel sess-confirm"
    >
      <header className="sess-dialog__head">
        <h2 id={titleId} className="sess-dialog__title">
          {title}
        </h2>
      </header>
      <div id={bodyId} className="sess-confirm__body">
        {body}
      </div>
      <footer className="sess-dialog__foot">
        <Button type="button" variant="ghost" disabled={busy} onClick={onCancel}>
          {cancelLabel}
        </Button>
        <Button type="button" variant="destructive" disabled={busy} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </footer>
    </ModalShell>
  )
}

// ── New-session dialog (agent picker + inline create) ────────────────────────
// sessions.js:561-716 — an agent combobox that either selects an existing agent
// or, when a novel id is typed, creates it (agents.create) before the session.
function NewSessionDialog({
  agents,
  onCancel,
  onSubmit,
  submitting,
  error,
}: {
  agents: { id: string; label: string; sublabel: string }[]
  onCancel: () => void
  onSubmit: (agentId: string, createPending: boolean) => void
  submitting: boolean
  error: string | null
}) {
  const titleId = useId()
  const listId = useId()
  // sessions.js:608 — default to `main` when it exists.
  const [value, setValue] = useState(() => (agents.some((a) => a.id === 'main') ? 'main' : ''))
  const typed = value.trim()
  // sessions.js:640-646 — an exact match selects that agent; otherwise a typed
  // id is a pending create.
  const exact = agents.find((a) => a.id === typed || a.label === typed)
  const createPending = !exact && typed.length > 0
  const canSubmit = typed.length > 0 && !submitting

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    const agentId = exact ? exact.id : typed
    onSubmit(agentId, createPending)
  }

  return (
    <ModalShell
      role="dialog"
      labelledBy={titleId}
      onClose={onCancel}
      overlayClassName="sess-modal__overlay"
      className="sess-modal panel sess-newchat"
    >
      <form className="sess-dialog" onSubmit={submit}>
        <header className="sess-dialog__head">
          <span className="t-label">{t('sessions.eyebrow')}</span>
          <h2 id={titleId} className="sess-dialog__title">
            {t('sessions.dialogTitle')}
          </h2>
        </header>
        <div className="sess-dialog__body">
          <label className="sess-field">
            <span className="t-label">{t('sessions.dialogAgent')}</span>
            <input
              className="sess-input"
              list={listId}
              autoComplete="off"
              value={value}
              placeholder={t('sessions.dialogAgentPlaceholder')}
              onChange={(e) => setValue(e.target.value)}
            />
            <datalist id={listId}>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.sublabel
                    ? t('sessions.dialogOptionWithSublabel', {
                        label: a.label,
                        sublabel: a.sublabel,
                      })
                    : a.label}
                </option>
              ))}
            </datalist>
            <small className="sess-field__hint">
              {createPending
                ? t('sessions.dialogHintCreate', { id: typed })
                : t('sessions.dialogHintPick')}
            </small>
          </label>
          {error ? (
            <div className="sess-field__error" role="alert">
              {error}
            </div>
          ) : null}
        </div>
        <footer className="sess-dialog__foot">
          <Button type="button" variant="ghost" disabled={submitting} onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={!canSubmit}>
            {submitting
              ? createPending
                ? t('sessions.dialogSubmitCreating')
                : t('sessions.dialogSubmitStarting')
              : t('sessions.dialogSubmit')}
          </Button>
        </footer>
      </form>
    </ModalShell>
  )
}

// ── Move-to-project dialog (radio list of projects + "no project") ───────────
function MoveToProjectDialog({
  projects,
  current,
  submitting,
  onCancel,
  onSubmit,
}: {
  projects: RawProject[]
  current: string
  submitting: boolean
  onCancel: () => void
  onSubmit: (projectId: string | null) => void
}) {
  const titleId = useId()
  const [value, setValue] = useState(current || 'none')
  const canSubmit = !submitting && value !== (current || 'none')

  function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    onSubmit(value === 'none' ? null : value)
  }

  return (
    <ModalShell
      role="dialog"
      labelledBy={titleId}
      onClose={onCancel}
      overlayClassName="sess-modal__overlay"
      className="sess-modal panel"
    >
      <form className="sess-dialog" onSubmit={submit}>
        <header className="sess-dialog__head">
          <span className="t-label">{t('sessions.eyebrow')}</span>
          <h2 id={titleId} className="sess-dialog__title">
            {t('sessions.moveDialogTitle')}
          </h2>
        </header>
        <div className="sess-dialog__body">
          <p className="sess-dim">{t('sessions.moveDialogBody')}</p>
          <div className="sess-move-options" role="radiogroup" aria-labelledby={titleId}>
            <label className="sess-move-option">
              <input
                type="radio"
                name="sess-move-project"
                value="none"
                checked={value === 'none'}
                onChange={() => setValue('none')}
              />
              <span>{t('sessions.moveNone')}</span>
            </label>
            {projects.map((p) => {
              const id = projectIdOf(p)
              return (
                <label key={id} className="sess-move-option">
                  <input
                    type="radio"
                    name="sess-move-project"
                    value={id}
                    checked={value === id}
                    onChange={() => setValue(id)}
                  />
                  <span>{projectName(p)}</span>
                </label>
              )
            })}
          </div>
        </div>
        <footer className="sess-dialog__foot">
          <Button type="button" variant="ghost" disabled={submitting} onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="submit" disabled={!canSubmit}>
            {submitting ? t('sessions.moveSubmitBusy') : t('sessions.moveSubmit')}
          </Button>
        </footer>
      </form>
    </ModalShell>
  )
}

// ── Stat tile ────────────────────────────────────────────────────────────────
function StatTile({
  label,
  value,
  hint,
  hero,
  active,
}: {
  label: string
  value: React.ReactNode
  hint: React.ReactNode
  hero?: boolean
  active?: boolean
}) {
  return (
    <div className={`sess-stat${hero ? ' sess-stat--hero' : ''}`} aria-label={label}>
      <span className="sess-stat__label t-label">{label}</span>
      <strong className="sess-stat__value t-data">
        {value}
        {active ? <span className="sess-stat__pulse tone-ok" aria-hidden="true" /> : null}
      </strong>
      <span className="sess-stat__hint">{hint}</span>
    </div>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────
type Dialog =
  | { kind: 'none' }
  | { kind: 'new' }
  | { kind: 'delete'; key: string }
  | { kind: 'bulk'; keys: string[] }
  | { kind: 'move'; key: string }

export function SessionsPage() {
  const rpc = useRpc()
  const reduceMotion = useReducedMotion()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [sortCol, setSortCol] = useState<SortColumn>('updated_at')
  const [sortAsc, setSortAsc] = useState(false)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(25)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [projectFilter, setProjectFilter] = useState('all')
  const [dialog, setDialog] = useState<Dialog>({ kind: 'none' })
  const [createError, setCreateError] = useState<string | null>(null)
  // Inline rename: the row key being edited, plus its in-flight input value.
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [nameDraft, setNameDraft] = useState('')

  useEffect(() => {
    document.title = t('sessions.documentTitle')
  }, [])

  // sessions.js:84-97 — debounce the search input (180ms); a new query resets
  // the page and selection.
  useEffect(() => {
    const id = setTimeout(() => {
      setDebounced(search.trim().toLowerCase())
      setPage(0)
      setSelected(new Set())
    }, 180)
    return () => clearTimeout(id)
  }, [search])

  // sessions.js:135-136 — sessions.list {limit:200} (opt into the larger page
  // size for the WebUI only; CLI default stays 50).
  const sessionsQuery = useQuery<RawSession[]>({
    queryKey: ['sessions'],
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<SessionsList>('sessions.list', { limit: 200 })
      return data.sessions ?? []
    },
    refetchOnWindowFocus: false,
  })

  // Projects drive the badge, the filter dropdown, and the move dialog. Shares
  // the ['projects'] cache key with ProjectsPage.
  const projectsQuery = useQuery<RawProject[]>({
    queryKey: ['projects'],
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<ProjectsList>('projects.list', {})
      return data.projects ?? []
    },
    refetchOnWindowFocus: false,
  })

  // sessions.js:137,140-148 — agents.list drives orphan detection; a failure
  // keeps the last known map (handled by react-query retaining prior data).
  const agentsQuery = useQuery<AgentEntry[]>({
    queryKey: ['sessions', 'agents'],
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<AgentsList>('agents.list', {})
      return data.agents ?? []
    },
    refetchOnWindowFocus: false,
  })

  // sessions.js:150-152 — every successful sessions fetch clears the selection
  // (legacy _loadData `_selected.clear()`), so a Refresh/refetch drops bulk
  // selection + the bulk-action bar. dataUpdatedAt advances on every successful
  // load (including a refetch that resolves to identical data). Done as a
  // render-phase reset keyed on dataUpdatedAt (React's supported "adjust state
  // when a derived value changes" pattern, mirroring ConfigPage) rather than an
  // effect, so the cleared state lands before paint with no cascading render.
  const sessionsUpdatedAt = sessionsQuery.dataUpdatedAt
  const [lastLoadAt, setLastLoadAt] = useState(0)
  if (sessionsUpdatedAt && sessionsUpdatedAt !== lastLoadAt) {
    setLastLoadAt(sessionsUpdatedAt)
    if (selected.size > 0) setSelected(new Set())
  }

  // sessions.js:158 — load-failure toast (stable id so repeats dedupe).
  useEffect(() => {
    if (sessionsQuery.isError) {
      const err = sessionsQuery.error
      const message = err instanceof Error ? err.message : String(err)
      toast.error(t('sessions.toastLoadFailed', { message }), { id: 'sessions-load-err' })
    }
  }, [sessionsQuery.isError, sessionsQuery.error])

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['sessions'] })
  }

  const allSessions = useMemo(() => sessionsQuery.data ?? [], [sessionsQuery.data])
  const agentsLoaded = agentsQuery.isSuccess
  const agentsById = useMemo(() => {
    const map = new Map<string, AgentEntry>()
    for (const a of agentsQuery.data ?? []) if (a.id) map.set(a.id, a)
    return map
  }, [agentsQuery.data])

  const projects = useMemo(() => projectsQuery.data ?? [], [projectsQuery.data])
  const projectsById = useMemo(() => {
    const map = new Map<string, RawProject>()
    for (const p of projects) {
      const id = projectIdOf(p)
      if (id) map.set(id, p)
    }
    return map
  }, [projects])

  const stats = sessionStats(allSessions)
  const filtered = useMemo(
    () =>
      sortSessions(
        filterSessions(filterSessionsByProject(allSessions, projectFilter), debounced),
        sortCol,
        sortAsc,
      ),
    [allSessions, debounced, sortCol, sortAsc, projectFilter],
  )

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize))
  const safePage = Math.min(page, totalPages - 1)
  const slice = filtered.slice(safePage * pageSize, (safePage + 1) * pageSize)
  const allOnPageSelected = slice.length > 0 && slice.every((s) => selected.has(s.key ?? ''))

  // ── Delete mutation (single + bulk share the endpoint) ─────────────────────
  const deleteMutation = useMutation({
    mutationFn: (keys: string[]) => rpc.call('sessions.delete', buildDeleteParams(keys)),
    onSuccess: (data, keys) => {
      if (keys.length === 1) {
        const outcome = parseSingleDeleteResult(data as never, keys[0]!)
        if (outcome.ok) toast.success(t('sessions.toastDeleted'), { id: 'sessions-delete' })
        else
          toast.error(t('sessions.toastDeleteFailed', { message: outcome.reason }), {
            id: 'sessions-delete-err',
          })
      } else {
        const { okCount, errCount } = parseBulkDeleteResult(data as never, keys.length)
        if (errCount > 0)
          toast.warning(t('sessions.toastBulkPartial', { ok: okCount, failed: errCount }), {
            id: 'sessions-delete',
          })
        else
          toast.success(tPlural('sessions.toastBulkDeleted', okCount), {
            id: 'sessions-delete',
          })
      }
      setSelected(new Set())
      setDialog({ kind: 'none' })
      invalidate()
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : String(err)
      toast.error(t('sessions.toastDeleteFailed', { message }), { id: 'sessions-delete-err' })
      setDialog({ kind: 'none' })
      invalidate()
    },
  })

  // ── Rename mutation (inline click-to-edit on a row) ───────────────────────
  const renameMutation = useMutation({
    mutationFn: (vars: { key: string; name: string }) =>
      rpc.call<{ name?: string | null }>('sessions.rename', { key: vars.key, name: vars.name }),
    onSuccess: (data) => {
      // The gateway normalizes (and may clear) the name, so report what it
      // actually stored rather than what was typed.
      toast.success(data?.name ? t('sessions.toastRenamed') : t('sessions.toastRenameCleared'), {
        id: 'sessions-rename',
      })
      setEditingKey(null)
      invalidate()
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : String(err)
      toast.error(t('sessions.toastRenameFailed', { message }), { id: 'sessions-rename-err' })
      setEditingKey(null)
    },
  })

  const startRename = (key: string, current: string) => {
    setEditingKey(key)
    setNameDraft(current)
  }

  const submitRename = (key: string) => {
    // Skip the round-trip when nothing actually changed.
    const row = allSessions.find((s) => (s.key ?? '') === key)
    if (row && sessionName(row).trim() === nameDraft.trim()) {
      setEditingKey(null)
      return
    }
    renameMutation.mutate({ key, name: nameDraft })
  }

  // ── Move-to-project mutation (sessions.patch projectId; null detaches) ─────
  const moveMutation = useMutation({
    mutationFn: (vars: { key: string; projectId: string | null }) =>
      rpc.call('sessions.patch', { key: vars.key, projectId: vars.projectId }),
    onSuccess: (_data, vars) => {
      toast.success(vars.projectId ? t('sessions.toastMoved') : t('sessions.toastDetached'), {
        id: 'sessions-move',
      })
      setDialog({ kind: 'none' })
      invalidate()
      void queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
    onError: (err) => {
      const message = err instanceof Error ? err.message : String(err)
      toast.error(t('sessions.toastMoveFailed', { message }), { id: 'sessions-move-err' })
      setDialog({ kind: 'none' })
    },
  })

  // ── Create-session mutation (optional inline agent create) ─────────────────
  const createMutation = useMutation({
    mutationFn: async (vars: { agentId: string; createPending: boolean }) => {
      let createdAgent = false
      if (vars.createPending) {
        try {
          await rpc.call('agents.create', { id: vars.agentId, name: vars.agentId })
          createdAgent = true
        } catch (err) {
          // sessions.js:686-688 — tolerate an already-existing agent.
          if ((err as RpcError).code !== 'agent.exists') throw err
        }
      }
      const res = await rpc.call<{ key?: string }>('sessions.create', { agentId: vars.agentId })
      return { key: res?.key, createdAgent }
    },
    onSuccess: (res, vars) => {
      toast.success(
        res.createdAgent
          ? t('sessions.toastCreatedWithAgent', { id: vars.agentId })
          : t('sessions.toastCreated'),
        { id: 'sessions-create' },
      )
      setDialog({ kind: 'none' })
      setCreateError(null)
      invalidate()
      if (res.key) navigate('/chat?session=' + encodeURIComponent(res.key))
    },
    onError: (err, vars) => {
      // sessions.js:698-708 — friendly inline errors; dialog stays open.
      const e = err as RpcError
      const code = e.code || ''
      let friendly = t('sessions.toastCreateFailed', { message: e.message || String(err) })
      if (code === 'UNAUTHORIZED' && vars.createPending)
        friendly = t('sessions.toastCreateUnauthorized')
      if (code === 'agent.not_found')
        friendly = t('sessions.toastAgentNotFound', { id: vars.agentId })
      if (code === 'agent.exists') friendly = t('sessions.toastAgentExists', { id: vars.agentId })
      setCreateError(friendly)
    },
  })

  const agentOptions = useMemo(
    () =>
      (agentsQuery.data ?? []).map((a) => {
        const withMeta = a as AgentEntry & { model?: string; type?: string; isBuiltin?: boolean }
        return {
          id: a.id ?? '',
          label: a.name || a.id || '',
          sublabel:
            withMeta.model ||
            (withMeta.isBuiltin || withMeta.type === 'builtin' ? t('sessions.agentBuiltin') : ''),
        }
      }),
    [agentsQuery.data],
  )

  function toggleRow(key: string, on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })
  }
  function toggleAllOnPage(on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev)
      for (const s of slice) {
        const k = s.key ?? ''
        if (on) next.add(k)
        else next.delete(k)
      }
      return next
    })
  }
  function onSort(col: SortColumn) {
    if (sortCol === col) setSortAsc((a) => !a)
    else {
      setSortCol(col)
      setSortAsc(true)
    }
  }
  async function copyKey(key: string) {
    try {
      await copyWithFallback(key)
      toast.success(t('sessions.toastCopied'), { id: 'sessions-copy-ok', duration: 1600 })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      toast.warning(t('sessions.toastCopyFailed', { message }), {
        id: 'sessions-copy-err',
        duration: 2500,
      })
    }
  }

  const hasSessions = allSessions.length > 0
  const sortArrow = (col: SortColumn) => (sortCol === col ? (sortAsc ? ' ▲' : ' ▼') : '')
  const ariaSort = (col: SortColumn): 'ascending' | 'descending' | 'none' =>
    sortCol === col ? (sortAsc ? 'ascending' : 'descending') : 'none'

  return (
    <div className="sess-stage">
      <header className="sess-stage__header">
        <div className="sess-stage__title-block">
          <span className="t-label">{t('sessions.eyebrow')}</span>
          <h1 className="t-display">{t('sessions.title')}</h1>
          <p className="sess-stage__subtitle">{t('sessions.subtitle')}</p>
        </div>
        <div className="sess-stage__actions">
          <Button
            variant="outline"
            title={t('sessions.refresh')}
            className="text-xs uppercase tracking-[0.14em]"
            disabled={sessionsQuery.isFetching}
            onClick={invalidate}
          >
            <RefreshCwIcon className={sessionsQuery.isFetching ? 'sess-refresh-spin' : undefined} />
            <span>
              {sessionsQuery.isFetching ? t('sessions.refreshBusy') : t('sessions.refresh')}
            </span>
          </Button>
          <Button
            className="text-xs uppercase tracking-[0.14em]"
            onClick={() => {
              setCreateError(null)
              setDialog({ kind: 'new' })
            }}
          >
            <PlusIcon />
            <span>{t('sessions.newSession')}</span>
          </Button>
        </div>
      </header>

      <section
        className={`sess-command${sessionsQuery.isFetching ? ' is-loading' : ''}`}
        aria-label={t('sessions.overviewLandmark')}
        aria-busy={sessionsQuery.isFetching}
      >
        <div className="sess-command__toolbar">
          <div className="sess-command__heading">
            <span className="sess-command__icon" aria-hidden="true">
              <ActivityIcon />
            </span>
            <div>
              <span className="t-label">{t('sessions.overviewEyebrow')}</span>
              <strong>{t('sessions.overviewTitle')}</strong>
            </div>
          </div>
          <span className="sess-command__meta">
            <span className={stats.activeRuns ? 'tone-ok' : 'tone-dim'} aria-hidden="true" />
            {stats.activeRuns
              ? t('sessions.overviewExecuting', { count: stats.activeRuns })
              : t('sessions.overviewIdle')}
          </span>
        </div>
        <div className="sess-stats" aria-label={t('sessions.statsLandmark')}>
          <StatTile
            label={t('sessions.statTotal')}
            hero
            value={stats.total}
            hint={t('sessions.statTotalHint', {
              open: stats.lifecycleOpen,
              done: stats.done,
              failed: stats.failedOrTimedOut,
              aborted: stats.aborted,
            })}
          />
          <StatTile
            label={t('sessions.statExecuting')}
            value={stats.activeRuns}
            active={stats.activeRuns > 0}
            hint={
              stats.activeRuns ? t('sessions.statExecutingHint') : t('sessions.statExecutingIdle')
            }
          />
          <StatTile
            label={t('sessions.statMessages')}
            value={stats.totalMessages.toLocaleString()}
            hint={tPlural('sessions.statMessagesHint', stats.agents)}
          />
        </div>
      </section>

      <section className="sess-list">
        <div className="sess-list__head">
          <div className="sess-list__heading">
            <h2 className="sess-list__title">
              {debounced ? t('sessions.listMatching') : t('sessions.listAll')}
            </h2>
            <span className="sess-list__count t-data">
              {debounced
                ? t('sessions.countFiltered', { shown: filtered.length, total: stats.total })
                : t('sessions.countTotal', { total: stats.total })}
            </span>
          </div>
          <div className="sess-list__tools">
            <div className="sess-search-wrap">
              <SearchIcon className="sess-search-icon" aria-hidden="true" />
              <input
                type="text"
                className="sess-search-input"
                placeholder={t('sessions.searchPlaceholder')}
                autoComplete="off"
                aria-label={t('sessions.searchLabel')}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            {projects.length > 0 ? (
              <label className="sess-page-size t-label">
                <span>{t('sessions.filterProjectLabel')}</span>
                <select
                  value={projectFilter}
                  aria-label={t('sessions.filterProjectLabel')}
                  onChange={(e) => {
                    setProjectFilter(e.target.value)
                    setPage(0)
                  }}
                >
                  <option value="all">{t('sessions.filterAllProjects')}</option>
                  <option value="none">{t('sessions.filterNoProject')}</option>
                  {projects.map((p) => {
                    const id = projectIdOf(p)
                    return (
                      <option key={id} value={id}>
                        {projectName(p)}
                      </option>
                    )
                  })}
                </select>
              </label>
            ) : null}
            <label className="sess-page-size t-label">
              <span>{t('sessions.rowsLabel')}</span>
              <select
                value={pageSize}
                aria-label={t('sessions.rowsPerPage')}
                onChange={(e) => {
                  setPageSize(Number(e.target.value))
                  setPage(0)
                }}
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>

        {selected.size > 0 ? (
          <div className="sess-bulk-bar" role="region" aria-label={t('sessions.bulkLandmark')}>
            <span className="sess-bulk-bar__count">
              <strong>{selected.size}</strong> {t('sessions.bulkSelected')}
            </span>
            <Button variant="ghost" size="sm" onClick={() => setSelected(new Set())}>
              {t('sessions.bulkClear')}
            </Button>
            <span className="sess-bulk-bar__spacer" />
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setDialog({ kind: 'bulk', keys: Array.from(selected) })}
            >
              <Trash2Icon />
              <span>{t('sessions.bulkDelete')}</span>
            </Button>
          </div>
        ) : null}

        {!hasSessions ? (
          <div className="sess-empty">
            <div className="sess-empty__title">{t('sessions.emptyTitle')}</div>
            <p className="sess-empty__msg">{t('sessions.emptyMsg')}</p>
            <Button
              onClick={() => {
                setCreateError(null)
                setDialog({ kind: 'new' })
              }}
            >
              <PlusIcon />
              <span>{t('sessions.emptyAction')}</span>
            </Button>
          </div>
        ) : slice.length === 0 ? (
          <div className="sess-empty sess-empty--search">
            <div className="sess-empty__title">{t('sessions.noMatchTitle')}</div>
            <p className="sess-empty__msg">{t('sessions.noMatchMsg')}</p>
          </div>
        ) : (
          <div className="sess-table-wrap">
            <table className="sess-table">
              <thead>
                <tr>
                  <th className="sess-table__cell--check">
                    <label className="sess-check-target">
                      <input
                        type="checkbox"
                        aria-label={t('sessions.selectAll')}
                        checked={allOnPageSelected}
                        onChange={(e) => toggleAllOnPage(e.target.checked)}
                      />
                    </label>
                  </th>
                  <th aria-sort={ariaSort('key')}>
                    <button type="button" className="sess-th-sort" onClick={() => onSort('key')}>
                      {t('sessions.colKey')}
                      <span aria-hidden="true">{sortArrow('key')}</span>
                    </button>
                  </th>
                  <th>{t('sessions.colStatus')}</th>
                  <th aria-sort={ariaSort('message_count')}>
                    <button
                      type="button"
                      className="sess-th-sort"
                      onClick={() => onSort('message_count')}
                    >
                      {t('sessions.colMessages')}
                      <span aria-hidden="true">{sortArrow('message_count')}</span>
                    </button>
                  </th>
                  <th aria-sort={ariaSort('updated_at')}>
                    <button
                      type="button"
                      className="sess-th-sort"
                      onClick={() => onSort('updated_at')}
                    >
                      {t('sessions.colModified')}
                      <span aria-hidden="true">{sortArrow('updated_at')}</span>
                    </button>
                  </th>
                  <th className="sess-table__cell--actions" />
                </tr>
              </thead>
              <tbody>
                <AnimatePresence initial={false}>
                  {slice.map((row) => {
                    const key = row.key ?? ''
                    const visual = sessionVisualStatus(row)
                    const statusTone = dotTone(visual)
                    const statusLabel = sessionStatusLabel(visual)
                    const chipTone: Tone = sessionStatusChip(visual)
                    const badge = runStatusBadge(row)
                    const agentId = row.agent_id || row.agentId || agentIdFromKey(key) || ''
                    const name = sessionName(row)
                    const sub = agentSubline(agentId, agentsById, agentsLoaded)
                    const isSel = selected.has(key)
                    const rowClass = isSel ? 'is-selected' : undefined
                    const rowProjectId = sessionProjectId(row)
                    const rowProject = rowProjectId ? projectsById.get(rowProjectId) : undefined
                    const rowContent = (
                      <>
                        <td className="sess-table__cell--check">
                          <label className="sess-check-target">
                            <input
                              type="checkbox"
                              aria-label={t('sessions.selectRow', { key })}
                              checked={isSel}
                              onChange={(e) => toggleRow(key, e.target.checked)}
                            />
                          </label>
                        </td>
                        <td className="sess-table__cell--key">
                          <div className="sess-key-content">
                            <span
                              className={`sess-dot tone-${statusTone}`}
                              title={statusLabel}
                              aria-hidden="true"
                            />
                            <button
                              type="button"
                              className="sess-key-link t-data"
                              title={t('sessions.openChat')}
                              onClick={() => navigate('/chat?session=' + encodeURIComponent(key))}
                            >
                              {key}
                            </button>
                          </div>
                          {key && editingKey === key ? (
                            <form
                              className="sess-rename"
                              onSubmit={(e) => {
                                e.preventDefault()
                                submitRename(key)
                              }}
                            >
                              <input
                                className="sess-rename__input"
                                autoFocus
                                value={nameDraft}
                                maxLength={SESSION_NAME_MAX}
                                placeholder={t('sessions.renamePlaceholder')}
                                aria-label={t('sessions.renameInput', { key })}
                                onChange={(e) => setNameDraft(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Escape') setEditingKey(null)
                                }}
                                onBlur={() => setEditingKey(null)}
                              />
                              <span className="sess-rename__hint">{t('sessions.renameHint')}</span>
                            </form>
                          ) : key ? (
                            <button
                              type="button"
                              className={`sess-name${name ? '' : ' sess-name--empty'}`}
                              title={t('sessions.renameTitle')}
                              aria-label={t('sessions.renameFor', { key })}
                              onClick={() => startRename(key, name)}
                            >
                              <PencilIcon aria-hidden="true" />
                              <span>{name || t('sessions.renamePlaceholder')}</span>
                            </button>
                          ) : null}
                          {rowProject ? (
                            <div className="sess-key-content">
                              <span className="sess-chip tone-info sess-project-chip">
                                <FolderKanbanIcon aria-hidden="true" />
                                {projectName(rowProject)}
                              </span>
                            </div>
                          ) : null}
                          <div className="sess-key-content">
                            {sub ? (
                              <span
                                className={`sess-key__agent${sub.orphan ? ' sess-key__agent--orphan' : ''}`}
                                title={
                                  sub.orphan
                                    ? t('sessions.orphanTitle', { name: sub.name })
                                    : undefined
                                }
                              >
                                {sub.name}
                                {sub.orphan ? (
                                  <span className="sess-chip tone-warn">
                                    {t('sessions.orphanChip')}
                                  </span>
                                ) : null}
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td>
                          <div className="sess-status-stack">
                            <span className={`sess-chip tone-${chipTone}`}>{statusLabel}</span>
                            {badge ? (
                              <span className={`sess-chip tone-${badge.tone}`} title={badge.label}>
                                {badge.label}
                              </span>
                            ) : null}
                          </div>
                        </td>
                        <td className="t-data sess-dim">
                          {row.message_count != null
                            ? Number(row.message_count).toLocaleString()
                            : t('common.dash')}
                        </td>
                        <td className="t-data sess-dim">
                          {row.updated_at != null ? relTimeLabel(row.updated_at) : t('common.dash')}
                        </td>
                        <td className="sess-table__cell--actions">
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            title={t('sessions.openChat')}
                            aria-label={t('sessions.openChatFor', { key })}
                            onClick={() => navigate('/chat?session=' + encodeURIComponent(key))}
                          >
                            <MessageSquareIcon />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            title={t('sessions.copyKeyTitle')}
                            aria-label={t('sessions.copyKeyFor', { key })}
                            onClick={() => void copyKey(key)}
                          >
                            <CopyIcon />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            title={t('sessions.moveToProject')}
                            aria-label={t('sessions.moveToProjectFor', { key })}
                            onClick={() => setDialog({ kind: 'move', key })}
                          >
                            <FolderKanbanIcon />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon-xs"
                            className="sess-iconbtn--danger"
                            title={t('sessions.deleteTitle')}
                            aria-label={t('sessions.deleteFor', { key })}
                            onClick={() => setDialog({ kind: 'delete', key })}
                          >
                            <Trash2Icon />
                          </Button>
                        </td>
                      </>
                    )
                    return reduceMotion ? (
                      <tr key={key} className={rowClass}>
                        {rowContent}
                      </tr>
                    ) : (
                      <motion.tr
                        key={key}
                        layout
                        className={rowClass}
                        variants={listItemVariants}
                        initial="initial"
                        animate="animate"
                        exit="exit"
                        transition={SUBTLE_EASE}
                      >
                        {rowContent}
                      </motion.tr>
                    )
                  })}
                </AnimatePresence>
              </tbody>
            </table>
          </div>
        )}

        {hasSessions && filtered.length > 0 ? (
          <div className="sess-pagination">
            <Button
              variant="ghost"
              size="icon-xs"
              disabled={safePage === 0}
              title={t('sessions.prevPage')}
              aria-label={t('sessions.prevPage')}
              onClick={() => setPage((p) => Math.max(0, p - 1))}
            >
              <ChevronLeftIcon />
            </Button>
            <span className="sess-page-info t-data">
              {safePage + 1} / {totalPages}{' '}
              <span className="sess-dim">
                {t('sessions.pageTotal', { total: filtered.length })}
              </span>
            </span>
            <Button
              variant="ghost"
              size="icon-xs"
              disabled={safePage >= totalPages - 1}
              title={t('sessions.nextPage')}
              aria-label={t('sessions.nextPage')}
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
            >
              <ChevronRightIcon />
            </Button>
          </div>
        ) : null}
      </section>

      <AnimatePresence>
        {dialog.kind === 'new' ? (
          <NewSessionDialog
            agents={agentOptions}
            submitting={createMutation.isPending}
            error={createError}
            onCancel={() => {
              setDialog({ kind: 'none' })
              setCreateError(null)
            }}
            onSubmit={(agentId, createPending) => {
              setCreateError(null)
              createMutation.mutate({ agentId, createPending })
            }}
          />
        ) : null}

        {dialog.kind === 'delete' ? (
          <ConfirmDialog
            title={t('sessions.confirmDeleteTitle')}
            body={
              <>
                <p>
                  {t('sessions.confirmDeleteLead')} <strong>{dialog.key}</strong>
                  {t('sessions.confirmDeleteTail')}
                </p>
                <p className="sess-confirm__warn">
                  {t('sessions.confirmWarnLead')} <code>{'/reset'}</code>{' '}
                  {t('sessions.confirmWarnTail')}
                </p>
              </>
            }
            confirmLabel={t('sessions.confirmDelete')}
            busy={deleteMutation.isPending}
            onCancel={() => setDialog({ kind: 'none' })}
            onConfirm={() => deleteMutation.mutate([dialog.key])}
          />
        ) : null}

        {dialog.kind === 'move' ? (
          <MoveToProjectDialog
            // Projects are cross-agent: any session may join any project.
            projects={projects}
            current={(() => {
              const row = allSessions.find((s) => (s.key ?? '') === dialog.key)
              return row ? sessionProjectId(row) : ''
            })()}
            submitting={moveMutation.isPending}
            onCancel={() => setDialog({ kind: 'none' })}
            onSubmit={(projectId) => moveMutation.mutate({ key: dialog.key, projectId })}
          />
        ) : null}

        {dialog.kind === 'bulk' ? (
          <ConfirmDialog
            title={t('sessions.confirmBulkTitle')}
            body={
              <>
                <p>
                  {t('sessions.confirmBulkLead')} <strong>{dialog.keys.length}</strong>{' '}
                  {dialog.keys.length === 1
                    ? t('sessions.confirmBulkTailSingular')
                    : t('sessions.confirmBulkTailPlural')}
                </p>
                <p className="sess-confirm__warn">
                  {t('sessions.confirmWarnLead')} <code>{'/reset'}</code>{' '}
                  {t('sessions.confirmWarnTail')}
                </p>
              </>
            }
            confirmLabel={t('sessions.confirmDeleteAll')}
            busy={deleteMutation.isPending}
            onCancel={() => setDialog({ kind: 'none' })}
            onConfirm={() => deleteMutation.mutate(dialog.keys)}
          />
        ) : null}
      </AnimatePresence>
    </div>
  )
}
