import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  fetchDevices,
  createDevice,
  deleteDevice,
  startDevice,
  stopDevice,
  restartDevice,
  bulkCreateDevices,
  type Device,
  type CreateDeviceData,
  type BulkCreateDeviceData,
} from '../api/devices';
import { exportDeviceOids } from '../api/oids';
import { fetchNetworks } from '../api/networks';
import { StatusBadge } from '../components/StatusBadge';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { Modal } from '../components/Modal';
import { Spinner } from '../components/Spinner';

// ─── Create single device ─────────────────────────────────────────────────────

function NewDeviceModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form, setForm] = useState<CreateDeviceData>({
    name: '',
    type: 'router',
    ip_address: '',
    mac_address: '',
    snmp_community: 'public',
    network_id: undefined,
    snmp_port: undefined,
  });
  const [error, setError] = useState('');
  const qc = useQueryClient();

  const { data: networks = [] } = useQuery({ queryKey: ['networks'], queryFn: fetchNetworks });

  const mut = useMutation({
    mutationFn: createDevice,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['devices'] });
      onClose();
    },
    onError: (e: unknown) => {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create device');
    },
  });

  function handleSubmit() {
    if (!form.name.trim() || !form.ip_address.trim()) { setError('Name and IP are required'); return; }
    mut.mutate({
      ...form,
      mac_address: form.mac_address || undefined,
    });
  }

  const set = (k: keyof CreateDeviceData, v: unknown) => setForm(f => ({ ...f, [k]: v }));

  return (
    <Modal title="New Device" open={open} onClose={onClose} onConfirm={handleSubmit} confirmLabel="Create" loading={mut.isPending}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {error && <div className="alert alert-error">{error}</div>}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Name *</label>
            <input className="form-input" value={form.name} onChange={e => set('name', e.target.value)} placeholder="router-01" autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label">Type</label>
            <select className="form-select" value={form.type} onChange={e => set('type', e.target.value)}>
              <option value="router">Router</option>
              <option value="switch">Switch</option>
              <option value="server">Server</option>
              <option value="generic">Generic</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">IP Address *</label>
            <input className="form-input" value={form.ip_address} onChange={e => set('ip_address', e.target.value)} placeholder="10.0.0.1" />
          </div>
          <div className="form-group">
            <label className="form-label">MAC Address</label>
            <input className="form-input" value={form.mac_address ?? ''} onChange={e => set('mac_address', e.target.value)} placeholder="auto-generated" />
          </div>
          <div className="form-group">
            <label className="form-label">Network</label>
            <select className="form-select" value={form.network_id ?? ''} onChange={e => set('network_id', e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">— None —</option>
              {networks.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">SNMP Community</label>
            <input className="form-input" value={form.snmp_community ?? 'public'} onChange={e => set('snmp_community', e.target.value)} placeholder="public" />
          </div>
          <div className="form-group" style={{ gridColumn: '1 / -1' }}>
            <label className="form-label">SNMP Port <span style={{ color: 'var(--muted)', fontWeight: 400 }}>(optional — for LAN access on macOS)</span></label>
            <input
              className="form-input"
              type="number"
              value={form.snmp_port ?? ''}
              onChange={e => set('snmp_port', e.target.value ? Number(e.target.value) : undefined)}
              placeholder="e.g. 10161 — maps host UDP port → container :161"
            />
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>
              Leave blank for same-host NMS access. Set a unique port (10161, 10162, …) to reach this device
              from other machines on your LAN via <code>your-mac-ip:port</code>.
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
}

// ─── Bulk create ──────────────────────────────────────────────────────────────

function BulkCreateModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [form, setForm] = useState<BulkCreateDeviceData>({
    base_ip: '10.0.0.1',
    count: 3,
    name_prefix: 'device-',
    network_id: undefined,
    type: 'generic',
    snmp_community: 'public',
  });
  const [error, setError] = useState('');
  const qc = useQueryClient();

  const { data: networks = [] } = useQuery({ queryKey: ['networks'], queryFn: fetchNetworks });

  const mut = useMutation({
    mutationFn: bulkCreateDevices,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['devices'] });
      onClose();
    },
    onError: (e: unknown) => {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Bulk create failed');
    },
  });

  const set = (k: keyof BulkCreateDeviceData, v: unknown) => setForm(f => ({ ...f, [k]: v }));

  return (
    <Modal title="Bulk Create Devices" open={open} onClose={onClose} onConfirm={() => mut.mutate(form)} confirmLabel="Create All" loading={mut.isPending}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {error && <div className="alert alert-error">{error}</div>}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div className="form-group">
            <label className="form-label">Name Prefix</label>
            <input className="form-input" value={form.name_prefix} onChange={e => set('name_prefix', e.target.value)} placeholder="device-" />
          </div>
          <div className="form-group">
            <label className="form-label">Count</label>
            <input className="form-input" type="number" min={1} max={50} value={form.count} onChange={e => set('count', Number(e.target.value))} />
          </div>
          <div className="form-group">
            <label className="form-label">Base IP</label>
            <input className="form-input" value={form.base_ip} onChange={e => set('base_ip', e.target.value)} placeholder="10.0.0.1" />
          </div>
          <div className="form-group">
            <label className="form-label">Type</label>
            <select className="form-select" value={form.type} onChange={e => set('type', e.target.value as BulkCreateDeviceData['type'])}>
              <option value="router">Router</option>
              <option value="switch">Switch</option>
              <option value="server">Server</option>
              <option value="generic">Generic</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Network</label>
            <select className="form-select" value={form.network_id ?? ''} onChange={e => set('network_id', e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">— None —</option>
              {networks.map(n => <option key={n.id} value={n.id}>{n.name}</option>)}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">SNMP Community</label>
            <input className="form-input" value={form.snmp_community ?? 'public'} onChange={e => set('snmp_community', e.target.value)} placeholder="public" />
          </div>
        </div>
        <p style={{ fontSize: 12, color: 'var(--muted)' }}>
          Creates {form.count} devices named {form.name_prefix}1 … {form.name_prefix}{form.count},
          with IPs auto-incremented from {form.base_ip}.
        </p>
      </div>
    </Modal>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function DevicesPage() {
  const [showCreate, setShowCreate] = useState(false);
  const [showBulk, setShowBulk] = useState(false);
  const [deleteId, setDeleteId] = useState<number | null>(null);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data = [], isLoading, error } = useQuery<Device[]>({
    queryKey: ['devices'],
    queryFn: fetchDevices,
    refetchInterval: 15_000,
  });

  const deleteMut = useMutation({
    mutationFn: deleteDevice,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['devices'] }); setDeleteId(null); },
  });

  const lifecycleMut = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'start' | 'stop' | 'restart' }) => {
      if (action === 'start') return startDevice(id);
      if (action === 'stop') return stopDevice(id);
      return restartDevice(id);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['devices'] }),
  });

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Devices</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn" onClick={() => setShowBulk(true)}>Bulk Create</button>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>+ New Device</button>
        </div>
      </div>

      {isLoading && (
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', color: 'var(--muted)' }}>
          <Spinner size={16} /> Loading…
        </div>
      )}

      {error && <div className="alert alert-error">Failed to load devices.</div>}

      {!isLoading && !error && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>IP Address</th>
                <th>MAC</th>
                <th>Community</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.length === 0 && (
                <tr>
                  <td colSpan={7}>
                    <div className="empty-state">No devices yet. Create one to get started.</div>
                  </td>
                </tr>
              )}
              {data.map(dev => (
                <tr
                  key={dev.id}
                  className="clickable"
                  onClick={() => navigate(`/devices/${dev.id}`)}
                >
                  <td style={{ fontWeight: 600 }}>{dev.name}</td>
                  <td>
                    <code style={{ fontSize: 11, background: 'var(--surface)', padding: '2px 6px', borderRadius: 4 }}>
                      {dev.type}
                    </code>
                  </td>
                  <td style={{ fontFamily: 'monospace', fontSize: 12 }}>{dev.ip_address}</td>
                  <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--muted)' }}>
                    {dev.mac_address ?? '—'}
                  </td>
                  <td style={{ color: 'var(--muted)' }}>{dev.snmp_community}</td>
                  <td><StatusBadge status={dev.status} /></td>
                  <td onClick={e => e.stopPropagation()}>
                    <div style={{ display: 'flex', gap: 4 }}>
                      {dev.status !== 'running' && (
                        <button
                          className="btn btn-sm"
                          disabled={lifecycleMut.isPending}
                          onClick={() => lifecycleMut.mutate({ id: dev.id, action: 'start' })}
                        >
                          Start
                        </button>
                      )}
                      {dev.status === 'running' && (
                        <>
                          <button
                            className="btn btn-sm"
                            disabled={lifecycleMut.isPending}
                            onClick={() => lifecycleMut.mutate({ id: dev.id, action: 'stop' })}
                          >
                            Stop
                          </button>
                          <button
                            className="btn btn-sm"
                            disabled={lifecycleMut.isPending}
                            onClick={() => lifecycleMut.mutate({ id: dev.id, action: 'restart' })}
                          >
                            Restart
                          </button>
                        </>
                      )}
                      <button
                        className="btn btn-sm"
                        title="Download all OID values as a seed JSON file"
                        onClick={() => exportDeviceOids(dev.id, dev.name)}
                      >
                        Export OIDs
                      </button>
                      <button
                        className="btn btn-danger btn-sm"
                        onClick={() => setDeleteId(dev.id)}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <NewDeviceModal open={showCreate} onClose={() => setShowCreate(false)} />
      <BulkCreateModal open={showBulk} onClose={() => setShowBulk(false)} />
      <ConfirmDialog
        open={deleteId !== null}
        title="Delete device"
        message="This will stop and remove the device container. OID values will be lost."
        onClose={() => setDeleteId(null)}
        onConfirm={() => deleteId !== null && deleteMut.mutate(deleteId)}
        loading={deleteMut.isPending}
      />
    </div>
  );
}
