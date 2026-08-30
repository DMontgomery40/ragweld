// Catch-all route body.
//
// `TabRouter` used to declare no `*` route, so any unknown path under the app base
// rendered an empty content area under a breadcrumb reading "Home": every API call
// succeeded, nothing said the route was wrong, and a stale bookmark was
// indistinguishable from a broken build (drive rows A-01, X-01, E-17).

import { Link, useLocation } from 'react-router-dom';
import { routes } from '@/config/routes';

export function NotFound() {
  const location = useLocation();
  const attempted = `${location.pathname}${location.search || ''}`;
  const suggestions = [...routes]
    .filter((r) => r.nav?.visible !== false)
    .sort((a, b) => a.order - b.order);

  return (
    <div
      data-testid="route-not-found"
      style={{
        padding: '48px 24px',
        maxWidth: '760px',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
      }}
    >
      <h2 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: 'var(--fg)' }}>
        Page not found
      </h2>
      <p style={{ margin: 0, fontSize: '14px', lineHeight: 1.6, color: 'var(--fg)' }}>
        Nothing in ragweld is routed to{' '}
        <span
          className="mono"
          data-testid="route-not-found-path"
          style={{ fontFamily: 'var(--font-mono)', color: 'var(--fg)' }}
        >
          {attempted}
        </span>
        . The link may be from an older build, or the tab may have been renamed.
      </p>

      <div>
        <Link
          to="/dashboard"
          data-testid="route-not-found-home"
          style={{
            display: 'inline-block',
            padding: '10px 16px',
            borderRadius: '8px',
            border: '1px solid var(--line)',
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            fontSize: '14px',
            fontWeight: 600,
            textDecoration: 'none',
          }}
        >
          Go to Dashboard
        </Link>
      </div>

      <div style={{ marginTop: '8px' }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--fg-muted)', letterSpacing: '0.04em', textTransform: 'uppercase', marginBottom: '8px' }}>
          Every tab in this build
        </div>
        <ul
          data-testid="route-not-found-routes"
          style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '6px' }}
        >
          {suggestions.map((route) => (
            <li key={route.path} style={{ fontSize: '14px', lineHeight: 1.5 }}>
              <Link to={route.path} style={{ color: 'var(--link)' }}>
                {route.label}
              </Link>
              <span style={{ color: 'var(--fg-muted)' }}>
                {' — '}
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: '13px' }}>{route.path}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
