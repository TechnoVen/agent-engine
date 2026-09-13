import React from 'react';
import {
  ArrowRight,
  Code2,
  Search,
  FileText,
  Table2,
  Presentation,
  Globe,
  Palette,
  Network,
  Sparkles,
  Layers,
  Coins,
} from 'lucide-react';
import { Mode } from '../types';

export interface FeaturedCardItem {
  id: string;
  title: string;
  category: string;
  description: string;
  mode: Mode;
  icon?: React.ReactNode;
  iconName?: string;
  estCost?: string;
  prompt: string;
  tags?: string[];
  toolChain?: string[];
}

export interface FeaturedGridProps {
  items: FeaturedCardItem[];
  onSelectCard: (item: FeaturedCardItem) => void;
  columns?: 2 | 3 | 4;
  className?: string;
}

export const renderCardIcon = (iconName?: string, mode?: Mode, className = 'w-4 h-4') => {
  if (iconName) {
    switch (iconName) {
      case 'code':
        return <Code2 className={`${className} text-warning`} />;
      case 'search':
        return <Search className={`${className} text-success`} />;
      case 'docs':
        return <FileText className={`${className} text-accent`} />;
      case 'sheets':
        return <Table2 className={`${className} text-success`} />;
      case 'slides':
        return <Presentation className={`${className} text-warning`} />;
      case 'websites':
        return <Globe className={`${className} text-accent`} />;
      case 'design':
        return <Palette className={`${className} text-accent`} />;
      case 'diagrams':
        return <Network className={`${className} text-accent`} />;
      case 'workflows':
        return <Layers className={`${className} text-accent`} />;
      default:
        return <Sparkles className={`${className} text-accent`} />;
    }
  }

  switch (mode) {
    case 'code':
      return <Code2 className={`${className} text-warning`} />;
    case 'deep-research':
      return <Search className={`${className} text-success`} />;
    case 'docs':
      return <FileText className={`${className} text-accent`} />;
    case 'sheets':
      return <Table2 className={`${className} text-success`} />;
    case 'slides':
      return <Presentation className={`${className} text-warning`} />;
    case 'websites':
      return <Globe className={`${className} text-accent`} />;
    case 'design':
      return <Palette className={`${className} text-accent`} />;
    case 'diagrams':
      return <Network className={`${className} text-accent`} />;
    case 'workflows':
      return <Layers className={`${className} text-accent`} />;
    default:
      return <Sparkles className={`${className} text-accent`} />;
  }
};

export const FeaturedGrid: React.FC<FeaturedGridProps> = ({
  items,
  onSelectCard,
  columns = 3,
  className = '',
}) => {
  const gridColsClass =
    columns === 2
      ? 'grid-cols-1 md:grid-cols-2'
      : columns === 4
      ? 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4'
      : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3';

  return (
    <div className={`grid ${gridColsClass} gap-3 ${className}`}>
      {items.map((item) => {
        const iconElement = item.icon || renderCardIcon(item.iconName, item.mode);
        return (
          <div
            key={item.id}
            role="button"
            tabIndex={0}
            onClick={() => onSelectCard(item)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelectCard(item);
              }
            }}
            aria-label={`Select template: ${item.title}`}
            className="p-4 rounded-xl bg-bg-elevated hover:bg-bg-hover border border-border-subtle hover:border-border-strong cursor-pointer transition-all duration-150 group flex flex-col justify-between text-left focus:outline-none focus:ring-1 focus:ring-accent"
          >
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono text-text-tertiary uppercase tracking-wider">
                  {item.category}
                </span>
                <div className="p-1 rounded-md bg-bg-base border border-border-subtle group-hover:border-accent/40 transition-colors">
                  {iconElement}
                </div>
              </div>

              <h3 className="text-xs font-semibold text-text-primary group-hover:text-accent transition-colors leading-snug">
                {item.title}
              </h3>

              <p className="text-[11px] text-text-secondary leading-relaxed line-clamp-2">
                {item.description}
              </p>

              {item.tags && item.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 pt-1">
                  {item.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.2 rounded bg-bg-base border border-border-subtle text-[9px] font-mono text-text-tertiary"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>

            <div className="pt-3 mt-3 border-t border-border-subtle/60 flex items-center justify-between text-[10px] font-mono text-text-tertiary">
              <div className="flex items-center gap-1">
                <Coins className="w-3 h-3 text-success/80" />
                <span>{item.estCost || '$0.0002'}</span>
              </div>
              <div className="flex items-center gap-1 text-accent font-medium group-hover:translate-x-0.5 transition-transform">
                <span>Run</span>
                <ArrowRight className="w-3 h-3" />
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
