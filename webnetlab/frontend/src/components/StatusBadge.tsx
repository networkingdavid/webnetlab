interface Props {
  status: string;
}

export function StatusBadge({ status }: Props) {
  const cls =
    status === 'running'
      ? 'badge badge-running'
      : status === 'stopped'
      ? 'badge badge-stopped'
      : status === 'error'
      ? 'badge badge-error'
      : 'badge badge-unknown';

  return <span className={cls}>{status}</span>;
}
