import { useQuery } from '@tanstack/react-query';
import { fetchStats, type Stats } from '../api/stats';
import { Spinner } from '../components/Spinner';

// ─── Stat card ────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
}

function StatCard({ label, value, sub }: StatCardProps) {
  return (
    <div className="card" style={{ flex: '1 1 180px', minWidth: 160 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8 }}>
        {label}
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--text)', lineHeight: 1.1 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{sub}</div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function DashboardPage() {
  const { data, isLoading, error } = useQuery<Stats>({
    queryKey: ['stats'],
    queryFn: fetchStats,
    refetchInterval: 10_000,
  });

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
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
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <StatCard
            label="Devices"
            value={data.devices}
            sub={data.devices_running !== undefined ? `${data.devices_running} running` : undefined}
          />
          <StatCard
            label="Networks"
            value={data.networks}
          />
          {data.mibs !== undefined && (
            <StatCard
              label="MIBs"
              value={data.mibs}
            />
          )}
          <StatCard
            label="SNMP Queries"
            value={data.snmp_queries.toLocaleString()}
            sub="lifetime total"
          />
        </div>
      )}

      <div style={{ marginTop: 32 }}>
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>Recent Activity</div>
        <div className="empty-state">No recent activity — audit log coming soon.</div>
      </div>
    </div>
  );
}
