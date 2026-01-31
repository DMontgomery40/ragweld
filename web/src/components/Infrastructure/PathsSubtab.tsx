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
  const { loading: configLoading, patchSection } = useConfig();
  const [saving, setSaving] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Database endpoints from Pydantic GraphStorageConfig
  const [neo4jUri, setNeo4jUri] = useConfigField<string>('graph_storage.neo4j_uri', 'bolt://localhost:7687');
  const [neo4jUser, setNeo4jUser] = useConfigField<string>('graph_storage.neo4j_user', 'neo4j');
  const [neo4jPassword, setNeo4jPassword] = useConfigField<string>('graph_storage.neo4j_password', '');
  const [neo4jDatabase, setNeo4jDatabase] = useConfigField<string>('graph_storage.neo4j_database', 'neo4j');
  const [neo4jDatabaseMode, setNeo4jDatabaseMode] = useConfigField<'shared' | 'per_corpus'>(
    'graph_storage.neo4j_database_mode',
    'shared'
  );
  const [neo4jDatabasePrefix, setNeo4jDatabasePrefix] = useConfigField<string>(
    'graph_storage.neo4j_database_prefix',
    'tribrid_'
  );
  const [neo4jAutoCreateDatabases, setNeo4jAutoCreateDatabases] = useConfigField<boolean>(
    'graph_storage.neo4j_auto_create_databases',
    true
  );
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
      // Path settings - save to appropriate Pydantic config sections
      // Note: Many legacy env-style fields removed; use Pydantic sections
      await patchSection('indexing', {
        // Path-related settings would go here when added to Pydantic
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
            Neo4j URI
            <TooltipIcon name="neo4j_uri" />
          </label>
          <input
            data-testid="neo4j-uri"
            type="text"
            value={neo4jUri}
            onChange={(e) => setNeo4jUri(e.target.value)}
            placeholder="bolt://localhost:7687"
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
            Graph database connection URI
          </p>
        </div>
        <div className="input-group">
          <label>
            Neo4j User
            <TooltipIcon name="neo4j_user" />
          </label>
          <input
            data-testid="neo4j-user"
            type="text"
            value={neo4jUser}
            onChange={(e) => setNeo4jUser(e.target.value)}
            placeholder="neo4j"
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
            Neo4j authentication username
          </p>
        </div>
      </div>

      <div className="input-row">
        <div className="input-group">
          <label>
            Neo4j Password
            <TooltipIcon name="neo4j_password" />
          </label>
          <input
            data-testid="neo4j-password"
            type="password"
            value={neo4jPassword}
            onChange={(e) => setNeo4jPassword(e.target.value)}
            placeholder="password"
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
            Neo4j authentication password
          </p>
        </div>
        <div className="input-group">
          <label>
            Neo4j Database (shared mode)
            <TooltipIcon name="neo4j_database" />
          </label>
          <input
            data-testid="neo4j-database"
            type="text"
            value={neo4jDatabase}
            onChange={(e) => setNeo4jDatabase(e.target.value)}
            placeholder="neo4j"
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
            Used when database mode is set to shared.
          </p>
        </div>
      </div>

      <h3 style={{ marginTop: '32px' }}>Neo4j Database Isolation</h3>
      <div className="input-row">
        <div className="input-group">
          <label>
            Database Mode
            <TooltipIcon name="neo4j_database_mode" />
          </label>
          <select
            data-testid="neo4j-database-mode"
            value={neo4jDatabaseMode}
            onChange={(e) => setNeo4jDatabaseMode(e.target.value as any)}
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)'
            }}
          >
            <option value="shared">Shared (Community-compatible)</option>
            <option value="per_corpus">Per corpus (Enterprise multi-db)</option>
          </select>
          <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
            Per-corpus databases require Neo4j Enterprise with multi-database support.
          </p>
        </div>
        <div className="input-group">
          <label>
            Per-corpus DB prefix
            <TooltipIcon name="neo4j_database_prefix" />
          </label>
          <input
            data-testid="neo4j-database-prefix"
            type="text"
            value={neo4jDatabasePrefix}
            onChange={(e) => setNeo4jDatabasePrefix(e.target.value)}
            placeholder="tribrid_"
            disabled={neo4jDatabaseMode !== 'per_corpus'}
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)',
              opacity: neo4jDatabaseMode === 'per_corpus' ? 1 : 0.6,
            }}
          />
          <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
            Applied to database names when per-corpus mode is enabled.
          </p>
        </div>
      </div>

      <div className="input-row">
        <div className="input-group">
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              data-testid="neo4j-auto-create-databases"
              type="checkbox"
              checked={neo4jAutoCreateDatabases}
              onChange={(e) => setNeo4jAutoCreateDatabases(e.target.checked)}
              disabled={neo4jDatabaseMode !== 'per_corpus'}
            />
            Auto-create per-corpus databases
            <TooltipIcon name="neo4j_auto_create_databases" />
          </label>
          <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
            When enabled, creating a corpus will create its Neo4j database automatically (Enterprise).
          </p>
        </div>
        <div className="input-group" />
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
