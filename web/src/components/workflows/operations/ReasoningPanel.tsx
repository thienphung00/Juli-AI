import type { WorkflowReasoning } from "@/lib/operations/reasoning";

export function ReasoningPanel({ reasoning }: { reasoning: WorkflowReasoning }) {
  return (
    <div
      className="mt-3 space-y-3 border-t pt-3"
      style={{ borderColor: "var(--border)" }}
      data-testid="reasoning-panel"
    >
      <section data-testid="reasoning-why">
        <h4 className="text-muted text-xs font-semibold uppercase tracking-wide">Tại sao</h4>
        <p className="mt-1 text-sm">{reasoning.why}</p>
      </section>

      <section data-testid="reasoning-impact">
        <h4 className="text-muted text-xs font-semibold uppercase tracking-wide">
          Tác động dự kiến
        </h4>
        <p className="mt-1 text-sm">{reasoning.expected_impact}</p>
      </section>

      <section data-testid="reasoning-next-steps">
        <h4 className="text-muted text-xs font-semibold uppercase tracking-wide">
          Bước tiếp theo
        </h4>
        <ol className="mt-1 list-decimal space-y-1 pl-4 text-sm">
          {reasoning.next_steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <p className="text-muted text-xs" data-testid="reasoning-copy-source">
        Nguồn: quy tắc ({reasoning.copy_source})
      </p>
    </div>
  );
}
