import { ReactNode } from 'react';

interface Props {
  title: string;
  open: boolean;
  onClose: () => void;
  onConfirm?: () => void;
  confirmLabel?: string;
  confirmDanger?: boolean;
  loading?: boolean;
  children: ReactNode;
}

export function Modal({
  title,
  open,
  onClose,
  onConfirm,
  confirmLabel = 'Confirm',
  confirmDanger = false,
  loading = false,
  children,
}: Props) {
  if (!open) return null;

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 200,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0,0,0,0.3)',
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div
        style={{
          background: '#fff',
          border: '1px solid var(--border)',
          borderRadius: 10,
          padding: 0,
          minWidth: 400,
          maxWidth: 540,
          width: '90vw',
          boxShadow: '0 8px 32px rgba(0,0,0,0.12)',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <span style={{ fontWeight: 700, fontSize: 15 }}>{title}</span>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              fontSize: 18,
              color: 'var(--muted)',
              lineHeight: 1,
              padding: '0 4px',
            }}
          >
            ×
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px' }}>{children}</div>

        {/* Footer */}
        {onConfirm && (
          <div
            style={{
              padding: '12px 20px',
              borderTop: '1px solid var(--border)',
              display: 'flex',
              justifyContent: 'flex-end',
              gap: 8,
            }}
          >
            <button className="btn" onClick={onClose} disabled={loading}>
              Cancel
            </button>
            <button
              className={`btn ${confirmDanger ? 'btn-danger' : 'btn-primary'}`}
              onClick={onConfirm}
              disabled={loading}
            >
              {loading ? 'Working…' : confirmLabel}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
