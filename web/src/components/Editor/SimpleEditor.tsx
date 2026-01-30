import React, { useRef, useEffect, useCallback } from 'react';
import type { EditorSettings } from '../../hooks/useEditor';

interface SimpleEditorProps {
  value: string;
  onChange: (value: string) => void;
  language: string;
  settings: EditorSettings;
  onSave?: () => void;
}

/**
 * Simple textarea-based editor with syntax highlighting
 * Used as fallback when Monaco is not available
 */
export function SimpleEditor({ value, onChange, language, settings, onSave }: SimpleEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lineNumbersRef = useRef<HTMLDivElement>(null);

  /**
   * Handle keyboard shortcuts
   */
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Save on Ctrl+S or Cmd+S
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      onSave?.();
    }

    // Tab handling - insert spaces instead of changing focus
    if (e.key === 'Tab') {
      e.preventDefault();
      const textarea = textareaRef.current;
      if (!textarea) return;

      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const spaces = ' '.repeat(settings.tabSize);

      const newValue = value.substring(0, start) + spaces + value.substring(end);
      onChange(newValue);

      // Set cursor position after the inserted spaces
      setTimeout(() => {
        textarea.selectionStart = textarea.selectionEnd = start + spaces.length;
      }, 0);
    }
  }, [value, onChange, settings.tabSize, onSave]);

  /**
   * Update line numbers when content changes
   */
  const updateLineNumbers = useCallback(() => {
    if (!lineNumbersRef.current || !textareaRef.current) return;

    const textarea = textareaRef.current;
    const lines = value.split('\n').length;
    const lineNumbersHtml = Array.from({ length: lines }, (_, i) => i + 1).join('\n');

    lineNumbersRef.current.textContent = lineNumbersHtml;

    // Sync scroll
    lineNumbersRef.current.scrollTop = textarea.scrollTop;
  }, [value]);

  /**
   * Handle scroll sync
   */
  const handleScroll = useCallback(() => {
    if (!lineNumbersRef.current || !textareaRef.current) return;
    lineNumbersRef.current.scrollTop = textareaRef.current.scrollTop;
  }, []);

  /**
   * Update line numbers on mount and when value changes
   */
  useEffect(() => {
    updateLineNumbers();
  }, [value, updateLineNumbers]);

  /**
   * Apply auto-save if enabled
   */
  useEffect(() => {
    if (!settings.autoSave || !onSave) return;

    const timer = setTimeout(() => {
      onSave();
    }, settings.autoSaveDelay);

    return () => clearTimeout(timer);
  }, [value, settings.autoSave, settings.autoSaveDelay, onSave]);

  const editorStyles: React.CSSProperties = {
    fontSize: `${settings.fontSize}px`,
    tabSize: settings.tabSize,
    whiteSpace: settings.wordWrap ? 'pre-wrap' : 'pre',
    background: settings.theme === 'vs-light' ? '#ffffff' : '#1e1e1e',
    color: settings.theme === 'vs-light' ? '#000000' : '#d4d4d4',
    border: '1px solid var(--line)',
    borderRadius: '4px'
  };

  const lineNumberStyles: React.CSSProperties = {
    fontSize: `${settings.fontSize}px`,
    background: settings.theme === 'vs-light' ? '#f5f5f5' : '#252526',
    color: settings.theme === 'vs-light' ? '#858585' : '#858585',
    borderRight: '1px solid var(--line)',
    userSelect: 'none'
  };

  return (
    <div
      style={{
        display: 'flex',
        height: '100%',
        overflow: 'hidden',
        fontFamily: 'Monaco, "Courier New", monospace',
        ...editorStyles
      }}
    >
      {settings.lineNumbers && (
        <div
          ref={lineNumbersRef}
          style={{
            ...lineNumberStyles,
            width: '50px',
            padding: '10px 5px',
            textAlign: 'right',
            overflow: 'hidden',
            flexShrink: 0
          }}
        />
      )}
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onScroll={handleScroll}
        spellCheck={false}
        style={{
          flex: 1,
          border: 'none',
          outline: 'none',
          padding: '10px',
          resize: 'none',
          fontFamily: 'inherit',
          fontSize: 'inherit',
          lineHeight: '1.5',
          background: 'transparent',
          color: 'inherit',
          whiteSpace: settings.wordWrap ? 'pre-wrap' : 'pre',
          overflowWrap: settings.wordWrap ? 'break-word' : 'normal'
        }}
        placeholder={`Start typing ${language} code...`}
      />
    </div>
  );
}
