// AGRO - Chat Subtabs Component
// Subtab navigation for Chat tab (UI and Settings)

import { useEffect } from 'react';

interface ChatSubtabsProps {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
}

export function ChatSubtabs({ activeSubtab, onSubtabChange }: ChatSubtabsProps) {
  useEffect(() => {
    // Legacy module compatibility - dispatch event for legacy JS
    window.dispatchEvent(new CustomEvent('subtab-changed', {
      detail: { parent: 'chat', subtab: activeSubtab }
    }));
  }, [activeSubtab]);

  return (
    <div id="chat-subtabs" className="subtab-bar" data-state="visible" style={{ display: 'flex' }}>
      <button
        className={`subtab-btn ${activeSubtab === 'ui' ? 'active' : ''}`}
        data-subtab="ui"
        data-parent="chat"
        onClick={() => onSubtabChange('ui')}
      >
        Interface
      </button>
      <button
        className={`subtab-btn ${activeSubtab === 'settings' ? 'active' : ''}`}
        data-subtab="settings"
        data-parent="chat"
        onClick={() => onSubtabChange('settings')}
      >
        Settings
      </button>
    </div>
  );
}
