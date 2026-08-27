import { defineNamespace } from '../registry'

export const sessions = defineNamespace('sessions', {
  documentTitle: 'Sessions - AgentOS Control',
  eyebrow: 'Control · Sessions',
  title: 'Sessions',
  subtitle:
    'Session history, current task activity, and agent runs — open one to chat, or clean up old state.',
  refresh: 'Refresh',
  refreshBusy: 'Refreshing…',
  newSession: 'New session',

  // Session lifecycle labels (logic.ts).
  statusRunning: 'Running',
  statusDone: 'Completed',
  statusFailed: 'Failed',
  statusKilled: 'Aborted by operator',
  statusTimeout: 'Timed out',
  statusUnknown: 'Unknown',

  // Relative timestamps (logic.ts).
  relJustNow: 'just now',
  relMinutes: '{count}m ago',
  relHours: '{count}h ago',
  relDays: '{count}d ago',

  // Run badges (logic.ts).
  runQueued: 'Task queued',
  runRunning: 'Task running',
  runInterrupted: 'Interrupted',
  runFailed: 'Last task failed',
  runTimeout: 'Last task timed out',
  runCancelled: 'Last task cancelled',

  // Activity overview.
  overviewLandmark: 'Session activity overview',
  overviewEyebrow: 'Activity ledger',
  overviewTitle: 'Session pulse',
  overviewExecuting: '{count} executing now',
  overviewIdle: 'No active runs',
  statsLandmark: 'Sessions summary',
  statTotal: 'Total sessions',
  statTotalHint: '{open} open · {done} completed · {failed} failed/timed out · {aborted} aborted',
  statExecuting: 'Executing',
  statExecutingHint: 'tasks queued/running',
  statExecutingIdle: 'none executing',
  statMessages: 'Messages',
  statMessagesHint_one: '{count} agent · across all sessions',
  statMessagesHint_other: '{count} agents · across all sessions',

  // List header and tools.
  listMatching: 'Matching sessions',
  listAll: 'All sessions',
  countFiltered: '{shown} of {total}',
  countTotal: '{total} total',
  searchPlaceholder: 'Search sessions…',
  searchLabel: 'Search sessions',
  rowsLabel: 'Rows',
  rowsPerPage: 'Rows per page',

  // Bulk bar.
  bulkLandmark: 'Bulk actions',
  bulkSelected: 'selected',
  bulkClear: 'Clear',
  bulkDelete: 'Delete selected',

  // Empty states.
  emptyTitle: 'No sessions yet.',
  emptyMsg:
    'Sessions appear here as soon as you chat with an agent or schedule a cron job. Start one and pick up the conversation any time.',
  emptyAction: 'Start a new session',
  noMatchTitle: 'No matches',
  noMatchMsg:
    'No sessions match your search. Try a different query, or clear it to see everything.',

  // Table.
  selectAll: 'Select all sessions on this page',
  colKey: 'Session key',
  colStatus: 'Status',
  colMessages: 'Msgs',
  colModified: 'Modified',
  selectRow: 'Select session {key}',
  openChat: 'Open chat',
  openChatFor: 'Open chat for {key}',
  copyKeyTitle: 'Copy session key',
  copyKeyFor: 'Copy session key {key}',
  deleteTitle: 'Delete',
  deleteFor: 'Delete session {key}',
  renameTitle: 'Rename session',
  renameFor: 'Rename session {key}',
  renameInput: 'Session name for {key}',
  renamePlaceholder: 'Add a name',
  renameHint: 'Enter to save · Esc to cancel',
  orphanTitle: "Agent '{name}' is no longer registered",
  orphanChip: '⚠ Orphaned',

  // Pagination.
  prevPage: 'Previous page',
  nextPage: 'Next page',
  pageTotal: '· {total} total',

  // New-session dialog.
  dialogTitle: 'Start a new chat',
  dialogAgent: 'Agent',
  dialogAgentPlaceholder: 'Pick an agent or type a new ID',
  dialogOptionWithSublabel: '{label} — {sublabel}',
  dialogHintCreate: '↵ Create a new agent "{id}" and start a chat.',
  dialogHintPick: 'Pick an agent or type a new ID to create it.',
  dialogSubmit: 'Start chat',
  dialogSubmitCreating: 'Creating…',
  dialogSubmitStarting: 'Starting…',
  agentBuiltin: 'built-in',

  // Delete confirmations. The sentences wrap a <strong> for the key/count, so
  // they are stored as the runs of text on either side of it.
  confirmDeleteTitle: 'Delete session',
  confirmDeleteLead: 'Delete session',
  confirmDeleteTail: '? This cannot be undone.',
  confirmBulkTitle: 'Delete sessions',
  confirmBulkLead: 'Delete',
  // Not a tPlural pair: the count renders in its own <strong> node, and the
  // catalog convention requires {count} inside every _one/_other value.
  confirmBulkTailSingular: 'session? This cannot be undone.',
  confirmBulkTailPlural: 'sessions? This cannot be undone.',
  confirmWarnLead: 'The transcript will not be flushed to disk; use',
  confirmWarnTail: 'first if you want a backup.',
  confirmDelete: 'Delete',
  confirmDeleteAll: 'Delete all',

  // Toasts.
  toastLoadFailed: 'Failed to load sessions: {message}',
  toastDeleted: 'Session deleted',
  toastRenamed: 'Session renamed',
  toastRenameCleared: 'Session name cleared',
  toastRenameFailed: 'Rename failed: {message}',
  toastDeleteFailed: 'Delete failed: {message}',
  toastBulkPartial: 'Deleted {ok}, {failed} failed',
  toastBulkDeleted_one: 'Deleted {count} session',
  toastBulkDeleted_other: 'Deleted {count} sessions',
  toastCreatedWithAgent: 'Created agent "{id}" and started chat',
  toastCreated: 'Session created',
  toastCreateFailed: 'Failed to start chat: {message}',
  toastCreateUnauthorized: 'This connection does not have permission to create agents.',
  toastAgentNotFound: 'Agent "{id}" doesn\'t exist. Type a new ID and it will be created.',
  toastAgentExists: 'Agent "{id}" already exists — pick it from the list instead.',
  toastCopied: 'Copied session key',
  toastCopyFailed: 'Copy failed: {message}',

  // Projects integration.
  moveToProject: 'Move to project',
  moveToProjectFor: 'Move session {key} to a project',
  moveDialogTitle: 'Move to project',
  moveDialogBody: 'Sessions in a project share its knowledge in every turn.',
  moveNone: 'No project',
  moveSubmit: 'Move',
  moveSubmitBusy: 'Moving…',
  toastMoved: 'Session moved to project',
  toastDetached: 'Session removed from project',
  toastMoveFailed: 'Move failed: {message}',
  filterAllProjects: 'All projects',
  filterNoProject: 'No project',
  filterProjectLabel: 'Filter by project',
} as const)
