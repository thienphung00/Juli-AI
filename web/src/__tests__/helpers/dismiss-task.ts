import { screen, waitFor, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import type { TaskDismissReason } from "@/lib/task-executor/dismiss-reasons";

export async function dismissTaskWithReason(
  user: UserEvent,
  reason: TaskDismissReason,
  options?: { note?: string; dismissButton?: HTMLElement },
) {
  const dismissButton =
    options?.dismissButton ?? screen.getAllByTestId("task-dismiss")[0]!;
  await user.click(dismissButton);

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
  await user.click(screen.getAllByTestId("task-dismiss")[0]!);

  await waitFor(() => {
    expect(screen.getByTestId("task-dismiss-modal")).toBeInTheDocument();
  });

  expect(screen.getByTestId("task-dismiss-submit")).toBeDisabled();
}
