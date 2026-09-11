import React, { useState, useEffect } from 'react';
import { Layout } from './shell/Layout';
import { Home } from './screens/Home';
import { Mode, ModelTier, SidecarHealth } from './types';
import { sidecarClient } from './api/client';
import { Sparkles } from 'lucide-react';

export const App: React.FC = () => {
  const [activeMode, setActiveMode] = useState<Mode>('home');
  const [activeModel, setActiveModel] = useState<ModelTier>('instant');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [health, setHealth] = useState<SidecarHealth>({ status: 'offline' });

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

  // Global keyboard shortcuts (Ctrl+K)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setActiveMode('home');
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleNewChat = () => {
    setActiveMode('home');
  };

  const renderActiveScreen = () => {
    switch (activeMode) {
      case 'home':
        return <Home onSelectMode={setActiveMode} activeModel={activeModel} />;
      default:
        return (
          <div className="h-full flex flex-col items-center justify-center p-8 text-center">
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
              onClick={() => setActiveMode('home')}
              className="px-4 py-2 bg-bg-elevated hover:bg-bg-hover border border-border-strong rounded-lg text-xs font-medium text-text-primary transition-all"
            >
              Return to Chat (Ctrl+K)
            </button>
          </div>
        );
    }
  };

  return (
    <Layout
      activeMode={activeMode}
      onSelectMode={setActiveMode}
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
