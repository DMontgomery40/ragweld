import { useEffect, useMemo, useRef, useState } from 'react';
import { Terminal } from 'xterm';
import { FitAddon } from '@xterm/addon-fit';
import { SearchAddon } from '@xterm/addon-search';
import 'xterm/css/xterm.css';

type Props = {
  logs: any[];
  loading: boolean;
  onDownload: () => void;
  onClear: () => void;
};

function logsToText(logs: any[]): string {
  if (!Array.isArray(logs) || logs.length === 0) return '';
  return logs
    .map((entry) => {
      if (typeof entry === 'string') return entry;
      try {
        return JSON.stringify(entry, null, 2);
      } catch {
        return String(entry);
      }
    })
    .join('\n');
}

export function StudioLogTerminal({ logs, loading, onDownload, onClear }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const searchAddonRef = useRef<SearchAddon | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [copied, setCopied] = useState(false);

  const text = useMemo(() => logsToText(logs), [logs]);

  useEffect(() => {
    if (!hostRef.current || termRef.current) return;

    const term = new Terminal({
      convertEol: true,
      scrollback: 100000,
      allowProposedApi: true,
      fontFamily: 'var(--font-mono)',
      fontSize: 12,
      theme: {
        background: '#050a15',
        foreground: '#d5e9ff',
        cursor: '#7ad8ff',
      },
    });

    const fitAddon = new FitAddon();
    const searchAddon = new SearchAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(searchAddon);

    term.open(hostRef.current);
    fitAddon.fit();

    const onResize = () => fitAddon.fit();
    window.addEventListener('resize', onResize);

    termRef.current = term;
    fitAddonRef.current = fitAddon;
    searchAddonRef.current = searchAddon;

    return () => {
      window.removeEventListener('resize', onResize);
      term.dispose();
      termRef.current = null;
      fitAddonRef.current = null;
      searchAddonRef.current = null;
    };
  }, []);

  useEffect(() => {
    const term = termRef.current;
    if (!term) return;

    term.reset();

    if (loading) {
      term.writeln('Loading logs...');
      return;
    }

    if (!text.trim()) {
      term.writeln('No logs.');
      return;
    }

    term.write(text.replace(/\n/g, '\r\n'));
  }, [loading, text]);

  useEffect(() => {
    const fitAddon = fitAddonRef.current;
    if (!fitAddon) return;
    fitAddon.fit();
  }, [text]);

  const onSearchNext = () => {
    if (!searchQuery.trim()) return;
    searchAddonRef.current?.findNext(searchQuery, {
      caseSensitive: false,
      regex: false,
      incremental: false,
      decorations: {
        activeMatchColorOverviewRuler: '#46e5ff',
        matchOverviewRuler: '#2d6ca2',
      },
    });
  };

  const onSearchPrev = () => {
    if (!searchQuery.trim()) return;
    searchAddonRef.current?.findPrevious(searchQuery, {
      caseSensitive: false,
      regex: false,
      incremental: false,
      decorations: {
        activeMatchColorOverviewRuler: '#46e5ff',
        matchOverviewRuler: '#2d6ca2',
      },
    });
  };

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(text || '');
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="studio-log-terminal" data-testid="studio-log-terminal">
      <div className="studio-log-toolbar">
        <input
          className="studio-search"
          placeholder="Search logs"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />
        <button className="small-button" onClick={onSearchPrev}>Prev</button>
        <button className="small-button" onClick={onSearchNext}>Next</button>
        <button className="small-button" onClick={onCopy}>{copied ? 'Copied' : 'Copy'}</button>
        <button className="small-button" onClick={onDownload}>Export</button>
        <button className="small-button" onClick={onClear}>Clear</button>
      </div>
      <div ref={hostRef} className="studio-log-terminal-host" />
    </div>
  );
}
