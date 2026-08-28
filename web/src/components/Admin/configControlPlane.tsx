import { type CSSProperties, useCallback, useEffect, useState } from 'react';

import { configApi } from '@/api/config';
import { useConfig } from '@/hooks';
import { useActiveRepo } from '@/stores';
import type {
  ConfigFieldDescriptor,
  ConfigReadinessResponse,
  ConfigRegistryResponse,
  IntegrationReadiness,
  SecretRequirementStatus,
  TriBridConfig,
} from '@/types/generated';

export type ConfigSurfaceId = 'runtime' | 'retrieval' | 'observability' | 'training' | 'eval' | 'graph' | 'shell';

export const CONFIG_SURFACES: Array<{ id: ConfigSurfaceId; title: string; description: string }> = [
  {
    id: 'runtime',
    title: 'Runtime',
    description: 'Gateway routing, serving backends, and primary chat generation controls.',
  },
  {
    id: 'retrieval',
    title: 'Retrieval',
    description: 'Indexing, retrieval fusion, reranking, and the Haystack/Docling/Qdrant lane.',
  },
  {
    id: 'observability',
    title: 'Observability',
    description: 'OTel export, Grafana/Tempo/Alloy, and Langfuse operator wiring.',
  },
  {
    id: 'training',
    title: 'Training',
    description: 'Flyte, MLflow, Unsloth, and Learning Agent control-plane settings.',
  },
  {
    id: 'eval',
    title: 'Eval',
    description: 'Ragas, Promptfoo, prompts, and evaluation dataset settings.',
  },
  {
    id: 'graph',
    title: 'Graph',
    description: 'Neo4j connection, graph parity, and graph retrieval controls.',
  },
  {
    id: 'shell',
    title: 'Shell',
    description: 'Workbench shell, admin, MCP, Docker, and operator-facing UI settings.',
  },
];

const CARD_STYLE: CSSProperties = {
  background: 'var(--bg-elev1)',
  border: '1px solid var(--line)',
  borderRadius: 12,
  padding: 16,
};

const CHIP_BASE: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '4px 8px',
  borderRadius: 999,
  border: '1px solid var(--line)',
  fontSize: 11,
  fontWeight: 700,
};

const WRAP_ANYWHERE_STYLE: CSSProperties = {
  minWidth: 0,
  overflowWrap: 'anywhere',
  wordBreak: 'break-word',
};

const FIELD_HEADER_STYLE: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 12,
  alignItems: 'flex-start',
  flexWrap: 'wrap',
  width: '100%',
  minWidth: 0,
};

const FIELD_CONTROL_ROW_STYLE: CSSProperties = {
  display: 'flex',
  gap: 10,
  alignItems: 'center',
  flexWrap: 'wrap',
  width: '100%',
  minWidth: 0,
};

const FIELD_TRAILING_ROW_STYLE: CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 12,
  alignItems: 'center',
  flexWrap: 'wrap',
  width: '100%',
  minWidth: 0,
};

const FIELD_INPUT_STYLE: CSSProperties = {
  flex: '1 1 240px',
  minWidth: 0,
  width: '100%',
  maxWidth: '100%',
  padding: '9px 12px',
  borderRadius: 8,
  background: 'var(--bg)',
  border: '1px solid var(--line)',
  color: 'var(--fg)',
};

const FIELD_TEXTAREA_STYLE: CSSProperties = {
  width: '100%',
  maxWidth: '100%',
  minWidth: 0,
  padding: 12,
  borderRadius: 10,
  border: '1px solid var(--line)',
  background: 'var(--bg)',
  color: 'var(--fg)',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
};

const ACTION_BUTTON_STYLE: CSSProperties = {
  padding: '8px 12px',
  borderRadius: 8,
  border: '1px solid var(--line)',
  background: 'var(--bg-elev2)',
  color: 'var(--fg)',
  fontWeight: 700,
  cursor: 'pointer',
  flex: '0 0 auto',
  maxWidth: '100%',
  alignSelf: 'flex-start',
};

const STATE_TONES: Record<string, { fg: string; bg: string; border: string }> = {
  ready: { fg: 'var(--ok)', bg: 'rgba(var(--ok-rgb), 0.12)', border: 'rgba(var(--ok-rgb), 0.28)' },
  degraded: { fg: 'var(--warn)', bg: 'rgba(var(--warn-rgb), 0.12)', border: 'rgba(var(--warn-rgb), 0.28)' },
  unconfigured: { fg: 'var(--err)', bg: 'rgba(var(--err-rgb), 0.12)', border: 'rgba(var(--err-rgb), 0.28)' },
  disabled: { fg: 'var(--fg-muted)', bg: 'var(--bg-elev2)', border: 'var(--line)' },
};

export function readConfigPath(config: TriBridConfig | null, path: string): unknown {
  if (!config) return undefined;
  const parts = path.split('.').filter(Boolean);
  let current: any = config;
  for (const part of parts) {
    if (current == null) return undefined;
    current = current[part];
  }
  return current;
}

function buildPatchForPath(path: string, value: unknown): { section: keyof TriBridConfig; patch: Record<string, unknown> | unknown } {
  const [section, ...rest] = path.split('.').filter(Boolean);
  if (!section) {
    throw new Error(`Invalid config path: ${path}`);
  }
  if (rest.length === 0) {
    return { section: section as keyof TriBridConfig, patch: value };
  }
  let patch: Record<string, unknown> | unknown = value;
  for (let idx = rest.length - 1; idx >= 0; idx -= 1) {
    patch = { [rest[idx]]: patch };
  }
  return { section: section as keyof TriBridConfig, patch };
}

function stringifyDraft(value: unknown, field: ConfigFieldDescriptor): string {
  if (value == null) return '';
  if (field.type === 'object' || field.type === 'array') {
    return JSON.stringify(value, null, 2);
  }
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function parseDraft(field: ConfigFieldDescriptor, draft: string): unknown {
  if (field.enum_values && field.enum_values.length > 0) return draft;
  if (field.type === 'integer') {
    if (!draft.trim()) return field.default ?? 0;
    const parsed = Number.parseInt(draft, 10);
    if (Number.isNaN(parsed)) throw new Error('Expected an integer value.');
    return parsed;
  }
  if (field.type === 'number') {
    if (!draft.trim()) return field.default ?? 0;
    const parsed = Number.parseFloat(draft);
    if (Number.isNaN(parsed)) throw new Error('Expected a numeric value.');
    return parsed;
  }
  if (field.type === 'object' || field.type === 'array') {
    if (!draft.trim()) return field.type === 'array' ? [] : {};
    return JSON.parse(draft);
  }
  return draft;
}

function formatValuePreview(value: unknown): string {
  if (value == null) return 'Unset';
  if (typeof value === 'boolean') return value ? 'Enabled' : 'Disabled';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value || 'Empty string';
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? '' : 's'}`;
  return 'JSON value';
}

export function stateChipStyle(state: string): CSSProperties {
  const tone = STATE_TONES[state] || STATE_TONES.disabled;
  return {
    ...CHIP_BASE,
    color: tone.fg,
    background: tone.bg,
    borderColor: tone.border,
  };
}

export function useConfigControlPlaneData() {
  const activeRepo = useActiveRepo();
  const [registry, setRegistry] = useState<ConfigRegistryResponse | null>(null);
  const [readiness, setReadiness] = useState<ConfigReadinessResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextRegistry, nextReadiness] = await Promise.all([
        configApi.registry(),
        configApi.readiness(),
      ]);
      setRegistry(nextRegistry);
      setReadiness(nextReadiness);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load config control plane data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [activeRepo, load]);

  return {
    registry,
    readiness,
    loading,
    error,
    reload: load,
  };
}

type ConfigFieldEditorProps = {
  field: ConfigFieldDescriptor;
  config: TriBridConfig | null;
  onSave: (path: string, value: unknown) => Promise<void>;
  onOpenRaw?: (section: string) => void;
  saving: boolean;
  showMetadata?: boolean;
};

export function ConfigFieldEditor({
  field,
  config,
  onSave,
  onOpenRaw,
  saving,
  showMetadata = true,
}: ConfigFieldEditorProps) {
  const currentValue = readConfigPath(config, field.path);
  const [draft, setDraft] = useState<string>(() => stringifyDraft(currentValue, field));
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    setDraft(stringifyDraft(currentValue, field));
    setFieldError(null);
  }, [currentValue, field]);

  const commit = async () => {
    try {
      const parsed = parseDraft(field, draft);
      await onSave(field.path, parsed);
      setFieldError(null);
      setStatus('Saved');
      window.setTimeout(() => setStatus(null), 1200);
    } catch (err) {
      setFieldError(err instanceof Error ? err.message : 'Unable to save this field.');
    }
  };

  const metaChips = showMetadata ? (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
      <span style={CHIP_BASE}>{field.scope}</span>
      <span style={CHIP_BASE}>{field.integration}</span>
      <span style={CHIP_BASE}>{field.impact}</span>
      <span style={CHIP_BASE}>{field.exposure_level}</span>
    </div>
  ) : null;

  const saveButton = (
    <button
      type="button"
      onClick={() => {
        void commit();
      }}
      disabled={saving}
      style={ACTION_BUTTON_STYLE}
    >
      {saving ? 'Saving…' : 'Save'}
    </button>
  );

  return (
    <div data-config-path={field.path} style={{ ...CARD_STYLE, padding: 14, width: '100%', minWidth: 0 }}>
      <div style={FIELD_HEADER_STYLE}>
        <div style={{ ...WRAP_ANYWHERE_STYLE, flex: '1 1 240px' }}>
          <div style={{ fontWeight: 700, color: 'var(--fg)' }}>{field.label}</div>
          <div
            style={{
              ...WRAP_ANYWHERE_STYLE,
              marginTop: 4,
              fontSize: 12,
              color: 'var(--fg-muted)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {field.path}
          </div>
          {field.description ? (
            <div style={{ ...WRAP_ANYWHERE_STYLE, marginTop: 8, fontSize: 12, color: 'var(--fg-muted)', lineHeight: 1.5 }}>
              {field.description}
            </div>
          ) : null}
          {metaChips}
        </div>
        {onOpenRaw ? (
          <button
            type="button"
            onClick={() => onOpenRaw(field.section)}
            style={{
              ...WRAP_ANYWHERE_STYLE,
              padding: '6px 10px',
              borderRadius: 8,
              border: '1px solid var(--line)',
              background: 'transparent',
              color: 'var(--fg-muted)',
              cursor: 'pointer',
            }}
          >
            Open Raw
          </button>
        ) : null}
      </div>

      <div style={{ marginTop: 12 }}>
        {field.type === 'boolean' ? (
          <label className="toggle" style={{ ...WRAP_ANYWHERE_STYLE, width: '100%' }}>
            <input
              type="checkbox"
              checked={Boolean(currentValue)}
              onChange={(event) => {
                void onSave(field.path, event.target.checked).catch((err) => {
                  setFieldError(err instanceof Error ? err.message : 'Unable to save this field.');
                });
              }}
            />
            <span className="toggle-track" aria-hidden="true">
              <span className="toggle-thumb"></span>
            </span>
            <span className="toggle-label" style={WRAP_ANYWHERE_STYLE}>
              {Boolean(currentValue) ? 'Enabled' : 'Disabled'}
            </span>
          </label>
        ) : field.enum_values && field.enum_values.length > 0 ? (
          <div style={FIELD_CONTROL_ROW_STYLE}>
            <select
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              style={FIELD_INPUT_STYLE}
            >
              {field.enum_values.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
            {saveButton}
          </div>
        ) : field.type === 'object' || field.type === 'array' ? (
          <div>
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              spellCheck={false}
              rows={8}
              style={FIELD_TEXTAREA_STYLE}
            />
            <div style={{ ...FIELD_TRAILING_ROW_STYLE, marginTop: 10 }}>
              <div style={{ ...WRAP_ANYWHERE_STYLE, fontSize: 12, color: 'var(--fg-muted)', flex: '1 1 220px' }}>
                Current: {formatValuePreview(currentValue)}
              </div>
              {saveButton}
            </div>
          </div>
        ) : (
          <div style={FIELD_CONTROL_ROW_STYLE}>
            <input
              type={field.type === 'integer' || field.type === 'number' ? 'number' : 'text'}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              step={field.type === 'integer' ? '1' : 'any'}
              style={FIELD_INPUT_STYLE}
            />
            {saveButton}
          </div>
        )}
      </div>

      {field.secret_dependency_ids && field.secret_dependency_ids.length > 0 ? (
        <div style={{ ...WRAP_ANYWHERE_STYLE, marginTop: 10, fontSize: 12, color: 'var(--fg-muted)' }}>
          Secret dependencies: {field.secret_dependency_ids.join(', ')}
        </div>
      ) : null}

      {fieldError ? <div style={{ ...WRAP_ANYWHERE_STYLE, marginTop: 10, fontSize: 12, color: 'var(--err)' }}>{fieldError}</div> : null}
      {status ? <div style={{ ...WRAP_ANYWHERE_STYLE, marginTop: 10, fontSize: 12, color: 'var(--ok)' }}>{status}</div> : null}
    </div>
  );
}

export function useConfigFieldSave() {
  const { patchSection, saveConfig, config, saving } = useConfig();

  const saveField = async (path: string, value: unknown) => {
    const { section, patch } = buildPatchForPath(path, value);
    await patchSection(section, patch as Record<string, unknown>);
  };

  const replaceSection = async (section: string, value: unknown) => {
    if (!config) {
      throw new Error('Configuration has not loaded yet.');
    }
    const nextConfig = {
      ...(config as unknown as Record<string, unknown>),
      [section]: value,
    } as TriBridConfig;
    await saveConfig(nextConfig);
  };

  return {
    config,
    saveField,
    replaceSection,
    saving,
  };
}

export function fieldsForSurface(
  registry: ConfigRegistryResponse | null,
  surfaceId: ConfigSurfaceId,
  exposure: 'basic' | 'advanced' | 'expert' | 'all' = 'all'
): ConfigFieldDescriptor[] {
  const fields = registry?.fields || [];
  return fields.filter((field) => {
    if (field.ui_surface !== surfaceId) return false;
    if (exposure === 'all') return true;
    return field.exposure_level === exposure;
  });
}

export function integrationsForSurface(
  readiness: ConfigReadinessResponse | null,
  surfaceId: ConfigSurfaceId
): IntegrationReadiness[] {
  return (readiness?.integrations || []).filter((item) => item.ui_surface === surfaceId);
}

export function secretStatusesForSurface(
  readiness: ConfigReadinessResponse | null,
  surfaceId: ConfigSurfaceId
): SecretRequirementStatus[] {
  return (readiness?.secrets || []).filter((item) => item.requirement.ui_surface === surfaceId);
}
