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

interface SidebarProps {
  activeMode: Mode;
  onSelectMode: (mode: Mode) => void;
  activeSessionId?: string;
  onSelectSession?: (sessionId: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNewChat: () => void;
  projects?: Project[];
  recentChats?: RecentChat[];
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeMode,
  onSelectMode,
  activeSessionId,
  onSelectSession,
  collapsed,
  onToggleCollapse,
  onNewChat,
  projects = [
    { id: '1', name: 'Agent Engine', icon: 'folder', threadCount: 12, lastActivity: '18m ago' },
    { id: '2', name: 'Organiser Workspace', icon: 'folder', threadCount: 8, lastActivity: '2h ago' },
    { id: '3', name: 'Client Website', icon: 'folder', threadCount: 3, lastActivity: '1d ago' },
  ],
  recentChats = [
    { id: 'c1', title: 'Agent Engine architecture review', mode: 'home', updatedAt: '18m ago' },
    { id: 'c2', title: 'THE DEN opening checklist', mode: 'sheets', updatedAt: 'Yesterday' },
    { id: 'c3', title: 'Article draft: Local AI', mode: 'docs', updatedAt: '2d ago' },
  ],
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SessionSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

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
  const primaryModes: { id: Mode; label: string; icon: React.ReactNode }[] = [
    { id: 'home', label: 'Home', icon: <HomeIcon className="w-4 h-4 text-text-secondary" /> },
    { id: 'projects', label: 'Projects', icon: <FolderKanban className="w-4 h-4 text-text-secondary" /> },
    { id: 'tasks', label: 'Tasks', icon: <Clock className="w-4 h-4 text-text-secondary" /> },
    { id: 'workflows', label: 'Automations', icon: <GitBranch className="w-4 h-4 text-text-secondary" /> },
  ];

  // Canonical TOOLS section
  const capabilityModes: { id: Mode; label: string; icon: React.ReactNode }[] = [
    { id: 'deep-research', label: 'Research', icon: <Search className="w-4 h-4 text-text-secondary" /> },
    { id: 'docs', label: 'Writing', icon: <FileText className="w-4 h-4 text-text-secondary" /> },
    { id: 'sheets', label: 'Data', icon: <Table2 className="w-4 h-4 text-text-secondary" /> },
    { id: 'code', label: 'Developer', icon: <Code2 className="w-4 h-4 text-text-secondary" /> },
  ];

  // Canonical LIBRARY section
  const libraryModes: { id: Mode; label: string; icon: React.ReactNode }[] = [
    { id: 'docs', label: 'Knowledge', icon: <BookOpen className="w-4 h-4 text-text-secondary" /> },
    { id: 'skills', label: 'Skills', icon: <Puzzle className="w-4 h-4 text-text-secondary" /> },
  ];

  // Canonical SYSTEM section
  const systemModes: { id: Mode; label: string; icon: React.ReactNode }[] = [
    { id: 'cost', label: 'Activity', icon: <Activity className="w-4 h-4 text-text-secondary" /> },
    { id: 'policies', label: 'Approvals', icon: <ShieldCheck className="w-4 h-4 text-text-secondary" /> },
    { id: 'benchmarks', label: 'Models', icon: <Gauge className="w-4 h-4 text-text-secondary" /> },
  ];

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
              const isActive = activeMode === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onSelectMode(item.id)}
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
              const isActive = activeMode === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onSelectMode(item.id)}
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
              const isActive = activeMode === item.id;
              return (
                <button
                  key={`${item.id}-${idx}`}
                  onClick={() => onSelectMode(item.id)}
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
              const isActive = activeMode === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onSelectMode(item.id)}
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
              onClick={() => onSelectMode('projects')}
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
                      onClick={() => onSelectMode('projects')}
                      aria-label="New Project"
                      className="text-text-tertiary hover:text-text-primary p-0.5 rounded"
                    >
                      <FolderPlus className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="space-y-0.5">
                    {projects.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => onSelectMode('projects')}
                        className="w-full flex items-center justify-between px-2 py-1 rounded-md text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover/60 transition-colors"
                      >
                        <span className="truncate flex items-center gap-1.5">
                          <FolderKanban className="w-3.5 h-3.5 text-text-tertiary flex-shrink-0" />
                          <span className="truncate">{p.name}</span>
                        </span>
                        <span className="text-[10px] text-text-tertiary font-mono">{p.threadCount}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Recent Chats */}
                <div>
                  <div className="px-2 mb-1 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
                    Recent
                  </div>
                  <div className="space-y-0.5">
                    {recentChats.map((c) => {
                      const isSelected = activeSessionId === c.id;
                      return (
                        <button
                          key={c.id}
                          onClick={() => {
                            onSelectSession?.(c.id);
                            onSelectMode(c.mode);
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
                    })}
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
          <div className="flex items-center gap-2 overflow-hidden">
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
              onClick={() => onSelectMode('settings')}
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
