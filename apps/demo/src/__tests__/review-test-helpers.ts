import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

export async function confirmApproveThroughGate(
  user: ReturnType<typeof userEvent.setup>,
) {
  await user.click(screen.getByRole("button", { name: "Phê duyệt" }));
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Phê duyệt" }));
}
