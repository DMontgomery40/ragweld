// AGRO - Live Terminal Panel Component
// Dropdown terminal that slides down with bezier animation

import { useEffect, useRef } from 'react';
import { LiveTerminal, LiveTerminalHandle } from '../LiveTerminal';

interface LiveTerminalPanelProps {
  containerId: string;
  isVisible: boolean;
}

export function LiveTerminalPanel({ containerId, isVisible }: LiveTerminalPanelProps) {
  const terminalRef = useRef<LiveTerminalHandle>(null);

  useEffect(() => {
    // Store terminal reference on window for QuickActions to use
    if (terminalRef.current) {
      (window as any)._dashboardTerminal = terminalRef.current;
    }
  }, []);

  return (
    <div
      id={containerId}
      style={{
        maxHeight: isVisible ? '400px' : '0',
        opacity: isVisible ? 1 : 0,
        overflow: 'hidden',
        transition: 'max-height 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease',
        marginTop: isVisible ? '12px' : '0',
      }}
    >
      <LiveTerminal
        ref={terminalRef}
        title="Dashboard Operations"
        initialContent={['Ready for operations...']}
      />
    </div>
  );
}

