import React from 'react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { Mode, ModelTier, SidecarHealth, PrivacyBoundary, RoutingObjective } from '../types';
import { AppRoute } from '../routes';

interface LayoutProps {
  currentRoute?: AppRoute;
  activeMode: Mode;
  onSelectMode: (mode: Mode) => void;
  onNavigate?: (route: AppRoute) => void;
  activeSessionId?: string;
  onSelectSession?: (sessionId: string) => void;
  activeModel?: ModelTier;
  onSelectModel?: (model: ModelTier) => void;
  routingObjective?: RoutingObjective;
  onSelectRoutingObjective?: (objective: RoutingObjective) => void;
  privacyBoundary?: PrivacyBoundary;
  onSelectPrivacyBoundary?: (boundary: PrivacyBoundary) => void;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onNewChat: () => void;
  health: SidecarHealth;
  isBusy?: boolean;
  projectName?: string;
  onOpenDiagnostics?: () => void;
  children: React.ReactNode;
}

export const Layout: React.FC<LayoutProps> = ({
  currentRoute,
  activeMode,
  onSelectMode,
  onNavigate,
  activeSessionId,
  onSelectSession,
  activeModel,
  onSelectModel,
  routingObjective,
  onSelectRoutingObjective,
  privacyBoundary,
  onSelectPrivacyBoundary,
  sidebarCollapsed,
  onToggleSidebar,
  onNewChat,
  health,
  isBusy,
  projectName,
  onOpenDiagnostics,
  children,
}) => {
  return (
    <div className="flex h-screen w-screen bg-bg-base overflow-hidden">
      {/* 3-Zone Sidebar */}
      <Sidebar
        currentRoute={currentRoute}
        activeMode={activeMode}
        onSelectMode={onSelectMode}
        onNavigate={onNavigate}
        activeSessionId={activeSessionId}
        onSelectSession={onSelectSession}
        collapsed={sidebarCollapsed}
        onToggleCollapse={onToggleSidebar}
        onNewChat={onNewChat}
      />

      {/* Main Shell Viewport */}
      <div className="flex-1 flex flex-col h-full overflow-hidden">
        <TopBar
          currentRoute={currentRoute}
          activeMode={activeMode}
          activeModel={activeModel}
          onSelectModel={onSelectModel}
          routingObjective={routingObjective}
          onSelectRoutingObjective={onSelectRoutingObjective}
          privacyBoundary={privacyBoundary}
          onSelectPrivacyBoundary={onSelectPrivacyBoundary}
          health={health}
          isBusy={isBusy}
          projectName={projectName}
          onOpenDiagnostics={onOpenDiagnostics}
        />
        <main className="flex-1 overflow-hidden bg-bg-base relative">
          {children}
        </main>
      </div>
    </div>
  );
};
