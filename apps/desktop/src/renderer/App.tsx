import React, { useState, useEffect, useRef } from 'react';
import { Layout } from './shell/Layout';
import { Home } from './screens/Home';
import { Agent } from './screens/Agent';
import { Tasks } from './screens/Tasks';
import { Projects } from './screens/Projects';
import { Settings } from './screens/Settings';
import { Policies } from './screens/Policies';
import { Cost } from './screens/Cost';
import { Skills } from './screens/Skills';
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
import { Mode, ModelTier, SidecarHealth } from './types';
import { sidecarClient } from './api/client';
import { Sparkles } from 'lucide-react';

export const App: React.FC = () => {
  const getHashMode = (): Mode => {
    const raw = window.location.hash.replace('#/', '').replace('#', '');
    const validModes: Mode[] = [
      'home', 'agent', 'tasks', 'swarm', 'workflows', 'code', 'deep-research',
      'docs', 'sheets', 'slides', 'websites', 'design', 'diagrams', 'channels',
      'skills', 'marketplace', 'cost', 'policies', 'benchmarks', 'settings', 'projects'
    ];
    return validModes.includes(raw as Mode) ? (raw as Mode) : 'home';
  };

  const [activeMode, setActiveModeState] = useState<Mode>(getHashMode);
  const [activeModel, setActiveModel] = useState<ModelTier>('instant');
  const [activeSessionId, setActiveSessionId] = useState<string | undefined>('c1');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [health, setHealth] = useState<SidecarHealth>({ status: 'offline' });

  const setActiveMode = (mode: Mode) => {
    setActiveModeState(mode);
    if (window.location.hash !== `#${mode}`) {
      window.location.hash = `#${mode}`;
    }
  };

  useEffect(() => {
    const handleHashChange = () => {
      setActiveModeState(getHashMode());
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
    switch (activeMode) {
      case 'home':
        return (
          <Home
            onSelectMode={setActiveMode}
            activeModel={activeModel}
            onSelectModel={setActiveModel}
            inputRef={chatInputRef}
            activeSessionId={activeSessionId}
          />
        );
      case 'agent':
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
      case 'skills':
        return (
          <Skills
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
              {activeMode.replace('-', ' ')} Mode
            </h2>
            <p className="text-sm text-text-secondary max-w-md mb-6 leading-relaxed">
              Integrated Kimi-style workspace for {activeMode}. Connected to the local-first sidecar engine with automated cost routing.
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
      activeMode={activeMode}
      onSelectMode={setActiveMode}
      activeSessionId={activeSessionId}
      onSelectSession={setActiveSessionId}
      activeModel={activeModel}
      onSelectModel={setActiveModel}
      sidebarCollapsed={sidebarCollapsed}
      onToggleSidebar={() => setSidebarCollapsed(!sidebarCollapsed)}
      onNewChat={handleNewChat}
      health={health}
    >
      {renderActiveScreen()}
    </Layout>
  );
};
