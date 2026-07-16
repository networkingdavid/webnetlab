import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  useReactFlow,
  ReactFlowProvider,
  type Node,
  type Edge,
  type Connection,
  type OnConnect,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { fetchTopology, createLink, deleteLink } from '../api/topology';
import type { TopologyNode, TopologyLink } from '../types/topology';
import { DeviceNode, type DeviceNodeData } from '../components/DeviceNode';

// ─── Node type registry ───────────────────────────────────────────────────────

const nodeTypes: NodeTypes = { device: DeviceNode };

// ─── Helpers ──────────────────────────────────────────────────────────────────

// Spread nodes in a pleasing layout: rows of 3, 280px apart horizontally, 280px vertically
function buildFlowNodes(apiNodes: TopologyNode[]): Node[] {
  return apiNodes.map((n, i) => ({
    id: String(n.id),
    type: 'device',
    position: { x: 80 + (i % 3) * 280, y: 60 + Math.floor(i / 3) * 280 },
    data: {
      label: n.name,
      ip: n.ip_address,
      type: n.type,
      status: n.status,
      interfaces: n.interfaces,
    } satisfies DeviceNodeData,
  }));
}

function buildFlowEdges(links: {
  id: number;
  src_device_id: number;
  src_interface: string;
  dst_device_id: number;
  dst_interface: string;
  docker_network_id: string | null;
}[]): Edge[] {
  return links.map(lnk => ({
    id: `link-${lnk.id}`,
    source: String(lnk.src_device_id),
    sourceHandle: lnk.src_interface,
    target: String(lnk.dst_device_id),
    targetHandle: lnk.dst_interface,
    data: { linkId: lnk.id },
    label: `${lnk.src_interface} ↔ ${lnk.dst_interface}`,
    labelStyle: { fontSize: 9, fill: '#57606a' },
    labelBgStyle: { fill: '#ffffff', fillOpacity: 0.85 },
    style: {
      stroke: lnk.docker_network_id ? '#22c55e' : '#9ca3af',
      strokeWidth: 2,
    },
    animated: !!lnk.docker_network_id,
  }));
}

// ─── Link creation dialog ─────────────────────────────────────────────────────

interface PendingConnection {
  srcDeviceId: number;
  srcDeviceName: string;
  srcInterfaces: string[];
  dstDeviceId: number;
  dstDeviceName: string;
  dstInterfaces: string[];
  // Pre-populated when dragging from a specific handle
  preselectedSrcIface?: string;
  preselectedDstIface?: string;
}

function LinkDialog({
  pending,
  onConfirm,
  onCancel,
  loading,
  error,
}: {
  pending: PendingConnection;
  onConfirm: (srcIface: string, dstIface: string) => void;
  onCancel: () => void;
  loading: boolean;
  error: string;
}) {
  const [srcIface, setSrcIface] = useState(pending.preselectedSrcIface ?? pending.srcInterfaces[0] ?? '');
  const [dstIface, setDstIface] = useState(pending.preselectedDstIface ?? pending.dstInterfaces[0] ?? '');

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.35)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: '#fff', borderRadius: 10, padding: '24px 28px',
        width: 460, boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
        fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif',
      }}>
        <h3 style={{ margin: '0 0 4px', fontSize: 16, fontWeight: 700, color: '#1f2328' }}>
          Create Link
        </h3>
        <p style={{ margin: '0 0 20px', fontSize: 13, color: '#57606a' }}>
          Select which interface on each device to connect.
        </p>

        {error && (
          <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', color: '#dc2626', borderRadius: 6, padding: '8px 12px', marginBottom: 16, fontSize: 13 }}>
            {error}
          </div>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 20 }}>
          {/* Source device */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 6 }}>
              {pending.srcDeviceName}
              <span style={{ fontWeight: 400, color: '#57606a' }}> (source)</span>
            </div>
            <select
              value={srcIface}
              onChange={e => setSrcIface(e.target.value)}
              style={{ width: '100%', padding: '7px 10px', fontSize: 13, borderRadius: 6, border: '1px solid #d1d5db', outline: 'none', background: '#f9fafb' }}
            >
              {pending.srcInterfaces.map(iface => (
                <option key={iface} value={iface}>{iface}</option>
              ))}
              {pending.srcInterfaces.length === 0 && <option value="">No interfaces</option>}
            </select>
          </div>

          {/* Dest device */}
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: '#374151', marginBottom: 6 }}>
              {pending.dstDeviceName}
              <span style={{ fontWeight: 400, color: '#57606a' }}> (destination)</span>
            </div>
            <select
              value={dstIface}
              onChange={e => setDstIface(e.target.value)}
              style={{ width: '100%', padding: '7px 10px', fontSize: 13, borderRadius: 6, border: '1px solid #d1d5db', outline: 'none', background: '#f9fafb' }}
            >
              {pending.dstInterfaces.map(iface => (
                <option key={iface} value={iface}>{iface}</option>
              ))}
              {pending.dstInterfaces.length === 0 && <option value="">No interfaces</option>}
            </select>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button
            onClick={onCancel}
            disabled={loading}
            style={{ padding: '8px 18px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer', fontSize: 13 }}
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(srcIface, dstIface)}
            disabled={loading || !srcIface || !dstIface}
            style={{
              padding: '8px 18px', borderRadius: 6, border: 'none',
              background: loading ? '#9ca3af' : '#3b82d4', color: '#fff',
              cursor: loading ? 'default' : 'pointer', fontSize: 13, fontWeight: 600,
            }}
          >
            {loading ? 'Connecting…' : 'Connect'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Inner canvas ──────────────────────────────────────────────────────────────

function TopologyCanvas({
  apiNodes,
  apiLinks,
  onConnect,
  onEdgeDelete,
  selectedNodeId,
}: {
  apiNodes: TopologyNode[];
  apiLinks: TopologyLink[];
  onConnect: OnConnect;
  onEdgeDelete: (edgeId: string) => void;
  selectedNodeId: string | null;
}) {
  const { setCenter, getNode } = useReactFlow();

  const initialNodes = useMemo(() => buildFlowNodes(apiNodes), []);  // eslint-disable-line react-hooks/exhaustive-deps
  const initialEdges = useMemo(() => buildFlowEdges(apiLinks), []);  // eslint-disable-line react-hooks/exhaustive-deps

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Sync edges when links change (after create/delete)
  useEffect(() => {
    setEdges(buildFlowEdges(apiLinks));
  }, [apiLinks, setEdges]);

  // Sync node data (status) when devices change, preserve positions
  useEffect(() => {
    setNodes(prev => {
      const posMap = new Map(prev.map(n => [n.id, n.position]));
      return buildFlowNodes(apiNodes).map(n => ({
        ...n,
        position: posMap.get(n.id) ?? n.position,
      }));
    });
  }, [apiNodes, setNodes]);

  // Pan to selected node when left-panel item is clicked
  useEffect(() => {
    if (!selectedNodeId) return;
    const node = getNode(selectedNodeId);
    if (node) {
      setCenter(node.position.x + 100, node.position.y + 80, { zoom: 1.3, duration: 500 });
    }
  }, [selectedNodeId, getNode, setCenter]);

  const handleEdgesDelete = useCallback(
    (deletedEdges: Edge[]) => { deletedEdges.forEach(e => onEdgeDelete(e.id)); },
    [onEdgeDelete],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onEdgesDelete={handleEdgesDelete}
      nodeTypes={nodeTypes}
      fitView
      deleteKeyCode="Delete"
      connectionLineStyle={{ stroke: '#3b82d4', strokeWidth: 2 }}
      defaultEdgeOptions={{ style: { strokeWidth: 2 } }}
    >
      <Background color="#e5e7eb" gap={20} />
      <Controls />
      <MiniMap nodeColor={() => '#3b82d4'} maskColor="rgba(247,248,250,0.7)" />
    </ReactFlow>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

function TopologyPageInner() {
  const queryClient = useQueryClient();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [pendingConn, setPendingConn] = useState<PendingConnection | null>(null);
  const [linkLoading, setLinkLoading] = useState(false);
  const [linkError, setLinkError] = useState('');

  const { data, isLoading, error } = useQuery({
    queryKey: ['topology'],
    queryFn: fetchTopology,
    refetchInterval: 30_000,
  });

  const nodeMap = useMemo(() => {
    const m = new Map<number, TopologyNode>();
    (data?.nodes ?? []).forEach(n => m.set(n.id, n));
    return m;
  }, [data?.nodes]);

  // Called when user drags from one handle to another
  const handleConnect: OnConnect = useCallback(
    (params: Connection) => {
      if (!params.source || !params.target) return;
      const src = nodeMap.get(Number(params.source));
      const dst = nodeMap.get(Number(params.target));
      if (!src || !dst) return;

      // Open dialog, pre-populate with the handles that were dragged from/to
      setPendingConn({
        srcDeviceId: src.id,
        srcDeviceName: src.name,
        srcInterfaces: src.interfaces.length ? src.interfaces : ['eth0'],
        dstDeviceId: dst.id,
        dstDeviceName: dst.name,
        dstInterfaces: dst.interfaces.length ? dst.interfaces : ['eth0'],
        preselectedSrcIface: params.sourceHandle ?? undefined,
        preselectedDstIface: params.targetHandle ?? undefined,
      });
      setLinkError('');
    },
    [nodeMap],
  );

  // Called when user clicks "Connect" in the dialog
  const handleConfirmLink = useCallback(
    async (srcIface: string, dstIface: string) => {
      if (!pendingConn) return;
      setLinkLoading(true);
      setLinkError('');
      try {
        await createLink({
          src_device_id: pendingConn.srcDeviceId,
          src_interface: srcIface,
          dst_device_id: pendingConn.dstDeviceId,
          dst_interface: dstIface,
        });
        setPendingConn(null);
        queryClient.invalidateQueries({ queryKey: ['topology'] });
      } catch (err: unknown) {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Failed to create link';
        setLinkError(msg);
      } finally {
        setLinkLoading(false);
      }
    },
    [pendingConn, queryClient],
  );

  // Also allow opening dialog from left panel by clicking a device then another
  const [firstSelected, setFirstSelected] = useState<number | null>(null);

  const handleDeviceClick = useCallback(
    (nodeId: string) => {
      setSelectedNodeId(nodeId);
      const devId = Number(nodeId);

      if (firstSelected !== null && firstSelected !== devId) {
        // Two devices selected — open dialog
        const src = nodeMap.get(firstSelected);
        const dst = nodeMap.get(devId);
        if (src && dst) {
          setPendingConn({
            srcDeviceId: src.id,
            srcDeviceName: src.name,
            srcInterfaces: src.interfaces.length ? src.interfaces : ['eth0'],
            dstDeviceId: dst.id,
            dstDeviceName: dst.name,
            dstInterfaces: dst.interfaces.length ? dst.interfaces : ['eth0'],
          });
          setLinkError('');
        }
        setFirstSelected(null);
      } else {
        setFirstSelected(prev => prev === devId ? null : devId);
      }
    },
    [firstSelected, nodeMap],
  );

  const handleEdgeDelete = useCallback(
    async (edgeId: string) => {
      const linkId = Number(edgeId.replace('link-', ''));
      if (isNaN(linkId)) return;
      try {
        await deleteLink(linkId);
        queryClient.invalidateQueries({ queryKey: ['topology'] });
      } catch (err) {
        console.error('Failed to delete link', err);
      }
    },
    [queryClient],
  );

  // ── Layout ──────────────────────────────────────────────────────────────────

  if (isLoading) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#57606a', fontFamily: 'sans-serif' }}>Loading topology…</div>;
  }
  if (error) {
    return <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#ef4444', fontFamily: 'sans-serif' }}>Failed to load topology.</div>;
  }

  const nodes = data?.nodes ?? [];
  const links = data?.links ?? [];

  return (
    <div style={{ display: 'flex', height: '100%', fontFamily: '-apple-system, "Segoe UI", system-ui, sans-serif', fontSize: 13, color: '#1f2328' }}>

      {/* ── Left panel ── */}
      <div style={{ width: 220, minWidth: 220, borderRight: '1px solid #e5e7eb', background: '#f7f8fa', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '14px 16px 8px', fontWeight: 700, fontSize: 13, borderBottom: '1px solid #e5e7eb', flexShrink: 0 }}>
          Devices ({nodes.length})
          <div style={{ fontSize: 11, fontWeight: 400, color: '#57606a', marginTop: 3 }}>
            Click two devices to create a link
          </div>
        </div>

        {nodes.map(node => {
          const isFirst = firstSelected === node.id;
          const isSelected = selectedNodeId === String(node.id);
          return (
            <div
              key={node.id}
              onClick={() => handleDeviceClick(String(node.id))}
              style={{
                padding: '10px 16px',
                cursor: 'pointer',
                background: isFirst ? '#fef3c7' : isSelected ? '#dbeafe' : 'transparent',
                borderBottom: '1px solid #e5e7eb',
                borderLeft: isFirst ? '3px solid #f59e0b' : isSelected ? '3px solid #3b82d4' : '3px solid transparent',
                transition: 'background 0.1s',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 13 }}>{node.name}</div>
              <div style={{ color: '#57606a', fontSize: 11, fontFamily: 'monospace' }}>{node.ip_address}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 3 }}>
                <div style={{
                  width: 7, height: 7, borderRadius: '50%',
                  background: node.status === 'running' ? '#22c55e' : node.status === 'stopped' ? '#ef4444' : '#9ca3af',
                }} />
                <span style={{ fontSize: 10, color: '#57606a' }}>{node.status}</span>
              </div>
              {isFirst && <div style={{ fontSize: 10, color: '#92400e', marginTop: 3, fontStyle: 'italic' }}>Click another device to link…</div>}
            </div>
          );
        })}

        {nodes.length === 0 && (
          <div style={{ padding: 16, color: '#57606a', fontSize: 12 }}>No devices. Create devices first.</div>
        )}

        {/* Link list */}
        {links.length > 0 && (
          <>
            <div style={{ padding: '12px 16px 6px', fontWeight: 700, fontSize: 12, borderTop: '1px solid #e5e7eb', borderBottom: '1px solid #e5e7eb', color: '#374151', flexShrink: 0, marginTop: 'auto' }}>
              Links ({links.length})
            </div>
            {links.map(lnk => {
              const src = nodeMap.get(lnk.src_device_id);
              const dst = nodeMap.get(lnk.dst_device_id);
              return (
                <div key={lnk.id} style={{ padding: '7px 16px', borderBottom: '1px solid #f3f4f6', fontSize: 11 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ fontWeight: 600, color: '#1f2328' }}>{src?.name ?? `#${lnk.src_device_id}`}</div>
                      <div style={{ color: '#57606a' }}>{lnk.src_interface}</div>
                      <div style={{ color: '#9ca3af', fontSize: 10, margin: '1px 0' }}>↔</div>
                      <div style={{ fontWeight: 600, color: '#1f2328' }}>{dst?.name ?? `#${lnk.dst_device_id}`}</div>
                      <div style={{ color: '#57606a' }}>{lnk.dst_interface}</div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                      <div style={{ width: 8, height: 8, borderRadius: '50%', background: lnk.docker_network_id ? '#22c55e' : '#9ca3af' }} title={lnk.docker_network_id ? 'Docker network active' : 'No network'} />
                      <button
                        onClick={() => handleEdgeDelete(`link-${lnk.id}`)}
                        style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, border: '1px solid #fca5a5', background: '#fff', color: '#ef4444', cursor: 'pointer' }}
                        title="Remove this link"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>

      {/* ── Canvas ── */}
      <div style={{ flex: 1, position: 'relative' }}>
        <TopologyCanvas
          apiNodes={nodes}
          apiLinks={links}
          onConnect={handleConnect}
          onEdgeDelete={handleEdgeDelete}
          selectedNodeId={selectedNodeId}
        />

        {/* Keyboard hint */}
        <div style={{ position: 'absolute', bottom: 48, left: '50%', transform: 'translateX(-50%)', background: 'rgba(255,255,255,0.9)', border: '1px solid #e5e7eb', borderRadius: 6, padding: '4px 12px', fontSize: 11, color: '#57606a', pointerEvents: 'none' }}>
          Drag from a blue handle to connect · Select edge + Delete to remove
        </div>
      </div>

      {/* ── Link dialog ── */}
      {pendingConn && (
        <LinkDialog
          pending={pendingConn}
          onConfirm={handleConfirmLink}
          onCancel={() => { setPendingConn(null); setFirstSelected(null); }}
          loading={linkLoading}
          error={linkError}
        />
      )}
    </div>
  );
}

export function TopologyPage() {
  return (
    <ReactFlowProvider>
      <TopologyPageInner />
    </ReactFlowProvider>
  );
}
