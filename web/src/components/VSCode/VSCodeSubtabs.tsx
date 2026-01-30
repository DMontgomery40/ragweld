// AGRO - VSCode Subtabs Component
// Subtab navigation for VSCode tab (Editor and Settings)

import { useEffect } from 'react';

interface VSCodeSubtabsProps {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
}

export function VSCodeSubtabs({ activeSubtab, onSubtabChange }: VSCodeSubtabsProps) {
  useEffect(() => {
    // Legacy module compatibility - dispatch event for legacy JS
    window.dispatchEvent(new CustomEvent('subtab-changed', {
      detail: { parent: 'vscode', subtab: activeSubtab }
    }));
  }, [activeSubtab]);

  return (
    <div id="vscode-subtabs" className="subtab-bar" data-state="visible" style={{ display: 'flex' }}>
      <button
        className={`subtab-btn ${activeSubtab === 'editor' ? 'active' : ''}`}
        data-subtab="editor"
        data-parent="vscode"
        onClick={() => onSubtabChange('editor')}
      >
        Editor
      </button>
      <button
        className={`subtab-btn ${activeSubtab === 'editor-settings' ? 'active' : ''}`}
        data-subtab="editor-settings"
        data-parent="vscode"
        onClick={() => onSubtabChange('editor-settings')}
      >
        Settings
      </button>
    </div>
  );
}
