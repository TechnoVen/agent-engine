import React from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { Mode, ModelTier, SidecarHealth } from '../types';

interface LayoutProps {
  activeMode: Mode;
  onSelectMode: (mode: Mode) => void;
  activeSessionId?: string;
  onSelectSession?: (sessionId: string) => void;
  activeModel: ModelTier;
  onSelectModel: (model: ModelTier) => void;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onNewChat: () => void;
  health: SidecarHealth;
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({
  activeMode,
  onSelectMode,
  activeSessionId,
  onSelectSession,
  activeModel,
  onSelectModel,
  sidebarCollapsed,
  onToggleSidebar,
  onNewChat,
  health,
  children,
}) => {
  return (
    <div className="flex h-screen w-screen bg-bg-base overflow-hidden">
      {/* 3-Zone Sidebar */}
      <Sidebar
        activeMode={activeMode}
        onSelectMode={onSelectMode}
        activeSessionId={activeSessionId}
        onSelectSession={onSelectSession}
        collapsed={sidebarCollapsed}
        onToggleCollapse={onToggleSidebar}
        onNewChat={onNewChat}
      />

      {/* Main Shell Viewport */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        <TopBar
          activeMode={activeMode}
          activeModel={activeModel}
          onSelectModel={onSelectModel}
          health={health}
        />
        <main className="flex-1 overflow-hidden bg-bg-base relative">
          {children}
        </main>
      </div>
    </div>
  );
};
