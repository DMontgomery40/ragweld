import { useEffect, useMemo, useState } from 'react';
import { routes } from '@/config/routes';
import { DOCK_DEFAULT_MODE_BY_PATH } from '@/config/dockCatalog';
import type { DockTarget } from '@/stores/useDockStore';

type DockPickerModalProps = {
  isOpen: boolean;
  onClose: () => void;
  onPick: (target: DockTarget) => void;
};

type DockEntry = {
  id: string;
  label: string;
  icon: string;
  path: string;
  search: string;
  subtabTitle?: string;
  renderMode: DockTarget['renderMode'];
};

const RECOMMENDED_TARGETS: Array<Pick<DockTarget, 'path' | 'search'>> = [
  { path: '/chat', search: '' },
  { path: '/rag', search: '?subtab=retrieval' },
  { path: '/rag', search: '?subtab=graph' },
  { path: '/admin', search: '?subtab=secrets' },
];

function normalizeSearch(search: string): string {
  if (!search) return '';
  return search.startsWith('?') ? search : `?${search}`;
}

function buildEntries(): DockEntry[] {
  const out: DockEntry[] = [];

  for (const r of routes) {
    const renderMode = (DOCK_DEFAULT_MODE_BY_PATH[r.path] ?? 'iframe') as DockTarget['renderMode'];

    // Tab-only entry
    out.push({
      id: `${r.path}`,
      label: r.label,
      icon: r.icon,
      path: r.path,
      search: '',
      renderMode,
    });

    // Subtab entries
    const subtabs = Array.isArray(r.subtabs) ? r.subtabs : [];
    for (const st of subtabs) {
      const search = `?subtab=${encodeURIComponent(st.id)}`;
      out.push({
        id: `${r.path}${search}`,
        label: r.label,
        icon: r.icon,
        path: r.path,
        search,
        subtabTitle: st.title,
        renderMode,
      });
    }
  }

  // Stable ordering: by route.order, then tab-only, then subtabs in declared order
  const routeOrder: Record<string, number> = Object.fromEntries(routes.map((r) => [r.path, r.order]));
  const subtabIndex: Record<string, number> = {};
  for (const r of routes) {
    const subtabs = Array.isArray(r.subtabs) ? r.subtabs : [];
    for (let i = 0; i < subtabs.length; i++) {
      const key = `${r.path}?subtab=${encodeURIComponent(subtabs[i].id)}`;
      subtabIndex[key] = i + 1;
    }
  }

  out.sort((a, b) => {
    const ao = routeOrder[a.path] ?? 9999;
    const bo = routeOrder[b.path] ?? 9999;
    if (ao !== bo) return ao - bo;

    const aIsTabOnly = a.search === '';
    const bIsTabOnly = b.search === '';
    if (aIsTabOnly !== bIsTabOnly) return aIsTabOnly ? -1 : 1;

    const ai = subtabIndex[`${a.path}${a.search}`] ?? 9999;
    const bi = subtabIndex[`${b.path}${b.search}`] ?? 9999;
    return ai - bi;
  });

  return out;
}

export function DockPickerModal({ isOpen, onClose, onPick }: DockPickerModalProps) {
  const [query, setQuery] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onClose]);

  useEffect(() => {
    if (!isOpen) setQuery('');
  }, [isOpen]);

  const allEntries = useMemo(() => buildEntries(), []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allEntries;

    return allEntries.filter((e) => {
      const hay = `${e.label} ${e.path} ${e.subtabTitle || ''}`.toLowerCase();
      return hay.includes(q);
    });
  }, [allEntries, query]);

  const recommended = useMemo(() => {
    const byId = new Map(filtered.map((e) => [e.id, e]));
    const out: DockEntry[] = [];
    for (const t of RECOMMENDED_TARGETS) {
      const id = `${t.path}${normalizeSearch(t.search)}`;
      const hit = byId.get(id);
      if (hit) out.push(hit);
    }
    return out;
  }, [filtered]);

  const showRecommended = query.trim().length === 0 && recommended.length > 0;

  if (!isOpen) return null;

  const handlePick = (entry: DockEntry) => {
    onPick({
      path: entry.path,
      search: entry.search,
      label: entry.label,
      icon: entry.icon,
      subtabTitle: entry.subtabTitle,
      renderMode: entry.renderMode,
    });
    onClose();
  };

  const SectionTitle = ({ children }: { children: string }) => (
    <div
      style={{
        fontSize: '11px',
        color: 'var(--fg-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.4px',
        marginTop: '14px',
        marginBottom: '8px',
      }}
    >
      {children}
    </div>
  );

  const EntryRow = ({ entry }: { entry: DockEntry }) => (
    <button
      type="button"
      onClick={() => handlePick(entry)}
      style={{
        width: '100%',
        background: 'var(--bg-elev2)',
        color: 'var(--fg)',
        border: '1px solid var(--line)',
        borderRadius: '10px',
        padding: '12px 12px',
        cursor: 'pointer',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: '12px',
        textAlign: 'left',
        transition: 'all 0.15s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', minWidth: 0 }}>
        <span style={{ fontSize: '18px', flex: '0 0 auto' }}>{entry.icon}</span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: '13px', fontWeight: 600, lineHeight: 1.2 }}>
            {entry.label}
          </div>
          <div
            style={{
              fontSize: '11px',
              color: 'var(--fg-muted)',
              marginTop: '2px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {entry.subtabTitle ? entry.subtabTitle : entry.path}
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: '0 0 auto' }}>
        {entry.renderMode === 'iframe' ? (
          <span
            style={{
              fontSize: '10px',
              padding: '2px 6px',
              borderRadius: '6px',
              border: '1px solid var(--line)',
              background: 'var(--bg-elev1)',
              color: 'var(--fg-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.4px',
            }}
          >
            Embed
          </span>
        ) : null}
      </div>
    </button>
  );

  // Everything section excludes items already shown in recommended (when no query)
  const recommendedIds = new Set(recommended.map((e) => e.id));
  const everything = showRecommended ? filtered.filter((e) => !recommendedIds.has(e.id)) : filtered;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 3000,
        backdropFilter: 'blur(2px)',
      }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="dock-picker-title"
    >
      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: '12px',
          padding: '18px',
          width: 'min(720px, calc(100vw - 32px))',
          maxHeight: '70vh',
          overflow: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '12px' }}>
          <div>
            <div
              id="dock-picker-title"
              style={{
                fontSize: '16px',
                fontWeight: 700,
                color: 'var(--fg)',
                display: 'flex',
                alignItems: 'center',
                gap: '10px',
              }}
            >
              <span style={{ fontSize: '18px' }}>📌</span> Choose something to dock
            </div>
            <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '4px' }}>
              This replaces the Dock contents without navigating the main view.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: '1px solid var(--line)',
              color: 'var(--fg-muted)',
              borderRadius: '8px',
              padding: '8px 10px',
              cursor: 'pointer',
              fontSize: '12px',
            }}
          >
            Esc
          </button>
        </div>

        <div style={{ marginTop: '14px' }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search tabs and subtabs…"
            autoFocus
            style={{
              width: '100%',
              padding: '10px 12px',
              borderRadius: '10px',
              border: '1px solid var(--line)',
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              fontSize: '13px',
            }}
          />
        </div>

        <div style={{ marginTop: '10px' }}>
          {showRecommended ? (
            <>
              <SectionTitle>Recommended</SectionTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {recommended.map((entry) => (
                  <EntryRow key={entry.id} entry={entry} />
                ))}
              </div>

              <SectionTitle>Everything</SectionTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {everything.map((entry) => (
                  <EntryRow key={entry.id} entry={entry} />
                ))}
              </div>
            </>
          ) : (
            <>
              <SectionTitle>{query.trim() ? 'Results' : 'Everything'}</SectionTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {everything.map((entry) => (
                  <EntryRow key={entry.id} entry={entry} />
                ))}
                {everything.length === 0 ? (
                  <div style={{ padding: '14px 4px', color: 'var(--fg-muted)', fontSize: '12px' }}>
                    No matches.
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

