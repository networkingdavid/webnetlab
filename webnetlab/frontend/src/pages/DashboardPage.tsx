import { useQuery } from '@tanstack/react-query';
import { fetchStats, type Stats } from '../api/stats';
import { api } from '../api/client';
import { Spinner } from '../components/Spinner';

// ─── Types ────────────────────────────────────────────────────────────────────

interface AuditEntry {
  id: number;
  action: string;
  entity_type: string | null;
  entity_id: number | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

// ─── Stat card ────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  accent?: string;
}

function StatCard({ label, value, sub, accent }: StatCardProps) {
  return (
    <div className="card" style={{ flex: '1 1 180px', minWidth: 160 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: accent ?? 'var(--text)', lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}

// ─── Action badge ─────────────────────────────────────────────────────────────

const ACTION_STYLES: Record<string, { bg: string; color: string; icon: string }> = {
  create: { bg: '#dcfce7', color: '#15803d', icon: '＋' },
  delete: { bg: '#fee2e2', color: '#b91c1c', icon: '✕' },
  start:  { bg: '#dbeafe', color: '#1d4ed8', icon: '▶' },
  stop:   { bg: '#fef3c7', color: '#92400e', icon: '■' },
  update: { bg: '#f3e8ff', color: '#6b21a8', icon: '✎' },
};

function ActionBadge({ action }: { action: string }) {
  const s = ACTION_STYLES[action] ?? { bg: '#f1f5f9', color: '#475569', icon: '•' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 10,
      background: s.bg, color: s.color,
    }}>
      {s.icon} {action}
    </span>
  );
}

function formatTimeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diffMs / 1000);
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return new Date(iso).toLocaleDateString();
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const { data, isLoading, error } = useQuery<Stats>({
    queryKey: ['stats'],
    queryFn: fetchStats,
    refetchInterval: 10_000,
  });

  const { data: auditLog = [], isLoading: auditLoading } = useQuery<AuditEntry[]>({
    queryKey: ['audit-log'],
    queryFn: () => api.get('/api/audit-log?limit=25').then(r => r.data),
    refetchInterval: 15_000,
  });

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>WebNetLab v1.0.0</span>
      </div>

      {isLoading && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', color: 'var(--muted)' }}>
          <Spinner size={16} /> Loading stats…
        </div>
      )}

      {error && (
        <div className="alert alert-error">Failed to load stats — is the backend running?</div>
      )}

      {data && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 32 }}>
          <StatCard
            label="Devices"
            value={data.devices}
            sub={data.devices_running !== undefined ? `${data.devices_running} running` : undefined}
            accent={data.devices_running ? 'var(--success, #16a34a)' : undefined}
          />
          <StatCard
            label="Networks"
            value={data.networks}
          />
          {data.mibs !== undefined && (
            <StatCard
              label="MIBs Loaded"
              value={data.mibs}
            />
          )}
          <StatCard
            label="SNMP Queries"
            value={data.snmp_queries.toLocaleString()}
            sub="lifetime total"
            accent={data.snmp_queries > 0 ? '#2563eb' : undefined}
          />
        </div>
      )}

      {/* ── Recent Activity ──────────────────────────────────────────────── */}
      <div>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
          Recent Activity
          {auditLoading && <Spinner size={12} />}
        </div>

        {auditLog.length === 0 && !auditLoading && (
          <div className="empty-state">
            No activity yet — create a device or import a MIB to get started.
          </div>
        )}

        {auditLog.length > 0 && (
          <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
            <table className="table" style={{ marginBottom: 0 }}>
              <thead>
                <tr>
                  <th style={{ width: 90 }}>Action</th>
                  <th>Entity</th>
                  <th>Details</th>
                  <th style={{ width: 90 }}>When</th>
                </tr>
              </thead>
              <tbody>
                {auditLog.map(entry => (
                  <tr key={entry.id}>
                    <td><ActionBadge action={entry.action} /></td>
                    <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                      {entry.entity_type ?? '—'}
                      {entry.entity_id !== null && (
                        <span style={{ color: 'var(--muted)', marginLeft: 4 }}>#{entry.entity_id}</span>
                      )}
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--muted)', maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {entry.payload
                        ? Object.entries(entry.payload)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join(' · ')
                        : '—'}
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                      {formatTimeAgo(entry.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Quick links ──────────────────────────────────────────────────── */}
      <div style={{ marginTop: 32, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {[
          { href: '/devices',  label: '⊕ New Device',  sub: 'Create and start an SNMP agent' },
          { href: '/mibs',     label: '⇪ Upload MIB',  sub: 'Import & browse MIB OID tree'  },
          { href: '/topology', label: '⬡ Topology',    sub: 'Wire devices together'          },
          { href: '/networks', label: '⊞ Networks',    sub: 'Manage Docker networks'         },
        ].map(link => (
          <a
            key={link.href}
            href={link.href}
            style={{
              flex: '1 1 160px', minWidth: 140,
              padding: '14px 16px',
              border: '1px solid var(--border)', borderRadius: 8,
              background: 'var(--surface)',
              textDecoration: 'none', color: 'var(--text)',
              display: 'flex', flexDirection: 'column', gap: 4,
              transition: 'border-color 0.15s',
            }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent, #2563eb)')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
          >
            <span style={{ fontWeight: 700 }}>{link.label}</span>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>{link.sub}</span>
          </a>
        ))}
      </div>
    </div>
  );
}
