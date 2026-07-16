import { Modal } from './Modal';

interface Props {
  open: boolean;
  title?: string;
  message?: string;
  onClose: () => void;
  onConfirm: () => void;
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  title = 'Confirm deletion',
  message = 'This action cannot be undone.',
  onClose,
  onConfirm,
  loading = false,
}: Props) {
  return (
    <Modal
      title={title}
      open={open}
      onClose={onClose}
      onConfirm={onConfirm}
      confirmLabel="Delete"
      confirmDanger
      loading={loading}
    >
      <p style={{ color: 'var(--muted)', fontSize: 13 }}>{message}</p>
    </Modal>
  );
}
