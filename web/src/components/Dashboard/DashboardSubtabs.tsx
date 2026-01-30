// AGRO - DashboardSubtabs Component
// Subtab navigation for Dashboard tab

interface DashboardSubtabsProps {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
}

export function DashboardSubtabs({ activeSubtab, onSubtabChange }: DashboardSubtabsProps) {
  const subtabs = [
    { id: 'system', title: 'System Status' },
    { id: 'monitoring', title: 'Monitoring' },
    { id: 'storage', title: 'Storage' },
    { id: 'help', title: 'Help' },
    { id: 'glossary', title: 'Glossary' }
  ];

  // No defensive useEffect needed - parent initializes activeSubtab to 'system'

  return (
    <div
      className="subtab-bar"
      id="dashboard-subtabs"
      data-state="visible"
      style={{
        display: 'flex',
        opacity: 1,
        transform: 'translateY(0)',
        pointerEvents: 'auto',
        visibility: 'visible'
      }}
    >
      {subtabs.map(subtab => (
        <button
          key={subtab.id}
          className={`subtab-btn ${activeSubtab === subtab.id ? 'active' : ''}`}
          data-subtab={subtab.id}
          onClick={() => onSubtabChange(subtab.id)}
        >
          {subtab.title}
        </button>
      ))}
    </div>
  );
}
