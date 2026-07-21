"use client";

import { Badge, Card, CardBody, CardHeader, CardTitle } from "@juli/ui";
import Link from "next/link";

import {
  groupWorkflowTemplatesByDomain,
  type WorkflowTemplateDefinition,
} from "../lib/settings";

function capabilityVariant(
  status: WorkflowTemplateDefinition["capabilityStatus"],
) {
  if (status === "supported") {
    return "success" as const;
  }

  if (status === "partial") {
    return "warning" as const;
  }

  return "info" as const;
}

export function SettingsWorkflowList() {
  const groupedTemplates = groupWorkflowTemplatesByDomain();

  return (
    <div className="settings-workflows">
      {groupedTemplates.map((group) => (
        <section
          aria-label={group.label}
          className="settings-workflows__domain"
          key={group.id}
          role="region"
        >
          <h2 className="settings-workflows__domain-title">{group.label}</h2>
          <ul className="settings-workflows__list">
            {group.templates.map((template) => (
              <li key={template.workflowKey}>
                <Card
                  className="settings-workflows__card"
                  data-testid={`settings-workflow-row-${template.workflowKey}`}
                  data-workflow-key={template.workflowKey}
                >
                  <CardHeader>
                    <CardTitle>{template.displayName}</CardTitle>
                    <Badge variant={capabilityVariant(template.capabilityStatus)}>
                      {template.capabilityBadge}
                    </Badge>
                  </CardHeader>
                  <CardBody>
                    <p className="settings-workflows__meta">
                      <span className="settings-workflows__key">
                        {template.workflowKey}
                      </span>
                      <span aria-hidden="true"> · </span>
                      <span>{template.toolName}</span>
                    </p>
                    <Link
                      className="settings-workflows__link"
                      href={`/settings/workflows/${template.workflowKey}`}
                    >
                      Chỉnh sửa mặc định
                    </Link>
                  </CardBody>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
