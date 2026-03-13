import { useState } from 'react';
import { lineageService } from '@/services/LineageService';
import { useNotification } from '@/hooks';
import type { LineageRef } from '@/types/generated';
import type { LineageAliasName } from '@/services/LineageService';

function shortId(value: string | null | undefined): string {
  const text = String(value || '').trim();
  if (!text) return '—';
  if (text.length <= 28) return text;
  return `${text.slice(0, 12)}...${text.slice(-12)}`;
}

export function LineageMeta({
  bundleId,
  inputBundleId,
  lineageRef,
  modelArtifactRef,
  corpusId,
}: {
  bundleId?: string | null;
  inputBundleId?: string | null;
  lineageRef?: LineageRef | null;
  modelArtifactRef?: LineageRef | null;
  corpusId?: string | null;
}) {
  const { success, error } = useNotification();
  const [savingAlias, setSavingAlias] = useState<LineageAliasName | null>(null);
  const canAlias = Boolean(bundleId);

  const setAlias = async (alias: LineageAliasName) => {
    if (!bundleId) return;
    setSavingAlias(alias);
    try {
      await lineageService.setAlias(alias, bundleId, corpusId || undefined);
      success(`Lineage alias updated: ${alias}`);
    } catch (e) {
      error(e instanceof Error ? e.message : `Failed to set ${alias}`);
    } finally {
      setSavingAlias(null);
    }
  };

  if (!bundleId && !inputBundleId && !lineageRef && !modelArtifactRef) {
    return null;
  }

  return (
    <div
      style={{
        border: '1px solid var(--line)',
        borderRadius: '8px',
        background: 'var(--bg-elev1)',
        padding: '12px',
        display: 'grid',
        gap: '8px',
      }}
    >
      <div style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.04em', color: 'var(--accent)' }}>
        LINEAGE
      </div>
      {inputBundleId ? (
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          input bundle: <span className="studio-mono">{shortId(inputBundleId)}</span>
        </div>
      ) : null}
      {bundleId ? (
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          current bundle: <span className="studio-mono">{shortId(bundleId)}</span>
        </div>
      ) : null}
      {lineageRef ? (
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          version: <span className="studio-mono">{lineageRef.kind}:{shortId(lineageRef.version_id)}</span>
        </div>
      ) : null}
      {modelArtifactRef ? (
        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          model artifact: <span className="studio-mono">{shortId(modelArtifactRef.version_id)}</span>
        </div>
      ) : null}
      {canAlias ? (
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {(['baseline', 'canary', 'current', 'promoted'] as LineageAliasName[]).map((alias) => (
            <button
              key={alias}
              className="small-button"
              onClick={() => void setAlias(alias)}
              disabled={savingAlias !== null}
            >
              {savingAlias === alias ? `Saving ${alias}...` : `Set ${alias}`}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
