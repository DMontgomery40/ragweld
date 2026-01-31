// Editor/VSCode functionality removed - this is a compatibility stub
// Will be systematically stripped in Phase 2 work

export interface EditorState {
  isLoaded: boolean;
  content: string;
  language: string;
  filePath: string | null;
  isDirty: boolean;
  isReadOnly: boolean;
}

export interface EditorActions {
  setContent: (content: string) => void;
  save: () => Promise<void>;
  load: (filePath: string) => Promise<void>;
  setLanguage: (language: string) => void;
  setReadOnly: (readOnly: boolean) => void;
}

// Legacy types for backward compatibility
export interface EditorSettings {
  theme: EditorTheme;
  fontSize: number;
  tabSize: number;
  wordWrap: boolean;
  minimap: boolean;
  lineNumbers: boolean;
  autoSave: boolean;
  autoSaveDelay: number;
  formatOnSave: boolean;
  renderWhitespace: boolean | 'none' | 'boundary' | 'selection' | 'trailing' | 'all';
  scrollBeyondLastLine: boolean;
}

export type EditorTheme = 'vs-dark' | 'vs-light' | 'hc-black';

export function useEditor(): EditorState & EditorActions {
  console.warn('useEditor is deprecated - Editor functionality removed');
  return {
    isLoaded: false,
    content: '',
    language: 'plaintext',
    filePath: null,
    isDirty: false,
    isReadOnly: true,
    setContent: () => {},
    save: async () => {},
    load: async () => {},
    setLanguage: () => {},
    setReadOnly: () => {},
  };
}

export default useEditor;
