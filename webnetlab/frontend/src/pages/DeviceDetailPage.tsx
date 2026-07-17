import { useState, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchDevice, startDevice, stopDevice, restartDevice } from '../api/devices';
import { fetchDeviceOids, setOid, seedDevice, type OidValue, type ValueMode } from '../api/oids';
import { fetchMibs, assignMib, unassignMib } from '../api/mibs';
import { StatusBadge } from '../components/StatusBadge';
import { Modal } from '../components/Modal';
import { Spinner } from '../components/Spinner';

// ─── OID module name map (common IETF prefixes) ───────────────────────────────

const OID_MODULE_NAMES: Record<string, string> = {
  '1.3.6.1.2.1.1': 'System',
  '1.3.6.1.2.1.2': 'Interfaces',
  '1.3.6.1.2.1.4': 'IP',
  '1.3.6.1.2.1.5': 'ICMP',
  '1.3.6.1.2.1.6': 'TCP',
  '1.3.6.1.2.1.7': 'UDP',
  '1.3.6.1.2.1.11': 'SNMP',
  '1.3.6.1.2.1.17': 'Bridge',
  '1.3.6.1.2.1.31': 'IF-MIB',
  '1.3.6.1.4.1': 'Enterprises',
};

// ─── OID → human name lookup (common IETF / Cisco OIDs) ─────────────────────

const OID_NAMES: Record<string, string> = {
  // SNMPv2-MIB / RFC1213-MIB System group
  '1.3.6.1.2.1.1.1.0':  'sysDescr',
  '1.3.6.1.2.1.1.2.0':  'sysObjectID',
  '1.3.6.1.2.1.1.3.0':  'sysUpTime',
  '1.3.6.1.2.1.1.4.0':  'sysContact',
  '1.3.6.1.2.1.1.5.0':  'sysName',
  '1.3.6.1.2.1.1.6.0':  'sysLocation',
  '1.3.6.1.2.1.1.7.0':  'sysServices',
  // IF-MIB
  '1.3.6.1.2.1.2.1.0':  'ifNumber',
  '1.3.6.1.2.1.2.2.1.1': 'ifIndex',
  '1.3.6.1.2.1.2.2.1.2': 'ifDescr',
  '1.3.6.1.2.1.2.2.1.3': 'ifType',
  '1.3.6.1.2.1.2.2.1.4': 'ifMtu',
  '1.3.6.1.2.1.2.2.1.5': 'ifSpeed',
  '1.3.6.1.2.1.2.2.1.6': 'ifPhysAddress',
  '1.3.6.1.2.1.2.2.1.7': 'ifAdminStatus',
  '1.3.6.1.2.1.2.2.1.8': 'ifOperStatus',
  '1.3.6.1.2.1.2.2.1.10': 'ifInOctets',
  '1.3.6.1.2.1.2.2.1.11': 'ifInUcastPkts',
  '1.3.6.1.2.1.2.2.1.13': 'ifInDiscards',
  '1.3.6.1.2.1.2.2.1.14': 'ifInErrors',
  '1.3.6.1.2.1.2.2.1.16': 'ifOutOctets',
  '1.3.6.1.2.1.2.2.1.17': 'ifOutUcastPkts',
  '1.3.6.1.2.1.2.2.1.19': 'ifOutDiscards',
  '1.3.6.1.2.1.2.2.1.20': 'ifOutErrors',
  // IP-MIB
  '1.3.6.1.2.1.4.1.0':  'ipForwarding',
  '1.3.6.1.2.1.4.2.0':  'ipDefaultTTL',
  '1.3.6.1.2.1.4.3.0':  'ipInReceives',
  // TCP-MIB
  '1.3.6.1.2.1.6.1.0':  'tcpRtoAlgorithm',
  '1.3.6.1.2.1.6.9.0':  'tcpCurrEstab',
  // SNMPv2-MIB
  '1.3.6.1.2.1.11.1.0': 'snmpInPkts',
  '1.3.6.1.2.1.11.2.0': 'snmpOutPkts',
  '1.3.6.1.2.1.11.30.0':'snmpEnableAuthenTraps',
  // IF-MIB ifXTable
  '1.3.6.1.2.1.31.1.1.1.1':  'ifName',
  '1.3.6.1.2.1.31.1.1.1.2':  'ifInMulticastPkts',
  '1.3.6.1.2.1.31.1.1.1.6':  'ifHCInOctets',
  '1.3.6.1.2.1.31.1.1.1.10': 'ifHCOutOctets',
  '1.3.6.1.2.1.31.1.1.1.15': 'ifHighSpeed',
  '1.3.6.1.2.1.31.1.1.1.18': 'ifAlias',
  // ENTITY-MIB
  '1.3.6.1.2.1.47.1.1.1.1.2': 'entPhysicalDescr',
  '1.3.6.1.2.1.47.1.1.1.1.7': 'entPhysicalName',
  // Cisco CISCO-PRODUCTS-MIB / CISCO-ENVMON-MIB
  '1.3.6.1.4.1.9.2.1.1.0':   'ciscoSysDescr',
  '1.3.6.1.4.1.9.2.1.3.0':   'ciscoLocalIfDescr',
  '1.3.6.1.4.1.9.9.13.1.3.1.3': 'ciscoEnvMonTemperatureStatusValue',
  '1.3.6.1.4.1.9.9.68.1.2.2.1.2': 'vmVlanType',
};

/** Return the human-readable name for an OID, or a short numeric suffix. */
function oidName(oid: string): string {
  // Exact match (scalar .0 OIDs)
  if (OID_NAMES[oid]) return OID_NAMES[oid];
  // Strip last segment and try as table column prefix (e.g. 1.3.6.1.2.1.2.2.1.2.X)
  const parts = oid.split('.');
  // Try stripping the last 1 or 2 parts (instance index)
  for (let trim = 1; trim <= 2; trim++) {
    const prefix = parts.slice(0, parts.length - trim).join('.');
    if (OID_NAMES[prefix]) return OID_NAMES[prefix];
  }
  // Fallback: last 3 numeric segments as short label
  return parts.slice(-3).join('.');
}

function getModule(oid: string): string {
  for (const prefix of Object.keys(OID_MODULE_NAMES).sort((a, b) => b.length - a.length)) {
    if (oid.startsWith(prefix)) return OID_MODULE_NAMES[prefix];
  }
  const parts = oid.split('.');
  return parts.slice(0, Math.min(6, parts.length)).join('.');
}

function groupOids(oids: OidValue[]): Map<string, OidValue[]> {
  const map = new Map<string, OidValue[]>();
  for (const o of oids) {
    const mod = getModule(o.oid);
    if (!map.has(mod)) map.set(mod, []);
    map.get(mod)!.push(o);
  }
  return map;
}

// ─── Mode badge ───────────────────────────────────────────────────────────────

function ModeBadge({ mode }: { mode: ValueMode }) {
  const colors: Record<ValueMode, { bg: string; color: string }> = {
    static: { bg: '#dbeafe', color: '#1d4ed8' },
    random: { bg: '#fef3c7', color: '#92400e' },
    scripted: { bg: '#f3e8ff', color: '#6b21a8' },
    walk_seed: { bg: '#dcfce7', color: '#15803d' },
  };
  const c = colors[mode] ?? { bg: '#f1f5f9', color: '#475569' };
  return (
    <span style={{ display: 'inline-block', fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 10, background: c.bg, color: c.color }}>
      {mode}
    </span>
  );
}

// ─── Inline OID editor ────────────────────────────────────────────────────────

function OidEditor({ deviceId, oid, onClose }: { deviceId: number; oid: OidValue; onClose: () => void }) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<ValueMode>(oid.value_mode);
  const [staticVal, setStaticVal] = useState(oid.static_value ?? '');
  const [script, setScript] = useState(oid.script ?? '');
  const [rndMin, setRndMin] = useState(oid.random_config?.min ?? 0);
  const [rndMax, setRndMax] = useState(oid.random_config?.max ?? 100);
  const [rndType, setRndType] = useState<'integer' | 'counter' | 'gauge'>(oid.random_config?.type ?? 'integer');
  const [status, setStatus] = useState<'idle' | 'saving' | 'ok' | 'err'>('idle');
  const [errMsg, setErrMsg] = useState('');

  const mut = useMutation({
    mutationFn: () =>
      setOid(deviceId, oid.oid, {
        value_mode: mode,
        static_value: mode === 'static' ? staticVal : null,
        random_config: mode === 'random' ? { min: rndMin, max: rndMax, type: rndType } : null,
        script: mode === 'scripted' ? script : null,
      }),
    onMutate: () => setStatus('saving'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['device-oids', deviceId] });
      setStatus('ok');
      setTimeout(() => { setStatus('idle'); onClose(); }, 800);
    },
    onError: (e: unknown) => {
      setStatus('err');
      setErrMsg((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Save failed');
    },
  });

  return (
    <div
      style={{
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: '14px 16px',
        margin: '4px 0 8px 24px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--muted)' }}>Mode</span>
        {(['static', 'random', 'scripted', 'walk_seed'] as ValueMode[]).map(m => (
          <button
            key={m}
            className={`btn btn-sm${mode === m ? ' btn-primary' : ''}`}
            onClick={() => setMode(m)}
            disabled={m === 'walk_seed'}
          >
            {m}
          </button>
        ))}
      </div>

      {mode === 'static' && (
        <div className="form-group">
          <label className="form-label">Value</label>
          <input className="form-input" value={staticVal} onChange={e => setStaticVal(e.target.value)} placeholder="string or integer" autoFocus />
        </div>
      )}

      {mode === 'random' && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Min</label>
            <input className="form-input" type="number" value={rndMin} onChange={e => setRndMin(Number(e.target.value))} />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Max</label>
            <input className="form-input" type="number" value={rndMax} onChange={e => setRndMax(Number(e.target.value))} />
          </div>
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label">Type</label>
            <select className="form-select" value={rndType} onChange={e => setRndType(e.target.value as typeof rndType)}>
              <option value="integer">Integer</option>
              <option value="counter">Counter</option>
              <option value="gauge">Gauge</option>
            </select>
          </div>
        </div>
      )}

      {mode === 'scripted' && (
        <div className="form-group">
          <label className="form-label">Python expression</label>
          <textarea className="form-textarea" value={script} onChange={e => setScript(e.target.value)} placeholder="e.g. int(time.time()) % 1000" autoFocus />
        </div>
      )}

      {mode === 'walk_seed' && (
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
          Value: <code>{oid.walk_seed_value ?? '(none)'}</code>
          <button className="btn btn-sm" style={{ marginLeft: 10 }} onClick={() => setMode('static')}>Switch to Static</button>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button className="btn btn-primary btn-sm" onClick={() => mut.mutate()} disabled={status === 'saving'}>
          {status === 'saving' ? 'Saving…' : 'Save'}
        </button>
        <button className="btn btn-sm" onClick={onClose}>Cancel</button>
        {status === 'ok' && <span style={{ fontSize: 12, color: 'var(--success)' }}>✓ Saved</span>}
        {status === 'err' && <span style={{ fontSize: 12, color: 'var(--error)' }}>{errMsg}</span>}
      </div>
    </div>
  );
}

// ─── OID row ──────────────────────────────────────────────────────────────────

function OidRow({ deviceId, oid, editing, onToggle }: {
  deviceId: number;
  oid: OidValue;
  editing: boolean;
  onToggle: () => void;
}) {
  const preview = oid.static_value ?? oid.walk_seed_value ?? (oid.random_config ? `rnd(${oid.random_config.min}–${oid.random_config.max})` : null);
  const name = oidName(oid.oid);

  return (
    <>
      <tr
        style={{ cursor: 'pointer', background: editing ? '#eff6ff' : undefined }}
        onClick={onToggle}
      >
        <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{oid.oid}</td>
        <td style={{ fontSize: 12, fontWeight: 500, color: name.includes('.') ? 'var(--muted)' : 'var(--text)' }}>{name}</td>
        <td><ModeBadge mode={oid.value_mode} /></td>
        <td style={{ fontFamily: 'monospace', fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--muted)' }}>
          {preview ?? '—'}
        </td>
      </tr>
      {editing && (
        <tr>
          <td colSpan={4} style={{ padding: 0 }}>
            <OidEditor deviceId={deviceId} oid={oid} onClose={onToggle} />
          </td>
        </tr>
      )}
    </>
  );
}

// ─── OID Browser tab ─────────────────────────────────────────────────────────

function OidBrowserTab({ deviceId }: { deviceId: number }) {
  const [expandedModules, setExpandedModules] = useState<Set<string>>(new Set());
  const [editingOid, setEditingOid] = useState<string | null>(null);

  const { data: oids = [], isLoading } = useQuery<OidValue[]>({
    queryKey: ['device-oids', deviceId],
    queryFn: () => fetchDeviceOids(deviceId),
  });

  const grouped = groupOids(oids);

  const toggleModule = (mod: string) =>
    setExpandedModules(s => {
      const next = new Set(s);
      next.has(mod) ? next.delete(mod) : next.add(mod);
      return next;
    });

  if (isLoading) return <div style={{ display: 'flex', gap: 10, alignItems: 'center', padding: 20, color: 'var(--muted)' }}><Spinner size={16} /> Loading OIDs…</div>;

  if (oids.length === 0)
    return <div className="empty-state">No OIDs configured for this device. Upload a MIB or seed from a walk file.</div>;

  return (
    <div>
      <div style={{ marginBottom: 12, fontSize: 12, color: 'var(--muted)' }}>
        {oids.length} OIDs in {grouped.size} modules — click a module to expand, click a row to edit.
      </div>
      {Array.from(grouped.entries()).map(([mod, modOids]) => {
        const expanded = expandedModules.has(mod);
        return (
          <div key={mod} style={{ border: '1px solid var(--border)', borderRadius: 6, marginBottom: 6, overflow: 'hidden' }}>
            {/* Module header */}
            <div
              onClick={() => toggleModule(mod)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 12px',
                background: 'var(--surface)',
                cursor: 'pointer',
                userSelect: 'none',
                borderBottom: expanded ? '1px solid var(--border)' : 'none',
              }}
            >
              <span style={{ fontSize: 12, color: 'var(--muted)', transform: expanded ? 'rotate(90deg)' : 'none', display: 'inline-block', transition: 'transform 0.15s' }}>▶</span>
              <span style={{ fontWeight: 600, fontSize: 13 }}>{mod}</span>
              <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--muted)' }}>{modOids.length} OIDs</span>
            </div>

            {/* OID rows */}
            {expanded && (
              <div style={{ overflowX: 'auto' }}>
                <table className="table" style={{ marginBottom: 0 }}>
                  <thead>
                    <tr>
                      <th>OID</th>
                      <th>Name</th>
                      <th>Mode</th>
                      <th>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {modOids.map(o => (
                      <OidRow
                        key={o.oid}
                        deviceId={deviceId}
                        oid={o}
                        editing={editingOid === o.oid}
                        onToggle={() => setEditingOid(prev => prev === o.oid ? null : o.oid)}
                      />
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

// ─── Seed Import tab ──────────────────────────────────────────────────────────

function SeedTab({ deviceId }: { deviceId: number }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<{ oid: string; value: string }[] | null>(null);
  const [previewFormat, setPreviewFormat] = useState<'json' | 'snmpwalk' | null>(null);
  const [previewTotal, setPreviewTotal] = useState<number>(0);
  const [imported, setImported] = useState<{ count: number; format: string } | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const qc = useQueryClient();

  // Detect file type from extension for hint text only — the server auto-detects
  const isJson = file?.name.endsWith('.json') ?? false;

  function handleFile(f: File) { setFile(f); setPreview(null); setPreviewFormat(null); setImported(null); setError(''); }

  async function handlePreview() {
    if (!file) return;
    setLoading(true); setError('');
    try {
      const result = await seedDevice(deviceId, file, true);
      setPreview(result.preview ?? result.oids ?? []);
      setPreviewTotal(result.parsed ?? result.count ?? 0);
      setPreviewFormat((result.format as 'json' | 'snmpwalk') ?? null);
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Preview failed');
    } finally { setLoading(false); }
  }

  async function handleImport() {
    if (!file) return;
    setLoading(true); setError('');
    try {
      const result = await seedDevice(deviceId, file, false);
      const count = result.seeded ?? result.count ?? 0;
      const fmt = result.format ?? 'unknown';
      setImported({ count, format: fmt });
      setPreview(null);
      qc.invalidateQueries({ queryKey: ['device-oids', deviceId] });
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Import failed');
    } finally { setLoading(false); }
  }

  return (
    <div>
      {/* Format hint */}
      <div style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 12, lineHeight: 1.6 }}>
        Accepts two file formats — auto-detected on upload:
        <ul style={{ margin: '4px 0 0 18px' }}>
          <li><strong>WebNetLab JSON export</strong> (<code>.json</code>) — produced by the <em>Export OIDs</em> button. Preserves all modes, types, and random configs exactly.</li>
          <li><strong>snmpwalk text</strong> (<code>.txt</code> / <code>.walk</code>) — standard <code>snmpwalk -v2c -c public …</code> output.</li>
        </ul>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
        onClick={() => inputRef.current?.click()}
        style={{
          border: `2px dashed ${dragging ? 'var(--accent)' : 'var(--border)'}`,
          borderRadius: 8,
          padding: '32px 20px',
          textAlign: 'center',
          cursor: 'pointer',
          background: dragging ? '#eff6ff' : 'var(--surface)',
          marginBottom: 16,
          transition: 'background 0.1s, border-color 0.1s',
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".txt,.walk,.json"
          style={{ display: 'none' }}
          onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
        />
        {file ? (
          <div>
            <span style={{ fontWeight: 600 }}>{file.name}</span>
            {isJson && (
              <span style={{ marginLeft: 8, fontSize: 12, background: '#dbeafe', color: '#1d4ed8', padding: '2px 8px', borderRadius: 10 }}>
                JSON seed export
              </span>
            )}
          </div>
        ) : (
          <span style={{ color: 'var(--muted)' }}>
            Drag &amp; drop a <code>.json</code> export or <code>.txt</code> / <code>.walk</code> snmpwalk file, or click to browse
          </span>
        )}
      </div>

      {error && <div className="alert alert-error" style={{ marginBottom: 12 }}>{error}</div>}
      {imported !== null && (
        <div className="alert" style={{ background: '#f0fdf4', border: '1px solid #86efac', color: '#166534', borderRadius: 6, padding: '10px 14px', marginBottom: 12 }}>
          Imported <strong>{imported.count}</strong> OIDs successfully
          {imported.format === 'json' && ' (full config restored from JSON export — modes, types, and random ranges preserved)'}
          {imported.format === 'snmpwalk' && ' (seeded as walk_seed mode from snmpwalk text)'}
          .
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button className="btn" disabled={!file || loading} onClick={handlePreview}>
          {loading ? <Spinner size={14} /> : 'Preview'}
        </button>
        <button className="btn btn-primary" disabled={!file || loading} onClick={handleImport}>
          {loading ? <Spinner size={14} /> : 'Import All'}
        </button>
        {file && <button className="btn" style={{ marginLeft: 'auto' }} onClick={() => handleFile(null as unknown as File)}>Clear</button>}
      </div>

      {preview && (
        <div className="table-wrap">
          <div style={{ padding: '6px 12px', fontSize: 12, color: 'var(--muted)', borderBottom: '1px solid var(--border)' }}>
            Preview — {previewTotal} OIDs detected
            {previewFormat && <span style={{ marginLeft: 8, background: 'var(--surface)', padding: '1px 6px', borderRadius: 4, border: '1px solid var(--border)' }}>
              {previewFormat === 'json' ? 'JSON export' : 'snmpwalk text'}
            </span>}
          </div>
          <table className="table">
            <thead>
              <tr><th>OID</th><th>Value / Config</th></tr>
            </thead>
            <tbody>
              {preview.map((row, i) => (
                <tr key={i}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{row.oid}</td>
                  <td style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--muted)', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis' }}>{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ padding: '8px 12px', fontSize: 11, color: 'var(--muted)' }}>Showing first 10 of {previewTotal} OIDs.</div>
        </div>
      )}
    </div>
  );
}

// ─── MIBs tab ─────────────────────────────────────────────────────────────────

function MibsTab({ deviceId }: { deviceId: number }) {
  const [showAdd, setShowAdd] = useState(false);
  const [selectedMibId, setSelectedMibId] = useState<number | null>(null);
  const qc = useQueryClient();

  const { data: allMibs = [] } = useQuery({ queryKey: ['mibs'], queryFn: fetchMibs });
  const { data: device } = useQuery({ queryKey: ['device', deviceId], queryFn: () => fetchDevice(deviceId) });

  // Device doesn't directly carry MIBs in this simple form; we show all MIBs and let user assign/unassign.
  // For now, list all mibs; "assigned" indicator could come from device_mibs junction in a future API response.
  const assignMut = useMutation({
    mutationFn: (mibId: number) => assignMib(mibId, deviceId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['mibs'] }); setShowAdd(false); },
  });
  const unassignMut = useMutation({
    mutationFn: (mibId: number) => unassignMib(mibId, deviceId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['mibs'] }); },
  });

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <button className="btn btn-primary btn-sm" onClick={() => setShowAdd(true)}>+ Add MIB</button>
      </div>

      {allMibs.length === 0 && <div className="empty-state">No MIBs uploaded yet. Upload one from the MIBs page.</div>}

      {allMibs.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr><th>MIB Name</th><th>OID Count</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {allMibs.map(m => (
                <tr key={m.id}>
                  <td style={{ fontWeight: 600 }}>{m.name}</td>
                  <td style={{ color: 'var(--muted)' }}>{m.oid_count ?? '—'}</td>
                  <td>
                    <button className="btn btn-danger btn-sm" onClick={() => unassignMut.mutate(m.id)} disabled={unassignMut.isPending}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {device && (
        <Modal title="Add MIB" open={showAdd} onClose={() => setShowAdd(false)} onConfirm={() => selectedMibId !== null && assignMut.mutate(selectedMibId)} confirmLabel="Assign" loading={assignMut.isPending}>
          <div className="form-group">
            <label className="form-label">Select MIB</label>
            <select className="form-select" value={selectedMibId ?? ''} onChange={e => setSelectedMibId(Number(e.target.value))}>
              <option value="">— Choose —</option>
              {allMibs.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
            </select>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export function DeviceDetailPage() {
  const { id } = useParams<{ id: string }>();
  const deviceId = Number(id);
  const [tab, setTab] = useState<'oids' | 'seed' | 'mibs'>('oids');
  const qc = useQueryClient();

  const { data: device, isLoading, error } = useQuery({
    queryKey: ['device', deviceId],
    queryFn: () => fetchDevice(deviceId),
  });

  const lifecycleMut = useMutation({
    mutationFn: ({ action }: { action: 'start' | 'stop' | 'restart' }) => {
      if (action === 'start') return startDevice(deviceId);
      if (action === 'stop') return stopDevice(deviceId);
      return restartDevice(deviceId);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['device', deviceId] }),
  });

  if (isLoading) return <div style={{ padding: 32, display: 'flex', gap: 10, alignItems: 'center', color: 'var(--muted)' }}><Spinner /> Loading device…</div>;
  if (error || !device) return <div style={{ padding: 32 }} className="alert alert-error">Failed to load device.</div>;

  return (
    <div className="page">
      {/* Device header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20, marginBottom: 24, flexWrap: 'wrap' }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6 }}>
            <h1 className="page-title" style={{ marginBottom: 0 }}>{device.name}</h1>
            <StatusBadge status={device.status} />
          </div>
          <div style={{ fontSize: 12, color: 'var(--muted)', display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            <span>IP: <code style={{ fontFamily: 'monospace' }}>{device.ip_address}</code></span>
            <span>Type: {device.type}</span>
            <span>Community: <code style={{ fontFamily: 'monospace' }}>{device.snmp_community}</code></span>
            {device.mac_address && <span>MAC: <code style={{ fontFamily: 'monospace' }}>{device.mac_address}</code></span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexShrink: 0 }}>
          {device.status !== 'running' && (
            <button className="btn btn-primary btn-sm" disabled={lifecycleMut.isPending} onClick={() => lifecycleMut.mutate({ action: 'start' })}>Start</button>
          )}
          {device.status === 'running' && (
            <>
              <button className="btn btn-sm" disabled={lifecycleMut.isPending} onClick={() => lifecycleMut.mutate({ action: 'stop' })}>Stop</button>
              <button className="btn btn-sm" disabled={lifecycleMut.isPending} onClick={() => lifecycleMut.mutate({ action: 'restart' })}>Restart</button>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="tabs">
        <button className={`tab-btn${tab === 'oids' ? ' active' : ''}`} onClick={() => setTab('oids')}>OID Browser</button>
        <button className={`tab-btn${tab === 'seed' ? ' active' : ''}`} onClick={() => setTab('seed')}>Seed Import</button>
        <button className={`tab-btn${tab === 'mibs' ? ' active' : ''}`} onClick={() => setTab('mibs')}>MIBs</button>
      </div>

      {tab === 'oids' && <OidBrowserTab deviceId={deviceId} />}
      {tab === 'seed' && <SeedTab deviceId={deviceId} />}
      {tab === 'mibs' && <MibsTab deviceId={deviceId} />}
    </div>
  );
}
