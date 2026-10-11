import React, { useState, useEffect, useRef } from 'react';
import { Layout } from './shell/Layout';
import { Home } from './screens/Home';
import { Agent } from './screens/Agent';
import { Tasks } from './screens/Tasks';
import { Swarm } from './screens/Swarm';
import { Workflows } from './screens/Workflows';
import { Projects } from './screens/Projects';
import { Settings } from './screens/Settings';
import { Policies } from './screens/Policies';
import { Cost } from './screens/Cost';
import { Skills } from './screens/Skills';
import { Knowledge } from './screens/Knowledge';
import { Writing } from './screens/Writing';
import { Research } from './screens/Research';
import { Data } from './screens/Data';
import { Developer } from './screens/Developer';
import { Models } from './screens/Models';
import { Approvals } from './screens/Approvals';
import { Activity } from './screens/Activity';
import {
  CodeMode,
  ResearchMode,
  DocsMode,
  SheetsMode,
  SlidesMode,
  WebsitesMode,
  DesignMode,
  DiagramsMode,
} from './screens/Modes';
import { Mode, ModelTier, SidecarHealth, PrivacyBoundary, RoutingObjective } from './types';
import { sidecarClient } from './api/client';
import { Sparkles } from 'lucide-react';
import { resolveRoute, AppRoute } from './routes';

export const App: React.FC = () => {
  const [currentRoute, setCurrentRoute] = useState<AppRoute>(() => resolveRoute(window.location.hash));
  const activeMode = currentRoute.id as Mode;

  const [activeModel, setActiveModel] = useState<ModelTier>('instant');
  const [routingObjective, setRoutingObjective] = useState<RoutingObjective>('balanced');
  const [privacyBoundary, setPrivacyBoundary] = useState<PrivacyBoundary>('local_only');
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>('c1');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [health, setHealth] = useState<SidecarHealth>({ status: 'healthy' });
  const [isBusy, setIsBusy] = useState(false);
  const [projectName, setProjectName] = useState('Agent Engine');

  const setActiveMode = (mode: Mode | string) => {
    const route = resolveRoute(mode);
    setCurrentRoute(route);
    if (window.location.hash !== route.path) {
      window.location.hash = route.path;
    }
  };

  const handleNavigate = (route: AppRoute) => {
    setCurrentRoute(route);
    if (window.location.hash !== route.path) {
      window.location.hash = route.path;
    }
  };

  useEffect(() => {
    const handleHashChange = () => {
      setCurrentRoute(resolveRoute(window.location.hash));
    };
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const chatInputRef = useRef<HTMLTextAreaElement>(null);

  // Health poll
  useEffect(() => {
    let mounted = true;
    const poll = async () => {
      const h = await sidecarClient.checkHealth();
      if (mounted) setHealth(h);
    };

    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  // Global keyboard shortcuts (Ctrl+K to focus input anywhere)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setActiveMode('home');
        setTimeout(() => {
          chatInputRef.current?.focus();
        }, 30);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleNewChat = () => {
    setActiveMode('home');
    setTimeout(() => {
      chatInputRef.current?.focus();
    }, 30);
  };

  const renderActiveScreen = () => {
    switch (currentRoute.id) {
      case 'home':
        return (
          <Home
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            routingObjective={routingObjective}
            onSelectRoutingObjective={setRoutingObjective}
            privacyBoundary={privacyBoundary}
            onSelectPrivacyBoundary={setPrivacyBoundary}
            inputRef={chatInputRef}
            activeSessionId={activeSessionId}
            onBusyChange={setIsBusy}
            onProjectNameChange={setProjectName}
          />
        );
      case 'knowledge':
        return <Knowledge />;
      case 'writing':
        return <Writing />;
      case 'research':
        return <Research />;
      case 'data':
        return <Data />;
      case 'developer':
        return <Developer />;
      case 'models':
        return <Models />;
      case 'approvals':
        return <Approvals />;
      case 'activity':
        return <Activity />;
      case 'agent':
      case 'profile':
        return (
          <Agent
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'tasks':
        return (
          <Tasks
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'swarm':
        return (
          <Swarm
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'workflows':
      case 'automations':
        return (
          <Workflows
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'projects':
        return (
          <Projects
            onSelectMode={setActiveMode}
            onSelectSession={setActiveSessionId}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'skills':
        return (
          <Skills
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'settings':
        return (
          <Settings
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'policies':
        return (
          <Policies
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'cost':
        return (
          <Cost
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'code':
        return (
          <CodeMode
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'deep-research':
        return (
          <ResearchMode
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'docs':
        return (
          <DocsMode
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'sheets':
        return (
          <SheetsMode
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'slides':
        return (
          <SlidesMode
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'websites':
        return (
          <WebsitesMode
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'design':
        return (
          <DesignMode
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      case 'diagrams':
        return (
          <DiagramsMode
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
          />
        );
      default:
        return (
          <div className="h-full flex flex-col items-center justify-center p-8 text-center select-none">
            <div className="w-14 h-14 rounded-2xl bg-bg-elevated border border-border-strong flex items-center justify-center mb-4 shadow-xl">
              <Sparkles className="w-7 h-7 text-accent" />
            </div>
            <h2 className="text-xl font-bold text-text-primary capitalize mb-2">
              {currentRoute.label}
            </h2>
            <p className="text-sm text-text-secondary max-w-md mb-6 leading-relaxed">
              {currentRoute.description || `Workspace for ${currentRoute.label}. Connected to local sidecar engine.`}
            </p>
            <button
              onClick={handleNewChat}
              className="px-4 py-2 bg-bg-elevated hover:bg-bg-hover border border-border-strong rounded-lg text-xs font-medium text-text-primary transition-all flex items-center gap-2"
            >
              <span>Return to Chat</span>
              <kbd className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-bg-base border border-border-subtle text-text-tertiary">
                Ctrl K
              </kbd>
            </button>
          </div>
        );
    }
  };

  return (
    <Layout
      currentRoute={currentRoute}
      activeMode={activeMode}
      onSelectMode={setActiveMode}
      onNavigate={handleNavigate}
      activeSessionId={activeSessionId}
      onSelectSession={setActiveSessionId}
      activeModel={activeModel}
      onSelectModel={setActiveModel}
      routingObjective={routingObjective}
      onSelectRoutingObjective={setRoutingObjective}
      privacyBoundary={privacyBoundary}
      onSelectPrivacyBoundary={setPrivacyBoundary}
      sidebarCollapsed={sidebarCollapsed}
      onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
      onNewChat={handleNewChat}
      health={health}
      isBusy={isBusy}
      projectName={projectName}
      onOpenDiagnostics={() => setActiveMode('developer')}
    >
      {renderActiveScreen()}
    </Layout>
  );
};
