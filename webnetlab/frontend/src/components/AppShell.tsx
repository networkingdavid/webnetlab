import { useState, useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import '../styles.css';

// ─── SVG icons (inline, no external dep) ─────────────────────────────────────

const IconDashboard = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
    <path d="M2 2h5v5H2V2zm0 7h5v5H2V9zm7-7h5v5H9V2zm0 7h5v5H9V9z" />
  </svg>
);
const IconNetworks = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
    <circle cx="8" cy="8" r="2.5" />
    <circle cx="2" cy="8" r="1.5" />
    <circle cx="14" cy="8" r="1.5" />
    <circle cx="8" cy="2" r="1.5" />
    <circle cx="8" cy="14" r="1.5" />
    <path d="M3.5 8h3M9.5 8h3M8 3.5v3M8 9.5v3" stroke="currentColor" strokeWidth="1" fill="none" />
  </svg>
);
const IconDevices = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
    <rect x="1" y="3" width="10" height="7" rx="1" />
    <path d="M3 12h6M6 10v2" stroke="currentColor" strokeWidth="1.2" fill="none" />
    <rect x="12" y="5" width="3" height="5" rx="0.5" />
  </svg>
);
const IconMibs = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
    <path d="M3 2h7l3 3v9H3V2z" />
    <path d="M10 2v3h3" stroke="#fff" strokeWidth="1" fill="none" />
    <path d="M5 7h6M5 9h4" stroke="#fff" strokeWidth="1" fill="none" />
  </svg>
);
const IconTopology = () => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
    <circle cx="8" cy="4" r="2" />
    <circle cx="3" cy="12" r="2" />
    <circle cx="13" cy="12" r="2" />
    <path d="M8 6l-3.5 4.5M8 6l3.5 4.5M3 12h10" stroke="currentColor" strokeWidth="1.2" fill="none" />
  </svg>
);
const IconCollapse = ({ collapsed }: { collapsed: boolean }) => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
    <path d={collapsed ? 'M5 3l5 4-5 4' : 'M9 3L4 7l5 4'} stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
  </svg>
);

// ─── Nav items ─────────────────────────────────────────────────────────────────

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', Icon: IconDashboard },
  { to: '/networks', label: 'Networks', Icon: IconNetworks },
  { to: '/devices', label: 'Devices', Icon: IconDevices },
  { to: '/mibs', label: 'MIBs', Icon: IconMibs },
  { to: '/topology', label: 'Topology', Icon: IconTopology },
];

// ─── Health check hook ────────────────────────────────────────────────────────

function useHealthStatus() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    let cancelled = false;
    const check = () => {
      api.get('/health', { timeout: 3000 })
        .then(() => { if (!cancelled) setOk(true); })
        .catch(() => { if (!cancelled) setOk(false); });
    };
    check();
    const id = setInterval(check, 15000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);
  return ok;
}

// ─── AppShell ─────────────────────────────────────────────────────────────────

export function AppShell() {
  const [collapsed, setCollapsed] = useState(false);
  const health = useHealthStatus();
  const location = useLocation();
  const isTopology = location.pathname === '/topology';
  const sidebarWidth = collapsed ? 48 : 220;

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* ── Sidebar ── */}
      <nav
        style={{
          width: sidebarWidth,
          minWidth: sidebarWidth,
          background: '#1a1f2e',
          color: '#c9d1d9',
          display: 'flex',
          flexDirection: 'column',
          transition: 'width 0.18s ease',
          overflow: 'hidden',
          zIndex: 10,
          flexShrink: 0,
        }}
      >
        {/* Logo / collapse toggle */}
        <div
          style={{
            height: 40,
            display: 'flex',
            alignItems: 'center',
            padding: '0 14px',
            borderBottom: '1px solid rgba(255,255,255,0.07)',
            gap: 8,
            flexShrink: 0,
          }}
        >
          {!collapsed && (
            <span
              style={{
                fontWeight: 700,
                fontSize: 14,
                color: '#fff',
                flex: 1,
                whiteSpace: 'nowrap',
                overflow: 'hidden',
              }}
            >
              WebNetLab
            </span>
          )}
          <button
            onClick={() => setCollapsed(c => !c)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: '#8b949e',
              display: 'flex',
              alignItems: 'center',
              padding: 4,
              borderRadius: 4,
              marginLeft: collapsed ? 'auto' : 0,
              marginRight: collapsed ? 'auto' : 0,
            }}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <IconCollapse collapsed={collapsed} />
          </button>
        </div>

        {/* Nav links */}
        <div style={{ flex: 1, overflowY: 'auto', paddingTop: 6 }}>
          {NAV_ITEMS.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              style={({ isActive }) => ({
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '9px 14px',
                color: isActive ? '#fff' : '#8b949e',
                textDecoration: 'none',
                fontSize: 13,
                fontWeight: isActive ? 600 : 400,
                borderLeft: isActive ? '3px solid #3b82d4' : '3px solid transparent',
                background: isActive ? 'rgba(59,130,212,0.12)' : 'transparent',
                transition: 'background 0.12s, color 0.12s',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
              })}
            >
              <span style={{ flexShrink: 0, display: 'flex', alignItems: 'center' }}>
                <Icon />
              </span>
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* ── Right side: topbar + content ── */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {/* Top bar */}
        <header
          style={{
            height: 40,
            background: '#fff',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            padding: '0 20px',
            gap: 10,
            flexShrink: 0,
            zIndex: 9,
          }}
        >
          <span style={{ flex: 1, fontWeight: 600, fontSize: 13, color: 'var(--muted)' }}>
            {NAV_ITEMS.find(n => location.pathname.startsWith(n.to))?.label ?? 'WebNetLab'}
          </span>
          <div
            title={health === null ? 'Checking…' : health ? 'Backend online' : 'Backend unreachable'}
            style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 12, color: 'var(--muted)' }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                background:
                  health === null ? '#9ca3af' : health ? 'var(--success)' : 'var(--error)',
                display: 'inline-block',
              }}
            />
            {health === null ? 'Checking' : health ? 'Online' : 'Offline'}
          </div>
        </header>

        {/* Content */}
        <main
          style={{
            flex: 1,
            overflow: isTopology ? 'hidden' : 'auto',
          }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
