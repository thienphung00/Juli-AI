import type { WorkspaceMode } from "@/lib/workspace-mode";

export interface ChatActionLink {
  label: string;
  href: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  actions?: ChatActionLink[];
  confidence?: number;
  data_sources?: string[];
}

export interface MockAiChatData {
  suggested_prompts: Record<WorkspaceMode, string[]>;
  welcome: Record<WorkspaceMode, string>;
  mock_conversation: ChatMessage[];
}

export const MOCK_AI_CHAT: MockAiChatData = {
  suggested_prompts: {
    seller: [
      "Creator nào nên đẩy tối nay?",
      "SKU nào sắp hết hàng?",
      "Livestream nào hiệu quả nhất tuần này?",
      "Đối thủ nào đang tăng hoa hồng cho creator?",
    ],
    affiliate: [
      "Sản phẩm nào đang xu hướng trước khi bão hòa?",
      "Shop nào chấp nhận creator mới như tôi?",
      "Format livestream nào chuyển đổi tốt nhất?",
      "Sản phẩm nào phù hợp nhất với audience của tôi?",
    ],
  },
  welcome: {
    seller:
      "Xin chào! Mình là Juli — AI vận hành cửa hàng của bạn. Hỏi mình về creator, tồn kho, livestream hay đối thủ nhé.",
    affiliate:
      "Xin chào! Mình là Juli — trợ lý affiliate của bạn. Hỏi mình về sản phẩm xu hướng, shop phù hợp hay chiến lược livestream nhé.",
  },
  mock_conversation: [
    {
      id: "seed-user-1",
      role: "user",
      content: "Creator nào chuyển đổi tốt nhất với son môi?",
      timestamp: "2026-05-27T20:01:00+07:00",
    },
    {
      id: "seed-assistant-1",
      role: "assistant",
      content:
        "@linh.nhi.beauty là creator tốt nhất cho son môi hiện tại — tỷ lệ chuyển đổi 8,3% (+42% so với trung bình), refund rate chỉ 0,9%. Hôm nay họ đã sẵn sàng livestream lúc 20:00.",
      actions: [
        { label: "Nhắn tin ngay", href: "/operation?section=creators&id=creator-linh-nhi" },
      ],
      timestamp: "2026-05-27T20:01:02+07:00",
      confidence: 0.91,
      data_sources: ["src/intelligence/scoring", "src/recommendations"],
    },
  ],
};

const KEYWORD_REPLIES: Record<
  WorkspaceMode,
  Array<{ match: RegExp; reply: Omit<ChatMessage, "id" | "role" | "timestamp"> }>
> = {
  seller: [
    {
      match: /creator|đẩy|chuyển đổi/i,
      reply: {
        content:
          "@linh.nhi.beauty đang có tỷ lệ chuyển đổi cao nhất (8,3%) cho danh mục làm đẹp. Khuyến nghị nhắn tin trước khung giờ vàng 20:00.",
        actions: [
          { label: "Xem creator", href: "/operation?section=creators&id=creator-linh-nhi" },
        ],
        confidence: 0.88,
      },
    },
    {
      match: /sku|tồn kho|hết hàng/i,
      reply: {
        content:
          "Serum Vitamin C 20ml chỉ còn 12 đơn vị (dưới ngưỡng 15). Đặt hàng bổ sung trong 48 giờ để tránh hết hàng cuối tuần.",
        actions: [{ label: "Xem tồn kho", href: "/operation?section=inventory" }],
        confidence: 0.85,
      },
    },
    {
      match: /livestream|stream/i,
      reply: {
        content:
          "Livestream tối thứ Tư đạt GMV 42,5 triệu ₫ — cao nhất tuần này. Khung giờ 20:00–22:00 có retention tốt nhất.",
        actions: [{ label: "Xem livestream", href: "/livestreams" }],
        confidence: 0.82,
      },
    },
  ],
  affiliate: [
    {
      match: /xu hướng|trending|sản phẩm/i,
      reply: {
        content:
          "Kem chống nắng SPF50+ đang tăng 34% tuần này — hoa hồng 18% từ BeautyShop VN. Phù hợp audience skincare 18–34.",
        actions: [{ label: "Khám phá xu hướng", href: "/trends" }],
        confidence: 0.86,
      },
    },
    {
      match: /shop|creator mới/i,
      reply: {
        content:
          "GlowLab VN đang mở chương trình creator mới — hoa hồng 15% + bonus 500k cho 3 đơn đầu. Yêu cầu tối thiểu 5k followers.",
        actions: [{ label: "Xem shop", href: "/trends" }],
        confidence: 0.8,
      },
    },
    {
      match: /livestream|format|chuyển đổi/i,
      reply: {
        content:
          "Format 'demo + flash sale 15 phút' có conversion cao nhất (6,2%) trong niche làm đẹp. Thử áp dụng vào stream tối nay.",
        actions: [{ label: "Gợi ý nội dung", href: "/operation" }],
        confidence: 0.79,
      },
    },
  ],
};

const DEFAULT_REPLIES: Record<WorkspaceMode, string> = {
  seller:
    "Mình đang phân tích dữ liệu shop realtime. Bạn có thể hỏi về creator hiệu quả, tồn kho sắp hết, hoặc livestream tuần này.",
  affiliate:
    "Mình đang theo dõi xu hướng affiliate. Bạn có thể hỏi về sản phẩm hot, shop phù hợp, hoặc chiến lược livestream.",
};

let messageCounter = 0;

export function nextMessageId(prefix: string): string {
  messageCounter += 1;
  return `${prefix}-${messageCounter}-${Date.now()}`;
}

export function buildMockAssistantReply(
  mode: WorkspaceMode,
  userText: string
): ChatMessage {
  const rules = KEYWORD_REPLIES[mode];
  const matched = rules.find((rule) => rule.match.test(userText));

  const base = matched?.reply ?? { content: DEFAULT_REPLIES[mode], confidence: 0.7 };

  return {
    id: nextMessageId("assistant"),
    role: "assistant",
    content: base.content,
    timestamp: new Date().toISOString(),
    actions: base.actions,
    confidence: base.confidence,
  };
}

export function getMockSuggestedPrompts(mode: WorkspaceMode): string[] {
  return MOCK_AI_CHAT.suggested_prompts[mode];
}

export function getMockWelcome(mode: WorkspaceMode): string {
  return MOCK_AI_CHAT.welcome[mode];
}

export function getMockSeedMessages(): ChatMessage[] {
  return MOCK_AI_CHAT.mock_conversation.map((msg) => ({ ...msg }));
}
