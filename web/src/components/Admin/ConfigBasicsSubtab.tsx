import {
  CONFIG_SURFACES,
  ConfigFieldEditor,
  fieldsForSurface,
  integrationsForSurface,
  stateChipStyle,
  useConfigControlPlaneData,
  useConfigFieldSave,
} from './configControlPlane';

type ConfigBasicsSubtabProps = {
  onOpenRaw: (section: string) => void;
};

export function ConfigBasicsSubtab({ onOpenRaw }: ConfigBasicsSubtabProps) {
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
      <div className="settings-section">
        <div style={{ color: 'var(--err)', marginBottom: 12 }}>Unable to load configuration control plane: {error}</div>
        <button type="button" onClick={() => { void reload(); }}>Retry</button>
      </div>
    );
  }

  return (
    <div className="settings-section">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
        <div>
          <h2 style={{ marginBottom: 8 }}>Configuration Center</h2>
          <p className="small" style={{ maxWidth: 860 }}>
            Curated operator controls for the locked OSS stack. Every field here comes from the backend registry, and every integration card reflects live readiness rather than hand-maintained UI copy.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'start', flexWrap: 'wrap' }}>
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

      <div style={{ display: 'grid', gap: 18 }}>
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
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 14 }}>
                <div>
                  <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--fg)' }}>{surface.title}</div>
                  <div style={{ marginTop: 6, fontSize: 13, color: 'var(--fg-muted)', maxWidth: 760 }}>{surface.description}</div>
                </div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'start' }}>
                  {integrations.map((integration) => (
                    <span key={integration.id} style={stateChipStyle(integration.state)}>
                      {integration.label}: {integration.state}
                    </span>
                  ))}
                </div>
              </div>

              {integrations.length > 0 ? (
                <div style={{ display: 'grid', gap: 10, marginBottom: 16 }}>
                  {integrations.map((integration) => (
                    <div
                      key={integration.id}
                      style={{
                        padding: 12,
                        borderRadius: 10,
                        border: '1px solid var(--line)',
                        background: 'var(--bg)',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                        <div style={{ fontWeight: 700, color: 'var(--fg)' }}>{integration.label}</div>
                        <span style={stateChipStyle(integration.state)}>{integration.state}</span>
                      </div>
                      {integration.operator_hint ? (
                        <div style={{ marginTop: 8, fontSize: 12, color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                          {integration.operator_hint}
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : null}

              {fields.length > 0 ? (
                <div style={{ display: 'grid', gap: 12 }}>
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
