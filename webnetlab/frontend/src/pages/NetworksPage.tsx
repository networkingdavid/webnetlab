import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchNetworks, createNetwork, deleteNetwork,
  fetchHostInterfaces,
  type Network, type CreateNetworkData,
} from '../api/networks';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Modal } from '../components/Modal';
import { Spinner } from '../components/Spinner';
import { api } from '../api/client';

// ─── Platform info ────────────────────────────────────────────────────────────

interface PlatformInfo {
  system: string;
  macvlan_supported: boolean;
  note?: string;
}

function usePlatform() {
  return useQuery<PlatformInfo>({
    queryKey: ['platform'],
    queryFn: () => api.get('/api/platform').then(r => r.data),
    staleTime: Infinity,
  });
}

// ─── Network type definitions ─────────────────────────────────────────────────

const NET_TYPES: {
  value: CreateNetworkData['type'];
  label: string;
  desc: string;
  linuxOnly?: boolean;
  badge?: string;
}[] = [
  {
    value: 'bridge',
    label: 'Bridge (isolated)',
    desc: 'Private Docker network. Containers talk to each other and to this host. Ideal for testing without LAN exposure.',
  },
  {
    value: 'host-bridge',
    label: 'Host-accessible Bridge',
    desc: 'Docker bridge with intent to route from host NMS. On macOS, Docker Desktop automatically routes container subnets to your Mac.',
  },
  {
    value: 'macvlan',
    label: 'Macvlan — LAN (Linux)',
    desc: 'Containers get unique MAC + IP addresses on your physical LAN. Any NMS on the network sees them as real devices. Requires Linux + promiscuous mode on the parent NIC.',
    linuxOnly: true,
    badge: 'LAN',
  },
  {
    value: 'ipvlan',
    label: 'IPvlan — LAN (Linux)',
    desc: 'Like macvlan but containers share the host MAC address. Works on hypervisors that block MAC spoofing (AWS, GCP, VMware). Requires Linux.',
    linuxOnly: true,
    badge: 'LAN',
  },
];

// ─── Form state ───────────────────────────────────────────────────────────────

const BLANK_FORM: CreateNetworkData = {
  name: '',
  type: 'host-bridge',
  subnet: '',
  gateway: '',
  host_interface: '',
};

// ─── New network modal ────────────────────────────────────────────────────────

function NewNetworkModal({ open, onClose, isLinux }: {
  open: boolean;
  onClose: () => void;
  isLinux: boolean;
}) {
  const [form, setForm] = useState<CreateNetworkData>(BLANK_FORM);
  const [error, setError] = useState('');
  const qc = useQueryClient();

  const isLanMode = form.type === 'macvlan' || form.type === 'ipvlan';

  // Fetch host interfaces when LAN mode is selected on Linux
  const { data: hostIfaces = [] } = useQuery({
    queryKey: ['host-interfaces'],
    queryFn: fetchHostInterfaces,
    enabled: isLanMode && isLinux,
    staleTime: 30_000,
  });

  const mut = useMutation({
    mutationFn: createNetwork,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['networks'] });
      setForm(BLANK_FORM);
      setError('');
      onClose();
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create network';
      setError(msg);
    },
  });

  const selectedType = NET_TYPES.find(t => t.value === form.type);

  function handleSubmit() {
    if (!form.name.trim()) { setError('Name is required'); return; }
    if (!(form.subnet ?? '').trim()) { setError('Subnet is required'); return; }
    if (!(form.gateway ?? '').trim()) { setError('Gateway is required'); return; }
    if (isLanMode && !isLinux) {
      setError(`${form.type} is only supported on Linux hosts. Use 'Host-accessible Bridge' on macOS.`);
      return;
    }
    if (isLanMode && !form.host_interface?.trim()) {
      setError('Parent interface is required for LAN mode networks');
      return;
    }
    mut.mutate({
      name: form.name.trim(),
      type: form.type,
      subnet: form.subnet,
      gateway: form.gateway,
      host_interface: isLanMode ? form.host_interface : undefined,
    });
  }

  return (
    <Modal title="New Network" open={open} onClose={onClose} onConfirm={handleSubmit} confirmLabel="Create" loading={mut.isPending}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {error && <div className="alert alert-error">{error}</div>}

        <div className="form-group">
          <label className="form-label">Name *</label>
          <input className="form-input" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="lab-net-01" autoFocus />
        </div>

        <div className="form-group">
          <label className="form-label">Type</label>
          <select
            className="form-select"
            value={form.type}
            onChange={e => setForm(f => ({ ...f, type: e.target.value as CreateNetworkData['type'] }))}
          >
            {NET_TYPES.map(t => (
              <option key={t.value} value={t.value} disabled={!!t.linuxOnly && !isLinux}>
                {t.label}{t.linuxOnly && !isLinux ? ' (Linux only)' : ''}
              </option>
            ))}
          </select>
          {selectedType && (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4, lineHeight: 1.5 }}>
              {selectedType.desc}
            </div>
          )}
        </div>

        {/* LAN mode — parent interface picker */}
        {isLanMode && isLinux && (
          <div className="form-group">
            <label className="form-label">Parent Interface *</label>
            {hostIfaces.length > 0 ? (
              <select
                className="form-select"
                value={form.host_interface ?? ''}
                onChange={e => setForm(f => ({ ...f, host_interface: e.target.value }))}
              >
                <option value="">— select NIC —</option>
                {hostIfaces.map(iface => (
                  <option key={iface.name} value={iface.name}>{iface.name}</option>
                ))}
              </select>
            ) : (
              <input
                className="form-input"
                value={form.host_interface ?? ''}
                onChange={e => setForm(f => ({ ...f, host_interface: e.target.value }))}
                placeholder="eth0"
              />
            )}
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
              Physical NIC on the Linux host. Run <code>sudo bash infra/linux-macvlan-setup.sh</code> first to enable promiscuous mode.
            </div>
          </div>
        )}

        {/* LAN mode warning on macOS */}
        {isLanMode && !isLinux && (
          <div className="alert alert-error" style={{ fontSize: 13 }}>
            ⚠️ <strong>{form.type}</strong> requires a Linux host. On macOS, Docker Desktop runs containers inside a VM and cannot expose them on the physical LAN. Use <strong>Host-accessible Bridge</strong> instead.
          </div>
        )}

        {/* macvlan setup hint on Linux */}
        {isLanMode && isLinux && (
          <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 6, padding: '8px 12px', fontSize: 12, color: '#1d4ed8' }}>
            💡 First time? Run <code style={{ background: '#dbeafe', padding: '1px 4px', borderRadius: 3 }}>sudo bash infra/linux-macvlan-setup.sh</code> on your Linux host to enable promiscuous mode and the host-to-container shim.
          </div>
        )}

        <div className="form-group">
          <label className="form-label">Subnet *</label>
          <input className="form-input" value={form.subnet} onChange={e => setForm(f => ({ ...f, subnet: e.target.value }))} placeholder="192.168.100.0/24" />
        </div>

        <div className="form-group">
          <label className="form-label">Gateway *</label>
          <input className="form-input" value={form.gateway} onChange={e => setForm(f => ({ ...f, gateway: e.target.value }))} placeholder="192.168.100.1" />
          {isLanMode && (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
              Must be a free IP in your physical LAN subnet (not the router's gateway — a new IP you'll assign to the Docker network).
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function NetworksPage() {
  const [showNew, setShowNew] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const qc = useQueryClient();
  const { data: platform } = usePlatform();
  const isLinux = platform?.system?.toLowerCase() === 'linux';

  const { data: networks = [], isLoading, error } = useQuery({
    queryKey: ['networks'],
    queryFn: fetchNetworks,
    refetchInterval: 15_000,
  });

  const deleteMut = useMutation({
    mutationFn: deleteNetwork,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['networks'] });
      setDeleteId(null);
    },
    onError: (e: unknown) => {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Delete failed';
      alert(msg);
    },
  });

  const TYPE_BADGE: Record<string, { bg: string; color: string; label: string }> = {
    bridge:       { bg: '#f3f4f6', color: '#374151',   label: 'Bridge'   },
    'host-bridge':{ bg: '#dbeafe', color: '#1d4ed8',   label: 'Host-Bridge' },
    macvlan:      { bg: '#dcfce7', color: '#15803d',   label: 'Macvlan LAN' },
    ipvlan:       { bg: '#fef3c7', color: '#92400e',   label: 'IPvlan LAN'  },
    nat:          { bg: '#ede9fe', color: '#5b21b6',   label: 'NAT'      },
  };

  if (isLoading) return <div style={{ padding: 32, color: 'var(--muted)' }}><Spinner /> Loading…</div>;
  if (error) return <div style={{ padding: 32, color: '#ef4444' }}>Failed to load networks.</div>;

  return (
    <div style={{ padding: '24px 28px', fontFamily: 'var(--font)', fontSize: 13 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Networks</h2>
          <p style={{ margin: '4px 0 0', color: 'var(--muted)', fontSize: 13 }}>
            Docker networks that host simulated devices.
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowNew(true)}>+ New Network</button>
      </div>

      {/* macOS info banner */}
      {!isLinux && (
        <div style={{ background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 8, padding: '12px 16px', marginBottom: 20, fontSize: 13, color: '#1d4ed8' }}>
          <strong>macOS detected.</strong> Using <em>Host-accessible Bridge</em> — Docker Desktop automatically routes container subnets to your Mac.
          LAN modes (macvlan / ipvlan) require a Linux host.{' '}
          <a href="https://github.com/your-org/webnetlab/blob/main/docs/linux-lan-mode.md" target="_blank" rel="noreferrer" style={{ color: '#1d4ed8' }}>
            Learn more →
          </a>
        </div>
      )}

      {/* Linux LAN mode info banner */}
      {isLinux && (
        <div style={{ background: '#f0fdf4', border: '1px solid #bbf7d0', borderRadius: 8, padding: '12px 16px', marginBottom: 20, fontSize: 13, color: '#15803d' }}>
          <strong>Linux detected.</strong> macvlan and ipvlan LAN modes are available.
          Run <code style={{ background: '#dcfce7', padding: '1px 4px', borderRadius: 3 }}>sudo bash infra/linux-macvlan-setup.sh</code> before creating a LAN-mode network.
        </div>
      )}

      {/* Network cards */}
      {networks.length === 0 ? (
        <div style={{ background: '#f7f8fa', border: '1px dashed #d1d5db', borderRadius: 8, padding: '40px 24px', textAlign: 'center', color: 'var(--muted)' }}>
          No networks yet. Create one to start simulating.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
          {networks.map(net => {
            const badge = TYPE_BADGE[net.type] ?? { bg: '#f3f4f6', color: '#374151', label: net.type };
            const isLan = net.type === 'macvlan' || net.type === 'ipvlan';
            return (
              <div key={net.id} style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 8, padding: '16px 18px', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
                  <div style={{ fontWeight: 700, fontSize: 14, color: '#1f2328' }}>{net.name}</div>
                  <span style={{ background: badge.bg, color: badge.color, fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4, letterSpacing: '0.04em' }}>
                    {badge.label}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: '#57606a', display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '3px 10px' }}>
                  <span style={{ color: '#9ca3af' }}>Subnet</span>
                  <span style={{ fontFamily: 'monospace' }}>{net.subnet ?? '—'}</span>
                  <span style={{ color: '#9ca3af' }}>Gateway</span>
                  <span style={{ fontFamily: 'monospace' }}>{net.gateway ?? '—'}</span>
                  {isLan && net.host_interface && (
                    <>
                      <span style={{ color: '#9ca3af' }}>Parent NIC</span>
                      <span style={{ fontFamily: 'monospace' }}>{net.host_interface}</span>
                    </>
                  )}
                  <span style={{ color: '#9ca3af' }}>Docker ID</span>
                  <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{net.docker_network_id ? net.docker_network_id.slice(0, 12) + '…' : '—'}</span>
                </div>
                <div style={{ marginTop: 12, display: 'flex', justifyContent: 'flex-end' }}>
                  <button
                    className="btn btn-danger"
                    style={{ fontSize: 12, padding: '4px 12px' }}
                    onClick={() => setDeleteId(net.id)}
                  >
                    Delete
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <NewNetworkModal open={showNew} onClose={() => setShowNew(false)} isLinux={!!isLinux} />

      <ConfirmDialog
        open={deleteId !== null}
        title="Delete network"
        message="Remove this Docker network? Devices attached to it will lose connectivity."
        onConfirm={() => deleteId !== null && deleteMut.mutate(deleteId)}
        onClose={() => setDeleteId(null)}
        loading={deleteMut.isPending}
      />
    </div>
  );
}
