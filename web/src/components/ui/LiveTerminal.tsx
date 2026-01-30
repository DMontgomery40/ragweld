import React, { useState, useEffect, useRef } from 'react';
import Ansi from 'ansi-to-react';

interface LiveTerminalProps {
  title: string;
  isVisible: boolean;
  onClose: () => void;
  lines: string[];
  progress: { percent: number; message: string } | null;
}


export const LiveTerminal: React.FC<LiveTerminalProps> = ({ title, isVisible, onClose, lines, progress }) => {
    const [autoScroll, setAutoScroll] = useState(true);
    const outputRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (autoScroll && outputRef.current) {
            outputRef.current.scrollTop = outputRef.current.scrollHeight;
        }
    }, [lines, autoScroll]);

    const handleScroll = () => {
        if (outputRef.current) {
            const atBottom = outputRef.current.scrollHeight - outputRef.current.scrollTop <= outputRef.current.clientHeight + 50;
            if (!atBottom && autoScroll) {
                setAutoScroll(false);
            }
        }
    };
    
    const clearOutput = () => {
        if (outputRef.current) {
            outputRef.current.innerHTML = '';
        }
    }

    return (
        <div 
            className="live-terminal" 
            style={{
                maxHeight: isVisible ? '500px' : '0',
                overflow: 'hidden',
                transition: 'max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
                marginTop: '16px',
                borderRadius: '8px',
                background: '#1a1a1a',
                border: '1px solid var(--line)',
                boxShadow: '0 4px 6px rgba(0, 0, 0, 0.3)',
            }}
        >
            <div className="terminal-header" style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '10px 16px',
                background: '#252525',
                borderBottom: '1px solid var(--line)',
                borderRadius: '8px 8px 0 0',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <div style={{ display: 'flex', gap: '6px' }}>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#ff5f57' }}></div>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#ffbd2e' }}></div>
                        <div style={{ width: '12px', height: '12px', borderRadius: '50%', background: '#28c840' }}></div>
                    </div>
                    <span className="terminal-title" style={{ fontFamily: "'SF Mono', 'Monaco', monospace", fontSize: '13px', color: '#e0e0e0', fontWeight: '500' }}>
                        {title}
                    </span>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <button className="terminal-scroll-toggle" style={{ background: 'transparent', border: '1px solid var(--line)', color: autoScroll ? 'var(--accent)' : 'var(--fg-muted)', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontFamily: "'SF Mono', monospace" }} title="Toggle auto-scroll" onClick={() => setAutoScroll(!autoScroll)}>
                        📜 {autoScroll ? 'Auto' : 'Manual'}
                    </button>
                    <button className="terminal-clear" style={{ background: 'transparent', border: '1px solid var(--line)', color: 'var(--fg-muted)', padding: '4px 10px', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', fontFamily: "'SF Mono', monospace" }} title="Clear output" onClick={clearOutput}>
                        🗑️ Clear
                    </button>
                    <button className="terminal-collapse" style={{ background: 'transparent', border: 'none', color: 'var(--fg-muted)', cursor: 'pointer', fontSize: '16px', padding: '0 4px' }} title="Collapse terminal" onClick={onClose}>
                        ▼
                    </button>
                </div>
            </div>
            {progress && (
                <div className="terminal-progress" style={{ padding: '8px 16px', background: '#1f1f1f', borderBottom: '1px solid var(--line)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <span className="progress-label" style={{ fontFamily: "'SF Mono', monospace", fontSize: '11px', color: 'var(--accent)' }}>{progress.message}</span>
                        <span className="progress-percent" style={{ fontFamily: "'SF Mono', monospace", fontSize: '11px', color: 'var(--fg-muted)' }}>{Math.round(progress.percent)}%</span>
                    </div>
                    <div style={{ width: '100%', height: '6px', background: '#0a0a0a', borderRadius: '3px', overflow: 'hidden' }}>
                        <div className="progress-fill" style={{ width: `${progress.percent}%`, height: '100%', background: 'linear-gradient(90deg, var(--accent) 0%, var(--link) 100%)', transition: 'width 0.3s ease-out', borderRadius: '3px' }}></div>
                    </div>
                </div>
            )}
            <div className="terminal-body" ref={outputRef} onScroll={handleScroll} style={{
                height: '350px',
                overflowY: 'auto',
                padding: '12px 16px',
                fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace",
                fontSize: '12px',
                lineHeight: '1.6',
                color: '#e0e0e0',
                background: '#1a1a1a',
                borderRadius: '0 0 8px 8px',
            }}>
                <pre className="terminal-output" style={{ margin: 0, whiteSpace: 'pre-wrap', wordWrap: 'break-word', color: '#e0e0e0' }}>
                    {lines.length > 0 ? lines.map((line, i) => (
                        <div key={i}><Ansi>{line}</Ansi></div>
                    )) : <span style={{ color: '#888' }}>Waiting for output...</span>}
                </pre>
            </div>
        </div>
    );
};