// AGRO - Code Editor Component
// Embedded Monaco editor with file tree
// Reference: /assets/dev tools - editor - embedded vscode editor - way cool.png

import { useState, useEffect, useRef } from 'react';
import { useAPI } from '@/hooks';

// Monaco Editor types (will be loaded dynamically)
declare global {
  interface Window {
    monaco: any;
  }
}

interface FileNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: FileNode[];
}

export function Editor() {
  const { api } = useAPI();
  const [fileTree, setFileTree] = useState<FileNode[]>([]);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [currentFile, setCurrentFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState('');
  const [language, setLanguage] = useState('typescript');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [monacoLoaded, setMonacoLoaded] = useState(false);
  const [cursorPosition, setCursorPosition] = useState({ line: 1, column: 1 });
  const editorRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Load Monaco Editor
  useEffect(() => {
    loadMonaco();
    loadFileTree();
  }, []);

  const loadMonaco = async () => {
    // Check if Monaco is already loaded
    if (window.monaco) {
      setMonacoLoaded(true);
      initEditor();
      return;
    }

    try {
      // Load Monaco from CDN
      const loaderScript = document.createElement('script');
      loaderScript.src = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js';
      loaderScript.async = true;

      loaderScript.onload = () => {
        const require = (window as any).require;
        require.config({
          paths: {
            vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs'
          }
        });

        require(['vs/editor/editor.main'], () => {
          setMonacoLoaded(true);
          initEditor();
        });
      };

      document.head.appendChild(loaderScript);
    } catch (error) {
      console.error('[Editor] Failed to load Monaco:', error);
    }
  };

  const initEditor = () => {
    if (!containerRef.current || !window.monaco) return;

    try {
      editorRef.current = window.monaco.editor.create(containerRef.current, {
        value: fileContent || '// Welcome to AGRO Code Editor\n// Open a file from the tree to start editing',
        language: language,
        theme: 'vs-dark',
        automaticLayout: true,
        minimap: { enabled: true },
        fontSize: 14,
        lineNumbers: 'on',
        renderWhitespace: 'selection',
        scrollBeyondLastLine: false,
        wordWrap: 'on'
      });

      // Listen to cursor position changes
      editorRef.current.onDidChangeCursorPosition((e: any) => {
        setCursorPosition({
          line: e.position.lineNumber,
          column: e.position.column
        });
      });

      // Listen to content changes
      editorRef.current.onDidChangeModelContent(() => {
        setFileContent(editorRef.current.getValue());
      });
    } catch (error) {
      console.error('[Editor] Failed to initialize Monaco editor:', error);
    }
  };

  // Update editor content when file content changes
  useEffect(() => {
    if (editorRef.current && monacoLoaded) {
      const currentValue = editorRef.current.getValue();
      if (currentValue !== fileContent) {
        editorRef.current.setValue(fileContent);
      }
    }
  }, [fileContent, monacoLoaded]);

  // Update editor language when it changes
  useEffect(() => {
    if (editorRef.current && monacoLoaded && window.monaco) {
      const model = editorRef.current.getModel();
      if (model) {
        window.monaco.editor.setModelLanguage(model, language);
      }
    }
  }, [language, monacoLoaded]);

  const loadFileTree = async () => {
    try {
      const response = await fetch(api('/files/tree'));
      if (response.ok) {
        const data = await response.json();
        setFileTree(data.tree || []);
      }
    } catch (error) {
      console.error('[Editor] Failed to load file tree:', error);
      // Set example tree if API fails
      setFileTree([
        {
          name: 'web',
          path: '/web',
          type: 'directory',
          children: [
            { name: 'src', path: '/web/src', type: 'directory' },
            { name: 'package.json', path: '/web/package.json', type: 'file' }
          ]
        },
        {
          name: 'server',
          path: '/server',
          type: 'directory',
          children: [
            { name: 'api.py', path: '/server/api.py', type: 'file' },
            { name: 'config.py', path: '/server/config.py', type: 'file' }
          ]
        }
      ]);
    }
  };

  const toggleFolder = (path: string) => {
    const newExpanded = new Set(expandedFolders);
    if (newExpanded.has(path)) {
      newExpanded.delete(path);
    } else {
      newExpanded.add(path);
    }
    setExpandedFolders(newExpanded);
  };

  const openFile = async (path: string) => {
    setLoading(true);
    try {
      const response = await fetch(api('/files/read'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });

      if (response.ok) {
        const data = await response.json();
        setFileContent(data.content || '');
        setCurrentFile(path);

        // Detect language from file extension
        const ext = path.split('.').pop()?.toLowerCase() || '';
        const langMap: Record<string, string> = {
          'ts': 'typescript',
          'tsx': 'typescript',
          'js': 'javascript',
          'jsx': 'javascript',
          'py': 'python',
          'json': 'json',
          'html': 'html',
          'css': 'css',
          'md': 'markdown',
          'yaml': 'yaml',
          'yml': 'yaml',
          'sh': 'shell',
          'sql': 'sql'
        };
        setLanguage(langMap[ext] || 'plaintext');
      }
    } catch (error) {
      console.error('[Editor] Failed to open file:', error);
      alert('Failed to open file');
    } finally {
      setLoading(false);
    }
  };

  const saveFile = async () => {
    if (!currentFile) return;

    setSaving(true);
    try {
      const response = await fetch(api('/files/write'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: currentFile,
          content: fileContent
        })
      });

      if (response.ok) {
        alert('File saved successfully!');
      } else {
        alert('Failed to save file');
      }
    } catch (error) {
      console.error('[Editor] Failed to save file:', error);
      alert('Failed to save file');
    } finally {
      setSaving(false);
    }
  };

  const formatCode = () => {
    if (editorRef.current) {
      editorRef.current.getAction('editor.action.formatDocument')?.run();
    }
  };

  const renderFileTree = (nodes: FileNode[], depth: number = 0): JSX.Element[] => {
    return nodes.map(node => (
      <div key={node.path}>
        <div
          onClick={() => {
            if (node.type === 'directory') {
              toggleFolder(node.path);
            } else {
              openFile(node.path);
            }
          }}
          style={{
            padding: '4px 8px',
            paddingLeft: `${8 + depth * 16}px`,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '13px',
            color: currentFile === node.path ? 'var(--accent)' : 'var(--fg)',
            background: currentFile === node.path ? 'var(--bg-elev2)' : 'transparent',
            borderLeft: currentFile === node.path ? '2px solid var(--accent)' : 'none'
          }}
          onMouseEnter={(e) => {
            if (currentFile !== node.path) {
              e.currentTarget.style.background = 'var(--bg-elev1)';
            }
          }}
          onMouseLeave={(e) => {
            if (currentFile !== node.path) {
              e.currentTarget.style.background = 'transparent';
            }
          }}
        >
          {node.type === 'directory' ? (
            <>
              <span style={{ fontSize: '10px' }}>
                {expandedFolders.has(node.path) ? '▼' : '▶'}
              </span>
              <span>📁</span>
            </>
          ) : (
            <span style={{ marginLeft: '16px' }}>📄</span>
          )}
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node.name}
          </span>
        </div>

        {node.type === 'directory' && expandedFolders.has(node.path) && node.children && (
          <div>
            {renderFileTree(node.children, depth + 1)}
          </div>
        )}
      </div>
    ));
  };

  return (
    <div style={{
      display: 'flex',
      height: '70vh',
      border: '1px solid var(--line)',
      borderRadius: '6px',
      overflow: 'hidden',
      background: 'var(--card-bg)'
    }}>
      {/* File Tree Sidebar */}
      <div style={{
        width: '250px',
        borderRight: '1px solid var(--line)',
        overflowY: 'auto',
        background: 'var(--bg-elev1)'
      }}>
        <div style={{
          padding: '12px',
          borderBottom: '1px solid var(--line)',
          fontWeight: '600',
          fontSize: '13px',
          color: 'var(--fg-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.5px'
        }}>
          Explorer
        </div>
        <div style={{ padding: '8px 0' }}>
          {renderFileTree(fileTree)}
        </div>
      </div>

      {/* Editor Area */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* Toolbar */}
        <div style={{
          padding: '8px 12px',
          borderBottom: '1px solid var(--line)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          background: 'var(--bg-elev1)'
        }}>
          {currentFile ? (
            <>
              <span style={{ fontSize: '13px', color: 'var(--fg)', flex: 1 }}>
                {currentFile}
              </span>

              <button
                onClick={saveFile}
                disabled={saving || !currentFile}
                style={{
                  background: 'var(--accent)',
                  color: 'var(--accent-contrast)',
                  border: 'none',
                  padding: '6px 12px',
                  borderRadius: '4px',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: saving || !currentFile ? 'not-allowed' : 'pointer',
                  opacity: saving || !currentFile ? 0.5 : 1
                }}
                aria-label="Save file"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>

              <button
                onClick={formatCode}
                disabled={!currentFile}
                style={{
                  background: 'var(--bg-elev2)',
                  color: 'var(--fg)',
                  border: '1px solid var(--line)',
                  padding: '6px 12px',
                  borderRadius: '4px',
                  fontSize: '12px',
                  fontWeight: '600',
                  cursor: !currentFile ? 'not-allowed' : 'pointer',
                  opacity: !currentFile ? 0.5 : 1
                }}
                aria-label="Format code"
              >
                Format
              </button>

              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                style={{
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                  fontSize: '12px'
                }}
                aria-label="Language selector"
              >
                <option value="typescript">TypeScript</option>
                <option value="javascript">JavaScript</option>
                <option value="python">Python</option>
                <option value="json">JSON</option>
                <option value="html">HTML</option>
                <option value="css">CSS</option>
                <option value="markdown">Markdown</option>
                <option value="yaml">YAML</option>
                <option value="shell">Shell</option>
                <option value="sql">SQL</option>
              </select>
            </>
          ) : (
            <span style={{ fontSize: '13px', color: 'var(--fg-muted)' }}>
              Select a file to edit
            </span>
          )}
        </div>

        {/* Monaco Editor Container */}
        <div
          ref={containerRef}
          style={{
            flex: 1,
            position: 'relative',
            overflow: 'hidden'
          }}
        >
          {loading && (
            <div style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'rgba(0, 0, 0, 0.5)',
              zIndex: 10
            }}>
              <div style={{ color: 'white', fontSize: '14px' }}>Loading file...</div>
            </div>
          )}

          {!monacoLoaded && !loading && (
            <div style={{
              position: 'absolute',
              top: 0,
              left: 0,
              right: 0,
              bottom: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'var(--code-bg)',
              color: 'var(--fg-muted)',
              fontSize: '14px'
            }}>
              Loading Monaco Editor...
            </div>
          )}
        </div>

        {/* Status Bar */}
        <div style={{
          padding: '4px 12px',
          borderTop: '1px solid var(--line)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          fontSize: '11px',
          color: 'var(--fg-muted)',
          background: 'var(--bg-elev1)'
        }}>
          <div>
            Ln {cursorPosition.line}, Col {cursorPosition.column}
          </div>
          <div style={{ display: 'flex', gap: '16px' }}>
            <span>UTF-8</span>
            <span>{language}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
