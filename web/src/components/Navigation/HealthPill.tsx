// TriBridRAG - Health pill (top bar)
//
// The pill used to be a dead control: it rendered "OK @ 7:12:03 AM" as a button, but clicking
// it only re-fired a health probe whose only visible effect was the timestamp ticking on its
// own (M-105). It also showed a bare time with no date and no statement of what "OK" covered
// (M-140 / A-38). This component makes the click open a component-status popover backed by the
// `/api/ready` dependency breakdown (postgres / neo4j / litellm / vllm / index manifests), says
// how stale the reading is, and offers a jump to the full System Status subtab.

import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useHealthStore } from '@/stores/useHealthStore';
import { getReadiness } from '@/api/dashboard';
import type { ReadinessStatus } from '@/types/generated';

const DEP_LABELS: Record<string, string> = {
  postgres: 'Postgres',
  neo4j: 'Neo4j',
  litellm: 'LiteLLM',
  vllm: 'vLLM',
  index_manifests: 'Index manifests',
};

function depLabel(key: string): string {
  return DEP_LABELS[key] ?? key;
}

/** A time-since string that never leaves the reader guessing which day it was ("2h ago"). */
function relativeSince(when: Date | null): string {
  if (!when) return 'not checked yet';
  const secs = Math.max(0, Math.round((Date.now() - when.getTime()) / 1000));
  if (secs < 5) return 'just now';
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

/** The short, non-sensitive line shown under one dependency. */
function depDetail(dep: ReadinessStatus['dependencies'][string]): string {
  if (dep.ok) {
    const info = dep.info as { status?: unknown } | null | undefined;
    const status = info && typeof info.status === 'string' ? info.status : '';
    return status || 'ready';
  }
  return dep.error || 'not ready';
}

export function HealthPill() {
  const navigate = useNavigate();
  const status = useHealthStore((s) => s.status);
  const lastChecked = useHealthStore((s) => s.lastChecked);
  const checkHealth = useHealthStore((s) => s.checkHealth);

  const [open, setOpen] = useState(false);
  const [readiness, setReadiness] = useState<ReadinessStatus | null>(null);
  const [readinessError, setReadinessError] = useState<string | null>(null);
  const [readinessLoading, setReadinessLoading] = useState(false);
  // Re-render the "checked Ns ago" label without waiting for the 30s health poll.
  const [, setTick] = useState(0);

  const wrapperRef = useRef<HTMLSpanElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);

  const isOk = !!status && (status.ok || status.status === 'healthy');
  const statusWord = status ? (isOk ? 'OK' : 'Not OK') : '—';
  const rel = relativeSince(lastChecked);
  // A date-bearing tooltip removes the last of the ambiguity the bare time left (M-140).
  const checkedTitle = lastChecked
    ? `Last checked ${lastChecked.toLocaleString()}`
    : 'Health has not been checked yet';

  const loadReadiness = useCallback(async () => {
    setReadinessLoading(true);
    setReadinessError(null);
    try {
      const data = await getReadiness();
      setReadiness(data);
    } catch (err) {
      setReadiness(null);
      setReadinessError(err instanceof Error ? err.message : 'Could not read /api/ready.');
    } finally {
      setReadinessLoading(false);
    }
  }, []);

  const openPopover = useCallback(() => {
    setOpen(true);
    // Refresh the top-line health probe and pull the dependency breakdown together, so the
    // pill and its popover agree. checkHealth shares one in-flight probe (see useHealthStore).
    void checkHealth();
    void loadReadiness();
  }, [checkHealth, loadReadiness]);

  const toggle = useCallback(() => {
    if (open) {
      setOpen(false);
    } else {
      openPopover();
    }
  }, [open, openPopover]);

  // Keep the relative-time label live while the popover is open.
  useEffect(() => {
    if (!open) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 5000);
    return () => window.clearInterval(id);
  }, [open]);

  // Dismiss on outside click or Escape; return focus to the trigger on Escape.
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  const overallReady = readiness ? readiness.ready : isOk;
  const deps = readiness ? Object.entries(readiness.dependencies) : [];

  return (
    <span ref={wrapperRef} style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: '10px' }}>
      <button
        id="btn-health"
        ref={buttonRef}
        type="button"
        onClick={toggle}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Show component readiness"
      >
        Health
      </button>
      <span
        id="health-status"
        className={status ? (isOk ? 'healthy' : 'unhealthy') : undefined}
        title={checkedTitle}
      >
        {statusWord} · {rel}
      </span>

      {open ? (
        <div
          role="dialog"
          aria-label="System readiness"
          data-testid="health-popover"
          style={{
            position: 'absolute',
            top: 'calc(100% + 8px)',
            right: 0,
            zIndex: 5000,
            width: '320px',
            maxWidth: '92vw',
            background: 'var(--panel)',
            border: '1px solid var(--line)',
            borderRadius: '10px',
            boxShadow: '0 12px 32px rgba(0,0,0,0.35)',
            padding: '14px',
            textAlign: 'left',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
            <span
              aria-hidden="true"
              style={{
                width: '10px',
                height: '10px',
                borderRadius: '50%',
                background: overallReady ? 'var(--ok)' : 'var(--err)',
                boxShadow: `0 0 8px ${overallReady ? 'var(--ok)' : 'var(--err)'}`,
                flex: '0 0 auto',
              }}
            />
            <span style={{ fontSize: '15px', fontWeight: 700, color: 'var(--fg)' }}>
              {overallReady ? 'All dependencies ready' : 'Not ready'}
            </span>
          </div>
          <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)', marginBottom: '12px' }}>
            Required runtime dependencies · checked {rel}
          </div>

          {readinessLoading && deps.length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--fg-muted)', padding: '8px 0' }}>Checking dependencies…</div>
          ) : readinessError ? (
            <div style={{ fontSize: '13px', color: 'var(--err)', lineHeight: 1.5, padding: '4px 0' }}>
              {readinessError}
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {deps.map(([key, dep]) => (
                <div
                  key={key}
                  data-testid={`health-dep-${key}`}
                  style={{
                    display: 'flex',
                    gap: '10px',
                    alignItems: 'flex-start',
                    padding: '8px 10px',
                    background: 'var(--card-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                  }}
                >
                  <span
                    aria-hidden="true"
                    style={{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      marginTop: '5px',
                      background: dep.ok ? 'var(--ok)' : 'var(--err)',
                      flex: '0 0 auto',
                    }}
                  />
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'baseline' }}>
                      <span style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--fg)' }}>{depLabel(key)}</span>
                      <span style={{ fontSize: '11.5px', fontWeight: 600, color: dep.ok ? 'var(--ok)' : 'var(--err)' }}>
                        {dep.ok ? 'ready' : 'unavailable'}
                      </span>
                    </span>
                    <span style={{ display: 'block', fontSize: '11.5px', color: 'var(--fg-muted)', marginTop: '2px', lineHeight: 1.45 }}>
                      {depDetail(dep)}
                    </span>
                    {!dep.ok && dep.operator_hint ? (
                      <span style={{ display: 'block', fontSize: '11.5px', color: 'var(--fg)', marginTop: '3px', lineHeight: 1.45 }}>
                        {dep.operator_hint}
                      </span>
                    ) : null}
                  </span>
                </div>
              ))}
            </div>
          )}

          <button
            type="button"
            data-testid="health-open-system-status"
            onClick={() => {
              setOpen(false);
              navigate('/dashboard?subtab=system');
            }}
            style={{
              marginTop: '12px',
              width: '100%',
              padding: '9px',
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              borderRadius: '8px',
              color: 'var(--link)',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Open System Status
          </button>
        </div>
      ) : null}
    </span>
  );
}
