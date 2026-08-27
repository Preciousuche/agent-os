import './skills.css'
import { useCallback, useEffect, useId, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence } from 'motion/react'
import {
  CheckIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  DownloadIcon,
  GlobeIcon,
  PackageIcon,
  RefreshCwIcon,
  SearchIcon,
  TriangleAlertIcon,
  XIcon,
} from 'lucide-react'
import { toast } from 'sonner'
import { MotionListItem } from '@/lib/motion'
import { ModalShell } from '@/components/ModalShell'
import { Button } from '@/components/ui/button'
import { t, tPlural } from '@/i18n'
import '@/i18n/en/skills'
import { useRpc } from '@/app/providers'
import agentosMarkUrl from '@/assets/agentos-mark.png'
import bankrSymbolUrl from '@/assets/bankr-symbol.svg'
import aeonSymbolUrl from '@/assets/aeon-symbol.png'
import capminalSymbolUrl from '@/assets/capminal-symbol.svg'
import gmgnSymbolUrl from '@/assets/gmgn-symbol.png'
import robinhoodSymbolUrl from '@/assets/robinhood-symbol.png'
import {
  catLabel,
  REGISTRY_SEARCH_DEBOUNCE_MS,
  categoryChips,
  communityFilter,
  filterRegistry,
  filterSkills,
  firstUpdateResult,
  groupSkills,
  initials,
  installAction,
  installSource,
  installedEmptyMessage,
  isGmgnSkill,
  isPartnerSkill,
  skillBucketLabel,
  skillBucket,
  layerHelp,
  layerLabel,
  markInstalled,
  mergeRegistryRows,
  registryEmptyMessage,
  registryKey,
  partnerEmptyMessage,
  safeUrl,
  skillAvailabilityLabel,
  skillAvailabilityTitle,
  skillAvailabilityTone,
  skillCanRemove,
  skillCanUpdate,
  skillChatPromptPath,
  skillDotClass,
  skillDotTitle,
  skillGroupKey,
  skillPublisherId,
  skillStats,
  skillStatus,
  skillsByPublisher,
  stillMissingCount,
  type DepsInstallResult,
  type RawSkill,
  type RegistryItem,
  type SkillRequirementItem,
  type SkillRequirements,
  type StatusFilter,
  type UpdateResult,
} from './logic'

// skills.js:7 — the Bankr partner tab is shown; the BankrSource backend stays
// wired either way so Bankr skills remain reachable via Community.
const SHOW_BANKR = true
const SHOW_CAPMINAL = true
const SHOW_AEON = true

type Tab = 'installed' | 'bankr' | 'capminal' | 'aeon' | 'robinhood' | 'community'
type RegistryGroup = 'bankr' | 'capminal' | 'aeon' | 'community'
type PartnerBrand = 'bankr' | 'capminal' | 'aeon' | 'robinhood'
// Drives arrow-key focus movement, so it must stay in lockstep with the order
// the buttons are rendered in below.
const TAB_ORDER: Tab[] = [
  'installed',
  'robinhood',
  ...(SHOW_BANKR ? ['bankr' as const] : []),
  ...(SHOW_AEON ? ['aeon' as const] : []),
  ...(SHOW_CAPMINAL ? ['capminal' as const] : []),
  'community',
]

/**
 * Sources that own a tab, and so must not also show up under Community.
 * Derived from the SHOW_ flags rather than restated, so hiding a partner's tab
 * is one edit and its rows fall back into Community automatically.
 */
const hiddenRegistrySources: ReadonlySet<string> = new Set(
  (
    [SHOW_BANKR ? 'bankr' : '', SHOW_CAPMINAL ? 'capminal' : '', SHOW_AEON ? 'aeon' : ''] as const
  ).filter(Boolean),
)

// The bundled brand artwork stays a client-side asset: a local import is not
// something a SKILL.md could carry. Membership, however, is the payload's call —
// `publisher.id` is resolved against a server-side allowlist.
const PARTNER_BRANDS: Record<PartnerBrand, { label: string; asset: string }> = {
  bankr: { label: 'Bankr', asset: bankrSymbolUrl },
  capminal: { label: 'Capminal', asset: capminalSymbolUrl },
  aeon: { label: 'Aeon', asset: aeonSymbolUrl },
  robinhood: { label: 'Robinhood', asset: robinhoodSymbolUrl },
}

/**
 * Header copy per catalog tab, keyed the same way the tabs are.
 *
 * This is a table rather than a conditional on purpose. `RegistryGroup` has
 * grown past two members, and every place that branched on `group === 'bankr'`
 * quietly filed Capminal under the community copy — the tab said "Partner
 * catalog" while the panel said "Discover skills published by the wider AgentOS
 * community". Adding the next partner should mean adding a row here, not
 * finding four more ternaries.
 *
 * Robinhood is absent: its tab lists installed skills, not a catalog, so it
 * renders its own intro (`ROBINHOOD_INTRO`) rather than going through
 * `RegistryPanel`.
 */
function registryIntro(): Record<
  Exclude<RegistryGroup, 'community'>,
  { title: string; description: string; notice?: string }
> {
  return {
    bankr: {
      title: t('skills.bankrTitle'),
      description: t('skills.bankrDesc'),
      notice: t('skills.bankrNotice'),
    },
    capminal: {
      title: t('skills.capminalTitle'),
      description: t('skills.capminalDesc'),
      notice: t('skills.capminalNotice'),
    },
    aeon: {
      title: t('skills.aeonTitle'),
      description: t('skills.aeonDesc'),
      notice: t('skills.aeonNotice'),
    },
  }
}

/**
 * Header copy for the Robinhood tab. Kept beside `REGISTRY_INTRO` so partner
 * copy lives in one place, even though the panel that renders it lists
 * installed skills instead of a remote catalog.
 *
 * The notice is skill-specific rather than catalog-wide: only
 * `robinhood-agentic-trading` needs the dedicated Agentic account, which
 * Robinhood provisions through its own onboarding flow — the skill cannot
 * create it, so a user who installs and runs it first only finds out when the
 * first tool call fails.
 */
function robinhoodIntro() {
  return {
    title: t('skills.robinhoodTitle'),
    description: t('skills.robinhoodDesc'),
    notice: t('skills.robinhoodNotice'),
  }
}

/** The brand name for a catalog tab's search/loading copy ('community' has none). */
function registryLabel(group: RegistryGroup): string {
  return group === 'community' ? t('skills.registryLabelCommunity') : PARTNER_BRANDS[group].label
}

/**
 * The short provenance label on a card: where the skill actually came from,
 * rather than which directory it happens to load from. A hub install shows the
 * hub it came from, which is the same string the catalog card prints.
 */
function acquisitionSourceLabel(skill: RawSkill): string {
  const acq = skill.acquisition
  if (acq?.kind === 'hub') return acq.source_id || t('skills.srcHub')
  if (acq?.kind === 'shipped') return t('skills.srcShipped')
  if (acq?.kind === 'local') return t('skills.srcLocal')
  // Pre-#130 gateway: fall back to the location layer rather than claim one.
  return layerLabel(skill.layer).toLowerCase()
}

/**
 * `skills.uninstall` deletes `<managed_dir>/<name>` and nothing else, so the
 * gateway reports `removable: false` when the recorded install sits somewhere
 * else (a re-pointed `skills.managed_dir`, or none configured). Its reason
 * string names filesystem paths and is deliberately kept off the wire, so say
 * what the operator has to do instead of rendering a button that half-succeeds.
 */
function removeBlockedNote(): string {
  return t('skills.removeBlockedNote')
}

/**
 * The "installed, but the agent is not being offered it" chip.
 *
 * Renders nothing when the skill IS offered (the status chip already says the
 * skill is fine) and nothing when availability was not computed — an absent
 * block means unknown, never not-offered. The reason is spelled out in text so
 * the state does not depend on the dot colour alone.
 */
function AvailabilityChip({ skill, className }: { skill: RawSkill; className?: string }) {
  if (skillAvailabilityTone(skill) !== 'not-offered') return null
  return (
    <span
      className={`sk-chip sk-chip--withheld${className ? ' ' + className : ''}`}
      title={skillAvailabilityTitle(skill)}
    >
      <span className="sk-chip__dot" aria-hidden="true" />
      {skillAvailabilityLabel(skill)}
    </span>
  )
}

interface SkillsListResponse {
  skills?: RawSkill[]
}
interface SearchResponse {
  results?: RegistryItem[]
}
interface InstallResponse {
  success?: boolean
  name?: string
  message?: string
  scan_verdict?: string
  scan_findings?: unknown[]
}
interface MutationResponse {
  success?: boolean
  message?: string
}

function PartnerLogo({
  brand,
  className,
  decorative = false,
}: {
  brand: PartnerBrand
  className: string
  decorative?: boolean
}) {
  const [broken, setBroken] = useState(false)
  const config = PARTNER_BRANDS[brand]

  if (broken) {
    return (
      <span className={`${className} ${className}--fallback`} aria-hidden="true">
        {config.label.slice(0, 1)}
      </span>
    )
  }

  return (
    <img
      className={className}
      src={config.asset}
      alt={decorative ? '' : `${config.label} logo`}
      width="40"
      height="40"
      onError={() => setBroken(true)}
    />
  )
}

// ── Logo badge (skills.js:643-655) ────────────────────────────────────────────
function LogoBadge({ item, cls }: { item: RegistryItem; cls: string }) {
  const logoUrl = safeUrl(item.logo)
  const [broken, setBroken] = useState(false)
  if (!logoUrl || broken) {
    if (item.source?.toLowerCase() === 'bankr') {
      return <PartnerLogo brand="bankr" className={cls} decorative />
    }
    if (item.source?.toLowerCase() === 'capminal') {
      return <PartnerLogo brand="capminal" className={cls} decorative />
    }
    if (item.source?.toLowerCase() === 'aeon') {
      return <PartnerLogo brand="aeon" className={cls} decorative />
    }
    return <span className={`${cls} ${cls}--initials`}>{initials(item.provider || item.name)}</span>
  }
  return (
    <img
      className={cls}
      src={logoUrl}
      alt=""
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setBroken(true)}
    />
  )
}

// ── Installed skill card (skills.js:447-465) ──────────────────────────────────
/**
 * "Where this came from" for a hub install: the hub, plus the author the
 * catalog credited.
 *
 * A community skill distributed through a partner's hub — a bankr.bot wallet
 * skill, say — is deliberately NOT a partner skill: `publisher.id` never
 * resolves for it, so it lands under "Installed from a hub" with no trace of
 * where it actually came from. This chip restores that trace without restoring
 * the brand. It is plain text on purpose: no partner logo, no partner styling.
 * The author string passed no allowlist, so it must not be able to look like
 * one that did.
 *
 * Renders nothing for shipped and local skills, which have no hub to name.
 */
/**
 * The bundled brand mark for a skill, or `null` when it has no allowlisted one.
 *
 * Keyed off `publisher.id`, which the server resolved against
 * `RECOGNIZED_PUBLISHERS` — the same field the Partners grouping uses, so a card
 * can never wear a logo for a group it is not in. The artwork itself is a local
 * import; nothing a `SKILL.md` carries can reach it.
 */
function partnerBrandOf(skill: RawSkill): PartnerBrand | null {
  const id = skillPublisherId(skill)
  return id in PARTNER_BRANDS ? (id as PartnerBrand) : null
}

/**
 * Avatar for an installed skill: the publisher's mark when it has one.
 *
 * The Installed tab groups by provenance, so a partner skill sat under
 * "Partners" wearing the same generic package glyph as everything else — the
 * catalog tabs showed the brand and the installed list dropped it, which reads
 * as two different skills.
 *
 * Marks resolve most specific first: partner publisher, then the GMGN upstream
 * (mark plus the skill's own emoji), then the AgentOS mark for the rest of the
 * crypto group, then the generic glyph. Every mark is a bundled asset; nothing a
 * SKILL.md carries can point this at a URL.
 */
function SkillIcon({
  skill,
  iconClass,
  brandClass,
}: {
  skill: RawSkill
  iconClass: string
  brandClass: string
}) {
  const brand = partnerBrandOf(skill)
  if (brand) return <PartnerLogo brand={brand} className={brandClass} />
  // The GMGN skills all share one upstream and one mark, so the mark alone would
  // make seven cards identical. The emoji each SKILL.md already declares rides
  // along as a corner badge — a per-skill icon without seven pieces of artwork.
  // It is decorative: the card names the skill right beside it.
  const emoji = (skill.emoji ?? '').trim()
  if (isGmgnSkill(skill)) {
    const mark = (
      <img
        className={brandClass}
        src={gmgnSymbolUrl}
        alt={t('skills.altGmgnLogo')}
        width="40"
        height="40"
      />
    )
    if (!emoji) return mark
    // The wrapper takes its footprint from the mark it holds, so one pair of
    // classes serves both the 2rem card box and the 2.25rem dialog box.
    return (
      <span className="sk-brandmark">
        {mark}
        <span className="sk-brandmark__emoji" aria-hidden="true">
          {emoji}
        </span>
      </span>
    )
  }
  // "AgentOS Crypto Skills" is an AgentOS-authored group by construction:
  // `skillGroupKey` only returns 'crypto' for a shipped/bundled skill, the same
  // trust gate that keeps a hand-dropped directory out of a heading carrying the
  // AgentOS name. Reusing it means a new crypto skill is branded without a
  // frontend edit, and it stays clear of `publisher` — routing through that would
  // move the skill into Partner Skills.
  if (skillGroupKey(skill) === 'crypto') {
    return (
      <img
        className={brandClass}
        src={agentosMarkUrl}
        alt={t('skills.altAgentosLogo')}
        width="40"
        height="40"
      />
    )
  }
  return (
    <span className={iconClass} aria-hidden="true">
      <PackageIcon />
    </span>
  )
}

function OriginChip({ skill }: { skill: RawSkill }) {
  const acq = skill.acquisition
  if (acq?.kind !== 'hub') return null
  const source = acq.source_id || 'hub'
  const author = (acq.author || '').trim()
  // A partner card already names its publisher, so repeating the source id
  // would be the same fact twice; the author credit is the part the brand does
  // not carry. An unbranded hub install has nothing else saying where it came
  // from, so it keeps the source.
  const branded = isPartnerSkill(skill)
  if (branded && !author) return null
  return (
    <span
      className="sk-chip sk-chip--origin"
      title={
        author ? `Installed from ${source}, authored by ${author}` : `Installed from ${source}`
      }
    >
      {branded ? null : source}
      {author ? <span className="sk-chip__author">{branded ? author : ` · ${author}`}</span> : null}
    </span>
  )
}

function SkillCard({
  skill,
  onOpen,
  onUse,
}: {
  skill: RawSkill
  onOpen: () => void
  onUse: () => void
}) {
  const desc = skill.description || ''
  const statusLabel = skillBucketLabel(skillBucket(skill))
  // The card used to be one big <button>. "Use" is a second action, and a
  // button cannot nest inside a button, so the shell splits the same way
  // RegistryCard/PartnerSkillCard already do: an <article> wrapper, a details
  // button covering the body, and an action row. The `Skill <name>` label stays
  // on the details button so it remains the one thing that opens the dialog.
  return (
    <article className="sk-card">
      <button
        type="button"
        className="sk-card__details"
        onClick={onOpen}
        aria-label={t('skills.cardSkillLabel', { name: String(skill.name) })}
        title={skill.name + (desc ? ': ' + desc : '')}
      >
        <div className="sk-card__head">
          <SkillIcon skill={skill} iconClass="sk-card__icon" brandClass="sk-card__brand" />
          <span className="sk-card__name">{skill.name}</span>
          <span className={`sk-card__status ${skillDotClass(skill)}`} title={skillDotTitle(skill)}>
            <span className="sk-card__dot" aria-hidden="true" />
            {statusLabel}
          </span>
        </div>
        <p className="sk-card__desc">{desc}</p>
        {/* The Installed tab groups on provenance now, so the loading layer moves
            to the card — precedence still has to be debuggable at a glance. */}
        <span className="sk-card__meta">
          <span className="sk-chip sk-chip--layer" title={layerHelp(skill.layer)}>
            {layerLabel(skill.layer)}
          </span>
          <OriginChip skill={skill} />
          <AvailabilityChip skill={skill} />
        </span>
      </button>
      <div className="sk-card__foot">
        {/* Still clickable, still out of the a11y tree: the details button above
            already carries the accessible name, so a second focusable "View
            details" here would only duplicate it. */}
        <button
          type="button"
          className="sk-card__foot-link"
          onClick={onOpen}
          tabIndex={-1}
          aria-hidden="true"
        >
          {t('skills.cardViewDetails')}
          <ChevronRightIcon />
        </button>
        <Button type="button" variant="outline" size="sm" onClick={onUse}>
          {t('skills.cardUse')}
        </Button>
      </div>
    </article>
  )
}

// ── Registry card (skills.js:657-678) ─────────────────────────────────────────
function RegistryCard({
  item,
  forceArmed,
  busy,
  onOpen,
  onInstall,
}: {
  item: RegistryItem
  forceArmed: Set<string>
  busy: boolean
  onOpen: () => void
  onInstall: (force: boolean) => void
}) {
  const action = installAction(item, forceArmed)
  // skills.js:659-660 — the category chip only shows for a known, non-'other'
  // category (label from CAT_LABEL, falling back to the raw category key).
  const cat = item.category && item.category !== 'other' ? item.category : ''
  return (
    <article
      className="sk-rcard"
      aria-label={t('skills.catalogSkillLabel', { name: String(item.name) })}
    >
      <button
        type="button"
        className="sk-rcard__details"
        aria-label={t('skills.cardDetailsFor', { name: String(item.name) })}
        onClick={onOpen}
      >
        <div className="sk-rcard__head">
          <LogoBadge item={item} cls="sk-rcard__logo" />
          <div className="sk-rcard__titles">
            <span className="sk-rcard__name">{item.name}</span>
            <span className="sk-rcard__provider">{item.provider || item.source || ''}</span>
          </div>
          {cat ? <span className="sk-rcard__cat">{catLabel(cat)}</span> : null}
        </div>
        <span className="sk-rcard__desc">{item.description || t('skills.cardOpenDetails')}</span>
      </button>
      <div className="sk-rcard__foot">
        <span className="sk-rcard__src sk-mono">{item.source || ''}</span>
        <InstallButton
          action={action}
          busy={busy}
          onInstall={(force, e) => {
            e.stopPropagation()
            onInstall(force)
          }}
        />
      </div>
    </article>
  )
}

function PartnerSkillCard({
  brand,
  skill,
  onOpen,
}: {
  brand: PartnerBrand
  skill: RawSkill
  onOpen: () => void
}) {
  const label = PARTNER_BRANDS[brand].label
  const bucket = skillBucket(skill)
  const statusLabel = skillBucketLabel(bucket)
  const statusClass =
    bucket === 'ready'
      ? 'sk-chip--ok'
      : bucket === 'needs-setup'
        ? 'sk-chip--warn'
        : 'sk-chip--unverified'

  return (
    <article
      className="sk-rcard sk-rcard--partner"
      aria-label={t('skills.partnerSkillLabel', { brand: label, name: String(skill.name) })}
    >
      <button
        type="button"
        className="sk-rcard__details"
        aria-label={t('skills.cardDetailsFor', { name: String(skill.name) })}
        onClick={onOpen}
      >
        <div className="sk-rcard__head">
          <PartnerLogo brand={brand} className="sk-rcard__logo" decorative />
          <div className="sk-rcard__titles">
            <span className="sk-rcard__name">{skill.name}</span>
            <span className="sk-rcard__provider">{label}</span>
          </div>
        </div>
        <span className="sk-rcard__desc">{skill.description || t('skills.cardOpenDetails')}</span>
      </button>
      <div className="sk-rcard__foot">
        {/* Not every partner skill ships with AgentOS — a partner hub install
            reaches this same tab, so the label comes off the payload. */}
        <span className="sk-rcard__src sk-mono">{acquisitionSourceLabel(skill)}</span>
        <AvailabilityChip skill={skill} />
        <span className={`sk-chip ${statusClass}`} title={skillDotTitle(skill)}>
          {bucket === 'ready' ? <CheckIcon aria-hidden="true" /> : null}
          {bucket === 'needs-setup' ? <TriangleAlertIcon aria-hidden="true" /> : null}
          {statusLabel}
        </span>
      </div>
    </article>
  )
}

// ── Install button (skills.js:633-641) — per-item busy, force arming ──────────
function InstallButton({
  action,
  busy,
  large,
  onInstall,
}: {
  action: ReturnType<typeof installAction>
  busy: boolean
  large?: boolean
  onInstall: (force: boolean, e: React.MouseEvent) => void
}) {
  if (action === 'installed')
    return (
      <span className={`sk-chip sk-chip--ok${large ? ' sk-chip--lg' : ' sk-chip--card-action'}`}>
        <CheckIcon aria-hidden="true" />
        {t('skills.installed')}
      </span>
    )
  if (action === 'force') {
    return (
      <Button
        type="button"
        size={large ? 'default' : 'sm'}
        variant="destructive"
        disabled={busy}
        onClick={(e) => onInstall(true, e)}
      >
        {!busy ? <TriangleAlertIcon aria-hidden="true" /> : null}
        {busy ? t('skills.forceInstalling') : t('skills.forceInstall')}
      </Button>
    )
  }
  return (
    <Button
      type="button"
      size={large ? 'default' : 'sm'}
      disabled={busy}
      onClick={(e) => onInstall(false, e)}
    >
      {busy ? t('skills.installing') : large ? t('skills.installSkill') : t('skills.install')}
    </Button>
  )
}

// ── Page ─────────────────────────────────────────────────────────────────────
type Dialog =
  | { kind: 'none' }
  | { kind: 'skill'; name: string }
  // The row is captured on open, not only its key: the list under the dialog is
  // a query result that changes when the search text does, and looking the row
  // up again is what used to unmount an open dialog on a cleared query.
  | { kind: 'registry'; group: RegistryGroup; key: string; item: RegistryItem }

export function SkillsPage() {
  const rpc = useRpc()
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const [tab, setTab] = useState<Tab>('installed')
  const [filterText, setFilterText] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [dialog, setDialog] = useState<Dialog>({ kind: 'none' })
  // Setting a variable without leaving the dialog: the operator is already
  // looking at why the skill is unavailable, and sending them to another
  // screen to fix it loses that context.
  const [envPrompt, setEnvPrompt] = useState<{ skill: string; name: string } | null>(null)
  const [envValue, setEnvValue] = useState('')
  const [envSaving, setEnvSaving] = useState(false)

  // "Use" hands the skill name to chat as a composer prefill rather than running
  // anything here — the same cross-screen hop AgentsPage/SessionsPage make with
  // `?agent=` / `?session=`. Closing the dialog first keeps the modal from
  // lingering over the chat view during the route change.
  const openSkillInChat = useCallback(
    (name: string) => {
      setDialog({ kind: 'none' })
      navigate(skillChatPromptPath(name))
    },
    [navigate],
  )

  // Registry (bankr/community) query text + debounced community query.
  const [bankrQuery, setBankrQuery] = useState('')
  const [capminalQuery, setCapminalQuery] = useState('')
  const [aeonQuery, setAeonQuery] = useState('')
  const [robinhoodQuery, setRobinhoodQuery] = useState('')
  const [communityText, setCommunityText] = useState('')
  const [communityQuery, setCommunityQuery] = useState('')
  const [bankrCat, setBankrCat] = useState('all')
  const [capminalCat, setCapminalCat] = useState('all')
  const [aeonCat, setAeonCat] = useState('all')
  const [robinhoodStatus, setRobinhoodStatus] = useState<StatusFilter>('all')
  const [communityCat, setCommunityCat] = useState('all')
  const [githubUrl, setGithubUrl] = useState('')

  // Force-armed identifiers (skills.js:34) + per-item busy keys.
  const [forceArmed, setForceArmed] = useState<Set<string>>(new Set())
  const [busyKeys, setBusyKeys] = useState<Set<string>>(new Set())

  // Catalog rows installed during this session. The gateway now synthesizes a
  // row for an install no catalog lists, so a refetch alone brings it back —
  // but only once the refetch lands. Merging locally keeps the row on screen
  // from the same tick the install succeeds, and the server's richer row wins
  // as soon as it arrives (mergeRegistryRows lets `base` win a collision).
  const [sessionInstalls, setSessionInstalls] = useState<RegistryItem[]>([])

  useEffect(() => {
    document.title = t('skills.documentTitle')
  }, [])

  // skills.js:210-220 — debounce the community search input (250ms). A cleared
  // input drops the query so the snapshot shows again.
  useEffect(() => {
    const id = setTimeout(
      () => setCommunityQuery(communityText.trim()),
      REGISTRY_SEARCH_DEBOUNCE_MS,
    )
    return () => clearTimeout(id)
  }, [communityText])

  // ── Installed skills (skills.js:325-340) ──────────────────────────────────
  const skillsQuery = useQuery<RawSkill[]>({
    queryKey: ['skills'],
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<SkillsListResponse>('skills.list', {})
      return data.skills ?? []
    },
    refetchOnWindowFocus: false,
  })

  useEffect(() => {
    if (skillsQuery.isError) {
      const err = skillsQuery.error
      toast.error(
        t('skills.toastLoadFailed', {
          message: err instanceof Error ? err.message : String(err),
        }),
        { id: 'skills-load-err' },
      )
    }
  }, [skillsQuery.isError, skillsQuery.error])

  // ── Registry snapshots: skills.search per group on tab entry (skills.js:507) ─
  const bankrSnapshot = useQuery<RegistryItem[]>({
    queryKey: ['skills.search', 'bankr'],
    enabled: SHOW_BANKR && tab === 'bankr',
    refetchOnWindowFocus: false,
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<SearchResponse>('skills.search', {
        query: '',
        limit: 500,
        source: 'bankr',
      })
      return data.results ?? []
    },
  })

  const capminalSnapshot = useQuery<RegistryItem[]>({
    queryKey: ['skills.search', 'capminal'],
    enabled: SHOW_CAPMINAL && tab === 'capminal',
    refetchOnWindowFocus: false,
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<SearchResponse>('skills.search', {
        query: '',
        limit: 500,
        source: 'capminal',
      })
      return data.results ?? []
    },
  })

  const aeonSnapshot = useQuery<RegistryItem[]>({
    queryKey: ['skills.search', 'aeon'],
    enabled: SHOW_AEON && tab === 'aeon',
    refetchOnWindowFocus: false,
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<SearchResponse>('skills.search', {
        query: '',
        limit: 500,
        source: 'aeon',
      })
      return data.results ?? []
    },
  })

  const communitySnapshot = useQuery<RegistryItem[]>({
    queryKey: ['skills.search', 'community'],
    enabled: tab === 'community',
    refetchOnWindowFocus: false,
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<SearchResponse>('skills.search', { query: '', limit: 500 })
      return communityFilter(data.results ?? [], hiddenRegistrySources)
    },
  })

  // skills.js:528-545 — a non-empty community query hits the server (the
  // snapshot only covers each source's first page). Debounced; stale drops are
  // handled by react-query keying the query text.
  const communitySearch = useQuery<RegistryItem[]>({
    queryKey: ['skills.search', 'community', communityQuery],
    enabled: tab === 'community' && communityQuery.length > 0,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      await rpc.waitForConnection()
      const data = await rpc.call<SearchResponse>('skills.search', {
        query: communityQuery,
        limit: 100,
      })
      return communityFilter(data.results ?? [], hiddenRegistrySources)
    },
  })

  const invalidateSkills = () => queryClient.invalidateQueries({ queryKey: ['skills'] })
  const invalidateRegistry = () => queryClient.invalidateQueries({ queryKey: ['skills.search'] })

  // Flip the Installed chip on every cached catalog list before the refetch
  // lands, so it never lags a network round trip behind the button. Lists that
  // hold no data yet are left alone: writing `[]` into a query that is still
  // in flight would resolve it to a "no results" state until the fetch lands.
  const markCached = (identifier: string, name: string, installed: boolean) =>
    queryClient.setQueriesData<RegistryItem[]>({ queryKey: ['skills.search'] }, (old) =>
      old ? markInstalled(old, identifier, name, installed) : old,
    )

  const setBusy = (key: string, on: boolean) =>
    setBusyKeys((prev) => {
      const next = new Set(prev)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })

  const armForce = (key: string, on: boolean) =>
    setForceArmed((prev) => {
      const next = new Set(prev)
      if (on) next.add(key)
      else next.delete(key)
      return next
    })

  // ── Mutations ─────────────────────────────────────────────────────────────
  // skills.js:926-977 — install. Per-item busy; a "dangerous" scan verdict
  // arms an explicit force-install override (not an error).
  const installMutation = useMutation({
    // `item` never reaches the wire — it is the catalog row to keep on screen
    // while the refetch is out. A GitHub install has none, and the gateway's
    // synthesized row covers it on the next fetch.
    mutationFn: (vars: {
      identifier: string
      source: string
      force: boolean
      item?: RegistryItem
    }) =>
      rpc.call<InstallResponse>('skills.install', {
        identifier: vars.identifier,
        source: vars.source,
        force: vars.force,
      }),
    onMutate: (vars) => setBusy(vars.identifier, true),
    onSettled: (_d, _e, vars) => setBusy(vars.identifier, false),
    onSuccess: (res, vars) => {
      if (res?.success) {
        armForce(vars.identifier, false)
        toast.success(t('skills.toastInstalled', { name: res.name || vars.identifier }), {
          id: 'skills-install',
        })
        if (vars.item) {
          const row = { ...vars.item, installed: true }
          setSessionInstalls((prev) => mergeRegistryRows([row], prev))
        }
        markCached(vars.identifier, res.name || '', true)
        void invalidateSkills()
        void invalidateRegistry()
        return
      }
      const blocked = res?.scan_verdict === 'dangerous'
      const n = (res?.scan_findings || []).length
      if (blocked && !vars.force) {
        armForce(vars.identifier, true)
        const name = res?.name || t('skills.toastScanUnnamed')
        toast.error(
          t('skills.toastScanBlocked', {
            target: n ? tPlural('skills.toastScanTarget', n, { name }) : name,
          }),
          { id: 'skills-install-err' },
        )
      } else {
        toast.error(res?.message || t('skills.toastInstallFailed'), { id: 'skills-install-err' })
      }
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : String(err), { id: 'skills-install-err' })
    },
  })

  // skills.js:979-991 — uninstall (managed skills only). Per-item busy.
  const uninstallMutation = useMutation({
    // `identifier` is the lockfile identifier the catalog row is keyed by; it
    // is not sent, it is what lets the Installed chip be un-flipped.
    mutationFn: (vars: { name: string; identifier: string }) =>
      rpc.call<MutationResponse>('skills.uninstall', { name: vars.name }),
    onMutate: (vars) => setBusy('uninstall:' + vars.name, true),
    onSettled: (_d, _e, vars) => setBusy('uninstall:' + vars.name, false),
    onSuccess: (res, vars) => {
      const name = vars.name
      if (res?.success) {
        toast.success(t('skills.toastRemoved', { name }), { id: 'skills-uninstall' })
        setDialog({ kind: 'none' })
        setSessionInstalls((prev) =>
          prev.filter((r) => r.name !== name && registryKey(r) !== vars.identifier),
        )
        markCached(vars.identifier, name, false)
        void invalidateSkills()
        // The catalog's "Installed" chip is derived from the same lockfile the
        // removal just edited, so it is stale until this refetch — install has
        // always invalidated it; removal never did.
        void invalidateRegistry()
      } else {
        toast.error(res?.message || t('skills.toastUninstallFailed'), {
          id: 'skills-uninstall-err',
        })
      }
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : String(err), { id: 'skills-uninstall-err' })
    },
  })

  // skills.js:993-1010 — update (re-pull latest). Per-item busy. skills.update
  // returns a results[] array.
  const updateMutation = useMutation({
    mutationFn: (name: string) => rpc.call<UpdateResult>('skills.update', { name }),
    onMutate: (name) => setBusy('update:' + name, true),
    onSettled: (_d, _e, name) => setBusy('update:' + name, false),
    onSuccess: (res, name) => {
      const result = firstUpdateResult(res)
      if (result.success) {
        toast.success(result.message || t('skills.toastUpdated', { name }), {
          id: 'skills-update',
        })
        void invalidateSkills()
      } else {
        toast.error(result.message || res?.message || t('skills.toastUpdateFailed'), {
          id: 'skills-update-err',
        })
      }
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : String(err), { id: 'skills-update-err' })
    },
  })

  // skills.js:879-908 — install a skill's declared dependency (deps.install).
  // Closes the dialog + reloads once nothing is still missing.
  const depsMutation = useMutation({
    mutationFn: (vars: { name: string; installId: string }) =>
      rpc.call<DepsInstallResult>('skills.deps.install', {
        name: vars.name,
        install_id: vars.installId,
      }),
    onMutate: (vars) => setBusy('deps:' + vars.name + ':' + vars.installId, true),
    onSettled: (_d, _e, vars) => setBusy('deps:' + vars.name + ':' + vars.installId, false),
    onSuccess: (res) => {
      if (res?.success) {
        toast.success(res.message || t('skills.toastDepsInstalled'), { id: 'skills-deps' })
        if (stillMissingCount(res) === 0) setDialog({ kind: 'none' })
      } else {
        toast.error(res?.message || t('skills.toastInstallFailed'), { id: 'skills-deps-err' })
      }
      void invalidateSkills()
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : String(err), { id: 'skills-deps-err' })
    },
  })

  // ── Derivations ───────────────────────────────────────────────────────────
  const allSkills = skillsQuery.data ?? []
  const stats = skillStats(allSkills)
  const filtered = filterSkills(allSkills, filterText, statusFilter)
  const groups = groupSkills(filtered)
  const rhSkills = skillsByPublisher(allSkills, 'robinhood')

  const runInstall = (item: RegistryItem, force: boolean) =>
    installMutation.mutate({
      identifier: registryKey(item),
      source: installSource(item),
      force,
      item,
    })

  // ── Catalog lists ─────────────────────────────────────────────────────────
  // A live query answers a question the snapshot cannot (the snapshot is only
  // each source's first page), so it still supersedes the snapshot as the base
  // list. What is new is that the browse list is a MERGE, not a swap: a row
  // installed while searching survives the search being cleared.
  const bankrRows = useMemo(
    () =>
      mergeRegistryRows(
        bankrSnapshot.data ?? [],
        sessionInstalls.filter((r) => r.source === 'bankr'),
      ),
    [bankrSnapshot.data, sessionInstalls],
  )

  const aeonRows = useMemo(
    () =>
      mergeRegistryRows(
        aeonSnapshot.data ?? [],
        sessionInstalls.filter((r) => r.source === 'aeon'),
      ),
    [aeonSnapshot.data, sessionInstalls],
  )

  const capminalRows = useMemo(
    () =>
      mergeRegistryRows(
        capminalSnapshot.data ?? [],
        sessionInstalls.filter((r) => r.source === 'capminal'),
      ),
    [capminalSnapshot.data, sessionInstalls],
  )

  const communityLive = communityQuery ? communitySearch.data : undefined
  const communityBrowse = useMemo(
    () =>
      mergeRegistryRows(
        communitySnapshot.data ?? [],
        communityFilter(sessionInstalls, hiddenRegistrySources),
      ),
    [communitySnapshot.data, sessionInstalls],
  )
  const communityRows = communityLive ?? communityBrowse

  // The rows on screen are the server's own answer only once the committed
  // query has caught up with the input and the response has landed; until then
  // the client text pass still narrows the stale list optimistically.
  const communityServerFiltered = Boolean(communityLive) && communityText.trim() === communityQuery

  // A failed live search used to fall through to the snapshot's error state,
  // which is empty — so a search that errored rendered as "no results".
  const communityError =
    communityQuery && communitySearch.isError
      ? String(communitySearch.error)
      : communitySnapshot.isError
        ? String(communitySnapshot.error)
        : ''

  /**
   * The row behind an open registry dialog. Prefers the live lists so the
   * Installed chip inside the dialog stays current, and falls back to the row
   * captured when the dialog opened — clearing the search swaps the list out
   * from under it, and the dialog must not vanish because of that.
   */
  const registryItemFor = (d: Extract<Dialog, { kind: 'registry' }>): RegistryItem => {
    const pools =
      d.group === 'bankr'
        ? [bankrRows]
        : d.group === 'capminal'
          ? [capminalRows]
          : d.group === 'aeon'
            ? [aeonRows]
            : [communityRows, communityBrowse, communitySearch.data]
    for (const pool of pools) {
      const hit = (pool ?? []).find((r) => registryKey(r) === d.key)
      if (hit) return hit
    }
    return d.item
  }

  const refresh = () => {
    if (tab === 'bankr') void bankrSnapshot.refetch()
    else if (tab === 'capminal') void capminalSnapshot.refetch()
    else if (tab === 'aeon') void aeonSnapshot.refetch()
    else if (tab === 'community') {
      void communitySnapshot.refetch()
      if (communityQuery) void communitySearch.refetch()
    } else void invalidateSkills()
  }

  return (
    <div className="sk-stage">
      <header className="sk-stage__header">
        <div className="sk-stage__title-block">
          <h1 className="t-display">{t('skills.title')}</h1>
          <p className="sk-stage__subtitle">{t('skills.subtitle')}</p>
        </div>
        <div className="sk-stage__actions">
          <Button
            variant="outline"
            title={t('skills.refresh')}
            className="sk-refresh"
            onClick={refresh}
          >
            <RefreshCwIcon />
            <span>{t('skills.refresh')}</span>
          </Button>
        </div>
      </header>

      {/* Tabs (skills.js:107-112) */}
      <nav className="sk-source-nav" aria-label={t('skills.tabsLandmark')}>
        <div className="sk-tabs" role="tablist" aria-label={t('skills.tabsLandmark')}>
          <TabButton
            current={tab}
            tab="installed"
            label={t('skills.tabInstalled')}
            description={t('skills.tabInstalledDesc', { count: stats.total })}
            icon={<PackageIcon aria-hidden="true" />}
            onSelect={setTab}
          />
          <TabButton
            current={tab}
            tab="robinhood"
            label={PARTNER_BRANDS.robinhood.label}
            description={t('skills.tabRobinhoodDesc')}
            icon={<PartnerLogo brand="robinhood" className="sk-tab__brand" decorative />}
            onSelect={setTab}
          />
          {SHOW_BANKR ? (
            <TabButton
              current={tab}
              tab="bankr"
              label={PARTNER_BRANDS.bankr.label}
              description={t('skills.tabPartnerDesc')}
              icon={<PartnerLogo brand="bankr" className="sk-tab__brand" decorative />}
              onSelect={setTab}
            />
          ) : null}
          {SHOW_AEON ? (
            <TabButton
              current={tab}
              tab="aeon"
              label={PARTNER_BRANDS.aeon.label}
              description={t('skills.tabPartnerDesc')}
              icon={<PartnerLogo brand="aeon" className="sk-tab__brand" decorative />}
              onSelect={setTab}
            />
          ) : null}
          {SHOW_CAPMINAL ? (
            <TabButton
              current={tab}
              tab="capminal"
              label={PARTNER_BRANDS.capminal.label}
              description={t('skills.tabPartnerDesc')}
              icon={<PartnerLogo brand="capminal" className="sk-tab__brand" decorative />}
              onSelect={setTab}
            />
          ) : null}
          <TabButton
            current={tab}
            tab="community"
            label={t('skills.tabCommunity')}
            description={t('skills.tabCommunityDesc')}
            icon={<GlobeIcon aria-hidden="true" />}
            onSelect={setTab}
          />
        </div>
      </nav>

      {tab === 'installed' ? (
        <div className="sk-library-tools">
          <div className="sk-search-wrap sk-search-wrap--library">
            <SearchIcon className="sk-search-icon" aria-hidden="true" />
            <input
              type="search"
              className="sk-search-input sk-search-input--library"
              placeholder={t('skills.searchPlaceholder')}
              aria-label={t('skills.searchLabel')}
              autoComplete="off"
              value={filterText}
              onChange={(e) => setFilterText(e.target.value)}
            />
          </div>
          {/* Metric pills → status filter (skills.js:342-367) */}
          <section className="sk-metrics" aria-label={t('skills.metricsLandmark')}>
            <MetricPill
              label={t('skills.metricAll')}
              value={stats.total}
              tone="accent"
              active={statusFilter === 'all'}
              onClick={() => setStatusFilter('all')}
            />
            <MetricPill
              label={t('skills.metricReady')}
              value={stats.ready}
              tone="ok"
              active={statusFilter === 'ready'}
              onClick={() => setStatusFilter('ready')}
            />
            <MetricPill
              label={t('skills.metricNeedsSetup')}
              value={stats.needs}
              tone="warn"
              active={statusFilter === 'needs-setup'}
              onClick={() => setStatusFilter('needs-setup')}
            />
            {/* Only when there is something to show: an operator who has
                disabled nothing should not be offered a permanently empty
                filter next to the ones that matter. */}
            {stats.disabled > 0 || statusFilter === 'disabled' ? (
              <MetricPill
                label={t('skills.metricDisabled')}
                value={stats.disabled}
                active={statusFilter === 'disabled'}
                onClick={() => setStatusFilter('disabled')}
              />
            ) : null}
          </section>
        </div>
      ) : null}

      {tab === 'installed' ? (
        <InstalledPanel
          loading={skillsQuery.isLoading}
          error={skillsQuery.isError ? String(skillsQuery.error) : ''}
          groups={groups}
          empty={filtered.length === 0}
          emptyMessage={installedEmptyMessage(filterText, statusFilter)}
          onOpen={(name) => setDialog({ kind: 'skill', name })}
          onUse={openSkillInChat}
        />
      ) : null}

      {SHOW_BANKR && tab === 'bankr' ? (
        <RegistryPanel
          group="bankr"
          snapshot={bankrRows}
          loading={bankrSnapshot.isLoading}
          error={bankrSnapshot.isError ? String(bankrSnapshot.error) : ''}
          query={bankrQuery}
          onQuery={setBankrQuery}
          category={bankrCat}
          onCategory={setBankrCat}
          forceArmed={forceArmed}
          busyKeys={busyKeys}
          onOpen={(item) =>
            setDialog({ kind: 'registry', group: 'bankr', key: registryKey(item), item })
          }
          onInstall={runInstall}
        />
      ) : null}

      {SHOW_CAPMINAL && tab === 'capminal' ? (
        <RegistryPanel
          group="capminal"
          snapshot={capminalSnapshot.data ?? []}
          loading={capminalSnapshot.isLoading}
          error={capminalSnapshot.isError ? String(capminalSnapshot.error) : ''}
          query={capminalQuery}
          onQuery={setCapminalQuery}
          category={capminalCat}
          onCategory={setCapminalCat}
          forceArmed={forceArmed}
          busyKeys={busyKeys}
          onOpen={(item) =>
            setDialog({ kind: 'registry', group: 'capminal', key: registryKey(item), item })
          }
          onInstall={runInstall}
        />
      ) : null}

      {SHOW_AEON && tab === 'aeon' ? (
        <RegistryPanel
          group="aeon"
          snapshot={aeonSnapshot.data ?? []}
          loading={aeonSnapshot.isLoading}
          error={aeonSnapshot.isError ? String(aeonSnapshot.error) : ''}
          query={aeonQuery}
          onQuery={setAeonQuery}
          category={aeonCat}
          onCategory={setAeonCat}
          forceArmed={forceArmed}
          busyKeys={busyKeys}
          onOpen={(item) =>
            setDialog({ kind: 'registry', group: 'aeon', key: registryKey(item), item })
          }
          onInstall={runInstall}
        />
      ) : null}

      {tab === 'robinhood' ? (
        <RobinhoodPanel
          skills={rhSkills}
          loading={skillsQuery.isLoading}
          error={skillsQuery.isError ? String(skillsQuery.error) : ''}
          query={robinhoodQuery}
          onQuery={setRobinhoodQuery}
          statusFilter={robinhoodStatus}
          onStatusFilter={setRobinhoodStatus}
          onOpen={(name) => setDialog({ kind: 'skill', name })}
        />
      ) : null}

      {tab === 'community' ? (
        <>
          <section className="sk-github-install" aria-labelledby="sk-github-title">
            <div className="sk-github-install__intro">
              <span className="sk-github-install__icon" aria-hidden="true">
                <DownloadIcon />
              </span>
              <div>
                <h2 id="sk-github-title">{t('skills.githubTitle')}</h2>
                <p>{t('skills.githubDesc')}</p>
              </div>
            </div>
            <div className="sk-github-install__controls">
              <div className="sk-search-wrap sk-search-wrap--lg">
                <input
                  type="url"
                  className="sk-search-input sk-search-input--lg"
                  placeholder={t('skills.githubPlaceholder')}
                  aria-label={t('skills.githubUrlLabel')}
                  autoComplete="off"
                  value={githubUrl}
                  onChange={(e) => setGithubUrl(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && githubUrl.trim()) {
                      installMutation.mutate({
                        identifier: githubUrl.trim(),
                        source: 'github',
                        force: false,
                      })
                    }
                  }}
                />
              </div>
              <Button
                disabled={!githubUrl.trim()}
                onClick={() => {
                  if (githubUrl.trim())
                    installMutation.mutate({
                      identifier: githubUrl.trim(),
                      source: 'github',
                      force: false,
                    })
                }}
              >
                {t('skills.githubInstall')}
              </Button>
            </div>
          </section>
          <RegistryPanel
            group="community"
            snapshot={communityRows}
            chipSnapshot={communityBrowse}
            serverFiltered={communityServerFiltered}
            loading={communityQuery ? communitySearch.isLoading : communitySnapshot.isLoading}
            error={communityError}
            query={communityText}
            onQuery={setCommunityText}
            category={communityCat}
            onCategory={setCommunityCat}
            forceArmed={forceArmed}
            busyKeys={busyKeys}
            onOpen={(item) =>
              setDialog({ kind: 'registry', group: 'community', key: registryKey(item), item })
            }
            onInstall={runInstall}
          />
        </>
      ) : null}

      <AnimatePresence>
        {dialog.kind === 'skill'
          ? (() => {
              const skill = allSkills.find((s) => s.name === dialog.name)
              if (!skill) return null
              return (
                <SkillDialog
                  skill={skill}
                  busyKeys={busyKeys}
                  onClose={() => setDialog({ kind: 'none' })}
                  onUpdate={() => updateMutation.mutate(skill.name!)}
                  onRemove={() =>
                    uninstallMutation.mutate({
                      name: skill.name!,
                      identifier: skill.acquisition?.identifier || '',
                    })
                  }
                  onInstallDeps={(installId) =>
                    depsMutation.mutate({ name: skill.name!, installId })
                  }
                  onSetEnv={(name) => setEnvPrompt({ skill: skill.name!, name })}
                  onUse={() => openSkillInChat(skill.name!)}
                />
              )
            })()
          : null}

        {envPrompt ? (
          <SetEnvDialog
            name={envPrompt.name}
            value={envValue}
            saving={envSaving}
            onChange={setEnvValue}
            onClose={() => {
              setEnvPrompt(null)
              setEnvValue('')
            }}
            onSubmit={async () => {
              setEnvSaving(true)
              try {
                await rpc.call('env.set', { name: envPrompt.name, value: envValue })
                await queryClient.invalidateQueries({ queryKey: ['skills'] })
                toast.success(t('skills.toastEnvSaved', { name: envPrompt.name }))
                setEnvPrompt(null)
                setEnvValue('')
              } catch (error) {
                toast.error(error instanceof Error ? error.message : String(error))
              } finally {
                setEnvSaving(false)
              }
            }}
          />
        ) : null}

        {dialog.kind === 'registry'
          ? (() => {
              const item = registryItemFor(dialog)
              return (
                <RegistryDialog
                  item={item}
                  forceArmed={forceArmed}
                  busy={busyKeys.has(registryKey(item))}
                  onClose={() => setDialog({ kind: 'none' })}
                  onInstall={(force) => runInstall(item, force)}
                />
              )
            })()
          : null}
      </AnimatePresence>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function MetricPill({
  label,
  value,
  tone,
  active,
  onClick,
}: {
  label: string
  value: number
  tone?: 'accent' | 'ok' | 'warn'
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className={`sk-metric${tone ? ' sk-metric--' + tone : ''}${active ? ' is-active' : ''}`}
      title={`Filter: ${label}`}
      aria-label={`Filter: ${label}`}
      aria-pressed={active}
      onClick={onClick}
    >
      <span className="sk-metric__value">{value}</span>
      <span className="sk-metric__label">{label}</span>
    </button>
  )
}

function TabButton({
  current,
  tab,
  label,
  description,
  icon,
  onSelect,
}: {
  current: Tab
  tab: Tab
  label: string
  description: string
  icon: React.ReactNode
  onSelect: (t: Tab) => void
}) {
  const active = current === tab
  const moveFocus = (next: Tab) => {
    onSelect(next)
    document.getElementById(`sk-tab-${next}`)?.focus()
  }
  return (
    <button
      type="button"
      className={`sk-tab${active ? ' is-active' : ''}`}
      id={`sk-tab-${tab}`}
      role="tab"
      aria-label={label}
      aria-selected={active}
      aria-controls={`sk-panel-${tab}`}
      tabIndex={active ? 0 : -1}
      onClick={() => onSelect(tab)}
      onKeyDown={(event) => {
        const index = TAB_ORDER.indexOf(tab)
        if (event.key === 'Home') {
          event.preventDefault()
          moveFocus(TAB_ORDER[0]!)
        } else if (event.key === 'End') {
          event.preventDefault()
          moveFocus(TAB_ORDER[TAB_ORDER.length - 1]!)
        } else if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
          event.preventDefault()
          const offset = event.key === 'ArrowRight' ? 1 : -1
          moveFocus(TAB_ORDER[(index + offset + TAB_ORDER.length) % TAB_ORDER.length]!)
        }
      }}
    >
      <span className="sk-tab__icon">{icon}</span>
      <span className="sk-tab__copy">
        <span className="sk-tab__label">{label}</span>
        <span className="sk-tab__description">{description}</span>
      </span>
    </button>
  )
}

function InstalledPanel({
  loading,
  error,
  groups,
  empty,
  emptyMessage,
  onOpen,
  onUse,
}: {
  loading: boolean
  error: string
  groups: ReturnType<typeof groupSkills>
  empty: boolean
  emptyMessage: string
  onOpen: (name: string) => void
  onUse: (name: string) => void
}) {
  if (error)
    return (
      <div id="sk-panel-installed" role="tabpanel" className="sk-error">
        {t('skills.installedLoadFailed', { error })}
      </div>
    )
  if (loading) return <SkillsSkeleton label={t('skills.loadingInstalled')} />
  if (empty)
    return (
      <div id="sk-panel-installed" role="tabpanel" className="sk-empty__state">
        {emptyMessage}
      </div>
    )
  return (
    <div
      id="sk-panel-installed"
      role="tabpanel"
      aria-labelledby="sk-tab-installed"
      className="sk-panel"
    >
      {groups.map((g) => (
        <details key={g.key} className="sk-group" open>
          <summary className="sk-group__head">
            <ChevronDownIcon className="sk-group__caret" aria-hidden="true" />
            <h2 className="sk-group__label">{g.label}</h2>
            <span className="sk-group__count">{g.skills.length}</span>
            <span className="sk-group__meta">{g.help}</span>
          </summary>
          <div className="sk-grid">
            <AnimatePresence initial={false}>
              {g.skills.map((s) => (
                <MotionListItem key={s.name}>
                  <SkillCard
                    skill={s}
                    onOpen={() => onOpen(s.name!)}
                    onUse={() => onUse(s.name!)}
                  />
                </MotionListItem>
              ))}
            </AnimatePresence>
          </div>
        </details>
      ))}
    </div>
  )
}

function SkillsSkeleton({ label }: { label: string }) {
  return (
    <div className="sk-skeleton" role="status" aria-label={label}>
      {Array.from({ length: 6 }, (_, index) => (
        <span key={index} className="sk-skeleton__card" aria-hidden="true">
          <span className="sk-skeleton__line sk-skeleton__line--title" />
          <span className="sk-skeleton__line" />
          <span className="sk-skeleton__line sk-skeleton__line--short" />
        </span>
      ))}
    </div>
  )
}

function PartnerIntro({
  brand,
  title,
  description,
  notice,
  count,
}: {
  brand: PartnerBrand
  title: string
  description: string
  /** Prerequisite the whole catalog depends on. Rendered as an alert so it is
   *  read before the user installs anything it applies to. */
  notice?: string
  count?: number
}) {
  return (
    <div className={`sk-partner sk-partner--${brand}`}>
      <PartnerLogo brand={brand} className="sk-partner__logo" decorative />
      <div className="sk-partner__copy">
        <h2>{title}</h2>
        <p>{description}</p>
        {notice ? (
          <p className="sk-partner__notice" role="note">
            <TriangleAlertIcon size={13} aria-hidden="true" />
            <span>
              <strong>{t('skills.importantPrefix')}</strong> {notice}
            </span>
          </p>
        ) : null}
      </div>
      {typeof count === 'number' ? (
        <span className="sk-partner__count">
          <strong>{count}</strong> {count === 1 ? t('skills.skillWord') : t('skills.skillsWord')}
        </span>
      ) : null}
    </div>
  )
}

function RobinhoodPanel({
  skills,
  loading,
  error,
  query,
  onQuery,
  statusFilter,
  onStatusFilter,
  onOpen,
}: {
  skills: RawSkill[]
  loading: boolean
  error: string
  query: string
  onQuery: (query: string) => void
  statusFilter: StatusFilter
  onStatusFilter: (status: StatusFilter) => void
  onOpen: (name: string) => void
}) {
  const stats = skillStats(skills)
  const filtered = filterSkills(skills, query.trim(), statusFilter)
  const filters = [
    { key: 'all' as const, label: t('skills.metricAll'), count: stats.total },
    { key: 'ready' as const, label: t('skills.metricReady'), count: stats.ready },
    { key: 'needs-setup' as const, label: t('skills.metricNeedsSetup'), count: stats.needs },
    { key: 'disabled' as const, label: t('skills.metricDisabled'), count: stats.disabled },
  ].filter((item) => item.key === 'all' || item.count > 0 || item.key === statusFilter)

  return (
    <div
      id="sk-panel-robinhood"
      role="tabpanel"
      aria-labelledby="sk-tab-robinhood"
      className="sk-panel sk-panel--source"
    >
      <PartnerIntro
        brand="robinhood"
        title={robinhoodIntro().title}
        description={robinhoodIntro().description}
        notice={robinhoodIntro().notice}
        count={skills.length}
      />
      <div className="sk-browse__bar">
        <div className="sk-search-wrap sk-search-wrap--lg">
          <SearchIcon className="sk-search-icon" aria-hidden="true" />
          <input
            type="search"
            className="sk-search-input sk-search-input--lg"
            placeholder={t('skills.registrySearchPlaceholder', {
              label: PARTNER_BRANDS.robinhood.label,
            })}
            aria-label={t('skills.registrySearchLabel', {
              label: PARTNER_BRANDS.robinhood.label,
            })}
            autoComplete="off"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
          />
        </div>
      </div>
      {filters.length > 1 ? (
        <div className="sk-chips" aria-label={t('skills.robinhoodStatusLandmark')}>
          {filters.map((filter) => (
            <button
              key={filter.key}
              type="button"
              className={`sk-chip-btn${statusFilter === filter.key ? ' is-active' : ''}`}
              aria-label={t('skills.robinhoodFilterLabel', { label: filter.label })}
              aria-pressed={statusFilter === filter.key}
              onClick={() => onStatusFilter(filter.key)}
            >
              {filter.label} <span className="sk-chip-btn__count">{filter.count}</span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="sk-browse__results">
        {error ? (
          <div className="sk-error">
            {t('skills.loadFailed', { error })}
            <br />
            <span className="sk-dim">{t('skills.retryHintRobinhood')}</span>
          </div>
        ) : loading ? (
          <SkillsSkeleton label={t('skills.loadingRobinhood')} />
        ) : filtered.length === 0 ? (
          <div className="sk-registry__hint">
            {partnerEmptyMessage(PARTNER_BRANDS.robinhood.label, query, statusFilter)}
          </div>
        ) : (
          <div className="sk-grid sk-grid--registry">
            <AnimatePresence initial={false}>
              {filtered.map((skill) => (
                <MotionListItem key={skill.name}>
                  <PartnerSkillCard
                    brand="robinhood"
                    skill={skill}
                    onOpen={() => onOpen(skill.name!)}
                  />
                </MotionListItem>
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  )
}

function RegistryPanel({
  group,
  snapshot,
  chipSnapshot,
  serverFiltered,
  loading,
  error,
  query,
  onQuery,
  category,
  onCategory,
  forceArmed,
  busyKeys,
  onOpen,
  onInstall,
}: {
  group: RegistryGroup
  snapshot: RegistryItem[]
  chipSnapshot?: RegistryItem[]
  serverFiltered?: boolean
  loading: boolean
  error: string
  query: string
  onQuery: (q: string) => void
  category: string
  onCategory: (c: string) => void
  forceArmed: Set<string>
  busyKeys: Set<string>
  onOpen: (item: RegistryItem) => void
  onInstall: (item: RegistryItem, force: boolean) => void
}) {
  // skills.js:567 — chips derive from the FULL snapshot only.
  const chips = useMemo(
    () => categoryChips(chipSnapshot ?? snapshot, category),
    [chipSnapshot, snapshot, category],
  )
  // skills.js:610-620 — apply category then text filter. The text pass is
  // skipped once these rows ARE the server's answer to the query: the server
  // also matches on tags, which never reach the client, so re-filtering there
  // can only drop real hits.
  const items = useMemo(
    () => filterRegistry(snapshot, category, query, { serverFiltered }),
    [snapshot, category, query, serverFiltered],
  )

  return (
    <div
      id={`sk-panel-${group}`}
      role="tabpanel"
      aria-labelledby={`sk-tab-${group}`}
      className={`sk-panel sk-panel--source sk-panel--${group}`}
    >
      {group !== 'community' ? (
        <PartnerIntro brand={group} {...registryIntro()[group]} count={snapshot.length} />
      ) : (
        <div className="sk-community-intro">
          <span className="sk-community-intro__icon" aria-hidden="true">
            <GlobeIcon />
          </span>
          <div>
            <h2>{t('skills.communityTitle')}</h2>
            <p>{t('skills.communityDesc')}</p>
          </div>
        </div>
      )}
      <div className="sk-browse__bar">
        <div className="sk-search-wrap sk-search-wrap--lg">
          <SearchIcon className="sk-search-icon" aria-hidden="true" />
          <input
            type="search"
            className="sk-search-input sk-search-input--lg"
            placeholder={t('skills.registrySearchPlaceholder', { label: registryLabel(group) })}
            aria-label={t('skills.registrySearchLabel', { label: registryLabel(group) })}
            autoComplete="off"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
          />
        </div>
      </div>
      {chips.length ? (
        <div className="sk-chips">
          {chips.map((c) => (
            <button
              key={c.cat}
              type="button"
              className={`sk-chip-btn${c.active ? ' is-active' : ''}`}
              onClick={() => onCategory(c.cat)}
            >
              {c.label} <span className="sk-chip-btn__count">{c.count}</span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="sk-browse__results">
        {error ? (
          <div className="sk-error">
            {t('skills.loadFailed', { error })}
            <br />
            <span className="sk-dim">{t('skills.retryHintCommunity')}</span>
          </div>
        ) : loading ? (
          <SkillsSkeleton label={t('skills.loadingCatalog', { label: registryLabel(group) })} />
        ) : items.length === 0 ? (
          <div className="sk-registry__hint">{registryEmptyMessage(group, query)}</div>
        ) : (
          <div className="sk-grid sk-grid--registry">
            <AnimatePresence initial={false}>
              {items.map((r) => (
                <MotionListItem key={registryKey(r)}>
                  <RegistryCard
                    item={r}
                    forceArmed={forceArmed}
                    busy={busyKeys.has(registryKey(r))}
                    onOpen={() => onOpen(r)}
                    onInstall={(force) => onInstall(r, force)}
                  />
                </MotionListItem>
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Requirements section (skills.js:743-777) ──────────────────────────────────
// Per-requirement name + status chip + missing/requires detail. Renders nothing
// when there are no requirement items.
function reqStatusLabel(status: string): string {
  if (status === 'ready') return t('skills.reqReady')
  if (status === 'needs_setup') return t('skills.reqNeedsSetup')
  if (status === 'missing_skill') return t('skills.reqMissingSkill')
  return t('skills.reqNotDeclared')
}

function reqStatusClass(status: string): string {
  if (status === 'ready') return 'sk-chip--ok'
  if (status === 'needs_setup' || status === 'missing_skill') return 'sk-chip--warn'
  return 'sk-chip--unverified'
}

function RequirementRow({ item }: { item: SkillRequirementItem }) {
  // skills.js:747-749 — missing bins + env, each rendered as <code>.
  const missing = [...(item.missing_bins || []), ...(item.missing_env || [])]
  // skills.js:750-755 — declared requirements as plain text fragments.
  const requires: string[] = [...(item.requires_bins || [])]
  if ((item.requires_any_bins || []).length) {
    requires.push(t('skills.reqOneOf', { list: (item.requires_any_bins || []).join(' / ') }))
  }
  ;(item.requires_env || []).forEach((e) => requires.push(t('skills.reqEnv', { name: e })))
  const status = item.status || 'not_declared'

  // skills.js:764-766 — detail prefers the missing codes, else the requires
  // text, else a fallback string.
  let detail: React.ReactNode
  if (missing.length) {
    detail = (
      <>
        {t('skills.reqMissingLead')}{' '}
        {missing.map((m, i) => (
          <span key={m}>
            {i > 0 ? ', ' : ''}
            <code>{m}</code>
          </span>
        ))}
      </>
    )
  } else if (requires.length) {
    detail = requires.join(', ')
  } else {
    detail = t('skills.reqNoDeps')
  }

  return (
    <div className="sk-dialog__req-row">
      <span className="sk-dialog__req-name">{item.name || t('skills.reqUnknown')}</span>
      <span className={`sk-chip ${reqStatusClass(status)}`}>{reqStatusLabel(status)}</span>
      <span className="sk-dialog__req-detail">{detail}</span>
    </div>
  )
}

function RequirementsSection({ requirements }: { requirements?: SkillRequirements }) {
  const items = Array.isArray(requirements?.items) ? requirements.items : []
  if (!items.length) return null
  return (
    <div className="sk-dialog__section">
      <div className="sk-dialog__section-title">{t('skills.reqTitle')}</div>
      <div className="sk-dialog__requirements">
        {items.map((item, i) => (
          <RequirementRow key={item.name || i} item={item} />
        ))}
      </div>
    </div>
  )
}

// ── Installed skill detail dialog (skills.js:779-864) ─────────────────────────
function SkillDialog({
  skill,
  busyKeys,
  onClose,
  onUpdate,
  onRemove,
  onInstallDeps,
  onSetEnv,
  onUse,
}: {
  skill: RawSkill
  busyKeys: Set<string>
  onClose: () => void
  onUpdate: () => void
  onRemove: () => void
  onInstallDeps: (installId: string) => void
  onSetEnv: (name: string) => void
  onUse: () => void
}) {
  const titleId = useId()
  const status = skillStatus(skill)
  const bucket = skillBucket(skill)
  const canUpdate = skillCanUpdate(skill)
  const canRemove = skillCanRemove(skill)
  const removeBlocked = skill.acquisition?.kind === 'hub' && !canRemove
  const availabilityDetail =
    skillAvailabilityTone(skill) === 'not-offered' ? skillAvailabilityTitle(skill) : ''
  const hasMissingBins = (skill.missing_bins || []).length > 0
  const installs = hasMissingBins ? skill.install || [] : []
  const homepage = safeUrl(skill.homepage)
  const updateBusy = busyKeys.has('update:' + skill.name)
  const removeBusy = busyKeys.has('uninstall:' + skill.name)

  // skills.js:792-803 — the Missing bins/env list only shows for needs_setup.
  const missingBins = status === 'needs_setup' ? skill.missing_bins || [] : []
  const missingEnv = status === 'needs_setup' ? skill.missing_env || [] : []
  const hasMissing = missingBins.length > 0 || missingEnv.length > 0

  return (
    <ModalShell
      role="dialog"
      labelledBy={titleId}
      onClose={onClose}
      overlayClassName="sk-modal__overlay"
      className="sk-modal panel"
    >
      <header className="sk-dialog__head">
        <div className="sk-dialog__head-left">
          <SkillIcon
            skill={skill}
            iconClass="sk-dialog__skill-icon"
            brandClass="sk-dialog__brand"
          />
          <h2 id={titleId} className="sk-dialog__name">
            {skill.name}
          </h2>
          <div className="sk-dialog__chips">
            <span className="sk-chip" title={layerHelp(skill.layer)}>
              {layerLabel(skill.layer)}
            </span>
            <OriginChip skill={skill} />
            {bucket === 'ready' ? (
              <span className="sk-chip sk-chip--ok">{t('skills.chipReady')}</span>
            ) : bucket === 'disabled' ? (
              <span className="sk-chip sk-chip--unverified">{t('skills.chipDisabled')}</span>
            ) : (
              <span className="sk-chip sk-chip--warn">{t('skills.chipNeedsDeps')}</span>
            )}
            <AvailabilityChip skill={skill} />
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t('common.close')}
        >
          <XIcon />
        </Button>
      </header>
      <section className="sk-dialog__body">
        <p className="sk-dialog__desc">{skill.description || ''}</p>
        {/* Installed and even "ready" is not the same as reaching the agent.
            This section is the answer to "I installed it, why can the agent
            still not find it?" — the gateway writes the prose. */}
        {availabilityDetail ? (
          <div className="sk-dialog__section sk-dialog__withheld">
            <div className="sk-dialog__section-title">{t('skills.sectionAvailability')}</div>
            <p className="sk-dialog__desc">{availabilityDetail}</p>
          </div>
        ) : null}
        <RequirementsSection requirements={skill.requirements} />
        {hasMissing ? (
          <div className="sk-dialog__section">
            <div className="sk-dialog__section-title">{t('skills.sectionMissing')}</div>
            <ul className="sk-dialog__missing">
              {missingBins.map((b) => (
                <li key={`bin:${b}`} className="sk-dialog__missing-row">
                  <div className="sk-dialog__missing-info">
                    <div className="sk-dialog__missing-head">
                      <code>{b}</code> <span className="sk-dim">{t('skills.missingBinary')}</span>
                    </div>
                  </div>
                </li>
              ))}
              {missingEnv.map((e) => {
                // A missing binary has always had an "Install via …" button
                // here while a missing variable was a dead end. Same dialog,
                // same class of problem, so it gets an action too.
                const detail = (skill.missing_env_detail || []).find((d) => d.name === e)
                return (
                  <li key={`env:${e}`} className="sk-dialog__missing-row sk-dialog__missing-env">
                    <div className="sk-dialog__missing-info">
                      <div className="sk-dialog__missing-head">
                        <code>{e}</code> <span className="sk-dim">{t('skills.missingEnvVar')}</span>
                      </div>
                      {detail?.description || detail?.url ? (
                        <p className="sk-dialog__missing-desc">
                          {detail.description}
                          {detail.url ? (
                            <>
                              {detail.description ? ' ' : null}
                              <a
                                className="sk-dialog__missing-link"
                                href={detail.url}
                                target="_blank"
                                rel="noopener noreferrer"
                              >
                                {t('skills.whereToGet')}
                              </a>
                            </>
                          ) : null}
                        </p>
                      ) : null}
                    </div>
                    {/* The name already sits in the chip beside it, so the button
                        says just "Set" — three long primary buttons read as a wall.
                        `aria-label` keeps the full accessible name. */}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      aria-label={t('skills.setEnvAria', { name: e })}
                      onClick={() => onSetEnv(e)}
                    >
                      {t('skills.setEnvAction')}
                    </Button>
                  </li>
                )
              })}
            </ul>
          </div>
        ) : null}
        {installs.length ? (
          <div className="sk-dialog__section">
            <div className="sk-dialog__section-title">{t('skills.sectionInstall')}</div>
            {installs.map((i) => {
              const busy = busyKeys.has('deps:' + skill.name + ':' + i.id)
              return (
                <div key={i.id} className="sk-dialog__install-row">
                  <span>
                    {i.label || `Install via ${i.kind}`}
                    {(i.bins || []).length ? (
                      <span className="sk-dim"> ({(i.bins || []).join(', ')})</span>
                    ) : null}
                  </span>
                  <Button
                    type="button"
                    size="sm"
                    disabled={busy}
                    onClick={() => onInstallDeps(i.id!)}
                  >
                    {busy
                      ? t('skills.installing')
                      : t('skills.installVia', { kind: String(i.kind) })}
                  </Button>
                </div>
              )
            })}
          </div>
        ) : null}
        {homepage ? (
          <div className="sk-dialog__section">
            <a href={homepage} target="_blank" rel="noopener" className="sk-dialog__link">
              {t('skills.homepage')}
            </a>
          </div>
        ) : null}
      </section>
      <footer className="sk-dialog__foot">
        {removeBlocked ? (
          <small className="sk-dim sk-dialog__note">{removeBlockedNote()}</small>
        ) : skill.file_path ? (
          <small className="sk-dim sk-dialog__path">{skill.file_path}</small>
        ) : null}
        <Button type="button" size="sm" onClick={onUse}>
          {t('skills.useInChat')}
        </Button>
        {canUpdate ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={updateBusy}
            onClick={onUpdate}
          >
            {updateBusy ? t('skills.updating') : t('skills.update')}
          </Button>
        ) : null}
        {canRemove ? (
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={removeBusy}
            onClick={onRemove}
          >
            {removeBusy ? t('skills.removing') : t('skills.remove')}
          </Button>
        ) : null}
      </footer>
    </ModalShell>
  )
}

// ── Registry detail dialog (skills.js:680-739) ────────────────────────────────
function RegistryDialog({
  item,
  forceArmed,
  busy,
  onClose,
  onInstall,
}: {
  item: RegistryItem
  forceArmed: Set<string>
  busy: boolean
  onClose: () => void
  onInstall: (force: boolean) => void
}) {
  const titleId = useId()
  const homepage = safeUrl(item.homepage)
  const action = installAction(item, forceArmed)
  // skills.js:685 — category chip between trust and source (known, non-'other').
  const cat = item.category && item.category !== 'other' ? item.category : ''
  // skills.js:703-704 — demo section heading appends the demo title + language.
  const demoTitle = item.demo?.title || ''
  const demoLang = item.demo?.language || ''
  return (
    <ModalShell
      role="dialog"
      labelledBy={titleId}
      onClose={onClose}
      overlayClassName="sk-modal__overlay"
      className="sk-modal panel"
    >
      <header className="sk-dialog__head">
        <div className="sk-dialog__head-left">
          <LogoBadge item={item} cls="sk-dialog__logo" />
          <div>
            <h2 id={titleId} className="sk-dialog__name">
              {item.name}
            </h2>
            <div className="sk-dialog__provider">{item.provider || ''}</div>
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label={t('common.close')}
        >
          <XIcon />
        </Button>
      </header>
      <section className="sk-dialog__body">
        <div className="sk-dialog__chips">
          <span
            className={`sk-chip ${item.trust_level === 'trusted' ? 'sk-chip--ok' : 'sk-chip--warn'}`}
          >
            {item.trust_level || t('skills.trustCommunity')}
          </span>
          {cat ? <span className="sk-chip">{catLabel(cat)}</span> : null}
          <span className="sk-chip sk-mono">{item.source || ''}</span>
        </div>
        {item.description ? (
          <p className="sk-dialog__desc">{item.description}</p>
        ) : (
          <p className="sk-dialog__desc sk-dim">{t('skills.descPending')}</p>
        )}
        {Array.isArray(item.setup) && item.setup.length ? (
          <div className="sk-dialog__section">
            <div className="sk-dialog__section-title">{t('skills.sectionSetup')}</div>
            <ol className="sk-dialog__setup">
              {item.setup.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ol>
          </div>
        ) : null}
        {item.demo && item.demo.code ? (
          <div className="sk-dialog__section">
            <div className="sk-dialog__section-title">
              {t('skills.sectionDemo')}{' '}
              {demoTitle ? (
                <span className="sk-dialog__demo-title sk-mono">{demoTitle}</span>
              ) : null}{' '}
              {demoLang ? <span className="sk-dialog__demo-lang sk-mono">{demoLang}</span> : null}
            </div>
            <pre className="sk-dialog__code">
              <code>{item.demo.code}</code>
            </pre>
          </div>
        ) : null}
        {homepage ? (
          <div className="sk-dialog__section">
            <a href={homepage} target="_blank" rel="noopener" className="sk-dialog__link">
              {t('skills.sourceLink')}
            </a>
          </div>
        ) : null}
      </section>
      <footer className="sk-dialog__foot">
        <small className="sk-dim sk-mono sk-dialog__path">{registryKey(item)}</small>
        <InstallButton action={action} busy={busy} large onInstall={(force) => onInstall(force)} />
      </footer>
    </ModalShell>
  )
}

// ── Set a missing environment variable without leaving the skill dialog ──────
function SetEnvDialog({
  name,
  value,
  saving,
  onChange,
  onClose,
  onSubmit,
}: {
  name: string
  value: string
  saving: boolean
  onChange: (value: string) => void
  onClose: () => void
  onSubmit: () => void
}) {
  const titleId = useId()
  return (
    <ModalShell
      role="dialog"
      labelledBy={titleId}
      onClose={onClose}
      overlayClassName="sk-modal__overlay"
      className="sk-modal panel"
    >
      <header className="sk-dialog__head">
        <h2 id={titleId} className="sk-dialog__title">
          {t('skills.setEnvTitle', { name })}
        </h2>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t('common.close')}
          onClick={onClose}
        >
          <XIcon />
        </Button>
      </header>
      <form
        className="sk-dialog__body"
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit()
        }}
      >
        <p className="sk-dialog__desc">
          {t('skills.setEnvDescLead')} <code>{'.env'}</code> {t('skills.setEnvDescTail')}
        </p>
        <input
          type="password"
          className="sk-dialog__input"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-label={`Value for ${name}`}
          autoFocus
        />
        <div className="sk-dialog__install-row">
          <Button type="submit" size="sm" disabled={saving || !value}>
            {saving ? t('skills.saving') : t('common.save')}
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            {t('common.cancel')}
          </Button>
        </div>
      </form>
    </ModalShell>
  )
}
