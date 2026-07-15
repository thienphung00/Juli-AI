interface DestinationPlaceholderProps {
  description: string;
  title: string;
}

export function DestinationPlaceholder({
  description,
  title,
}: DestinationPlaceholderProps) {
  return (
    <section className="demo-placeholder">
      <p className="demo-kicker">Bản xem trước</p>
      <h1>{title}</h1>
      <p>{description}</p>
    </section>
  );
}
