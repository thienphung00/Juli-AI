const EMPHASIS_PATTERN = /(\*\*[^*]+\*\*)/g;

export function JourneyEmphasisText({ text }: { text: string }) {
  const parts = text.split(EMPHASIS_PATTERN).filter((part) => part.length > 0);

  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={index}>{part.slice(2, -2)}</strong>;
        }

        return <span key={index}>{part}</span>;
      })}
    </>
  );
}
