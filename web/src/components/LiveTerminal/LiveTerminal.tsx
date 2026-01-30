import React, { useState, useRef, useEffect, useCallback, forwardRef, useImperativeHandle } from 'react';
import './LiveTerminal.css';

interface LiveTerminalProps {
  id?: string;
  title?: string;
  initialContent?: string[];
  onClose?: () => void;
}

interface ProgressState {
  visible: boolean;
  percent: number;
  message: string;
}

export interface LiveTerminalHandle {
  show: () => void;
  hide: () => void;
  clear: () => void;
  appendLine: (line: string) => void;
  appendLines: (lines: string[]) => void;
  setContent: (lines: string[]) => void;
  updateProgress: (percent: number, message?: string) => void;
  hideProgress: () => void;
  setTitle: (title: string) => void;
}

export const LiveTerminal = forwardRef<LiveTerminalHandle, LiveTerminalProps>(({
  id = 'terminal',
  title: initialTitle = 'Live Output',
  initialContent = ['Waiting for output...'],
  onClose
}, ref) => {
  const [isVisible, setIsVisible] = useState(true); // Start visible
  const [isExpanded, setIsExpanded] = useState(true);
  const [autoScroll, setAutoScroll] = useState(true);
  const [lines, setLines] = useState<string[]>(initialContent);
  const [title, setTitle] = useState(initialTitle);
  const [progress, setProgress] = useState<ProgressState>({
    visible: false,
    percent: 0,
    message: ''
  });

  const terminalRef = useRef<HTMLDivElement>(null);
  const outputRef = useRef<HTMLPreElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  // ANSI color code mapping
  const colorMap: Record<string, string> = {
    '30': '#000', '31': '#ff5f57', '32': '#28c840', '33': '#ffbd2e',
    '34': '#5c9fd8', '35': '#c678dd', '36': '#56b6c2', '37': '#e0e0e0',
    '90': '#666', '91': '#ff6b6b', '92': '#5af78e', '93': '#f9f871',
    '94': '#6baeff', '95': '#e599f7', '96': '#76e1ff', '97': '#fff'
  };

  // Parse ANSI color codes into React elements (safe, no dangerouslySetInnerHTML)
  const parseANSI = useCallback((text: string): React.ReactNode[] => {
    const result: React.ReactNode[] = [];
    let currentColor: string | null = null;
    let buffer = '';
    let i = 0;
    let keyIdx = 0;

    const flushBuffer = () => {
      if (buffer) {
        if (currentColor) {
          result.push(<span key={keyIdx++} style={{ color: currentColor }}>{buffer}</span>);
        } else {
          result.push(<React.Fragment key={keyIdx++}>{buffer}</React.Fragment>);
        }
        buffer = '';
      }
    };

    while (i < text.length) {
      // Check for ANSI escape sequence
      if (text[i] === '\x1b' && text[i + 1] === '[') {
        const match = text.slice(i).match(/^\x1b\[([0-9;]+)m/);
        if (match) {
          flushBuffer();
          const code = match[1];
          if (code === '0') {
            currentColor = null;
          } else if (colorMap[code]) {
            currentColor = colorMap[code];
          }
          i += match[0].length;
          continue;
        }
      }
      buffer += text[i];
      i++;
    }
    flushBuffer();

    return result.length > 0 ? result : [text];
  }, []);

  // Scroll to bottom
  const scrollToBottom = useCallback(() => {
    if (bodyRef.current && autoScroll) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [autoScroll]);

  // Append line
  const appendLine = useCallback((line: string) => {
    setLines(prev => {
      const newLines = prev[0] === 'Waiting for output...' ? [line] : [...prev, line];
      return newLines;
    });
  }, []);

  // Clear terminal
  const clear = useCallback(() => {
    setLines(['Waiting for output...']);
  }, []);

  // Update progress
  const updateProgress = useCallback((percent: number, message?: string) => {
    setProgress({
      visible: true,
      percent: Math.min(100, Math.max(0, percent)),
      message: message || progress.message
    });
  }, [progress.message]);

  // Hide progress
  const hideProgress = useCallback(() => {
    setProgress(prev => ({ ...prev, visible: false }));
  }, []);

  // Show terminal with animation
  const show = useCallback(() => {
    setIsVisible(true);
    setIsExpanded(true);
  }, []);

  // Hide terminal with animation
  const hide = useCallback(() => {
    setIsExpanded(false);
    setTimeout(() => setIsVisible(false), 400); // Wait for animation
  }, []);

  // Handle manual scroll detection
  const handleScroll = useCallback(() => {
    if (!bodyRef.current) return;
    const { scrollHeight, scrollTop, clientHeight } = bodyRef.current;
    const atBottom = scrollHeight - scrollTop <= clientHeight + 50;

    if (!atBottom && autoScroll) {
      setAutoScroll(false);
    }
  }, [autoScroll]);

  // Auto-scroll when new lines are added
  useEffect(() => {
    scrollToBottom();
  }, [lines, scrollToBottom]);

  // Expose methods via ref
  useImperativeHandle(ref, () => ({
    show,
    hide,
    clear,
    appendLine,
    appendLines: (lines: string[]) => lines.forEach(appendLine),
    setContent: (lines: string[]) => setLines(lines),
    updateProgress,
    hideProgress,
    setTitle: (newTitle: string) => setTitle(newTitle)
  }), [show, hide, clear, appendLine, updateProgress, hideProgress]);

  // Store terminal instance on window for legacy compatibility
  useEffect(() => {
    const terminal = {
      show,
      hide,
      clear,
      appendLine,
      appendLines: (lines: string[]) => lines.forEach(appendLine),
      setContent: (lines: string[]) => setLines(lines),
      updateProgress,
      hideProgress,
      setTitle: (newTitle: string) => setTitle(newTitle)
    };

    (window as any)[`terminal_${id}`] = terminal;

    return () => {
      delete (window as any)[`terminal_${id}`];
    };
  }, [id, show, hide, clear, appendLine, updateProgress, hideProgress]);

  // Start with showing the terminal immediately
  useEffect(() => {
    show();
  }, [show]);


  return (
    <div
      ref={terminalRef}
      className={`live-terminal ${isExpanded ? 'expanded' : 'collapsed'}`}
      id={id}
    >
      <div className="terminal-header">
        <div className="terminal-header-left">
          <div className="terminal-controls">
            <div className="control-dot control-red" onClick={onClose}></div>
            <div className="control-dot control-yellow"></div>
            <div className="control-dot control-green"></div>
          </div>
          <span className="terminal-title">{title}</span>
        </div>

        <div className="terminal-header-right">
          <button
            className={`terminal-btn ${autoScroll ? 'active' : ''}`}
            onClick={() => {
              setAutoScroll(!autoScroll);
              if (!autoScroll) scrollToBottom();
            }}
            title="Toggle auto-scroll"
          >
            📜 {autoScroll ? 'Auto' : 'Manual'}
          </button>

          <button
            className="terminal-btn"
            onClick={clear}
            title="Clear output"
          >
            🗑️ Clear
          </button>

          <button
            className="terminal-collapse-btn"
            onClick={() => setIsExpanded(!isExpanded)}
            title={isExpanded ? 'Collapse' : 'Expand'}
          >
            {isExpanded ? '▼' : '▲'}
          </button>
        </div>
      </div>

      {progress.visible && (
        <div className="terminal-progress">
          <div className="progress-info">
            <span className="progress-label">{progress.message}</span>
            <span className="progress-percent">{Math.round(progress.percent)}%</span>
          </div>
          <div className="progress-bar">
            <div
              className="progress-fill"
              style={{ width: `${progress.percent}%` }}
            />
          </div>
        </div>
      )}

      <div
        ref={bodyRef}
        className="terminal-body"
        onScroll={handleScroll}
      >
        <pre ref={outputRef} className="terminal-output">
          {lines.map((line, i) => (
            <div key={i}>{parseANSI(line)}</div>
          ))}
        </pre>
      </div>
    </div>
  );
});

LiveTerminal.displayName = 'LiveTerminal';