// AGRO - TabBar Component  
// EXACT copy of /gui tab-bar structure

import { NavLink } from 'react-router-dom';

interface TabBarProps {
  mobileOpen?: boolean;
  onNavigate?: () => void;
}

export function TabBar({ mobileOpen = false, onNavigate }: TabBarProps) {
  const handleClick = () => {
    // Close mobile menu after navigation
    if (onNavigate) onNavigate();
  };

  return (
    <div 
      className={`tab-bar ${mobileOpen ? 'mobile-open' : ''}`} 
      style={{ display: 'flex', gap: '8px', padding: '12px 24px', overflowX: 'auto' }}
    >
      <NavLink
        to="/start"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        🚀 Get Started
      </NavLink>
      
      <NavLink
        to="/dashboard"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        📊 Dashboard
      </NavLink>

      <NavLink
        to="/chat"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        💬 Chat
      </NavLink>

      <NavLink
        to="/vscode"
        className={({ isActive }) => `${isActive ? 'active' : ''} promoted-tab`}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        📝 VS Code
      </NavLink>

      <NavLink
        to="/grafana"
        className={({ isActive }) => `${isActive ? 'active' : ''} promoted-tab`}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        📈 Grafana
      </NavLink>

      <NavLink
        to="/rag"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        🧠 RAG
      </NavLink>

      <NavLink
        to="/eval"
        className={({ isActive }) => `${isActive ? 'active' : ''} keystone-tab`}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
        title="Deep-dive into evaluation runs with AI-powered analysis"
      >
        🔬 Eval Analysis
      </NavLink>

      {/* Profiles tab removed - banned feature per CLAUDE.md */}

      <NavLink
        to="/infrastructure"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        🔧 Infrastructure
      </NavLink>

      <NavLink
        to="/admin"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleClick}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        ⚙️ Admin
      </NavLink>
    </div>
  );
}
