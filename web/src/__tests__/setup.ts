import "@testing-library/jest-dom";
import {
  WORKSPACE_MODE_STORAGE_KEY,
  applyWorkspaceTheme,
} from "@/lib/workspace-mode";
import { clearTaskExecutorSession } from "@/lib/task-executor";

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn(), back: jest.fn() }),
  usePathname: () => "/",
}));

beforeEach(() => {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  applyWorkspaceTheme("seller");
});

afterEach(() => {
  clearTaskExecutorSession();
});
