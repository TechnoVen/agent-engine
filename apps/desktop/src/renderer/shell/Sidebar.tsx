import React, { useState, useEffect, useRef } from 'react';
import {
  Home as HomeIcon,
  FolderKanban,
  Clock,
  GitBranch,
  Search,
  FileText,
  Table2,
  Code2,
  BookOpen,
  Puzzle,
  Activity,
  ShieldCheck,
  Gauge,
  Plus,
  PanelLeftClose,
  PanelLeftOpen,
  Settings as SettingsIcon,
  FolderPlus,
  MessageSquare,
  X,
  Loader2,
} from 'lucide-react';
import { Mode, Project, RecentChat, SessionSearchResult } from '../types';
import { sidecarClient } from '../api/client';
import { AppRoute, resolveRoute } from '../routes';

interface SidebarProps {
  currentRoute?: AppRoute;
  activeMode?: Mode;
  onSelectMode: (mode: Mode) => void;
  onNavigate?: (route: AppRoute) => void;
  activeSessionId?: string;
  onSelectSession?: (sessionId: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNewChat: () => void;
  projects?: Project[];
  recentChats?: RecentChat[];
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentRoute,
  activeMode,
  onSelectMode,
  onNavigate,
  activeSessionId,
  onSelectSession,
  collapsed,
  onToggleCollapse,
  onNewChat,
  projects = [],
  recentChats = [],
}) => {
  const [realProjects, setRealProjects] = useState<Project[]>(projects);
  const [realChats, setRealChats] = useState<RecentChat[]>(recentChats);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SessionSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    const fetchSidebarData = async () => {
      try {
        const [projs, sess] = await Promise.all([
          sidecarClient.getProjects(),
          sidecarClient.getSessions(5),
        ]);
        if (active) {
          if (projs && projs.length > 0) {
            setRealProjects(
              projs.map((p) => ({
                id: p.id,
                name: p.name,
                icon: 'folder',
                threadCount: 0,
                lastActivity: 'Active',
              }))
            );
          }
          if (sess && sess.length > 0) {
            setRealChats(
              sess.map((s) => ({
                id: s.id,
                title: s.title || 'Untitled Session',
                mode: (s.channel || 'home') as Mode,
                updatedAt: s.updated_at
                  ? new Date(s.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                  : 'Recent',
              }))
            );
          }
        }
      } catch {
        // Fallback gracefully
      }
    };
    fetchSidebarData();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const trimmed = searchQuery.trim();
    if (!trimmed) {
      setSearchResults([]);
      setIsSearching(false);
      return;
    }

    let active = true;
    setIsSearching(true);
    const timer = setTimeout(async () => {
      try {
        const results = await sidecarClient.searchSessions(trimmed);
        if (active) {
          setSearchResults(results);
          setIsSearching(false);
        }
      } catch {
        if (active) {
          setSearchResults([]);
          setIsSearching(false);
        }
      }
    }, 200);

    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [searchQuery]);

  const handleClearSearch = () => {
    setSearchQuery('');
    setSearchResults([]);
  };

  const handleKeyDownSearch = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Escape') {
      handleClearSearch();
      searchInputRef.current?.blur();
    }
  };

  // Canonical WORK section
  const primaryModes = [
    { id: 'home', path: '#home', label: 'Home', icon: <HomeIcon className="w-4 h-4 text-text-secondary" /> },
    { id: 'projects', path: '#projects', label: 'Projects', icon: <FolderKanban className="w-4 h-4 text-text-secondary" /> },
    { id: 'tasks', path: '#tasks', label: 'Tasks', icon: <Clock className="w-4 h-4 text-text-secondary" /> },
    { id: 'automations', path: '#automations', label: 'Automations', icon: <GitBranch className="w-4 h-4 text-text-secondary" /> },
  ];

  // Canonical TOOLS section
  const capabilityModes = [
    { id: 'research', path: '#research', label: 'Research', icon: <Search className="w-4 h-4 text-text-secondary" /> },
    { id: 'writing', path: '#writing', label: 'Writing', icon: <FileText className="w-4 h-4 text-text-secondary" /> },
    { id: 'data', path: '#data', label: 'Data', icon: <Table2 className="w-4 h-4 text-text-secondary" /> },
    { id: 'developer', path: '#developer', label: 'Developer', icon: <Code2 className="w-4 h-4 text-text-secondary" /> },
  ];

  // Canonical LIBRARY section
  const libraryModes = [
    { id: 'knowledge', path: '#knowledge', label: 'Knowledge', icon: <BookOpen className="w-4 h-4 text-text-secondary" /> },
    { id: 'skills', path: '#skills', label: 'Skills', icon: <Puzzle className="w-4 h-4 text-text-secondary" /> },
  ];

  // Canonical SYSTEM section
  const systemModes = [
    { id: 'activity', path: '#activity', label: 'Activity', icon: <Activity className="w-4 h-4 text-text-secondary" /> },
    { id: 'approvals', path: '#approvals', label: 'Approvals', icon: <ShieldCheck className="w-4 h-4 text-text-secondary" /> },
    { id: 'models', path: '#models', label: 'Models', icon: <Gauge className="w-4 h-4 text-text-secondary" /> },
  ];

  const activeRouteId = currentRoute?.id || (activeMode ? resolveRoute(activeMode).id : resolveRoute(window.location.hash).id);

  const handleNavigate = (item: { id: string; path: string }) => {
    window.location.hash = item.path;
    const resolved = resolveRoute(item.path);
    onNavigate?.(resolved);
    onSelectMode(item.id as Mode);
  };

  const displayProjects = projects.length > 0 ? projects : realProjects;
  const displayChats = recentChats.length > 0 ? recentChats : realChats;

  return (
    <aside
      className={`h-full bg-bg-elevated border-r border-border-subtle flex flex-col justify-between select-none panel-transition ${
        collapsed ? 'w-14' : 'w-[240px]'
      }`}
    >
      {/* Zone A: Global Header & New Action */}
      <div className="p-3 border-b border-border-subtle flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div
            onClick={() => onSelectMode('home')}
            className="flex items-center gap-2 cursor-pointer group"
          >
            <div className="w-6 h-6 rounded bg-accent flex items-center justify-center font-bold text-[11px] text-white shadow-sm group-hover:bg-accent-hover transition-colors">
              AE
            </div>
            {!collapsed && (
              <span className="font-semibold text-xs tracking-tight text-text-primary">
                Agent Engine
              </span>
            )}
          </div>
          <button
            onClick={onToggleCollapse}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="p-1 rounded hover:bg-bg-hover text-text-tertiary hover:text-text-primary transition-colors"
          >
            {collapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
          </button>
        </div>

        {/* New Chat Button (Ctrl+K) */}
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-between px-2.5 py-1.5 bg-bg-base hover:bg-bg-hover border border-border-subtle hover:border-border-strong rounded-md text-text-primary text-xs font-medium transition-all group"
        >
          <div className="flex items-center gap-2">
            <Plus className="w-3.5 h-3.5 text-text-secondary" />
            {!collapsed && <span>New Chat</span>}
          </div>
          {!collapsed && (
            <kbd className="px-1.5 py-0.2 text-[10px] font-mono rounded bg-bg-elevated border border-border-strong text-text-tertiary group-hover:text-text-secondary">
              Ctrl K
            </kbd>
          )}
        </button>
      </div>

      {/* Zone B: Navigation Hierarchy (Scrollable) */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-3 scrollbar-thin">
        {/* WORK Section */}
        <div>
          {!collapsed && (
            <div className="px-2 mb-1 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
              Work
            </div>
          )}
          <div className="space-y-0.5">
            {primaryModes.map((item) => {
              const isActive = activeRouteId === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => handleNavigate(item)}
                  title={collapsed ? item.label : undefined}
                  className={`w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs transition-colors ${
                    isActive
                      ? 'bg-bg-hover text-text-primary font-medium border-l-2 border-accent'
                      : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover/60'
                  }`}
                >
                  {item.icon}
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </button>
              );
            })}
          </div>
        </div>

        {/* TOOLS Section */}
        <div>
          {!collapsed && (
            <div className="px-2 mb-1 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
              Tools
            </div>
          )}
          <div className="space-y-0.5">
            {capabilityModes.map((item) => {
              const isActive = activeRouteId === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => handleNavigate(item)}
                  title={collapsed ? item.label : undefined}
                  className={`w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs transition-colors ${
                    isActive
                      ? 'bg-bg-hover text-text-primary font-medium border-l-2 border-accent'
                      : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover/60'
                  }`}
                >
                  {item.icon}
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </button>
              );
            })}
          </div>
        </div>

        {/* LIBRARY Section */}
        <div>
          {!collapsed && (
            <div className="px-2 mb-1 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
              Library
            </div>
          )}
          <div className="space-y-0.5">
            {libraryModes.map((item, idx) => {
              const isActive = activeRouteId === item.id;
              return (
                <button
                  key={`${item.id}-${idx}`}
                  onClick={() => handleNavigate(item)}
                  title={collapsed ? item.label : undefined}
                  className={`w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs transition-colors ${
                    isActive
                      ? 'bg-bg-hover text-text-primary font-medium border-l-2 border-accent'
                      : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover/60'
                  }`}
                >
                  {item.icon}
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </button>
              );
            })}
          </div>
        </div>

        {/* SYSTEM Section */}
        <div>
          {!collapsed && (
            <div className="px-2 mb-1 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
              System
            </div>
          )}
          <div className="space-y-0.5">
            {systemModes.map((item) => {
              const isActive = activeRouteId === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => handleNavigate(item)}
                  title={collapsed ? item.label : undefined}
                  className={`w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs transition-colors ${
                    isActive
                      ? 'bg-bg-hover text-text-primary font-medium border-l-2 border-accent'
                      : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover/60'
                  }`}
                >
                  {item.icon}
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </button>
              );
            })}
          </div>
        </div>

        {/* Collapsed strip extras */}
        {collapsed && (
          <div className="pt-2 border-t border-border-subtle space-y-1">
            <button
              onClick={() => {
                onToggleCollapse();
                setTimeout(() => searchInputRef.current?.focus(), 100);
              }}
              title="Search sessions (Ctrl+/)"
              aria-label="Search sessions"
              className="w-full flex items-center justify-center p-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-hover"
            >
              <Search className="w-4 h-4" />
            </button>
            <button
              onClick={() => handleNavigate({ id: 'projects', path: '#projects' })}
              title="Projects"
              aria-label="Projects"
              className="w-full flex items-center justify-center p-2 rounded-md text-text-secondary hover:text-text-primary hover:bg-bg-hover"
            >
              <FolderKanban className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Zone C: Context (Search, Projects, Recent Chats) */}
        {!collapsed && (
          <div className="space-y-3 pt-2 border-t border-border-subtle">
            {/* Real-Time Session Search */}
            <div className="px-1">
              <div
                role="search"
                className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-bg-base border border-border-subtle focus-within:border-accent/50 focus-within:ring-1 focus-within:ring-accent/30 transition-all text-xs"
              >
                <Search className="w-3.5 h-3.5 text-text-tertiary flex-shrink-0" />
                <input
                  ref={searchInputRef}
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={handleKeyDownSearch}
                  placeholder="Search sessions... (Esc)"
                  aria-label="Search sessions"
                  className="bg-transparent text-text-primary placeholder:text-text-tertiary focus:outline-none w-full text-xs"
                />
                {isSearching && <Loader2 className="w-3 h-3 text-accent animate-spin flex-shrink-0" />}
                {searchQuery && !isSearching && (
                  <button
                    onClick={handleClearSearch}
                    aria-label="Clear search"
                    className="text-text-tertiary hover:text-text-primary p-0.5 rounded"
                  >
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
            </div>

            {/* If actively searching: show search results */}
            {searchQuery.trim() ? (
              <div className="space-y-1">
                <div className="flex items-center justify-between px-2 mb-1">
                  <span className="text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
                    Search Results ({searchResults.length})
                  </span>
                  <button
                    onClick={handleClearSearch}
                    className="text-[10px] text-accent hover:underline"
                  >
                    Clear
                  </button>
                </div>
                {searchResults.length === 0 && !isSearching ? (
                  <div className="px-2 py-2 text-center text-xs text-text-tertiary">
                    No sessions matching &ldquo;{searchQuery}&rdquo;
                  </div>
                ) : (
                  <div className="space-y-1 max-h-40 overflow-y-auto px-1">
                    {searchResults.map((res) => {
                      const isSelected = activeSessionId === res.session_id;
                      const snippet = res.matched_snippets?.[0]?.content;
                      return (
                        <button
                          key={res.session_id}
                          onClick={() => {
                            onSelectSession?.(res.session_id);
                            onSelectMode('home');
                          }}
                          aria-selected={isSelected}
                          className={`w-full text-left p-1.5 rounded-md text-xs transition-all ${
                            isSelected
                              ? 'bg-accent/15 text-accent font-medium border-l-2 border-accent'
                              : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover/60 border border-transparent'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-1 mb-0.5">
                            <span className="font-medium truncate text-text-primary">{res.title}</span>
                            <span className="px-1 py-0.2 rounded bg-bg-base text-[9px] text-text-tertiary uppercase">
                              {res.channel}
                            </span>
                          </div>
                          {snippet && (
                            <p className="text-[10px] text-text-tertiary line-clamp-1 italic">
                              &ldquo;{snippet}&rdquo;
                            </p>
                          )}
                          <div className="text-[9px] text-text-tertiary mt-0.5">
                            {res.total_messages} messages
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : (
              <>
                {/* Projects Section */}
                <div>
                  <div className="flex items-center justify-between px-2 mb-1">
                    <span className="text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
                      Projects
                    </span>
                    <button
                      title="New Project"
                      onClick={() => handleNavigate({ id: 'projects', path: '#projects' })}
                      aria-label="New Project"
                      className="text-text-tertiary hover:text-text-primary p-0.5 rounded"
                    >
                      <FolderPlus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="space-y-0.5">
                    {displayProjects.length === 0 ? (
                      <div className="px-2 py-1 text-[11px] text-text-tertiary">
                        No projects yet
                      </div>
                    ) : (
                      displayProjects.map((p) => (
                        <button
                          key={p.id}
                          onClick={() => handleNavigate({ id: 'projects', path: '#projects' })}
                          className="w-full flex items-center justify-between px-2 py-1 rounded-md text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover/60 transition-colors"
                        >
                          <span className="truncate flex items-center gap-1.5">
                            <FolderKanban className="w-3.5 h-3.5 text-text-tertiary flex-shrink-0" />
                            <span className="truncate">{p.name}</span>
                          </span>
                          <span className="text-[10px] text-text-tertiary font-mono">{p.threadCount}</span>
                        </button>
                      ))
                    )}
                  </div>
                </div>

                {/* Recent Chats */}
                <div>
                  <div className="px-2 mb-1 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
                    Recent Chats
                  </div>
                  <div className="space-y-0.5">
                    {displayChats.length === 0 ? (
                      <div className="px-2 py-1 text-[11px] text-text-tertiary">
                        No recent sessions
                      </div>
                    ) : (
                      displayChats.map((c) => {
                        const isSelected = activeSessionId === c.id;
                        return (
                          <button
                            key={c.id}
                            onClick={() => {
                              onSelectSession?.(c.id);
                              handleNavigate({ id: 'home', path: '#home' });
                            }}
                            aria-selected={isSelected}
                            className={`w-full flex items-center justify-between px-2 py-1 rounded-md text-xs transition-colors ${
                              isSelected
                                ? 'bg-accent/15 text-accent font-medium border-l-2 border-accent'
                                : 'text-text-secondary hover:text-text-primary hover:bg-bg-hover/60'
                            }`}
                          >
                            <span className="truncate flex items-center gap-1.5">
                              <MessageSquare className="w-3.5 h-3.5 text-text-tertiary flex-shrink-0" />
                              <span className="truncate text-left">{c.title}</span>
                            </span>
                            <span className="text-[10px] text-text-tertiary flex-shrink-0 ml-1">{c.updatedAt}</span>
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Zone C: User Profile & Settings Footer */}
      <div className="p-2 border-t border-border-subtle bg-bg-elevated">
        <div className="flex items-center justify-between p-1.5 rounded-md hover:bg-bg-hover transition-colors">
          <div
            onClick={() => handleNavigate({ id: 'profile', path: '#profile' })}
            className="flex items-center gap-2 overflow-hidden cursor-pointer"
          >
            <div className="relative flex-shrink-0">
              <div className="w-6 h-6 rounded-full bg-border-strong flex items-center justify-center text-[11px] font-medium text-text-primary">
                N
              </div>
              <span className="absolute bottom-0 right-0 w-2 h-2 rounded-full bg-emerald-400 ring-2 ring-bg-elevated" />
            </div>
            {!collapsed && (
              <div className="truncate text-left">
                <div className="text-xs font-medium text-text-primary truncate">Nadir</div>
                <div className="text-[10px] text-text-tertiary truncate">nadir@local</div>
              </div>
            )}
          </div>
          {!collapsed && (
            <button
              onClick={() => handleNavigate({ id: 'settings', path: '#settings' })}
              title="Settings"
              aria-label="Settings"
              className="p-1 text-text-tertiary hover:text-text-primary rounded transition-colors"
            >
              <SettingsIcon className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </aside>
  );
};
