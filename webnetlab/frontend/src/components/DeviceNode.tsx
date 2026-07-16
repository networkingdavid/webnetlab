import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';

export interface DeviceNodeData {
  label: string;
  ip: string;
  type: string;
  status: string;
  interfaces: string[];
  [key: string]: unknown;
}

const STATUS_COLOR: Record<string, string> = {
  running: '#22c55e',
  stopped: '#ef4444',
  error:   '#f97316',
};

const TYPE_COLOR: Record<string, { bg: string; color: string }> = {
  router:  { bg: '#dbeafe', color: '#1d4ed8' },
  switch:  { bg: '#dcfce7', color: '#15803d' },
  server:  { bg: '#fef3c7', color: '#92400e' },
  generic: { bg: '#f3f4f6', color: '#374151' },
};

function shortIface(name: string): string {
  return name
    .replace('GigabitEthernet', 'Gi')
    .replace('FastEthernet',    'Fa')
    .replace('TenGigabitEthernet', 'Te')
    .replace('HundredGigE',    'Hu')
    .replace('Ethernet',       'Et')
    .replace('Loopback',       'Lo')
    .replace('Port-channel',   'Po')
    .replace('Vlan',           'Vl')
    .replace('Tunnel',         'Tu');
}

// A bidirectional port: renders both a source and target handle at the same spot.
// ReactFlow v12 requires sourceHandle to match a type="source" handle on the source node,
// and targetHandle to match a type="target" handle on the target node.
// By rendering both types with the same id, one handle acts as both endpoint types.
function IfaceHandle({ id, side }: { id: string; side: 'left' | 'right' }) {
  const pos = side === 'left' ? Position.Left : Position.Right;
  const sharedStyle = {
    width: 10,
    height: 10,
    background: '#3b82d4',
    border: '2px solid #fff',
    // Do NOT override top/left — let ReactFlow centre it on the row naturally
  };
  return (
    <>
      <Handle type="source" position={pos} id={id} style={sharedStyle} />
      <Handle type="target" position={pos} id={id} style={{ ...sharedStyle, background: 'transparent', border: 'none', pointerEvents: 'none' }} />
    </>
  );
}

export const DeviceNode = memo(({ data }: NodeProps) => {
  const d = data as DeviceNodeData;
  const statusColor = STATUS_COLOR[d.status] ?? '#9ca3af';
  const typeStyle   = TYPE_COLOR[d.type] ?? TYPE_COLOR.generic;
  const interfaces: string[] = Array.isArray(d.interfaces) ? d.interfaces : [];

  // Even-indexed interfaces on the left, odd on the right
  const leftIfaces  = interfaces.filter((_, i) => i % 2 === 0);
  const rightIfaces = interfaces.filter((_, i) => i % 2 !== 0);
  const rowCount    = Math.max(leftIfaces.length, rightIfaces.length);

  const ROW_H = 24;

  return (
    <div style={{
      background: '#ffffff',
      border: '1.5px solid #e5e7eb',
      borderRadius: 8,
      fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif',
      fontSize: 12,
      minWidth: 210,
      boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
    }}>

      {/* ── Header ── */}
      <div style={{ padding: '8px 12px 6px', borderBottom: interfaces.length ? '1px solid #e5e7eb' : undefined }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 3 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, letterSpacing: '0.05em',
            background: typeStyle.bg, color: typeStyle.color,
            padding: '1px 6px', borderRadius: 4,
          }}>
            {d.type.toUpperCase()}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 10, color: '#57606a' }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: statusColor, display: 'inline-block' }} />
            {d.status}
          </span>
        </div>
        <div style={{ fontWeight: 700, fontSize: 13, color: '#1f2328', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {d.label}
        </div>
        <div style={{ fontSize: 11, color: '#57606a', fontFamily: 'monospace' }}>{d.ip}</div>
      </div>

      {/* ── Interface rows ── */}
      {interfaces.length > 0 && (
        <div>
          {Array.from({ length: rowCount }).map((_, rowIdx) => {
            const leftIface  = leftIfaces[rowIdx];
            const rightIface = rightIfaces[rowIdx];
            return (
              <div key={rowIdx} style={{
                display: 'flex',
                alignItems: 'center',
                height: ROW_H,
                borderBottom: rowIdx < rowCount - 1 ? '1px solid #f3f4f6' : undefined,
              }}>

                {/* ── Left cell ── */}
                <div style={{
                  flex: 1, display: 'flex', alignItems: 'center',
                  borderRight: rightIface ? '1px solid #f3f4f6' : undefined,
                  minWidth: 0,
                }}>
                  {leftIface ? (
                    <>
                      <IfaceHandle id={leftIface} side="left" />
                      <span title={leftIface} style={{
                        paddingLeft: 8, fontSize: 10, color: '#374151',
                        userSelect: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {shortIface(leftIface)}
                      </span>
                    </>
                  ) : <span />}
                </div>

                {/* ── Right cell ── */}
                <div style={{
                  flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
                  minWidth: 0,
                }}>
                  {rightIface ? (
                    <>
                      <span title={rightIface} style={{
                        paddingRight: 8, fontSize: 10, color: '#374151',
                        userSelect: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                      }}>
                        {shortIface(rightIface)}
                      </span>
                      <IfaceHandle id={rightIface} side="right" />
                    </>
                  ) : <span />}
                </div>

              </div>
            );
          })}
        </div>
      )}

      {/* ── Fallback when no interfaces ── */}
      {interfaces.length === 0 && (
        <>
          <IfaceHandle id="__left"  side="left"  />
          <IfaceHandle id="__right" side="right" />
        </>
      )}

    </div>
  );
});

DeviceNode.displayName = 'DeviceNode';
