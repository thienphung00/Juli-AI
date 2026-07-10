"use client";

import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import type {
  TemplateControl,
  WorkflowTemplateDefinition,
  WorkflowTemplateSession,
} from "@/lib/decisions/workflow-templates";

function formatSliderValue(control: Extract<TemplateControl, { type: "slider" }>, value: number) {
  const formatted = Number.isInteger(control.step)
    ? String(Math.round(value))
    : value.toFixed(1);
  return control.unit ? `${formatted} ${control.unit}` : formatted;
}

export function WorkflowTemplateGroup({
  definition,
  values,
  onControlChange,
}: {
  definition: WorkflowTemplateDefinition;
  values: Record<string, number | boolean>;
  onControlChange: (
    workflowId: ValidatedWorkflowId,
    controlId: string,
    value: number | boolean,
  ) => void;
}) {
  const { workflowId, displayName, controls } = definition;

  return (
    <section
      className="rounded-xl border p-4"
      style={{ borderColor: "var(--border)", background: "var(--muted)" }}
      data-testid={`workflow-template-group-${workflowId}`}
      aria-labelledby={`workflow-template-title-${workflowId}`}
    >
      <h3
        id={`workflow-template-title-${workflowId}`}
        className="text-sm font-semibold"
        style={{ color: "var(--foreground)" }}
      >
        {displayName}
      </h3>

      <ul className="mt-3 space-y-4">
        {controls.map((control) => (
          <li key={control.id}>
            {control.type === "slider" ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <label
                    htmlFor={`template-${workflowId}-${control.id}`}
                    className="text-sm"
                    style={{ color: "var(--foreground)" }}
                  >
                    {control.label}
                  </label>
                  <span
                    className="shrink-0 text-xs font-medium tabular-nums"
                    style={{ color: "var(--muted-foreground)" }}
                    data-testid={`template-value-${workflowId}-${control.id}`}
                  >
                    {formatSliderValue(control, values[control.id] as number)}
                  </span>
                </div>
                {control.description ? (
                  <p className="text-xs" style={{ color: "var(--muted-foreground)" }}>
                    {control.description}
                  </p>
                ) : null}
                <input
                  id={`template-${workflowId}-${control.id}`}
                  type="range"
                  min={control.min}
                  max={control.max}
                  step={control.step}
                  value={values[control.id] as number}
                  data-testid={`template-control-${workflowId}-${control.id}`}
                  className="w-full accent-[var(--primary)]"
                  onChange={(event) =>
                    onControlChange(workflowId, control.id, Number(event.target.value))
                  }
                />
              </div>
            ) : (
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <label
                    htmlFor={`template-${workflowId}-${control.id}`}
                    className="text-sm"
                    style={{ color: "var(--foreground)" }}
                  >
                    {control.label}
                  </label>
                  {control.description ? (
                    <p className="mt-0.5 text-xs" style={{ color: "var(--muted-foreground)" }}>
                      {control.description}
                    </p>
                  ) : null}
                </div>
                <input
                  id={`template-${workflowId}-${control.id}`}
                  type="checkbox"
                  role="switch"
                  checked={values[control.id] as boolean}
                  data-testid={`template-control-${workflowId}-${control.id}`}
                  className="mt-1 h-5 w-9 shrink-0 cursor-pointer accent-[var(--primary)]"
                  onChange={(event) =>
                    onControlChange(workflowId, control.id, event.target.checked)
                  }
                />
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
