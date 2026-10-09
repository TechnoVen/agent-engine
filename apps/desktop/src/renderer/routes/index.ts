/**
 * Canonical Route Registry for Agent Engine Desktop Shell
 *
 * Governing Document: docs/GUI_CANONICAL_REDESIGN.md
 * Single source of truth for:
 * - Route resolution
 * - Sidebar selected state
 * - Rendered screen
 * - TopBar breadcrumbs
 * - Command palette / quick navigation
 * - Browser back/forward navigation
 * - Deep linking & aliases
 */

export type RouteSection = 'work' | 'tools' | 'library' | 'system' | 'settings';
export type RouteAvailability = 'available' | 'preview' | 'disabled';

export interface AppRoute {
  id: string;
  path: string;
  label: string;
  section: RouteSection;
  breadcrumb: string[];
  availability: RouteAvailability;
  aliases?: string[];
  iconName?: string;
  description?: string;
}

export const CANONICAL_ROUTES: AppRoute[] = [
  // ── WORK SECTION ────────────────────────────────────────────────────────
  {
    id: 'home',
    path: '#home',
    label: 'Home',
    section: 'work',
    breadcrumb: ['Agent Engine', 'Home'],
    availability: 'available',
    aliases: ['#', ''],
    iconName: 'Home',
    description: 'Universal workbench and command surface',
  },
  {
    id: 'projects',
    path: '#projects',
    label: 'Projects',
    section: 'work',
    breadcrumb: ['Agent Engine', 'Projects'],
    availability: 'available',
    iconName: 'FolderKanban',
    description: 'Workspaces, project instructions, and connected sources',
  },
  {
    id: 'tasks',
    path: '#tasks',
    label: 'Tasks',
    section: 'work',
    breadcrumb: ['Agent Engine', 'Tasks'],
    availability: 'preview',
    iconName: 'Clock',
    description: 'Preview · Runtime not available yet · Coming in R4',
  },
  {
    id: 'automations',
    path: '#automations',
    label: 'Automations',
    section: 'work',
    breadcrumb: ['Agent Engine', 'Automations'],
    availability: 'preview',
    aliases: ['#workflows', '#swarm'],
    iconName: 'GitBranch',
    description: 'Preview · Runtime not available yet · Coming in R4',
  },

  // ── TOOLS SECTION ───────────────────────────────────────────────────────
  {
    id: 'research',
    path: '#research',
    label: 'Research',
    section: 'tools',
    breadcrumb: ['Agent Engine', 'Research'],
    availability: 'available',
    aliases: ['#deep-research'],
    iconName: 'Search',
    description: 'Sources, synthesis report, notes, and citations',
  },
  {
    id: 'writing',
    path: '#writing',
    label: 'Writing',
    section: 'tools',
    breadcrumb: ['Agent Engine', 'Writing'],
    availability: 'available',
    aliases: ['#docs'],
    iconName: 'FileText',
    description: 'Document editor workspace and context pane',
  },
  {
    id: 'data',
    path: '#data',
    label: 'Data',
    section: 'tools',
    breadcrumb: ['Agent Engine', 'Data'],
    availability: 'available',
    aliases: ['#sheets'],
    iconName: 'Table2',
    description: 'Dataset table view, filters, and analysis pane',
  },
  {
    id: 'developer',
    path: '#developer',
    label: 'Developer',
    section: 'tools',
    breadcrumb: ['Agent Engine', 'Developer'],
    availability: 'available',
    aliases: ['#code'],
    iconName: 'Code2',
    description: 'Engineering console, runtime logs, MCP tools, and DSPy trace',
  },

  // ── LIBRARY SECTION ─────────────────────────────────────────────────────
  {
    id: 'knowledge',
    path: '#knowledge',
    label: 'Knowledge',
    section: 'library',
    breadcrumb: ['Agent Engine', 'Knowledge'],
    availability: 'available',
    iconName: 'BookOpen',
    description: 'Sources, documents, project knowledge, and user memory',
  },
  {
    id: 'skills',
    path: '#skills',
    label: 'Skills',
    section: 'library',
    breadcrumb: ['Agent Engine', 'Skills'],
    availability: 'available',
    aliases: ['#marketplace'],
    iconName: 'Puzzle',
    description: 'Installed skills, curated registry, and skill editor',
  },

  // ── SYSTEM SECTION ──────────────────────────────────────────────────────
  {
    id: 'activity',
    path: '#activity',
    label: 'Activity',
    section: 'system',
    breadcrumb: ['Agent Engine', 'Activity'],
    availability: 'available',
    aliases: ['#cost'],
    iconName: 'Activity',
    description: 'Execution history, usage economics, and audit ledger',
  },
  {
    id: 'approvals',
    path: '#approvals',
    label: 'Approvals',
    section: 'system',
    breadcrumb: ['Agent Engine', 'Approvals'],
    availability: 'available',
    aliases: ['#policies'],
    iconName: 'ShieldCheck',
    description: 'Operator approval queue for pending high-risk operations',
  },
  {
    id: 'models',
    path: '#models',
    label: 'Models',
    section: 'system',
    breadcrumb: ['Agent Engine', 'Models'],
    availability: 'available',
    aliases: ['#benchmarks'],
    iconName: 'Gauge',
    description: 'R3 model hub: local hardware recommendations and cloud provider tests',
  },

  // ── SETTINGS SECTION ────────────────────────────────────────────────────
  {
    id: 'settings',
    path: '#settings',
    label: 'Settings',
    section: 'settings',
    breadcrumb: ['Agent Engine', 'Settings'],
    availability: 'available',
    iconName: 'Settings',
    description: 'Application settings, provider connections, and developer mode',
  },
  {
    id: 'profile',
    path: '#profile',
    label: 'Profile & Memory',
    section: 'settings',
    breadcrumb: ['Agent Engine', 'Profile & Memory'],
    availability: 'available',
    aliases: ['#agent'],
    iconName: 'User',
    description: 'User profile, preferences, instructions, and memory',
  },
];

/**
 * Normalizes any URL hash string into standard format (e.g. '#home').
 */
export function normalizeHash(hash?: string): string {
  if (!hash) return '#home';
  const clean = hash.trim();
  if (clean === '#' || clean === '#/' || clean === '') return '#home';
  return clean.startsWith('#') ? clean : `#${clean}`;
}

/**
 * Single authoritative route resolution function.
 * Matches by exact path, ID, or aliases.
 */
export function resolveRoute(hash?: string): AppRoute {
  const normalized = normalizeHash(hash);
  const rawId = normalized
    .replace(/^#\/?/, '')
    .split('/')[0]
    .split('?')[0]
    .toLowerCase();

  // 1. Exact path match
  for (const route of CANONICAL_ROUTES) {
    if (route.path.toLowerCase() === normalized.toLowerCase()) {
      return route;
    }
  }

  // 2. Exact ID match
  for (const route of CANONICAL_ROUTES) {
    if (route.id.toLowerCase() === rawId) {
      return route;
    }
  }

  // 3. Alias match
  for (const route of CANONICAL_ROUTES) {
    if (route.aliases) {
      for (const alias of route.aliases) {
        const cleanAlias = alias.replace(/^#\/?/, '').toLowerCase();
        if (cleanAlias === rawId || alias.toLowerCase() === normalized.toLowerCase()) {
          return route;
        }
      }
    }
  }

  // 4. Default fallback: Home
  return CANONICAL_ROUTES[0];
}

/**
 * Finds a route by its canonical ID.
 */
export function findRouteById(id: string): AppRoute {
  return CANONICAL_ROUTES.find((r) => r.id === id) || CANONICAL_ROUTES[0];
}

/**
 * Returns all canonical routes belonging to a given sidebar section.
 */
export function getRoutesBySection(section: RouteSection): AppRoute[] {
  return CANONICAL_ROUTES.filter((r) => r.section === section);
}

/**
 * Constructs truthful breadcrumb segments.
 * Never outputs duplicate 'Agent Engine / Agent Engine'.
 */
export function buildBreadcrumb(route: AppRoute, projectName?: string): string[] {
  if (route.id === 'projects' && projectName && projectName.trim() && projectName !== 'Agent Engine') {
    return ['Agent Engine', 'Projects', projectName.trim()];
  }
  return route.breadcrumb;
}
