import { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchMibs, fetchMibOids, uploadMib, assignMib, type Mib, type MibOid } from '../api/mibs';
import { fetchDevices } from '../api/devices';
import { Modal } from '../components/Modal';
import { Spinner } from '../components/Spinner';

// ─── OID tree viewer (collapsed by default) ───────────────────────────────────

function MibOidTree({ mibId }: { mibId: number }) {
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());

  const { data: oids = [], isLoading } = useQuery<MibOid[]>({
    queryKey: ['mib-oids', mibId],
    queryFn: () => fetchMibOids(mibId),
  });

  if (isLoading) return <div style={{ padding: 16, display: 'flex', gap: 8, alignItems: 'center', color: 'var(--muted)' }}><Spinner size={14} /> Loading OIDs…</div>;
  if (oids.length === 0) return <div style={{ padding: 16, color: 'var(--muted)', fontSize: 12 }}>No OIDs in this MIB.</div>;

  // Group by top-level OID prefix (first 6 segments)
  const groups = new Map<string, MibOid[]>();
  for (const o of oids) {
    const parts = o.oid.split('.');
    const key = parts.slice(0, 6).join('.');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(o);
  }

  const toggle = (k: string) =>
    setExpandedModules(s => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });

  return (
    <div style={{ padding: '0 0 8px 0' }}>
      {Array.from(groups.entries()).map(([prefix, items]) => {
        const exp = expandedModules.has(prefix);
        return (
          <div key={prefix} style={{ borderTop: '1px solid var(--border)' }}>
            <div
              onClick={() => toggle(prefix)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', cursor: 'pointer', background: exp ? '#f0f9ff' : 'var(--surface)' }}
            >
              <span style={{ fontSize: 11, color: 'var(--muted)', transform: exp ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform 0.15s' }}>▶</span>
              <code style={{ fontSize: 11 }}>{prefix}</code>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--muted)' }}>{items.length}</span>
            </div>
            {exp && (
              <div style={{ overflowX: 'auto' }}>
                <table className="table" style={{ marginBottom: 0 }}>
                  <thead>
                    <tr><th>OID</th><th>Name</th><th>Syntax</th><th>Access</th></tr>
                  </thead>
                  <tbody>
                    {items.map(o => (
                      <tr key={o.oid}>
                        <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{o.oid}</td>
                        <td style={{ fontWeight: 600, fontSize: 12 }}>{o.name}</td>
                        <td style={{ fontSize: 11, color: 'var(--muted)' }}>{o.syntax}</td>
                        <td style={{ fontSize: 11, color: 'var(--muted)' }}>{o.access}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Assign modal ─────────────────────────────────────────────────────────────

function AssignModal({ mib, open, onClose }: { mib: Mib; open: boolean; onClose: () => void }) {
  const [selected, setSelected] = useState<number[]>([]);
  const qc = useQueryClient();
  const { data: devices = [] } = useQuery({ queryKey: ['devices'], queryFn: fetchDevices });

  const mut = useMutation({
    mutationFn: async () => {
      for (const devId of selected) {
        await assignMib(mib.id, devId);
      }
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['mibs'] }); onClose(); },
  });

  function toggleDevice(id: number) {
    setSelected(s => s.includes(id) ? s.filter(x => x !== id) : [...s, id]);
  }

  return (
    <Modal title={`Assign "${mib.name}" to devices`} open={open} onClose={onClose} onConfirm={() => mut.mutate()} confirmLabel={`Assign to ${selected.length} device(s)`} loading={mut.isPending}>
      <div style={{ maxHeight: 280, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {devices.length === 0 && <p style={{ color: 'var(--muted)', fontSize: 13 }}>No devices available.</p>}
        {devices.map(d => (
          <label key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '6px 4px', borderRadius: 4, background: selected.includes(d.id) ? '#eff6ff' : 'transparent' }}>
            <input type="checkbox" checked={selected.includes(d.id)} onChange={() => toggleDevice(d.id)} />
            <span style={{ fontWeight: 600 }}>{d.name}</span>
            <span style={{ fontSize: 11, color: 'var(--muted)' }}>{d.ip_address}</span>
          </label>
        ))}
      </div>
    </Modal>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export function MibsPage() {
  const [browsingId, setBrowsingId] = useState<number | null>(null);
  const [assignMib_, setAssignMib] = useState<Mib | null>(null);
  const [uploadBanner, setUploadBanner] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  const { data = [], isLoading, error } = useQuery<Mib[]>({
    queryKey: ['mibs'],
    queryFn: fetchMibs,
  });

  async function handleUpload(file: File) {
    setUploading(true);
    setUploadBanner(null);
    setUploadError('');
    try {
      const result = await uploadMib(file);
      qc.invalidateQueries({ queryKey: ['mibs'] });
      setUploadBanner(`Compiled "${result.name}": ${result.oid_count ?? 0} OIDs found.`);
    } catch (e: unknown) {
      setUploadError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">MIBs</h1>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {uploading && <Spinner size={16} />}
          <input
            ref={fileInputRef}
            type="file"
            accept=".mib,.txt,.my"
            style={{ display: 'none' }}
            onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); }}
          />
          <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()} disabled={uploading}>
            {uploading ? 'Uploading…' : '+ Upload MIB'}
          </button>
        </div>
      </div>

      {uploadBanner && (
        <div className="alert alert-success" style={{ marginBottom: 16 }}>
          {uploadBanner}
          <button onClick={() => setUploadBanner(null)} style={{ marginLeft: 12, background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 700 }}>×</button>
        </div>
      )}
      {uploadError && (
        <div className="alert alert-error" style={{ marginBottom: 16 }}>
          {uploadError}
          <button onClick={() => setUploadError('')} style={{ marginLeft: 12, background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 700 }}>×</button>
        </div>
      )}

      {isLoading && <div style={{ display: 'flex', gap: 10, alignItems: 'center', color: 'var(--muted)' }}><Spinner size={16} /> Loading…</div>}
      {error && <div className="alert alert-error">Failed to load MIBs.</div>}

      {!isLoading && !error && (
        <div>
          {data.length === 0 && <div className="empty-state">No MIBs uploaded yet. Click "Upload MIB" to get started.</div>}

          {data.map(mib => (
            <div key={mib.id} style={{ border: '1px solid var(--border)', borderRadius: 8, marginBottom: 10, overflow: 'hidden' }}>
              {/* MIB row */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 16px', background: 'var(--bg)' }}>
                <div style={{ flex: 1 }}>
                  <span style={{ fontWeight: 700 }}>{mib.name}</span>
                  <span style={{ marginLeft: 12, fontSize: 11, color: 'var(--muted)' }}>{mib.filename}</span>
                </div>
                <span style={{ fontSize: 12, color: 'var(--muted)' }}>
                  {mib.oid_count ?? 0} OIDs
                </span>
                {mib.parsed_at && (
                  <span style={{ fontSize: 11, color: 'var(--muted)' }}>
                    {new Date(mib.parsed_at).toLocaleDateString()}
                  </span>
                )}
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    className="btn btn-sm"
                    onClick={() => setBrowsingId(prev => prev === mib.id ? null : mib.id)}
                  >
                    {browsingId === mib.id ? 'Hide OIDs' : 'Browse'}
                  </button>
                  <button className="btn btn-sm btn-primary" onClick={() => setAssignMib(mib)}>
                    Assign
                  </button>
                </div>
              </div>

              {/* OID tree slide-down */}
              {browsingId === mib.id && (
                <div style={{ borderTop: '1px solid var(--border)', background: 'var(--surface)' }}>
                  <MibOidTree mibId={mib.id} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {assignMib_ && (
        <AssignModal mib={assignMib_} open onClose={() => setAssignMib(null)} />
      )}
    </div>
  );
}
