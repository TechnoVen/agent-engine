import React from 'react';
import {
  Sparkles,
  Clock,
  Zap,
  GitBranch,
  Code2,
  Search,
  FileText,
  Table2,
  Presentation,
  Globe,
  Palette,
  Network,
  Radio,
  Puzzle,
  Users,
  CircleDollarSign,
  ShieldCheck,
  Gauge,
  Plus,
  PanelLeftClose,
  PanelLeftOpen,
  Settings as SettingsIcon,
  FolderPlus,
  FolderKanban,
  MessageSquare,
} from 'lucide-react';
import { Mode, Project, RecentChat } from '../types';

interface SidebarProps {
  activeMode: Mode;
  onSelectMode: (mode: Mode) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onNewChat: () => void;
  projects?: Project[];
  recentChats?: RecentChat[];
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeMode,
  onSelectMode,
  collapsed,
  onToggleCollapse,
  onNewChat,
  projects = [
    { id: '1', name: 'Organiser Workspace', icon: 'folder', threadCount: 8, lastActivity: '2h ago' },
    { id: '2', name: 'Client Website', icon: 'folder', threadCount: 3, lastActivity: '1d ago' },
  ],
  recentChats = [
    { id: 'c1', title: 'Saturday Party Planning', mode: 'home', updatedAt: 'Just now' },
    { id: 'c2', title: 'Invoice March 2026', mode: 'sheets', updatedAt: '2h ago' },
    { id: 'c3', title: 'Book Chapter 4', mode: 'docs', updatedAt: 'Yesterday' },
  ],
}) => {
  const primaryModes: { id: Mode; label: string; icon: React.ReactNode }[] = [
    { id: 'agent', label: 'My Agent', icon: <Sparkles className="w-4 h-4 text-accent" /> },
    { id: 'tasks', label: 'Scheduled Tasks', icon: <Clock className="w-4 h-4 text-text-secondary" /> },
    { id: 'swarm', label: 'Swarm', icon: <Zap className="w-4 h-4 text-warning" /> },
    { id: 'workflows', label: 'Workflows', icon: <GitBranch className="w-4 h-4 text-text-secondary" /> },
  ];

  const capabilityModes: { id: Mode; label: string; icon: React.ReactNode }[] = [
    { id: 'code', label: 'Code', icon: <Code2 className="w-4 h-4 text-text-secondary" /> },
    { id: 'deep-research', label: 'Deep Research', icon: <Search className="w-4 h-4 text-text-secondary" /> },
    { id: 'docs', label: 'Docs', icon: <FileText className="w-4 h-4 text-text-secondary" /> },
    { id: 'sheets', label: 'Sheets', icon: <Table2 className="w-4 h-4 text-text-secondary" /> },
    { id: 'slides', label: 'Slides', icon: <Presentation className="w-4 h-4 text-text-secondary" /> },
    { id: 'websites', label: 'Websites', icon: <Globe className="w-4 h-4 text-text-secondary" /> },
    { id: 'design', label: 'Design', icon: <Palette className="w-4 h-4 text-text-secondary" /> },
    { id: 'diagrams', label: 'Diagrams', icon: <Network className="w-4 h-4 text-text-secondary" /> },
  ];

  const agentSections: { id: Mode; label: string; icon: React.ReactNode }[] = [
    { id: 'channels', label: 'Channels', icon: <Radio className="w-4 h-4 text-text-secondary" /> },
    { id: 'skills', label: 'Skills & Adapters', icon: <Puzzle className="w-4 h-4 text-text-secondary" /> },
    { id: 'marketplace', label: 'Marketplace', icon: <Users className="w-4 h-4 text-text-secondary" /> },
  ];

  const opSections: { id: Mode; label: string; icon: React.ReactNode }[] = [
    { id: 'cost', label: 'Cost', icon: <CircleDollarSign className="w-4 h-4 text-success" /> },
    { id: 'policies', label: 'Policies & Approvals', icon: <ShieldCheck className="w-4 h-4 text-text-secondary" /> },
    { id: 'benchmarks', label: 'Benchmarks', icon: <Gauge className="w-4 h-4 text-text-secondary" /> },
  ];

  return (
    <aside
      className={`h-full bg-bg-elevated border-r border-border-subtle flex flex-col justify-between select-none panel-transition ${
        collapsed ? 'w-16' : 'w-[280px]'
      }`}
    >
      {/* Zone A: Global Actions */}
      <div className="p-3 border-b border-border-subtle flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <div
            onClick={() => onSelectMode('home')}
            className="flex items-center gap-2 cursor-pointer group"
          >
            <div className="w-7 h-7 rounded-md bg-accent flex items-center justify-center font-bold text-xs text-white shadow-sm group-hover:bg-accent-hover transition-colors">
              AE
            </div>
            {!collapsed && (
              <span className="font-semibold text-sm tracking-tight text-text-primary">
                Agent Engine
              </span>
            )}
          </div>
          <button
            onClick={onToggleCollapse}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="p-1.5 rounded-md hover:bg-bg-hover text-text-tertiary hover:text-text-primary transition-colors"
          >
            {collapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
          </button>
        </div>

        {/* New Chat Button (Ctrl+K) */}
        <button
          onClick={onNewChat}
          className="w-full flex items-center justify-between px-3 py-2 bg-accent/10 hover:bg-accent/20 border border-accent/20 hover:border-accent/40 rounded-lg text-accent text-sm font-medium transition-all group"
        >
          <div className="flex items-center gap-2">
            <Plus className="w-4 h-4" />
            {!collapsed && <span>New Chat</span>}
          </div>
          {!collapsed && (
            <kbd className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-bg-base border border-border-strong text-text-tertiary group-hover:text-text-secondary">
              Ctrl K
            </kbd>
          )}
        </button>
      </div>

      {/* Zone B: Mode Navigation (Scrollable) */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden p-2 space-y-4">
        {/* Core items */}
        <div className="space-y-0.5">
          {primaryModes.map((item) => {
            const isActive = activeMode === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onSelectMode(item.id)}
                title={collapsed ? item.label : undefined}
                className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition-colors ${
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

        {/* Capabilities Section */}
        <div>
          {!collapsed && (
            <div className="px-2.5 mb-1.5 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
              Modes
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
                  className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition-colors ${
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

        {/* Agents & Channels */}
        <div>
          {!collapsed && (
            <div className="px-2.5 mb-1.5 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
              Agents
            </div>
          )}
          <div className="space-y-0.5">
            {agentSections.map((item) => {
              const isActive = activeMode === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onSelectMode(item.id)}
                  title={collapsed ? item.label : undefined}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition-colors ${
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

        {/* Operations */}
        <div>
          {!collapsed && (
            <div className="px-2.5 mb-1.5 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
              Operations
            </div>
          )}
          <div className="space-y-0.5">
            {opSections.map((item) => {
              const isActive = activeMode === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onSelectMode(item.id)}
                  title={collapsed ? item.label : undefined}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-sm transition-colors ${
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

        {/* Projects Section */}
        {!collapsed && (
          <div>
            <div className="flex items-center justify-between px-2.5 mb-1.5">
              <span className="text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
                Projects
              </span>
              <button
                title="New Project"
                onClick={() => onSelectMode('projects')}
                className="text-text-tertiary hover:text-text-primary"
              >
                <FolderPlus className="w-3.5 h-3.5" />
              </button>
            </div>
            <div className="space-y-0.5">
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => onSelectMode('projects')}
                  className="w-full flex items-center justify-between px-2.5 py-1 rounded-md text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover/60 transition-colors"
                >
                  <span className="truncate flex items-center gap-1.5">
                    <FolderKanban className="w-3.5 h-3.5 text-text-tertiary flex-shrink-0" />
                    <span>{p.name}</span>
                  </span>
                  <span className="text-[10px] text-text-tertiary">{p.threadCount}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Recent Chats */}
        {!collapsed && (
          <div>
            <div className="px-2.5 mb-1.5 text-[10px] font-semibold tracking-wider text-text-tertiary uppercase">
              Recent Chats
            </div>
            <div className="space-y-0.5">
              {recentChats.map((c) => (
                <button
                  key={c.id}
                  onClick={() => onSelectMode(c.mode)}
                  className="w-full flex items-center gap-2 px-2.5 py-1 rounded-md text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover/60 transition-colors"
                >
                  <MessageSquare className="w-3 h-3 text-text-tertiary flex-shrink-0" />
                  <span className="truncate text-left">{c.title}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Zone C: User Profile Footer */}
      <div className="p-2 border-t border-border-subtle bg-bg-elevated">
        <div className="flex items-center justify-between p-1.5 rounded-lg hover:bg-bg-hover transition-colors">
          <div className="flex items-center gap-2 overflow-hidden">
            <div className="relative flex-shrink-0">
              <div className="w-7 h-7 rounded-full bg-border-strong flex items-center justify-center text-xs font-medium text-text-primary">
                N
              </div>
              <span className="absolute bottom-0 right-0 w-2 h-2 rounded-full bg-success ring-2 ring-bg-elevated" />
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
              className="p-1 text-text-tertiary hover:text-text-primary rounded"
            >
              <SettingsIcon className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </aside>
  );
};
