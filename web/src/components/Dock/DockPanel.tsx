import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Sidepanel } from '@/components/Sidepanel';
import { DockPickerModal } from '@/components/Dock/DockPickerModal';
import { DockView } from '@/components/Dock/DockView';
import { DOCK_DEFAULT_MODE_BY_PATH } from '@/config/dockCatalog';
import { getRouteByPath } from '@/config/routes';
import { useDockStore } from '@/stores';
import type { DockTarget } from '@/stores/useDockStore';

type UndoToastState = {
  message: string;
  onUndo: () => void;
};

function formatDockTitle(target: DockTarget): string {
  if (target.subtabTitle) return `${target.label} — ${target.subtabTitle}`;
  return target.label;
}

export function DockPanel() {
  const navigate = useNavigate();
  const location = useLocation();

  const mode = useDockStore((s) => s.mode);
  const docked = useDockStore((s) => s.docked);
  const setMode = useDockStore((s) => s.setMode);
  const setDocked = useDockStore((s) => s.setDocked);
  const clearDocked = useDockStore((s) => s.clearDocked);

  const [pickerOpen, setPickerOpen] = useState(false);
  const [undoToast, setUndoToast] = useState<UndoToastState | null>(null);
  const undoTimerRef = useRef<number | null>(null);

  const clearUndoToast = useCallback(() => {
    if (undoTimerRef.current) {
      window.clearTimeout(undoTimerRef.current);
      undoTimerRef.current = null;
    }
    setUndoToast(null);
  }, []);

  const showUndoToast = useCallback(
    (state: UndoToastState) => {
      clearUndoToast();
      setUndoToast(state);
      undoTimerRef.current = window.setTimeout(() => {
        setUndoToast(null);
        undoTimerRef.current = null;
      }, 5000);
    },
    [clearUndoToast]
  );

  useEffect(() => {
    return () => {
      if (undoTimerRef.current) window.clearTimeout(undoTimerRef.current);
    };
  }, []);

  // Default to Dock mode if something is docked (on refresh / rehydrate).
  useEffect(() => {
    if (docked) setMode('dock');
  }, [docked, setMode]);

  const currentMainTarget = useMemo(() => {
    const route = getRouteByPath(location.pathname);
    if (!route) return null;

    const params = new URLSearchParams(location.search || '');
    const subtabId = params.get('subtab') || '';
    const subtabTitle =
      subtabId && Array.isArray(route.subtabs)
        ? route.subtabs.find((s) => s.id === subtabId)?.title
        : undefined;

    const renderMode = (DOCK_DEFAULT_MODE_BY_PATH[location.pathname] ?? 'iframe') as DockTarget['renderMode'];

    return {
      path: location.pathname,
      search: location.search || '',
      label: route.label,
      icon: route.icon,
      subtabTitle,
      renderMode,
    } satisfies DockTarget;
  }, [location.pathname, location.search]);

  const dockCurrentSwap = useCallback(() => {
    if (!currentMainTarget) return;

    // If we're already showing the same thing in main and dock, just switch to Dock mode.
    if (docked && docked.path === currentMainTarget.path && docked.search === currentMainTarget.search) {
      setMode('dock');
      return;
    }

    if (docked) {
      const prevDocked = docked;
      setDocked(currentMainTarget);
      setMode('dock');
      navigate(prevDocked.path + prevDocked.search);
      return;
    }

    setDocked(currentMainTarget);
    setMode('dock');
    navigate('/chat');
  }, [currentMainTarget, docked, navigate, setDocked, setMode]);

  const swap = useCallback(() => {
    if (!docked) return;
    if (!currentMainTarget) return;

    const prevDocked = docked;
    setDocked(currentMainTarget);
    setMode('dock');
    navigate(prevDocked.path + prevDocked.search);
  }, [currentMainTarget, docked, navigate, setDocked, setMode]);

  const dockChat = useCallback(() => {
    const route = getRouteByPath('/chat');
    if (!route) return;
    const target: DockTarget = {
      path: '/chat',
      search: '',
      label: route.label,
      icon: route.icon,
      renderMode: (DOCK_DEFAULT_MODE_BY_PATH['/chat'] ?? 'native') as DockTarget['renderMode'],
    };
    setDocked(target);
    setMode('dock');
  }, [setDocked, setMode]);

  const handlePick = useCallback(
    (target: DockTarget) => {
      // If user picked exactly what is already in main, treat it as Dock Current (swap)
      if (target.path === location.pathname && (target.search || '') === (location.search || '')) {
        dockCurrentSwap();
        return;
      }

      const prevDocked = docked;
      setDocked(target);
      setMode('dock');

      showUndoToast({
        message: `Dock set to: ${formatDockTitle(target)}`,
        onUndo: () => {
          if (prevDocked) {
            setDocked(prevDocked, { rememberLast: false });
            setMode('dock');
          } else {
            setDocked(null, { rememberLast: false });
            setMode('dock');
          }
          clearUndoToast();
        },
      });
    },
    [clearUndoToast, dockCurrentSwap, docked, location.pathname, location.search, setDocked, setMode, showUndoToast]
  );

  const title = useMemo(() => {
    if (mode === 'settings') return 'Settings';
    if (!docked) return 'Dock';
    return `Dock: ${formatDockTitle(docked)}`;
  }, [docked, mode]);

  const SegmentedButton = ({
    active,
    label,
    onClick,
    testId,
  }: {
    active: boolean;
    label: string;
    onClick: () => void;
    testId: string;
  }) => (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      style={{
        background: active ? 'var(--accent)' : 'var(--bg-elev2)',
        color: active ? 'var(--accent-contrast)' : 'var(--fg-muted)',
        border: `1px solid ${active ? 'var(--accent)' : 'var(--line)'}`,
        padding: '8px 10px',
        borderRadius: '10px',
        cursor: 'pointer',
        fontSize: '12px',
        fontWeight: 600,
        minHeight: '38px',
      }}
    >
      {label}
    </button>
  );

  const HeaderButton = ({
    label,
    onClick,
    disabled,
    testId,
  }: {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    testId: string;
  }) => (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      disabled={disabled}
      style={{
        background: 'var(--bg-elev2)',
        color: 'var(--fg)',
        border: '1px solid var(--line)',
        padding: '8px 10px',
        borderRadius: '10px',
        cursor: disabled ? 'not-allowed' : 'pointer',
        fontSize: '12px',
        fontWeight: 600,
        minHeight: '38px',
        opacity: disabled ? 0.6 : 1,
      }}
    >
      {label}
    </button>
  );

  return (
    <div
      data-testid="dock-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
      }}
    >
      <div className="dock-header">
        <div className="dock-header-inner">
          <div className="dock-header-tabs">
            <SegmentedButton
              active={mode === 'settings'}
              label="Settings"
              onClick={() => setMode('settings')}
              testId="dock-mode-settings"
            />
            <SegmentedButton
              active={mode === 'dock'}
              label="Dock"
              onClick={() => setMode('dock')}
              testId="dock-mode-dock"
            />
          </div>

          <div
            className="dock-header-title"
            title={title}
            data-testid="dock-title"
          >
            {title}
          </div>

          <div className="dock-header-actions">
            <HeaderButton label="Dock Current" onClick={dockCurrentSwap} testId="dock-current" disabled={!currentMainTarget} />
            <HeaderButton label="Choose…" onClick={() => setPickerOpen(true)} testId="dock-choose" />
            {docked ? (
              <>
                <HeaderButton label="Swap" onClick={swap} testId="dock-swap" />
                <HeaderButton
                  label="Clear"
                  onClick={() => {
                    clearDocked();
                    setMode('dock');
                  }}
                  testId="dock-clear"
                />
              </>
            ) : null}
          </div>
        </div>
      </div>

      <div
        style={{
          flex: '1 1 auto',
          minHeight: 0,
          overflow: 'hidden',
        }}
      >
        {mode === 'settings' ? (
          <div style={{ height: '100%', overflow: 'auto', padding: '20px' }}>
            <Sidepanel />
          </div>
        ) : docked ? (
          <div style={{ height: '100%', overflow: 'hidden' }}>
            <DockView target={docked} />
          </div>
        ) : (
          <div
            data-testid="dock-empty"
            style={{
              height: '100%',
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '14px',
              padding: '18px',
              color: 'var(--fg-muted)',
              textAlign: 'center',
            }}
          >
            <div style={{ fontSize: '28px' }}>📌</div>
            <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--fg)' }}>Nothing docked yet</div>
            <div style={{ fontSize: '12px', maxWidth: '320px' }}>
              Dock Chat while you browse Grafana/RAG.
            </div>
            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', justifyContent: 'center' }}>
              <HeaderButton label="Dock Chat" onClick={dockChat} testId="dock-chat" />
              <HeaderButton label="Dock Current" onClick={dockCurrentSwap} testId="dock-current-empty" disabled={!currentMainTarget} />
              <HeaderButton label="Choose…" onClick={() => setPickerOpen(true)} testId="dock-choose-empty" />
            </div>
          </div>
        )}
      </div>

      {undoToast ? (
        <div
          data-testid="dock-undo-toast"
          style={{
            position: 'fixed',
            top: '16px',
            right: '16px',
            zIndex: 5000,
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderLeft: '4px solid var(--accent)',
            borderRadius: '10px',
            padding: '10px 12px',
            boxShadow: '0 8px 24px rgba(0,0,0,0.25)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            maxWidth: '360px',
          }}
          role="status"
          aria-live="polite"
        >
          <div style={{ fontSize: '12px', color: 'var(--fg)', lineHeight: 1.4, flex: 1 }}>
            {undoToast.message}
          </div>
          <button
            type="button"
            onClick={undoToast.onUndo}
            style={{
              background: 'transparent',
              border: '1px solid var(--accent)',
              color: 'var(--accent)',
              borderRadius: '8px',
              padding: '6px 10px',
              cursor: 'pointer',
              fontSize: '12px',
              fontWeight: 700,
            }}
          >
            Undo
          </button>
          <button
            type="button"
            onClick={clearUndoToast}
            aria-label="Dismiss"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--fg-muted)',
              cursor: 'pointer',
              fontSize: '16px',
              lineHeight: 1,
              padding: '0 2px',
            }}
          >
            ×
          </button>
        </div>
      ) : null}

      <DockPickerModal isOpen={pickerOpen} onClose={() => setPickerOpen(false)} onPick={handlePick} />
    </div>
  );
}

