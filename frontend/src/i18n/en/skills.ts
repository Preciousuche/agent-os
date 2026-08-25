import { defineNamespace } from '../registry'

export const skills = defineNamespace('skills', {
  documentTitle: 'Skills - AgentOS Control',
  title: 'Skills',
  subtitle: 'Manage installed capabilities and discover trusted skills for your agents.',
  refresh: 'Refresh',

  // Brand artwork. Brand *names* (Bankr / Capminal / Robinhood) are proper
  // nouns and stay literal in the component.
  altGmgnLogo: 'GMGN logo',
  altAgentosLogo: 'AgentOS logo',

  // Source tabs.
  tabsLandmark: 'Skill source',
  tabInstalled: 'Installed',
  tabInstalledDesc: '{count} local skills',
  tabPartnerDesc: 'Partner catalog',
  tabRobinhoodDesc: 'Bundled partner',
  tabCommunity: 'Community',
  tabCommunityDesc: 'Open catalog',

  // Installed toolbar.
  searchPlaceholder: 'Search installed skills',
  searchLabel: 'Filter installed skills',
  metricsLandmark: 'Skills summary',
  metricAll: 'All',
  metricReady: 'Ready',
  metricNeedsSetup: 'Needs setup',
  metricDisabled: 'Disabled',

  // Install from GitHub.
  githubTitle: 'Install from GitHub',
  githubDesc: 'Add a skill directly from a public repository or folder.',
  githubPlaceholder: 'https://github.com/owner/repo/tree/main/skill',
  githubUrlLabel: 'Install from GitHub URL',
  githubInstall: 'Install',

  // Cards.
  cardSkillLabel: 'Skill {name}',
  cardViewDetails: 'View details',
  cardUse: 'Use',
  cardDetailsFor: 'View details for {name}',
  cardOpenDetails: 'Open details',
  catalogSkillLabel: 'Catalog skill {name}',
  partnerSkillLabel: '{brand} skill {name}',

  // Install button.
  installed: 'Installed',
  forceInstalling: 'Force installing…',
  forceInstall: 'Force install',
  installing: 'Installing…',
  installSkill: 'Install skill',
  install: 'Install',

  // Catalog panels.
  communityTitle: 'Community catalog',
  communityDesc: 'Discover skills published by the wider AgentOS community.',
  registryLabelCommunity: 'community',
  registrySearchPlaceholder: 'Search {label} skills…',
  registrySearchLabel: 'Search {label} skills',
  loadingCatalog: 'Loading {label} catalog',
  loadFailed: 'Failed to load: {error}',
  retryHintCommunity: 'Re-open the tab or press Refresh to retry.',
  retryHintRobinhood: 'Press Refresh to retry.',
  importantPrefix: 'IMPORTANT:',
  // The partner count renders in its own <strong>, so the noun is a plain key
  // rather than a tPlural() pair (which must carry {count} in the value).
  skillWord: 'skill',
  skillsWord: 'skills',

  // Partner catalog intros.
  bankrTitle: 'Bankr skill catalog',
  bankrDesc: 'Curated financial and on-chain capabilities maintained by the Bankr ecosystem.',
  bankrNotice: "the 'bankr' skill is required for all skills in this catalog.",
  capminalTitle: 'Capminal skill catalog',
  capminalDesc:
    'Wallet, token-launch, and on-chain execution skills maintained by the Capminal team.',
  capminalNotice: "the 'capminal' skill is required for all skills in this catalog.",
  aeonTitle: 'Aeon skill catalog',
  aeonDesc:
    'On-chain investigation, token research, and trend-tracking skills maintained by the Aeon team.',
  aeonNotice:
    "Aeon skills are written for Aeon's scheduled runtime; AgentOS adapts them on install. Some need an API key you supply yourself — each card lists what it wants.",
  robinhoodTitle: 'Robinhood skills',
  robinhoodDesc:
    'Official bundled capabilities for Robinhood products and on-chain assets, maintained by AgentOS against the Robinhood Trading MCP.',
  robinhoodNotice:
    "the 'robinhood-agentic-trading' skill trades from a dedicated Robinhood Agentic account — create that account in Robinhood and complete its authorization flow before using the skill.",

  // Robinhood panel.
  robinhoodStatusLandmark: 'Robinhood skill status',
  robinhoodFilterLabel: 'Filter Robinhood skills: {label}',
  loadingRobinhood: 'Loading Robinhood skills',

  // Installed panel.
  installedLoadFailed: 'Failed to load skills: {error}',
  loadingInstalled: 'Loading installed skills',

  // Requirements section.
  reqTitle: 'Requirements',
  reqReady: 'ready',
  reqNeedsSetup: 'needs setup',
  reqMissingSkill: 'missing skill',
  reqNotDeclared: 'no deps declared',
  reqMissingLead: 'Missing',
  reqOneOf: 'one of {list}',
  reqEnv: '{name} env',
  reqNoDeps: 'No declared dependencies',
  reqUnknown: 'unknown',

  // Skill detail dialog.
  chipReady: '✓ ready',
  chipDisabled: 'disabled',
  chipNeedsDeps: 'needs deps',
  sectionAvailability: 'Agent availability',
  sectionMissing: 'Missing',
  missingBinary: 'binary',
  missingEnvVar: 'env var',
  whereToGet: 'where to get it ↗',
  setEnvAria: 'Set {name}',
  setEnvAction: 'Set',
  sectionInstall: 'Install',
  homepage: 'Homepage ↗',
  useInChat: 'Use in chat',
  installVia: 'Install via {kind}',
  updating: 'Updating…',
  update: 'Update',
  removing: 'Removing…',
  remove: 'Remove',
  removeBlockedNote:
    'AgentOS cannot remove this skill: the configured managed skills directory does not hold it. Check skills.managed_dir, or delete the files by hand.',

  // Registry detail dialog.
  descPending: "Description loads after install (from the skill's SKILL.md).",
  sectionSetup: 'Setup',
  sectionDemo: 'Demo',
  sourceLink: 'Source ↗',
  trustCommunity: 'community',

  // Set-env dialog.
  setEnvTitle: 'Set {name}',
  setEnvDescLead: 'Stored in the AgentOS',
  setEnvDescTail: 'and applied to the running gateway.',
  saving: 'Saving…',

  // Toasts.
  toastLoadFailed: 'Failed to load skills: {message}',
  toastInstalled: 'Installed {name}',
  toastScanBlocked: 'Security scan flagged {target}. Click again to install anyway.',
  toastScanTarget_one: '{name} ({count} finding)',
  toastScanTarget_other: '{name} ({count} findings)',
  toastScanUnnamed: 'this skill',
  toastInstallFailed: 'Install failed',
  toastRemoved: 'Removed {name}',
  toastUninstallFailed: 'Uninstall failed',
  toastUpdated: 'Updated {name}',
  toastUpdateFailed: 'Update failed',
  toastDepsInstalled: 'Installed',
  toastEnvSaved: '{name} saved.',

  // Loading layers (logic.ts).
  layerWorkspace: 'Workspace',
  layerBundled: 'Bundled',
  layerManaged: 'Managed',
  layerPersonal: 'Personal',
  layerProject: 'Project',
  layerExtra: 'Extra',
  layerUnknown: 'Unknown',
  layerHelpWorkspace: 'Workspace skills are local to the active workspace.',
  layerHelpBundled: 'Bundled skills ship with AgentOS.',
  layerHelpManaged: 'Managed skills are locally installed into AgentOS state.',
  layerHelpPersonal: 'Personal skills are local user installs, not bundled.',
  layerHelpProject: 'Project skills are local to the current project.',
  layerHelpExtra: 'Extra skills come from configured local directories.',
  layerHelpFallback: 'Configured local skill directory.',

  // Acquisition provenance (logic.ts).
  srcHub: 'hub',
  srcShipped: 'shipped',
  srcLocal: 'local',

  // Catalog categories (logic.ts).
  catAll: 'All',
  catTrading: 'Trading',
  catDefi: 'DeFi',
  catWallet: 'Wallets',
  catMarkets: 'Markets',
  catSocial: 'Social',
  catData: 'Data',
  catNft: 'NFT',
  catDev: 'Dev tools',
  catInfra: 'Infra',
  catCrypto: 'Crypto',
  catOther: 'Other',

  // Installed empty states (logic.ts).
  emptyMatch: 'No skills match {query}.',
  emptyReady: 'No skills are ready. Install dependencies to enable them.',
  emptyNeedsSetup: 'No skills currently need setup.',
  emptyDisabled: 'No skills are switched off.',
  emptyNone: 'No skills installed.',

  // Provenance groups (logic.ts).
  groupPartners: 'Partner Skills',
  groupCrypto: 'AgentOS Crypto Skills',
  groupShipped: 'AgentOS Normal Skills',
  groupHub: 'Installed from a hub',
  groupLocal: 'Your local skills',
  groupHelpPartners: 'Skills published by an AgentOS partner.',
  groupHelpCrypto: 'On-chain and wallet skills that ship with AgentOS.',
  groupHelpShipped: 'Skills that ship with AgentOS.',
  groupHelpHub: 'Skills you installed from a skill hub.',
  groupHelpLocal: 'Skills you added yourself, from a local skill directory.',

  // Status buckets + dot tooltip (logic.ts).
  bucketReady: 'Ready',
  bucketNeedsSetup: 'Setup required',
  bucketDisabled: 'Disabled',
  dotDisabled: 'Disabled in config',
  dotReady: 'Ready',
  dotNeedsSetup: 'Needs setup',

  // Availability (logic.ts).
  availOffered: 'Offered to the agent',
  availNotOffered: 'Not offered to the agent',
  availModelInvocationDisabled: 'Not offered — agent cannot invoke',
  availIneligible: 'Not offered — needs setup',
  availToolGate: 'Not offered — missing tools',
  availFallbackSuperseded: 'Not offered — superseded',
  availNotRetrieved: 'Not offered — not retrieved',
  availPromptBudget: 'Not offered — prompt too long',

  // Partner empty states (logic.ts).
  partnerEmptyMatch: 'No {brand} skills match {query}.',
  partnerEmptyReady: 'No {brand} skills are ready.',
  partnerEmptyNeedsSetup: 'No {brand} skills currently need setup.',
  partnerEmptyDisabled: 'No {brand} skills are switched off.',
  partnerEmptyNone: '{brand} skills are on the way. No {brand} skills are installed yet.',

  // Catalog empty states (logic.ts).
  registryEmptyMatch: 'No skills match {query}.',
  registryEmptyBankr: 'No Bankr skills available right now.',
  registryEmptyCapminal: 'No Capminal skills available right now.',
  registryEmptyAeon: 'No Aeon skills available right now.',
  registryEmptyCommunity: 'No community skills available right now.',
} as const)
