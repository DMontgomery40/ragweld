// AGRO - Paths & Stores Subtab Component
// Directory paths and storage configuration

import { useState } from 'react';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { useConfig, useConfigField } from '@/hooks';

/**
 * ---agentspec
 * what: |
 *   React component that manages a configuration subtab for file paths within a settings interface.
 *   Accepts no props; uses Zustand-backed config fields plus local saving/action message state.
 *   Returns JSX rendering a form/UI for path configuration with real-time feedback.
 *   Reads/writes config via useConfigField and saveNow for explicit saves.
 *   Handles loading and saving states independently to show spinners/disabled states during async operations.
 *
 * why: |
 *   Separates path configuration UI from business logic by using Zustand for config and local state for UI.
 *   Follows standard React patterns: loading state prevents render-before-data bugs, saving state prevents double-submit, actionMessage provides user feedback.
 *
 * guardrails:
 *   - DO NOT keep config values in local state; use useConfigField/useConfig instead
 *   - ALWAYS call setSaving(false) after save operations complete (success or failure) to re-enable form controls
 *   - NOTE: actionMessage state has no auto-clear timeout; component relies on parent or explicit setActionMessage(null) to dismiss messages
 *   - ASK USER: Confirm whether tooltips should be optional (graceful fallback if useTooltips() returns undefined) or required before rendering
 * ---/agentspec
 */
export function PathsSubtab() {
  const { loading: configLoading, saveNow } = useConfig();
  const [saving, setSaving] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const [qdrantUrl, setQdrantUrl] = useConfigField<string>('QDRANT_URL', '');
  const [redisUrl, setRedisUrl] = useConfigField<string>('REDIS_URL', '');
  const [repoRoot, setRepoRoot] = useConfigField<string>('REPO_ROOT', '');
  const [filesRoot, setFilesRoot] = useConfigField<string>('FILES_ROOT', '');
  const [repoName, setRepoName] = useConfigField<string>('REPO', '');
  const [collectionSuffix, setCollectionSuffix] = useConfigField<string>('COLLECTION_SUFFIX', '');
  const [collectionName, setCollectionName] = useConfigField<string>('COLLECTION_NAME', '');
  const [repoPath, setRepoPath] = useConfigField<string>('REPO_PATH', '');
  const [guiDir, setGuiDir] = useConfigField<string>('GUI_DIR', '');
  const [docsDir, setDocsDir] = useConfigField<string>('DOCS_DIR', '');
  const [dataDir, setDataDir] = useConfigField<string>('DATA_DIR', '');
  const [reposFile, setReposFile] = useConfigField<string>('REPOS_FILE', '');
  const [outDirBase, setOutDirBase] = useConfigField<string>('OUT_DIR_BASE', '');
  const [ragOutBase, setRagOutBase] = useConfigField<string>('RAG_OUT_BASE', '');

  async function saveConfig() {
    setSaving(true);
    setActionMessage('Saving configuration...');

    try {
      await saveNow({
        QDRANT_URL: qdrantUrl,
        REDIS_URL: redisUrl,
        REPO_ROOT: repoRoot,
        FILES_ROOT: filesRoot,
        REPO: repoName,
        COLLECTION_SUFFIX: collectionSuffix,
        COLLECTION_NAME: collectionName,
        REPO_PATH: repoPath,
        GUI_DIR: guiDir,
        DOCS_DIR: docsDir,
        DATA_DIR: dataDir,
        REPOS_FILE: reposFile,
        OUT_DIR_BASE: outDirBase,
        RAG_OUT_BASE: ragOutBase,
      });
      setActionMessage('Configuration saved successfully!');
    } catch (error: any) {
      console.error('[PathsSubtab] Failed to save config:', error);
      setActionMessage(`Failed to save configuration: ${error.message || error}`);
    } finally {
      setSaving(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  }

  if (configLoading) {
    return (
      <div style={{ padding: '20px', textAlign: 'center', color: 'var(--fg-muted)' }}>
        Loading configuration...
      </div>
    );
  }

  return (
    <div className="settings-section">
      {/* Action message */}
      {actionMessage && (
        <div style={{
          padding: '12px',
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          marginBottom: '16px',
          fontSize: '12px',
          color: 'var(--fg)'
        }}>
          {actionMessage}
        </div>
      )}

      <h2>Infrastructure Configuration</h2>
      <p className="small" style={{ marginBottom: '24px' }}>
        Configure database endpoints, file paths, and storage locations.
      </p>

      {/* Database Endpoints */}
      <h3>Database Endpoints</h3>
      <div className="input-row">
        <div className="input-group">
          <label>
            Qdrant URL
            <TooltipIcon name="QDRANT_URL" />
          </label>
          <input
            type="text"
            value={qdrantUrl}
            onChange={(e) => setQdrantUrl(e.target.value)}
            placeholder="http://127.0.0.1:6333"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
          <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
            Vector database URL
          </p>
        </div>
        <div className="input-group">
          <label>
            Redis URL
            <TooltipIcon name="REDIS_URL" />
          </label>
          <input
            type="text"
            value={redisUrl}
            onChange={(e) => setRedisUrl(e.target.value)}
            placeholder="redis://127.0.0.1:6379/0"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
          <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
            LangGraph memory store
          </p>
        </div>
      </div>

      {/* Repository Configuration */}
      <h3 style={{ marginTop: '32px' }}>Repository Configuration</h3>
      <div className="input-row">
        <div className="input-group">
          <label>
            Repo Root
            <TooltipIcon name="REPO_ROOT" />
          </label>
          <input
            type="text"
            value={repoRoot}
            onChange={(e) => setRepoRoot(e.target.value)}
            placeholder="Override project root (optional)"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
        <div className="input-group">
          <label>
            Files Root
            <TooltipIcon name="FILES_ROOT" />
          </label>
          <input
            type="text"
            value={filesRoot}
            onChange={(e) => setFilesRoot(e.target.value)}
            placeholder="/files mount root (optional)"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
      </div>

      <div className="input-row">
        <div className="input-group">
          <label>
            Repository
            <TooltipIcon name="REPO" />
          </label>
          <input
            type="text"
            value={repoName}
            onChange={(e) => setRepoName(e.target.value)}
            placeholder="agro"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
        <div className="input-group">
          <label>
            Collection Suffix
            <TooltipIcon name="COLLECTION_SUFFIX" />
          </label>
          <input
            type="text"
            value={collectionSuffix}
            onChange={(e) => setCollectionSuffix(e.target.value)}
            placeholder="default"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
      </div>

      <div className="input-row">
        <div className="input-group">
          <label>
            Collection Name
            <TooltipIcon name="COLLECTION_NAME" />
          </label>
          <input
            type="text"
            value={collectionName}
            onChange={(e) => setCollectionName(e.target.value)}
            placeholder="code_chunks_{REPO}"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
        <div className="input-group">
          <label>
            Repo Path
            <TooltipIcon name="REPO_PATH" />
          </label>
          <input
            type="text"
            value={repoPath}
            onChange={(e) => setRepoPath(e.target.value)}
            placeholder="/path/to/repo"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
      </div>

      {/* Directory Paths */}
      <h3 style={{ marginTop: '32px' }}>Directory Paths</h3>
      <div className="input-row">
        <div className="input-group">
          <label>
            GUI Directory
            <TooltipIcon name="GUI_DIR" />
          </label>
          <input
            type="text"
            value={guiDir}
            onChange={(e) => setGuiDir(e.target.value)}
            placeholder="./web/public"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
        <div className="input-group">
          <label>
            Docs Directory
            <TooltipIcon name="DOCS_DIR" />
          </label>
          <input
            type="text"
            value={docsDir}
            onChange={(e) => setDocsDir(e.target.value)}
            placeholder="./docs"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
      </div>

      <div className="input-row">
        <div className="input-group">
          <label>
            Data Directory
            <TooltipIcon name="DATA_DIR" />
          </label>
          <input
            type="text"
            value={dataDir}
            onChange={(e) => setDataDir(e.target.value)}
            placeholder="./data"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
        <div className="input-group">
          <label>
            Repos File
            <TooltipIcon name="REPOS_FILE" />
          </label>
          <input
            type="text"
            value={reposFile}
            onChange={(e) => setReposFile(e.target.value)}
            placeholder="./repos.json"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
      </div>

      {/* Storage Configuration */}
      <h3 style={{ marginTop: '32px' }}>Storage Configuration</h3>
      <div className="input-row">
        <div className="input-group">
          <label>
            Output Directory Base
            <TooltipIcon name="OUT_DIR_BASE" />
          </label>
          <input
            type="text"
            value={outDirBase}
            onChange={(e) => setOutDirBase(e.target.value)}
            placeholder="./out"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
          <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
            Primary storage location for all indexed data
          </p>
        </div>
        <div className="input-group">
          <label>
            RAG Output Base
            <TooltipIcon name="RAG_OUT_BASE" />
          </label>
          <input
            type="text"
            value={ragOutBase}
            onChange={(e) => setRagOutBase(e.target.value)}
            placeholder="Override for OUT_DIR_BASE"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          />
        </div>
      </div>

      {/* Save Button */}
      <div style={{ marginTop: '32px' }}>
        <button
          className="small-button"
          onClick={saveConfig}
          disabled={saving}
          style={{
            width: '100%',
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            fontWeight: '600',
            padding: '12px',
            opacity: saving ? 0.5 : 1,
            cursor: saving ? 'not-allowed' : 'pointer'
          }}
        >
          {saving ? 'Saving...' : 'Save Configuration'}
        </button>
      </div>
    </div>
  );
}
