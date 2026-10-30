import React, { useState, useEffect } from 'react';
import {
  BookOpen,
  Search,
  FileText,
  Brain,
  Plus,
  RefreshCw,
  Info,
} from 'lucide-react';
import { sidecarClient } from '../api/client';

export type KnowledgeCategory = 'all' | 'documents' | 'sources' | 'memory' | 'procedures' | 'project';

export interface KnowledgeItem {
  id: string;
  title: string;
  category: 'document' | 'source' | 'memory' | 'procedure' | 'project';
  snippet: string;
  source: string;
  scope: string;
  updatedAt: string;
  origin?: string;
  metadata?: Record<string, any>;
}

export const Knowledge: React.FC = () => {
  const [activeTab, setActiveTab] = useState<KnowledgeCategory>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<KnowledgeItem | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [newContent, setNewContent] = useState('');
  const [newCategory, setNewCategory] = useState<'document' | 'memory'>('document');
  const [newTitle, setNewTitle] = useState('');

  const loadKnowledge = async (showIndicator = false) => {
    if (showIndicator) setIsRefreshing(true);
    else setIsLoading(true);

    try {
      // Query real observational memory and documents
      const query = searchQuery.trim() || 'knowledge document memory';
      const obs = await sidecarClient.queryObservations(query, 50);

      const parsed: KnowledgeItem[] = (obs || []).map((o: any, idx: number) => {
        const cat = o.category === 'rag_document' ? 'document' : 'memory';
        const titleMatch = o.content.match(/^\[(.*?)\]/);
        const title = titleMatch
          ? titleMatch[1]
          : `${cat === 'document' ? 'Document' : 'Memory'} #${o.id || idx + 1}`;
        const cleanSnippet = o.content.replace(/^\[.*?\]\s*/, '');

        return {
          id: String(o.id || `k-${idx}`),
          title,
          category: cat,
          snippet: cleanSnippet.slice(0, 300),
          source: o.metadata?.filename || o.metadata?.source || (cat === 'document' ? 'File upload' : 'Session observer'),
          scope: o.session_id ? `Session ${o.session_id}` : 'Global workspace',
          updatedAt: o.created_at ? new Date(o.created_at).toLocaleString() : 'Recent',
          origin: o.metadata?.type || 'AST / Observer',
          metadata: o.metadata || {},
        };
      });

      setItems(parsed);
      if (parsed.length > 0 && !selectedItem) {
        setSelectedItem(parsed[0]);
      }
    } catch {
      setItems([]);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  };

  useEffect(() => {
    loadKnowledge();
  }, [searchQuery]);

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newContent.trim()) return;

    try {
      if (newCategory === 'document') {
        await sidecarClient.ingestMemory(newContent.trim(), newTitle.trim() || 'Manual Document');
      } else {
        await sidecarClient.observeMemory({
          content: `[${newTitle.trim() || 'User Memory'}]\n${newContent.trim()}`,
          category: 'user_preference',
          metadata: { source: 'Operator Entry' },
        });
      }
      setAddModalOpen(false);
      setNewContent('');
      setNewTitle('');
      await loadKnowledge(true);
    } catch (err) {
      console.error('Failed to save knowledge item', err);
    }
  };

  const filteredItems = items.filter((item) => {
    if (activeTab === 'all') return true;
    if (activeTab === 'documents') return item.category === 'document';
    if (activeTab === 'memory') return item.category === 'memory';
    if (activeTab === 'sources') return item.category === 'source';
    if (activeTab === 'procedures') return item.category === 'procedure';
    if (activeTab === 'project') return item.category === 'project';
    return true;
  });

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="knowledge-screen">
      {/* Workspace Header */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <BookOpen className="w-4 h-4 text-accent" />
          <h1 className="text-sm font-semibold tracking-tight text-text-primary">Knowledge Workspace</h1>
          <span className="text-[11px] font-mono text-text-tertiary">
            ({filteredItems.length} {filteredItems.length === 1 ? 'item' : 'items'})
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => loadKnowledge(true)}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
          <button
            type="button"
            onClick={() => setAddModalOpen(true)}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>Add Item</span>
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="px-4 py-2.5 border-b border-border-subtle bg-bg-elevated/50 flex flex-wrap items-center justify-between gap-3">
        {/* Category Tabs */}
        <div className="flex items-center gap-1 bg-bg-base p-0.5 rounded-md border border-border-subtle text-xs">
          {(
            [
              { id: 'all', label: 'All' },
              { id: 'documents', label: 'Documents' },
              { id: 'sources', label: 'Sources' },
              { id: 'project', label: 'Project' },
              { id: 'memory', label: 'Memory' },
              { id: 'procedures', label: 'Procedures' },
            ] as { id: KnowledgeCategory; label: string }[]
          ).map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setActiveTab(tab.id)}
              className={`px-2.5 py-1 rounded transition-colors text-xs font-medium ${
                activeTab === tab.id
                  ? 'bg-bg-elevated text-text-primary shadow-xs'
                  : 'text-text-tertiary hover:text-text-secondary'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search Input */}
        <div className="relative w-64">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search knowledge & memory..."
            className="w-full pl-8 pr-3 py-1 bg-bg-base border border-border-subtle rounded text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
          />
        </div>
      </div>

      {/* Main 2-Pane Content Area: List + Inspector */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: List Pane */}
        <div className="w-1/2 border-r border-border-subtle overflow-y-auto p-3 space-y-2">
          {isLoading ? (
            <div className="py-16 text-center text-xs text-text-tertiary">
              <RefreshCw className="w-5 h-5 mx-auto animate-spin mb-2 text-accent" />
              Loading knowledge records...
            </div>
          ) : activeTab === 'procedures' || activeTab === 'sources' || activeTab === 'project' ? (
            <div className="py-12 px-4 text-center">
              <div className="w-10 h-10 rounded-lg bg-bg-elevated border border-border-subtle mx-auto flex items-center justify-center text-text-tertiary mb-3">
                <Info className="w-5 h-5" />
              </div>
              <h3 className="text-xs font-semibold text-text-primary capitalize mb-1">
                {activeTab} Management
              </h3>
              <p className="text-[11px] text-text-tertiary max-w-sm mx-auto mb-3">
                {activeTab === 'procedures' && 'Procedures & runbooks execution runtime is not available yet.'}
                {activeTab === 'sources' && 'Connected data sources & connectors runtime is not available yet.'}
                {activeTab === 'project' && 'Project-specific workspace context is linked via active project settings.'}
              </p>
              <span className="inline-block px-2 py-0.5 rounded bg-bg-elevated border border-border-subtle text-[10px] font-mono text-warning">
                Runtime not available yet
              </span>
            </div>
          ) : filteredItems.length === 0 ? (
            <div className="py-16 text-center text-xs text-text-tertiary" data-testid="knowledge-empty-state">
              <BookOpen className="w-8 h-8 mx-auto text-text-tertiary/50 mb-2" />
              <div className="font-medium text-text-secondary">No knowledge records indexed</div>
              <div className="text-[11px] mt-1 max-w-xs mx-auto text-text-tertiary">
                {searchQuery
                  ? `No records matching "${searchQuery}".`
                  : 'Add documents, session groundings, or operator memories to view them here.'}
              </div>
            </div>
          ) : (
            filteredItems.map((item) => {
              const isSelected = selectedItem?.id === item.id;
              return (
                <div
                  key={item.id}
                  onClick={() => setSelectedItem(item)}
                  className={`p-3 rounded-lg border cursor-pointer transition-all ${
                    isSelected
                      ? 'bg-bg-elevated border-accent shadow-xs'
                      : 'bg-bg-elevated/50 border-border-subtle hover:border-border-strong hover:bg-bg-elevated'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-1.5 font-medium text-xs text-text-primary truncate">
                      {item.category === 'document' ? (
                        <FileText className="w-3.5 h-3.5 text-accent flex-shrink-0" />
                      ) : (
                        <Brain className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                      )}
                      <span className="truncate">{item.title}</span>
                    </div>
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-text-tertiary uppercase flex-shrink-0">
                      {item.category}
                    </span>
                  </div>
                  <p className="text-[11px] text-text-secondary line-clamp-2 leading-relaxed mb-2 font-mono">
                    {item.snippet}
                  </p>
                  <div className="flex items-center justify-between text-[10px] text-text-tertiary font-mono pt-1 border-t border-border-subtle/50">
                    <span className="truncate mr-2">Src: {item.source}</span>
                    <span className="flex-shrink-0">{item.updatedAt}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Right: Inspector Pane */}
        <div className="w-1/2 overflow-y-auto p-4 bg-bg-elevated/20">
          {selectedItem ? (
            <div className="space-y-4">
              <div className="pb-3 border-b border-border-subtle">
                <div className="flex items-center gap-2 text-[10px] font-mono text-text-tertiary uppercase mb-1">
                  <span>Knowledge Provenance</span>
                  <span>•</span>
                  <span className="text-accent">{selectedItem.category}</span>
                </div>
                <h2 className="text-base font-semibold text-text-primary">
                  {selectedItem.title}
                </h2>
              </div>

              {/* Factual Provenance Metadata */}
              <div className="space-y-2 bg-bg-elevated p-3 rounded-lg border border-border-subtle text-xs">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary mb-1">
                  Provenance Details
                </div>
                <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                  <div>
                    <span className="text-text-tertiary block">Source</span>
                    <span className="text-text-primary font-medium">{selectedItem.source}</span>
                  </div>
                  <div>
                    <span className="text-text-tertiary block">Scope</span>
                    <span className="text-text-primary font-medium">{selectedItem.scope}</span>
                  </div>
                  <div>
                    <span className="text-text-tertiary block">Updated</span>
                    <span className="text-text-primary font-medium">{selectedItem.updatedAt}</span>
                  </div>
                  <div>
                    <span className="text-text-tertiary block">Origin</span>
                    <span className="text-text-primary font-medium">{selectedItem.origin || 'Observer'}</span>
                  </div>
                </div>
              </div>

              {/* Document / Observation Content */}
              <div className="space-y-1.5">
                <div className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                  Content Preview
                </div>
                <div className="p-3 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-secondary whitespace-pre-wrap leading-relaxed max-h-80 overflow-y-auto">
                  {selectedItem.snippet}
                </div>
              </div>
            </div>
          ) : (
            <div className="py-24 text-center text-xs text-text-tertiary">
              Select an item on the left to inspect its provenance and content.
            </div>
          )}
        </div>
      </div>

      {/* Add Item Modal */}
      {addModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-bg-elevated border border-border-strong rounded-xl p-5 max-w-md w-full shadow-2xl space-y-4">
            <h3 className="text-sm font-semibold text-text-primary">Add Knowledge Item</h3>
            <form onSubmit={handleAddSubmit} className="space-y-3">
              <div>
                <label className="text-xs text-text-secondary block mb-1">Category</label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => setNewCategory('document')}
                    className={`flex-1 py-1.5 text-xs rounded border transition-colors ${
                      newCategory === 'document'
                        ? 'bg-accent/15 border-accent text-accent font-medium'
                        : 'bg-bg-base border-border-subtle text-text-secondary'
                    }`}
                  >
                    Document (Vector RAG)
                  </button>
                  <button
                    type="button"
                    onClick={() => setNewCategory('memory')}
                    className={`flex-1 py-1.5 text-xs rounded border transition-colors ${
                      newCategory === 'memory'
                        ? 'bg-accent/15 border-accent text-accent font-medium'
                        : 'bg-bg-base border-border-subtle text-text-secondary'
                    }`}
                  >
                    Memory (Observation)
                  </button>
                </div>
              </div>
              <div>
                <label className="text-xs text-text-secondary block mb-1">Title</label>
                <input
                  type="text"
                  value={newTitle}
                  onChange={(e) => setNewTitle(e.target.value)}
                  placeholder="e.g. API Specification or User Requirement"
                  className="w-full px-3 py-1.5 bg-bg-base border border-border-subtle rounded text-xs text-text-primary focus:outline-none focus:border-accent"
                />
              </div>
              <div>
                <label className="text-xs text-text-secondary block mb-1">Content</label>
                <textarea
                  value={newContent}
                  onChange={(e) => setNewContent(e.target.value)}
                  placeholder="Paste document text or user observation..."
                  rows={5}
                  className="w-full px-3 py-1.5 bg-bg-base border border-border-subtle rounded text-xs text-text-primary focus:outline-none focus:border-accent font-mono"
                  required
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setAddModalOpen(false)}
                  className="px-3 py-1.5 rounded border border-border-subtle text-xs text-text-secondary hover:bg-bg-hover"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-3 py-1.5 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium"
                >
                  Save to Knowledge Base
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
