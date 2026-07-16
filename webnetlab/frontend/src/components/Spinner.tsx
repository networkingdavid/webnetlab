interface Props {
  size?: number;
}

export function Spinner({ size = 20 }: Props) {
  return (
    <span
      className="spinner"
      style={{ width: size, height: size }}
      role="status"
      aria-label="Loading"
    />
  );
}
