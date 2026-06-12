import "@testing-library/jest-dom";
import {
  WORKSPACE_MODE_STORAGE_KEY,
  applyWorkspaceTheme,
} from "@/lib/workspace-mode";
import { clearTaskExecutorSession } from "@/lib/task-executor";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: jest.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
});

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn(), push: jest.fn(), back: jest.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
  useParams: () => ({}),
}));

beforeEach(() => {
  localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "seller");
  applyWorkspaceTheme("seller");
});

afterEach(() => {
  clearTaskExecutorSession();
});
