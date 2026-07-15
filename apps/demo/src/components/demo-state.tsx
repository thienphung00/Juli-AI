"use client";

import {
  createContext,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

export const DEMO_MODE_STORAGE_KEY = "juli_demo_mode";
export const DEMO_MUTABLE_STATE_STORAGE_KEY = "juli_demo_mutable_state";

export interface RecommendationAssistanceContext {
  evidence: string;
  risks: string;
  title: string;
  workflowKey: string;
}

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
  recommendationContext: RecommendationAssistanceContext | null;
  requestSignIn: () => void;
  resetMockState: () => void;
  setRecommendationContext: (
    context: RecommendationAssistanceContext | null,
  ) => void;
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
  const [mutableState, setMutableState] = useState<MutableMockState>(
    createDefaultMutableState,
  );
  const [recommendationContext, setRecommendationContext] =
    useState<RecommendationAssistanceContext | null>(null);

  useEffect(() => {
    localStorage.setItem(DEMO_MODE_STORAGE_KEY, "mock");
    const persistedState = localStorage.getItem(DEMO_MUTABLE_STATE_STORAGE_KEY);
    let restoreTimer: number | undefined;

    if (persistedState) {
      try {
        const restoredState = {
          ...createDefaultMutableState(),
          ...(JSON.parse(persistedState) as Partial<MutableMockState>),
        };
        restoreTimer = window.setTimeout(
          () => setMutableState(restoredState),
          0,
        );
      } catch {
        localStorage.removeItem(DEMO_MUTABLE_STATE_STORAGE_KEY);
      }
    }

    return () => {
      if (restoreTimer !== undefined) {
        window.clearTimeout(restoreTimer);
      }
    };
  }, []);

  const updateMutableState = useCallback<
    Dispatch<SetStateAction<MutableMockState>>
  >((nextState) => {
    setMutableState((current) => {
      const resolved =
        typeof nextState === "function" ? nextState(current) : nextState;

      localStorage.setItem(
        DEMO_MUTABLE_STATE_STORAGE_KEY,
        JSON.stringify(resolved),
      );
      return resolved;
    });
  }, []);

  const resetMockState = useCallback(() => {
    const defaultState = createDefaultMutableState();

    setMutableState(defaultState);
    setRecommendationContext(null);
    localStorage.setItem(DEMO_MODE_STORAGE_KEY, "mock");
    localStorage.removeItem(DEMO_MUTABLE_STATE_STORAGE_KEY);
    setFeedback(
      "Demo đã trở về trạng thái ban đầu tại Quyết định — Đề xuất.",
    );
  }, []);

  const value = useMemo<DemoStateValue>(
    () => ({
      feedback,
      mode: "mock",
      mutableState,
      recommendationContext,
      requestSignIn: () => {
        localStorage.setItem(DEMO_MODE_STORAGE_KEY, "mock");
        setFeedback(
          "Sign-in sắp ra mắt. Bạn vẫn có thể khám phá toàn bộ Demo bằng dữ liệu mẫu.",
        );
      },
      resetMockState,
      setRecommendationContext,
      updateMutableState,
    }),
    [
      feedback,
      mutableState,
      recommendationContext,
      resetMockState,
      updateMutableState,
    ],
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
