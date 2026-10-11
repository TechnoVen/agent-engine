import React, { useState, useRef, useEffect } from 'react';
import {
  Table2,
  Upload,
  Download,
  Search,
  Loader2,
  Sparkles,
} from 'lucide-react';
import { sidecarClient } from '../api/client';

interface DataRow {
  [key: string]: string | number;
}

const DEFAULT_COLUMNS = ['model', 'provider', 'prompt_tokens', 'completion_tokens', 'cost_usd', 'latency_ms'];

const DEFAULT_ROWS: DataRow[] = [];

export const Data: React.FC = () => {
  const [columns, setColumns] = useState<string[]>(DEFAULT_COLUMNS);
  const [rows, setRows] = useState<DataRow[]>(DEFAULT_ROWS);
  const [filterText, setFilterText] = useState('');
  const [analysisPrompt, setAnalysisPrompt] = useState('');
  const [analysisResult, setAnalysisResult] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [datasetName, setDatasetName] = useState('Dataset');

  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let mounted = true;
    const loadTelemetryData = async () => {
      try {
        const metrics = await sidecarClient.getCostMetrics('day');
        if (mounted && metrics && Array.isArray((metrics as any).breakdown) && (metrics as any).breakdown.length > 0) {
          const telemetryRows = (metrics as any).breakdown.map((b: any) => ({
            group: b.group || 'day',
            calls: b.calls ?? 0,
            prompt_tokens: b.prompt_tokens ?? 0,
            completion_tokens: b.completion_tokens ?? 0,
            total_tokens: b.total_tokens ?? 0,
            cost_usd: b.cost_usd ?? 0.0,
          }));
          if (telemetryRows.length > 0) {
            setColumns(['group', 'calls', 'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost_usd']);
            setRows(telemetryRows);
            setDatasetName('Execution Economics Telemetry');
          }
        }
      } catch {
        // start empty
      }
    };
    loadTelemetryData();
    return () => {
      mounted = false;
    };
  }, []);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (event) => {
      const text = event.target?.result as string;
      if (!text) return;

      const lines = text.trim().split('\n');
      if (lines.length > 0) {
        const header = lines[0].split(',').map((h) => h.trim().replace(/^"|"$/g, ''));
        const parsedRows: DataRow[] = [];
        for (let i = 1; i < lines.length; i++) {
          const cells = lines[i].split(',').map((c) => c.trim().replace(/^"|"$/g, ''));
          const rowObj: DataRow = {};
          header.forEach((h, idx) => {
            const raw = cells[idx] || '';
            const num = Number(raw);
            rowObj[h] = isNaN(num) || raw === '' ? raw : num;
          });
          parsedRows.push(rowObj);
        }
        setColumns(header);
        setRows(parsedRows);
        setDatasetName(file.name.replace(/\.[^/.]+$/, ''));
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  const filteredRows = rows.filter((r) => {
    if (!filterText) return true;
    const query = filterText.toLowerCase();
    return Object.values(r).some((v) => String(v).toLowerCase().includes(query));
  });

  const handleRunAnalysis = async () => {
    if (isAnalyzing) return;
    setIsAnalyzing(true);
    setAnalysisResult('');

    const promptText = analysisPrompt.trim()
      ? `Analyze this dataset based on query: "${analysisPrompt}".\nData summary:\nColumns: ${columns.join(', ')}\nSample rows (${Math.min(rows.length, 10)}):\n${JSON.stringify(rows.slice(0, 10), null, 2)}`
      : `Provide statistical distribution summary and actionable insights for this dataset:\nColumns: ${columns.join(', ')}\nRows: ${JSON.stringify(rows.slice(0, 10), null, 2)}`;

    try {
      await sidecarClient.streamChatCompletion({
        prompt: promptText,
        onToken: (tok) => {
          setAnalysisResult((prev) => prev + tok);
        },
      });
    } catch (err: any) {
      setAnalysisResult(`[Analysis Error: ${err?.message || 'Unable to complete analysis'}]`);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleExportCSV = () => {
    const header = columns.join(',');
    const body = rows.map((r) => columns.map((c) => `"${r[c] ?? ''}"`).join(',')).join('\n');
    const csvContent = `${header}\n${body}`;
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `${datasetName.toLowerCase().replace(/\s+/g, '_')}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="h-full flex flex-col bg-bg-base text-text-primary select-none overflow-hidden" data-testid="data-screen">
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,.json"
        onChange={handleFileUpload}
        className="hidden"
      />

      {/* Header Bar */}
      <div className="h-12 border-b border-border-subtle bg-bg-elevated px-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Table2 className="w-4 h-4 text-accent" />
          <span className="text-sm font-semibold tracking-tight text-text-primary">{datasetName}</span>
          <span className="text-[11px] font-mono text-text-tertiary">
            ({filteredRows.length} rows · {columns.length} columns)
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
          >
            <Upload className="w-3.5 h-3.5" />
            <span>Open CSV</span>
          </button>
          <button
            type="button"
            onClick={handleExportCSV}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bg-base hover:bg-bg-hover border border-border-subtle text-xs text-text-secondary transition-colors"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export CSV</span>
          </button>
        </div>
      </div>

      {/* Filter & Analysis Input Strip */}
      <div className="px-4 py-2 border-b border-border-subtle bg-bg-elevated/50 flex flex-wrap items-center justify-between gap-3">
        {/* Filter Input */}
        <div className="relative w-72">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary" />
          <input
            type="text"
            value={filterText}
            onChange={(e) => setFilterText(e.target.value)}
            placeholder="Filter table rows..."
            className="w-full pl-8 pr-3 py-1 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
          />
        </div>

        {/* Natural Language Analysis Prompt */}
        <div className="flex items-center gap-2 flex-1 max-w-lg">
          <input
            type="text"
            value={analysisPrompt}
            onChange={(e) => setAnalysisPrompt(e.target.value)}
            placeholder="Ask question about this dataset (e.g. Find outliers or calculate average cost)..."
            className="w-full px-3 py-1 bg-bg-base border border-border-subtle rounded-lg text-xs text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={handleRunAnalysis}
            disabled={isAnalyzing}
            className="px-3 py-1 rounded bg-accent hover:bg-accent-hover text-white text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50 flex-shrink-0"
          >
            {isAnalyzing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            <span>Analyze</span>
          </button>
        </div>
      </div>

      {/* Main 2-Pane View: Table View (Left) & Analysis Panel (Right) */}
      <div className="flex-1 flex overflow-hidden">
        {/* Table View */}
        <div className="flex-1 overflow-auto p-4">
          {filteredRows.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center border border-border-subtle rounded-lg bg-bg-elevated/20 p-8 text-center text-text-tertiary">
              <Table2 className="w-8 h-8 mb-3 opacity-40 text-accent" />
              <p className="text-sm font-semibold text-text-primary">No execution records or dataset loaded</p>
              <p className="text-xs text-text-tertiary mt-1 max-w-sm">
                Upload a CSV dataset or execute agent runs to inspect structured tabular telemetry here.
              </p>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="mt-4 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-hover transition-colors"
              >
                <Upload className="w-3.5 h-3.5" />
                <span>Open CSV File</span>
              </button>
            </div>
          ) : (
            <div className="border border-border-subtle rounded-lg overflow-hidden bg-bg-elevated/40">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="bg-bg-elevated border-b border-border-subtle">
                    {columns.map((col) => (
                      <th
                        key={col}
                        className="px-3 py-2 font-mono text-[11px] font-semibold text-text-secondary uppercase tracking-wider border-r border-border-subtle/50 last:border-r-0"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-subtle/50 font-mono text-[11px]">
                  {filteredRows.map((row, rIdx) => (
                    <tr key={rIdx} className="hover:bg-bg-hover transition-colors">
                      {columns.map((col) => (
                        <td
                          key={col}
                          className="px-3 py-2 text-text-primary border-r border-border-subtle/30 last:border-r-0 whitespace-nowrap"
                        >
                          {String(row[col] ?? '')}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Analysis & Summary Panel */}
        <div className="w-80 border-l border-border-subtle bg-bg-elevated/30 p-4 space-y-4 overflow-y-auto">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-text-tertiary">
            Dataset Summary & Analytics
          </div>

          {/* Quick Metrics */}
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div className="p-2.5 rounded bg-bg-elevated border border-border-subtle">
              <span className="text-[10px] text-text-tertiary block font-mono">Total Rows</span>
              <span className="text-sm font-semibold text-text-primary font-mono">{rows.length}</span>
            </div>
            <div className="p-2.5 rounded bg-bg-elevated border border-border-subtle">
              <span className="text-[10px] text-text-tertiary block font-mono">Attributes</span>
              <span className="text-sm font-semibold text-text-primary font-mono">{columns.length}</span>
            </div>
          </div>

          {/* AI Analysis Insight Output */}
          <div className="space-y-1.5 flex-1 flex flex-col">
            <div className="flex items-center justify-between text-xs text-text-secondary">
              <span className="font-medium">Data Insight</span>
              {analysisResult && (
                <button
                  type="button"
                  onClick={() => setAnalysisResult('')}
                  className="text-[10px] text-text-tertiary hover:underline"
                >
                  Clear
                </button>
              )}
            </div>
            {analysisResult ? (
              <div className="p-3 bg-bg-base border border-border-subtle rounded-lg text-xs font-mono text-text-secondary whitespace-pre-wrap leading-relaxed max-h-72 overflow-y-auto">
                {analysisResult}
              </div>
            ) : (
              <div className="p-4 bg-bg-base/50 border border-border-subtle/60 rounded-lg text-center text-xs text-text-tertiary">
                Enter an analysis prompt above and click "Analyze" to run automated dataset inspection.
              </div>
            )}
          </div>

          {/* Spreadsheet Runtime Notice */}
          <div className="p-3 rounded-lg bg-bg-elevated border border-border-subtle space-y-1 text-xs">
            <div className="font-medium text-text-primary text-[11px]">Spreadsheet Formula Engine</div>
            <p className="text-[11px] text-text-tertiary leading-relaxed">
              CSV data viewing and natural-language analysis are active. Dynamic spreadsheet formulas (=SUM, =VLOOKUP) runtime is in active development.
            </p>
            <span className="inline-block px-1.5 py-0.5 rounded bg-bg-base border border-border-subtle text-[10px] font-mono text-text-tertiary">
              Formula Runtime: Planned
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
