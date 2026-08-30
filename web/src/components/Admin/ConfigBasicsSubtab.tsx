import {
  CONFIG_SURFACES,
  ConfigFieldEditor,
  fieldsForSurface,
  integrationsForSurface,
  stateChipStyle,
  useConfigControlPlaneData,
  useConfigFieldSave,
} from './configControlPlane';
import { useActiveRepo } from '@/stores/useRepoStore';

type ConfigBasicsSubtabProps = {
  onOpenRaw: (section: string) => void;
};

export function ConfigBasicsSubtab({ onOpenRaw }: ConfigBasicsSubtabProps) {
  const activeRepo = useActiveRepo();
  const { registry, readiness, loading, error, reload } = useConfigControlPlaneData();
  const { config, saveField, saving } = useConfigFieldSave();
  const saveAndRefresh = async (path: string, value: unknown) => {
    await saveField(path, value);
    await reload();
  };

  if (loading) {
    return <div className="settings-section">Loading configuration control plane…</div>;
  }

  if (error) {
    return (
      <div className="settings-section" style={{ minWidth: 0 }}>
        <div style={{ color: 'var(--err)', marginBottom: 12 }}>Unable to load configuration control plane: {error}</div>
        <button type="button" onClick={() => { void reload(); }}>Retry</button>
      </div>
    );
  }

  return (
    <div className="settings-section" style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 20, minWidth: 0, width: '100%' }}>
        <div style={{ minWidth: 0, flex: '1 1 320px' }}>
          <h2 style={{ marginBottom: 8 }}>Configuration Center</h2>
          {/* The page was titled as though it edited global defaults, while every write
              carried `?corpus_id=<active corpus>`. An operator changing a corpus-scoped
              field here believed they were setting the default for everything (M-28). */}
          <div
            data-testid="admin-basic-scope"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 10,
              padding: '6px 12px',
              borderRadius: 999,
              border: '1px solid var(--line)',
              background: 'var(--bg-elev2)',
              fontSize: 12.5,
              color: 'var(--fg)',
            }}
          >
            <span style={{ fontWeight: 700, letterSpacing: '0.04em', textTransform: 'uppercase', color: 'var(--fg-muted)' }}>
              Editing corpus
            </span>
            <span data-testid="admin-basic-scope-corpus" style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
              {activeRepo || 'none selected'}
            </span>
          </div>
          <p className="small" style={{ maxWidth: 860, minWidth: 0, overflowWrap: 'anywhere' }}>
            Curated operator controls for the locked OSS stack. Every field here comes from the backend registry, and every integration card reflects live readiness rather than hand-maintained UI copy. Fields tagged <strong>corpus</strong> are saved against the corpus named above and change nothing for any other corpus; fields tagged <strong>global</strong> apply to the whole deployment.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'start', flexWrap: 'wrap', minWidth: 0 }}>
          <button
            type="button"
            onClick={() => {
              void reload();
            }}
            style={{
              padding: '10px 12px',
              borderRadius: 8,
              border: '1px solid var(--line)',
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              cursor: 'pointer',
              fontWeight: 700,
            }}
          >
            Refresh Readiness
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 18, minWidth: 0 }}>
        {CONFIG_SURFACES.map((surface) => {
          const fields = fieldsForSurface(registry, surface.id, 'basic');
          const integrations = integrationsForSurface(readiness, surface.id);
          return (
            <section
              key={surface.id}
              style={{
                background: 'var(--bg-elev1)',
                border: '1px solid var(--line)',
                borderRadius: 14,
                padding: 18,
                minWidth: 0,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 14, minWidth: 0, width: '100%' }}>
                <div style={{ minWidth: 0, flex: '1 1 280px' }}>
                  <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--fg)' }}>{surface.title}</div>
                  <div style={{ marginTop: 6, fontSize: 13, color: 'var(--fg-muted)', maxWidth: 760, minWidth: 0, overflowWrap: 'anywhere' }}>
                    {surface.description}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'start', minWidth: 0 }}>
                  {integrations.map((integration) => (
                    <span key={integration.id} style={stateChipStyle(integration.state)}>
                      {integration.label}: {integration.state}
                    </span>
                  ))}
                </div>
              </div>

              {integrations.length > 0 ? (
                <div style={{ display: 'grid', gap: 10, marginBottom: 16, minWidth: 0 }}>
                  {integrations.map((integration) => (
                    <div
                      key={integration.id}
                      style={{
                        padding: 12,
                        borderRadius: 10,
                        border: '1px solid var(--line)',
                        background: 'var(--bg)',
                        minWidth: 0,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', minWidth: 0, width: '100%' }}>
                        <div style={{ fontWeight: 700, color: 'var(--fg)', minWidth: 0, overflowWrap: 'anywhere' }}>{integration.label}</div>
                        <span style={stateChipStyle(integration.state)}>{integration.state}</span>
                      </div>
                      {integration.operator_hint ? (
                        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--fg-muted)', lineHeight: 1.5, minWidth: 0, overflowWrap: 'anywhere' }}>
                          {integration.operator_hint}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}

              {fields.length > 0 ? (
                <div style={{ display: 'grid', gap: 12, minWidth: 0 }}>
                  {fields.map((field) => (
                    <ConfigFieldEditor
                      key={field.path}
                      field={field}
                      config={config}
                      onSave={saveAndRefresh}
                      onOpenRaw={onOpenRaw}
                      saving={saving}
                      showMetadata={false}
                    />
                  ))}
                </div>
              ) : (
                <div style={{ color: 'var(--fg-muted)', fontSize: 13 }}>
                  No Basic fields are classified for this surface yet. Use Advanced or Raw to inspect the full contract.
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
