import { useCallback, useEffect, useState } from 'react';
import { lineageService } from '@/services/LineageService';
import { showToast } from '@/utils/toast';
import type { LineageRef } from '@/types/generated';
import type { LineageAliasName } from '@/services/LineageService';

const ALIASES: LineageAliasName[] = ['baseline', 'canary', 'current', 'promoted'];

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
  const [savingAlias, setSavingAlias] = useState<LineageAliasName | null>(null);
  // alias name -> bundle id it currently points at (for this corpus)
  const [aliasTargets, setAliasTargets] = useState<Record<string, string>>({});
  // Distinguish "no aliases exist" from "the lookup failed" — the empty-state
  // copy must never paper over an unreachable alias store.
  const [aliasLookupFailed, setAliasLookupFailed] = useState(false);
  const canAlias = Boolean(bundleId);

  const refreshAliases = useCallback(async () => {
    try {
      const data = await lineageService.listAliases(corpusId || undefined);
      const next: Record<string, string> = {};
      for (const entry of data.aliases || []) {
        next[entry.alias] = entry.bundle_id;
      }
      setAliasTargets(next);
      setAliasLookupFailed(false);
    } catch {
      setAliasLookupFailed(true);
    }
  }, [corpusId]);

  useEffect(() => {
    if (canAlias) void refreshAliases();
  }, [canAlias, refreshAliases]);

  const setAlias = async (alias: LineageAliasName) => {
    if (!bundleId) return;
    setSavingAlias(alias);
    try {
      await lineageService.setAlias(alias, bundleId, corpusId || undefined);
      showToast(`Lineage alias "${alias}" now points at ${shortId(bundleId)}`, 'success');
      await refreshAliases();
    } catch (e) {
      showToast(e instanceof Error ? e.message : `Failed to set ${alias}`, 'error');
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
        <div style={{ display: 'grid', gap: '6px' }}>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
            {ALIASES.map((alias) => {
              const pointsHere = Boolean(bundleId) && aliasTargets[alias] === bundleId;
              return (
                <button
                  key={alias}
                  className="small-button"
                  data-testid={`lineage-set-${alias}`}
                  onClick={() => void setAlias(alias)}
                  disabled={savingAlias !== null || pointsHere}
                  aria-pressed={pointsHere}
                  title={
                    pointsHere
                      ? `"${alias}" already points at this bundle`
                      : aliasTargets[alias]
                        ? `"${alias}" currently points at ${shortId(aliasTargets[alias])}; click to move it here`
                        : `"${alias}" is unset; click to point it at this bundle`
                  }
                  style={
                    pointsHere
                      ? { borderColor: 'var(--ok)', color: 'var(--ok)', fontWeight: 700 }
                      : undefined
                  }
                >
                  {savingAlias === alias ? `Saving ${alias}...` : pointsHere ? `✓ ${alias}` : `Set ${alias}`}
                </button>
              );
            })}
          </div>
          {aliasLookupFailed ? (
            <div style={{ fontSize: '11.5px', color: 'var(--warn, var(--fg-muted))' }}>
              Alias state unavailable — the lineage alias lookup failed; buttons still write.
            </div>
          ) : Object.keys(aliasTargets).length ? (
            <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>
              {ALIASES.filter((a) => aliasTargets[a]).map((a) => (
                <span key={a} style={{ marginRight: '12px' }}>
                  {a} → <span className="studio-mono">{shortId(aliasTargets[a])}</span>
                </span>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>
              No aliases set for this corpus yet.
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
