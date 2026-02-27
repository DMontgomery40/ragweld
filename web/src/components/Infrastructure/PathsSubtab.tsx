import { useEffect, useMemo, useState } from 'react';

import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { useConfig, useConfigField } from '@/hooks';
import { useRepoStore } from '@/stores/useRepoStore';

export function PathsSubtab() {
  const { loading: configLoading, flushPendingPatches } = useConfig();
  const { activeRepo, repos, updateCorpus } = useRepoStore();
  const [saving, setSaving] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  // Valid nested config keys only.
  const [postgresUrl, setPostgresUrl] = useConfigField<string>(
    'indexing.postgres_url',
    'postgresql://postgres:postgres@localhost:5432/tribrid_rag'
  );
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

  const activeCorpus = useMemo(() => {
    const id = String(activeRepo || '').trim();
    if (!id) return undefined;
    return repos.find((r) => r.corpus_id === id || r.slug === id || r.name === id);
  }, [activeRepo, repos]);

  const [corpusName, setCorpusName] = useState('');
  const [corpusPath, setCorpusPath] = useState('');
  const [corpusDescription, setCorpusDescription] = useState('');

  useEffect(() => {
    setCorpusName(String(activeCorpus?.name || ''));
    setCorpusPath(String(activeCorpus?.path || ''));
    setCorpusDescription(String(activeCorpus?.description || ''));
  }, [activeCorpus]);

  async function saveConfig() {
    setSaving(true);
    setActionMessage('Saving configuration...');

    try {
      await flushPendingPatches();

      if (activeCorpus) {
        const updates: { name?: string; path?: string; description?: string | null } = {};
        if (corpusName !== String(activeCorpus.name || '')) updates.name = corpusName;
        if (corpusPath !== String(activeCorpus.path || '')) updates.path = corpusPath;
        if (corpusDescription !== String(activeCorpus.description || '')) updates.description = corpusDescription;
        if (Object.keys(updates).length > 0) {
          await updateCorpus(activeCorpus.corpus_id, updates);
        }
      }

      setActionMessage('Configuration saved successfully!');
    } catch (error: any) {
      setActionMessage(`Failed to save configuration: ${error?.message || String(error)}`);
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
      {actionMessage && (
        <div
          style={{
            padding: '12px',
            background: 'var(--bg-elev2)',
            border: '1px solid var(--line)',
            borderRadius: '6px',
            marginBottom: '16px',
            fontSize: '12px',
            color: 'var(--fg)',
          }}
        >
          {actionMessage}
        </div>
      )}

      <h2>Infrastructure Configuration</h2>
      <p className="small" style={{ marginBottom: '24px' }}>
        Configure database endpoints and active corpus metadata.
      </p>

      <h3>Database Endpoints</h3>
      <div className="input-row">
        <div className="input-group">
          <label>
            PostgreSQL DSN
            <TooltipIcon name="POSTGRES_URL" />
          </label>
          <input
            data-testid="postgres-url"
            type="text"
            value={postgresUrl}
            onChange={(e) => setPostgresUrl(e.target.value)}
            placeholder="postgresql://postgres:postgres@localhost:5432/tribrid_rag"
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)',
            }}
          />
        </div>
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
              color: 'var(--fg)',
            }}
          />
        </div>
      </div>

      <div className="input-row">
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
              color: 'var(--fg)',
            }}
          />
        </div>
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
              color: 'var(--fg)',
            }}
          />
        </div>
      </div>

      <div className="input-row">
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
              color: 'var(--fg)',
            }}
          />
        </div>
        <div className="input-group">
          <label>
            Database Mode
            <TooltipIcon name="neo4j_database_mode" />
          </label>
          <select
            data-testid="neo4j-database-mode"
            value={neo4jDatabaseMode}
            onChange={(e) => setNeo4jDatabaseMode(e.target.value as 'shared' | 'per_corpus')}
            style={{
              width: '100%',
              padding: '8px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)',
            }}
          >
            <option value="shared">Shared (Community-compatible)</option>
            <option value="per_corpus">Per corpus (Enterprise multi-db)</option>
          </select>
        </div>
      </div>

      <div className="input-row">
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
        </div>
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
        </div>
      </div>

      <h3 style={{ marginTop: '32px' }}>Active Corpus Metadata</h3>
      {!activeCorpus ? (
        <p className="small" style={{ color: 'var(--fg-muted)' }}>
          Select a corpus to edit corpus path/name/description.
        </p>
      ) : (
        <>
          <div className="input-row">
            <div className="input-group">
              <label>Corpus Name</label>
              <input
                data-testid="corpus-name"
                type="text"
                value={corpusName}
                onChange={(e) => setCorpusName(e.target.value)}
                style={{
                  width: '100%',
                  padding: '8px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '4px',
                  color: 'var(--fg)',
                }}
              />
            </div>
            <div className="input-group">
              <label>Corpus Path</label>
              <input
                data-testid="corpus-path"
                type="text"
                value={corpusPath}
                onChange={(e) => setCorpusPath(e.target.value)}
                placeholder="/absolute/path/to/repo"
                style={{
                  width: '100%',
                  padding: '8px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '4px',
                  color: 'var(--fg)',
                }}
              />
            </div>
          </div>
          <div className="input-row">
            <div className="input-group">
              <label>Description</label>
              <input
                data-testid="corpus-description"
                type="text"
                value={corpusDescription}
                onChange={(e) => setCorpusDescription(e.target.value)}
                placeholder="Optional corpus description"
                style={{
                  width: '100%',
                  padding: '8px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '4px',
                  color: 'var(--fg)',
                }}
              />
            </div>
            <div className="input-group" />
          </div>
        </>
      )}

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
            cursor: saving ? 'not-allowed' : 'pointer',
          }}
        >
          {saving ? 'Saving...' : 'Save Configuration'}
        </button>
      </div>
    </div>
  );
}
