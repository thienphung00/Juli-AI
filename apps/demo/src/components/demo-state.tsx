"use client";

import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export const DEMO_MODE_STORAGE_KEY = "juli_demo_mode";

export interface MutableMockState {
  rejectedRecommendationIds: string[];
  approvedRecommendationIds: string[];
  workflowInputs: Record<string, string>;
  executionProgress: Record<
    string,
    "needs_input" | "executing" | "completed"
  >;
  decisionsView: "recommendations" | "in-progress";
  analyticsMetric: string;
  analyticsRange: "7d" | "30d" | "90d";
  settingsDraft: Record<string, string>;
}

export const DEFAULT_MUTABLE_MOCK_STATE: MutableMockState = {
  rejectedRecommendationIds: [],
  approvedRecommendationIds: [],
  workflowInputs: {},
  executionProgress: {},
  decisionsView: "recommendations",
  analyticsMetric: "net-revenue",
  analyticsRange: "30d",
  settingsDraft: {},
};

interface DemoStateValue {
  feedback: string | null;
  mode: "mock";
  mutableState: MutableMockState;
  requestSignIn: () => void;
  resetMockState: () => void;
  updateMutableState: Dispatch<SetStateAction<MutableMockState>>;
}

const DemoStateContext = createContext<DemoStateValue | null>(null);

function createDefaultMutableState(): MutableMockState {
  return {
    ...DEFAULT_MUTABLE_MOCK_STATE,
    rejectedRecommendationIds: [],
    approvedRecommendationIds: [],
    workflowInputs: {},
    executionProgress: {},
    settingsDraft: {},
  };
}

export function DemoStateProvider({ children }: { children: ReactNode }) {
  const [feedback, setFeedback] = useState<string | null>(null);
  const [mutableState, updateMutableState] = useState<MutableMockState>(
    createDefaultMutableState,
  );

  useEffect(() => {
    localStorage.setItem(DEMO_MODE_STORAGE_KEY, "mock");
  }, []);

  const value = useMemo<DemoStateValue>(
    () => ({
      feedback,
      mode: "mock",
      mutableState,
      requestSignIn: () => {
        localStorage.setItem(DEMO_MODE_STORAGE_KEY, "mock");
        setFeedback(
          "Sign-in sắp ra mắt. Bạn vẫn có thể khám phá toàn bộ Demo bằng dữ liệu mẫu.",
        );
      },
      resetMockState: () => {
        updateMutableState(createDefaultMutableState());
        localStorage.setItem(DEMO_MODE_STORAGE_KEY, "mock");
        setFeedback(
          "Demo đã trở về trạng thái ban đầu tại Quyết định — Đề xuất.",
        );
      },
      updateMutableState,
    }),
    [feedback, mutableState],
  );

  return (
    <DemoStateContext.Provider value={value}>
      {children}
    </DemoStateContext.Provider>
  );
}

export function useDemoState(): DemoStateValue {
  const context = useContext(DemoStateContext);

  if (!context) {
    throw new Error("useDemoState must be used within DemoStateProvider");
  }

  return context;
}
