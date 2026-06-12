import { screen, waitFor, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import type { TaskDismissReason } from "@/lib/task-executor/dismiss-reasons";

async function openDismissAction(
  user: UserEvent,
  options?: { dismissButton?: HTMLElement },
) {
  if (options?.dismissButton) {
    const card = options.dismissButton.closest('[data-testid="task-card"]');
    const moreMenu = card
      ? within(card as HTMLElement).queryByTestId("task-more-menu")
      : screen.queryByTestId("task-more-menu");

    if (moreMenu) {
      await user.click(moreMenu);
    }

    await user.click(options.dismissButton);
    return;
  }

  const moreMenus = screen.getAllByTestId("task-more-menu");
  await user.click(moreMenus[0]!);
  const dismissButtons = screen.getAllByTestId("task-dismiss");
  await user.click(dismissButtons[0]!);
}

export async function dismissTaskWithReason(
  user: UserEvent,
  reason: TaskDismissReason,
  options?: { note?: string; dismissButton?: HTMLElement },
) {
  await openDismissAction(user, options);

  await waitFor(() => {
    expect(screen.getByTestId("task-dismiss-modal")).toBeInTheDocument();
  });

  await user.click(screen.getByTestId(`task-dismiss-reason-${reason}`));

  if (reason === "other" && options?.note) {
    await user.type(screen.getByTestId("task-dismiss-note"), options.note);
  }

  const submit = screen.getByTestId("task-dismiss-submit");
  await waitFor(() => {
    expect(submit).toBeEnabled();
  });
  await user.click(submit);

  await waitFor(() => {
    expect(screen.queryByTestId("task-dismiss-modal")).not.toBeInTheDocument();
  });
}

export async function expectDismissBlockedWithoutReason(user: UserEvent) {
  await openDismissAction(user);

  await waitFor(() => {
    expect(screen.getByTestId("task-dismiss-modal")).toBeInTheDocument();
  });

  expect(screen.getByTestId("task-dismiss-submit")).toBeDisabled();
}
