import './health.css'
import { useQuery } from '@tanstack/react-query'
import { ActivityIcon, RefreshCwIcon, ShieldAlertIcon, ShieldCheckIcon } from 'lucide-react'
import { CommandLine } from '@/components/CommandLine'
import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { useBootstrap, useRpc } from '@/app/providers'
// Registers this view's copy; it ships in this chunk, not the entry bundle.
import '@/i18n/en/health'
import { formatNumber, t } from '@/i18n'
import {
  evidenceLabel,
  evidenceValue,
  findingGroupKind,
  gatewayUnavailableFixSteps,
  impactCountsFromSeverity,
  impactValue,
  statusLabel,
  visibleEvidenceEntries,
  type Finding,
  type GroupKind,
  type HealthReport,
  type Impact,
} from './logic'

const WS_URL_KEY = 'agentos.wsUrl'

// health.js:422-430 — impact -> human label for the finding meta line.
function impactLabel(impact: Impact): string {
  const labels: Record<Impact, string> = {
    blocks_ready: t('health.impactBlocksReady'),
    degrades: t('health.impactDegrades'),
    optional: t('health.impactOptional'),
    none: t('health.impactNone'),
  }
  return labels[impact]
}

// health.js:432-437 — finding kind -> tone token used for the card accent.
const FINDING_TONE: Record<GroupKind, string> = {
  action: 'error',
  degraded: 'warn',
  optional: 'info',
  ready: 'ok',
}

// health.js:397-401 — steps heading by group kind.
function stepsHeading(kind: GroupKind): string {
  if (kind === 'optional') return t('health.stepsOptional')
  if (kind === 'ready') return t('health.stepsReference')
  return t('health.stepsRecovery')
}

// health.js:485-487 — normalize a value into a CSS-safe class token.
function classToken(value: string): string {
  return String(value || 'unknown')
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
}

// health.js:356-368 — id-derived badge for known finding families.
function findingBadge(finding: Finding): string | null {
  const id = String(finding?.id || '')
  if (id.endsWith('.diagnostic.incomplete')) return t('health.badgeDiagnosticsIncomplete')
  if (id.endsWith('.repair.pending')) return t('health.badgeRepairPending')
  if (id === 'gateway.config.mismatch') return t('health.badgeConfigMismatch')
  return null
}

// health.js:191-195 — detail text for the synthetic gateway.unavailable finding.
function gatewayUnavailableDetail(gatewayUrl: string, err: unknown): string {
  const reason = err instanceof Error ? err.message : String(err)
  if (!gatewayUrl) return reason
  return t('health.gatewayUnavailableDetail', { url: gatewayUrl, reason })
}

// health.js:35-62 + components.js UI.toast — copy handling now lives in the
// COMMON <CommandLine> component (clipboard + execCommand fallback, 1600ms ok
// / 2500ms err toasts, stable ids for dedupe; the sonner a11y seam stays
// recorded on parity matrix row 64). Health scopes its toast ids with the
// legacy-compatible "health-copy" prefix.
function CommandRow({ command }: { command: string }) {
  // health.js:388-395 — terminal command line + copy.
  return <CommandLine command={command} toastIdPrefix="health-copy" />
}

function StepsList({ steps, kind }: { steps: NonNullable<Finding['fixSteps']>; kind: GroupKind }) {
  // health.js:370-386 — numbered steps, optional command + detail.
  if (!steps.length) return null
  return (
    <div className="health-steps">
      <div className="health-steps__heading">{stepsHeading(kind)}</div>
      <ol>
        {steps.map((step, index) => (
          <li className="health-step" key={index}>
            <span className="health-step__number">{index + 1}</span>
            <span className="health-step__body">
              <b>{step.label || t('health.stepFallbackLabel')}</b>
              {step.command ? <CommandRow command={step.command} /> : null}
              {step.detail ? <span className="health-step__detail">{step.detail}</span> : null}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

function EvidenceTags({ evidence }: { evidence?: Record<string, unknown> }) {
  // health.js:439-446 — up to 6 visible evidence entries.
  const entries = visibleEvidenceEntries(evidence).slice(0, 6)
  if (!entries.length) return null
  return (
    <div className="health-evidence" aria-label={t('health.findingEvidence')}>
      {entries.map(([key, value]) => (
        <span key={key}>
          <b>{evidenceLabel(key)}</b>
          {evidenceValue(value)}
        </span>
      ))}
    </div>
  )
}

function FindingCard({ finding, index }: { finding: Finding; index: number }) {
  // health.js:324-354 — meta line, title/detail, evidence + steps.
  const kind = findingGroupKind(finding)
  const severity = String(finding.severity || 'info')
  const impact = impactValue(finding)
  const surface = String(finding.surface || 'system')
  const badge = findingBadge(finding)
  return (
    <article className={`health-finding is-${classToken(FINDING_TONE[kind])}`}>
      <div className="health-finding__marker" aria-hidden="true">
        <span className="health-finding__dot" />
        <span className="health-finding__line" />
      </div>
      <div className="health-finding__body">
        <div className="health-finding__meta">
          <span>{severity}</span>
          <span className="health-impact">{impactLabel(impact)}</span>
          <span className="health-surface">{surface}</span>
          {badge ? <span className="health-chip health-chip--badge">{badge}</span> : null}
          {finding.restartRequired ? (
            <span className="health-chip">{t('health.findingRestart')}</span>
          ) : null}
        </div>
        <div className="health-finding__title">
          {finding.title || finding.id || t('health.findingFallbackTitle', { index: index + 1 })}
        </div>
        <div className="health-finding__detail">{finding.detail || ''}</div>
        <EvidenceTags evidence={finding.evidence} />
        <StepsList steps={finding.fixSteps || []} kind={kind} />
      </div>
    </article>
  )
}

function findingGroups(): Array<{ kind: GroupKind; title: string; note: string }> {
  // health.js:281-301
  return [
    {
      kind: 'action',
      title: t('health.groupActionTitle'),
      note: t('health.groupActionNote'),
    },
    {
      kind: 'degraded',
      title: t('health.groupDegradedTitle'),
      note: t('health.groupDegradedNote'),
    },
    {
      kind: 'optional',
      title: t('health.groupOptionalTitle'),
      note: t('health.groupOptionalNote'),
    },
    {
      kind: 'ready',
      title: t('health.groupReadyTitle'),
      note: t('health.groupReadyNote'),
    },
  ]
}

function FindingsSection({ findings }: { findings: Finding[] }) {
  // health.js:277-313 — empty state else grouped sections.
  if (!findings.length) {
    return <article className="health-empty">{t('health.findingsEmpty')}</article>
  }
  const groups = findingGroups()
    .map((group) => ({
      ...group,
      findings: findings.filter((finding) => findingGroupKind(finding) === group.kind),
    }))
    .filter((group) => group.findings.length)

  return (
    <>
      {groups.map((group) => (
        <section className={`health-finding-group is-${group.kind}`} key={group.kind}>
          <header className="health-finding-group__header">
            <div>
              <h2>{group.title}</h2>
              <p>{group.note}</p>
            </div>
            <span>{group.findings.length}</span>
          </header>
          {group.findings.map((finding, index) => (
            <FindingCard finding={finding} index={index} key={finding.id || index} />
          ))}
        </section>
      ))}
    </>
  )
}

function CountTile({
  label,
  value,
  kind,
  total,
  loading = false,
}: {
  label: string
  value: number
  kind: string
  total: number
  loading?: boolean
}) {
  // health.js:270-275
  const percentage = total > 0 ? Math.round((value / total) * 100) : 0
  return (
    <div
      className={`health-count is-${classToken(kind)}${loading ? ' is-loading' : ''}`}
      aria-label={t('health.railCountValue', { label, value: Number(value || 0) })}
    >
      <span className="health-count__dot" aria-hidden="true" />
      <span className="health-count__label">{label}</span>
      <strong>{loading ? t('common.dash') : formatNumber(Number(value || 0))}</strong>
      <span className="health-count__share">
        {loading
          ? t('health.railCountChecking')
          : t('health.railCountShare', { percent: percentage })}
      </span>
    </div>
  )
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'ready') return <ShieldCheckIcon />
  if (status === 'degraded') return <ActivityIcon />
  return <ShieldAlertIcon />
}

function ReportContext({
  report,
  fallbackGatewayUrl,
}: {
  report: HealthReport
  fallbackGatewayUrl: string
}) {
  // health.js:152-170 — gateway/config/agent context row.
  const items: Array<[string, string]> = []
  const gatewayUrl = report.gatewayUrl || fallbackGatewayUrl
  if (gatewayUrl) items.push([t('health.contextGateway'), gatewayUrl])
  if (report.configPath) items.push([t('health.contextConfig'), report.configPath])
  if (report.requestedConfigPath && report.requestedConfigPath !== report.configPath) {
    items.push([t('health.contextRequestedConfig'), report.requestedConfigPath])
  }
  if (report.agentId) items.push([t('health.contextAgent'), report.agentId])
  if (!items.length) return null
  return (
    <div className="health-report-context" aria-label={t('health.contextLandmark')}>
      {items.map(([label, value]) => (
        <span className="health-report-context__item" key={label}>
          <b>{label}</b>
          <span className="health-report-context__value">{value}</span>
        </span>
      ))}
    </div>
  )
}

function StatusRail({
  report,
  fallbackGatewayUrl,
}: {
  report: HealthReport
  fallbackGatewayUrl: string
}) {
  // health.js:133-150 — readiness label + 4 count tiles.
  const impactCounts = report.impactCounts || impactCountsFromSeverity(report.counts || {})
  const status = report.status || 'unknown'
  const counts = [
    {
      label: t('health.countBlocksReady'),
      value: impactCounts.blocks_ready || 0,
      kind: 'blocks_ready',
    },
    { label: t('health.countDegrades'), value: impactCounts.degrades || 0, kind: 'degrades' },
    { label: t('health.countOptional'), value: impactCounts.optional || 0, kind: 'optional' },
    { label: t('health.countNone'), value: impactCounts.none || 0, kind: 'none' },
  ]
  const total = counts.reduce((sum, item) => sum + item.value, 0)
  return (
    <section
      className={`health-status__rail is-${classToken(status)}`}
      aria-label={t('health.railLandmark')}
    >
      <div className="health-score">
        <span className="health-score__icon" aria-hidden="true">
          <StatusIcon status={status} />
        </span>
        <div className="health-score__copy">
          <span className="health-score__label">{t('health.railReadiness')}</span>
          <strong>{statusLabel(status, report.ready)}</strong>
          <span className="health-score__summary">{report.summary || status}</span>
        </div>
      </div>
      <div className="health-impact-profile">
        <div className="health-impact-profile__head">
          <span>{t('health.railImpactHead')}</span>
          <strong>{t('health.railImpactChecks', { count: total })}</strong>
        </div>
        <div
          className={`health-impact-meter${total === 0 ? ' is-empty' : ''}`}
          role="img"
          aria-label={t('health.railImpactMeter', {
            breakdown: counts.map((item) => `${item.label} ${item.value}`).join(', '),
          })}
        >
          {counts
            .filter((item) => item.value > 0)
            .map((item) => (
              <span
                className={`health-impact-meter__segment is-${classToken(item.kind)}`}
                key={item.kind}
                style={{ flexGrow: item.value }}
              />
            ))}
        </div>
        <div className="health-count-grid">
          {counts.map((item) => (
            <CountTile {...item} total={total} key={item.kind} />
          ))}
        </div>
      </div>
      <ReportContext report={report} fallbackGatewayUrl={fallbackGatewayUrl} />
    </section>
  )
}

function LoadingRail() {
  // health.js:118-130 — loading strip.
  return (
    <section className="health-status__rail is-loading" aria-label={t('health.railLandmark')}>
      <div className="health-score">
        <span className="health-score__icon" aria-hidden="true">
          <ActivityIcon />
        </span>
        <div className="health-score__copy">
          <span className="health-score__label">{t('health.railReadiness')}</span>
          <strong>{t('health.checking')}</strong>
          <span className="health-score__summary">{t('health.railWaiting')}</span>
        </div>
      </div>
      <div className="health-impact-profile">
        <div className="health-impact-profile__head">
          <span>{t('health.railImpactHead')}</span>
          <strong>{t('health.railImpactRunning')}</strong>
        </div>
        <div className="health-impact-meter is-loading" aria-hidden="true">
          <span />
        </div>
        <div className="health-count-grid">
          <CountTile
            label={t('health.countBlocksReady')}
            value={0}
            kind="blocks_ready"
            total={0}
            loading
          />
          <CountTile
            label={t('health.countDegrades')}
            value={0}
            kind="degrades"
            total={0}
            loading
          />
          <CountTile
            label={t('health.countOptional')}
            value={0}
            kind="optional"
            total={0}
            loading
          />
          <CountTile label={t('health.countNone')} value={0} kind="none" total={0} loading />
        </div>
      </div>
    </section>
  )
}

export function HealthPage() {
  const rpc = useRpc()
  const bootstrap = useBootstrap()

  useEffect(() => {
    document.title = t('health.documentTitle')
  }, [])

  // Simplification (parity matrix): legacy _gatewayContextUrl() read
  // App.loadConnectionSettings(); the new console owns the same effective value
  // via the stored WS override falling back to bootstrap.ws_url. Storage access
  // is guarded like legacy app.js:205 — blocked storage falls back, not throws.
  let storedWsUrl: string | null = null
  try {
    storedWsUrl = localStorage.getItem(WS_URL_KEY)
  } catch {
    /* blocked storage: fall back to bootstrap */
  }
  const gatewayUrl = storedWsUrl || bootstrap.ws_url || ''

  const query = useQuery<HealthReport>({
    queryKey: ['doctor.status', 'main'],
    queryFn: async () => {
      await rpc.waitForConnection()
      const report = await rpc.call<HealthReport>('doctor.status', { agentId: 'main', deep: true })
      if (!report.gatewayUrl) report.gatewayUrl = gatewayUrl
      return report
    },
    // health.js:64-77 — legacy _load issues exactly one deep doctor.status call
    // per view entry and renders the error immediately. Pin the react-query
    // lifecycle to that contract: no retry before the error state, no cached
    // report served across view entries (fresh load + loading strip each time),
    // and no background deep diagnostics on tab focus or network reconnect.
    retry: false,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  // health.js:64-74 — legacy _load resets the view to the loading state at the
  // very top of every (re)load, BEFORE the deep doctor.status call settles:
  // summary → "Checking readiness", rail → is-loading strip, findings →
  // "Loading health report". react-query keeps the previous data/error across a
  // refetch, so gate the whole view on isFetching to reproduce that reset —
  // Refresh (and every fresh view entry) blanks the stale report immediately.
  const showLoading = query.isFetching

  const summaryText = showLoading
    ? t('health.summaryChecking')
    : query.isError
      ? t('health.summaryUnavailable')
      : query.data
        ? query.data.summary || query.data.status || t('health.summaryLoaded')
        : t('health.summaryChecking')

  let railNode
  let findingsNode
  if (showLoading) {
    railNode = <LoadingRail />
    findingsNode = <article className="health-empty">{t('health.findingsLoading')}</article>
  } else if (query.isError) {
    // health.js:86-115 — synthetic gateway.unavailable report + finding.
    // Legacy read the host config path off the inlined bootstrap and, when the
    // gateway URL was the default one, produced --config fix steps from it
    // (health.js:227-238). /api/bootstrap is unauthenticated, so it no longer
    // carries that path: the offline report has no config path to target and
    // falls back to the gateway/bind pair. The live report is unaffected — its
    // configPath comes from the authenticated doctor.status RPC.
    const errorReport: HealthReport = {
      status: 'unavailable',
      ready: false,
      // health.js:92-95 — the rail summary carries the same
      // "Gateway health report unavailable" string legacy set on the synthetic
      // report, so the readiness rail reads a human sentence rather than the raw
      // "unavailable" status token. (The header #health-summary line stays the
      // distinct "Health report unavailable" per health.js:89.)
      summary: t('health.gatewayUnavailableTitle'),
      gatewayUrl,
      configPath: '',
      counts: { error: 1, warn: 0, info: 0, ok: 0 },
      impactCounts: { blocks_ready: 1, degrades: 0, optional: 0, none: 0 },
    }
    const finding: Finding = {
      id: 'gateway.unavailable',
      severity: 'error',
      readinessImpact: 'blocks_ready',
      surface: 'gateway',
      title: t('health.gatewayUnavailableTitle'),
      detail: gatewayUnavailableDetail(gatewayUrl, query.error),
      evidence: { gatewayUrl },
      fixSteps: gatewayUnavailableFixSteps(gatewayUrl, '', false),
      restartRequired: false,
    }
    railNode = <StatusRail report={errorReport} fallbackGatewayUrl={gatewayUrl} />
    findingsNode = <FindingsSection findings={[finding]} />
  } else if (query.data) {
    railNode = <StatusRail report={query.data} fallbackGatewayUrl={gatewayUrl} />
    findingsNode = <FindingsSection findings={query.data.findings || []} />
  } else {
    railNode = <LoadingRail />
    findingsNode = <article className="health-empty">{t('health.findingsLoading')}</article>
  }

  return (
    <div className="health-layout health-stage">
      <header className="health-stage__header">
        <div className="health-stage__title-block">
          <span className="health-eyebrow">{t('health.eyebrow')}</span>
          <h1>{t('health.title')}</h1>
          <p id="health-summary">{summaryText}</p>
        </div>
        <Button
          variant="outline"
          id="health-refresh"
          title={t('health.refreshTitle')}
          className="btn-refresh btn-term"
          disabled={showLoading}
          onClick={() => void query.refetch()}
        >
          <RefreshCwIcon className={showLoading ? 'health-spin' : undefined} />
          <span>{showLoading ? t('health.checking') : t('health.refresh')}</span>
        </Button>
      </header>
      {railNode}
      <section className="health-findings" aria-labelledby="health-findings-title">
        <div className="health-findings__intro">
          <div>
            <span className="health-findings__eyebrow">{t('health.findingsEyebrow')}</span>
            <h2 id="health-findings-title">{t('health.findingsTitle')}</h2>
          </div>
          <p>{t('health.findingsIntro')}</p>
        </div>
        <div className="health-findings__stack">{findingsNode}</div>
      </section>
    </div>
  )
}
