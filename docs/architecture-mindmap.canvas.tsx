import { computeDAGLayout, useHostTheme, H1, Text } from 'cursor/canvas';
import { useMemo, useState } from 'react';

type NodeData = {
  id: string;
  label: string;
  level: number;
  category?: string;
};

const nodes: NodeData[] = [
  { id: 'root', label: 'AI POS System', level: 0 },

  { id: 'philosophy', label: 'Core Philosophy', level: 1, category: 'philosophy' },
  { id: 'layer1', label: '1. API & Connector Layer', level: 1, category: 'api' },
  { id: 'layer2', label: '2. AI Gateway Layer', level: 1, category: 'gateway' },
  { id: 'layer3', label: '3. Hybrid AI Model Layer', level: 1, category: 'model' },
  { id: 'layer4', label: '4. Interface Layer', level: 1, category: 'interface' },
  { id: 'layer5', label: '5. Caching Layer', level: 1, category: 'cache' },
  { id: 'layer6', label: '6. Data Architecture', level: 1, category: 'data' },
  { id: 'layer7', label: '7. Load Balancing & Hosting', level: 1, category: 'hosting' },
  { id: 'layer8', label: '8. Automation & Monitoring', level: 1, category: 'automation' },

  { id: 'ph1', label: 'Data Infrastructure + Operational Intelligence + AI Workflow', level: 2, category: 'philosophy' },
  { id: 'ph2', label: 'Event-driven (not Request-driven)', level: 2, category: 'philosophy' },

  { id: 'l1_goal', label: 'Normalized data integrations & event infra', level: 2, category: 'api' },
  { id: 'l1_design', label: 'Connector-Based Design (KiotViet, GrabFood...)', level: 2, category: 'api' },
  { id: 'l1_why', label: 'Normalization prevents tech debt', level: 2, category: 'api' },
  { id: 'l1_tech', label: 'FastAPI + Celery + Redis + SQLAlchemy', level: 2, category: 'api' },

  { id: 'l2_tool', label: 'LiteLLM', level: 2, category: 'gateway' },
  { id: 'l2_benefits', label: 'Model abstraction, retries, fallback, cost tracking', level: 2, category: 'gateway' },

  { id: 'l3_t1', label: 'Tier 1: Gemini Flash (90-95% requests)', level: 2, category: 'model' },
  { id: 'l3_t2', label: 'Tier 2: Claude/GPT-4o (complex reasoning)', level: 2, category: 'model' },
  { id: 'l3_t3', label: 'Tier 3: Ollama/vLLM (local embeddings)', level: 2, category: 'model' },

  { id: 'l4_dash', label: 'A. AI Dashboard (summaries, alerts)', level: 2, category: 'interface' },
  { id: 'l4_work', label: 'B. Guided AI Workflows (pre-packaged skills)', level: 2, category: 'interface' },
  { id: 'l4_chat', label: 'C. Chat (secondary interface only)', level: 2, category: 'interface' },
  { id: 'l4_tech', label: 'Next.js + shadcn/ui + Supabase + Recharts', level: 2, category: 'interface' },

  { id: 'l5_goal', label: 'Reduce AI costs 50-80%', level: 2, category: 'cache' },
  { id: 'l5_what', label: 'Cache: API responses, AI outputs, prompts', level: 2, category: 'cache' },
  { id: 'l5_tools', label: 'Redis + LiteLLM cache + PostgreSQL', level: 2, category: 'cache' },

  { id: 'l6_pg', label: 'PostgreSQL (orders, analytics, workflows)', level: 2, category: 'data' },
  { id: 'l6_redis', label: 'Redis (cache, queues, sessions)', level: 2, category: 'data' },
  { id: 'l6_r2', label: 'Cloudflare R2 (exports, logs, AI artifacts)', level: 2, category: 'data' },

  { id: 'l7_rule', label: 'Do NOT overengineer (no K8s at MVP)', level: 2, category: 'hosting' },
  { id: 'l7_mvp', label: 'MVP: Railway (fast deploy, autoscale)', level: 2, category: 'hosting' },
  { id: 'l7_scale', label: 'Scale: Hetzner VPS (cost-effective)', level: 2, category: 'hosting' },
  { id: 'l7_flow', label: 'Cloudflare → Nginx → FastAPI → Redis', level: 2, category: 'hosting' },

  { id: 'l8_rule', label: 'No autonomous AI deployments at MVP', level: 2, category: 'automation' },
  { id: 'l8_workflow', label: 'Sentry → Cursor analyzes → Draft PR → Human Review', level: 2, category: 'automation' },
  { id: 'l8_stack', label: 'Grafana Loki + Prometheus + Langfuse + Sentry', level: 2, category: 'automation' },
];

const edges = [
  { from: 'root', to: 'philosophy' },
  { from: 'root', to: 'layer1' },
  { from: 'root', to: 'layer2' },
  { from: 'root', to: 'layer3' },
  { from: 'root', to: 'layer4' },
  { from: 'root', to: 'layer5' },
  { from: 'root', to: 'layer6' },
  { from: 'root', to: 'layer7' },
  { from: 'root', to: 'layer8' },

  { from: 'philosophy', to: 'ph1' },
  { from: 'philosophy', to: 'ph2' },

  { from: 'layer1', to: 'l1_goal' },
  { from: 'layer1', to: 'l1_design' },
  { from: 'layer1', to: 'l1_why' },
  { from: 'layer1', to: 'l1_tech' },

  { from: 'layer2', to: 'l2_tool' },
  { from: 'layer2', to: 'l2_benefits' },

  { from: 'layer3', to: 'l3_t1' },
  { from: 'layer3', to: 'l3_t2' },
  { from: 'layer3', to: 'l3_t3' },

  { from: 'layer4', to: 'l4_dash' },
  { from: 'layer4', to: 'l4_work' },
  { from: 'layer4', to: 'l4_chat' },
  { from: 'layer4', to: 'l4_tech' },

  { from: 'layer5', to: 'l5_goal' },
  { from: 'layer5', to: 'l5_what' },
  { from: 'layer5', to: 'l5_tools' },

  { from: 'layer6', to: 'l6_pg' },
  { from: 'layer6', to: 'l6_redis' },
  { from: 'layer6', to: 'l6_r2' },

  { from: 'layer7', to: 'l7_rule' },
  { from: 'layer7', to: 'l7_mvp' },
  { from: 'layer7', to: 'l7_scale' },
  { from: 'layer7', to: 'l7_flow' },

  { from: 'layer8', to: 'l8_rule' },
  { from: 'layer8', to: 'l8_workflow' },
  { from: 'layer8', to: 'l8_stack' },
];

const categoryColors: Record<string, string> = {
  philosophy: '#8b5cf6',
  api: '#3b82f6',
  gateway: '#06b6d4',
  model: '#10b981',
  interface: '#f59e0b',
  cache: '#ef4444',
  data: '#ec4899',
  hosting: '#6366f1',
  automation: '#14b8a6',
};

function MindmapNode({ node, data, theme, collapsed, onToggle }: {
  node: { id: string; x: number; y: number };
  data: NodeData;
  theme: ReturnType<typeof useHostTheme>;
  collapsed: boolean;
  onToggle?: () => void;
}) {
  const isRoot = data.level === 0;
  const isCategory = data.level === 1;
  const color = data.category ? categoryColors[data.category] : theme.accent.primary;

  const width = isRoot ? 160 : isCategory ? 240 : 320;
  const height = isRoot ? 48 : isCategory ? 36 : 30;

  const bg = isRoot
    ? theme.accent.primary
    : isCategory
      ? `${color}22`
      : theme.bg.elevated;

  const border = isRoot
    ? 'none'
    : isCategory
      ? `2px solid ${color}`
      : `1px solid ${theme.stroke.secondary}`;

  const textColor = isRoot
    ? theme.text.onAccent
    : isCategory
      ? color
      : theme.text.primary;

  const fontSize = isRoot ? 14 : isCategory ? 12 : 11;
  const fontWeight = isRoot ? 700 : isCategory ? 600 : 400;

  return (
    <g>
      <foreignObject
        x={node.x}
        y={node.y}
        width={width}
        height={height}
      >
        <div
          style={{
            width: '100%',
            height: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: isRoot ? 'center' : 'flex-start',
            padding: '0 10px',
            borderRadius: isRoot ? 8 : 6,
            background: bg,
            border,
            cursor: isCategory ? 'pointer' : 'default',
            userSelect: 'none',
            boxSizing: 'border-box',
            overflow: 'hidden',
          }}
          onClick={onToggle}
        >
          {isCategory && (
            <span style={{
              marginRight: 6,
              fontSize: 10,
              color,
              transform: collapsed ? 'rotate(-90deg)' : 'rotate(0deg)',
              transition: 'transform 0.2s',
              display: 'inline-block',
            }}>
              ▼
            </span>
          )}
          <span style={{
            color: textColor,
            fontSize,
            fontWeight,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            fontFamily: '-apple-system, BlinkMacSystemFont, sans-serif',
          }}>
            {data.label}
          </span>
        </div>
      </foreignObject>
    </g>
  );
}

export default function AIPOSArchitectureMindmap() {
  const theme = useHostTheme();
  const [collapsedCategories, setCollapsedCategories] = useState<Record<string, boolean>>({});

  const toggleCategory = (id: string) => {
    setCollapsedCategories(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const visibleData = useMemo(() => {
    const collapsedParents = new Set(
      Object.entries(collapsedCategories)
        .filter(([, v]) => v)
        .map(([k]) => k)
    );

    const visibleNodes = nodes.filter(n => {
      if (n.level <= 1) return true;
      const parentEdge = edges.find(e => e.to === n.id);
      if (!parentEdge) return true;
      return !collapsedParents.has(parentEdge.from);
    });

    const visibleNodeIds = new Set(visibleNodes.map(n => n.id));
    const visibleEdges = edges.filter(
      e => visibleNodeIds.has(e.from) && visibleNodeIds.has(e.to)
    );

    return { nodes: visibleNodes, edges: visibleEdges };
  }, [collapsedCategories]);

  const layout = useMemo(() => {
    return computeDAGLayout({
      nodes: visibleData.nodes.map(n => ({ id: n.id })),
      edges: visibleData.edges,
      direction: 'horizontal',
      nodeWidth: 240,
      nodeHeight: 36,
      rankGap: 80,
      nodeGap: 12,
      padding: 40,
    });
  }, [visibleData]);

  const nodeDataMap = useMemo(() => {
    const map: Record<string, NodeData> = {};
    nodes.forEach(n => { map[n.id] = n; });
    return map;
  }, []);

  const getNodeWidth = (id: string) => {
    const data = nodeDataMap[id];
    if (!data) return 240;
    if (data.level === 0) return 160;
    if (data.level === 1) return 240;
    return 320;
  };

  const getNodeHeight = (id: string) => {
    const data = nodeDataMap[id];
    if (!data) return 36;
    if (data.level === 0) return 48;
    if (data.level === 1) return 36;
    return 30;
  };

  return (
    <div style={{ padding: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <H1>AI POS System Architecture</H1>
        <Text tone="secondary" size="small">
          Click category nodes to expand/collapse branches
        </Text>
      </div>
      <div style={{
        overflow: 'auto',
        border: `1px solid ${theme.stroke.tertiary}`,
        borderRadius: 8,
        background: theme.bg.editor,
      }}>
        <svg
          width={Math.max(layout.width + 200, 900)}
          height={Math.max(layout.height + 40, 500)}
          style={{ display: 'block' }}
        >
          {layout.edges.map((edge, i) => {
            const fromNode = layout.nodes.find(n => n.id === edge.from);
            const toNode = layout.nodes.find(n => n.id === edge.to);
            if (!fromNode || !toNode) return null;

            const fromWidth = getNodeWidth(edge.from);
            const fromHeight = getNodeHeight(edge.from);
            const toHeight = getNodeHeight(edge.to);

            const x1 = fromNode.x + fromWidth;
            const y1 = fromNode.y + fromHeight / 2;
            const x2 = toNode.x;
            const y2 = toNode.y + toHeight / 2;

            const midX = (x1 + x2) / 2;
            const path = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;

            const category = nodeDataMap[edge.from]?.category || nodeDataMap[edge.to]?.category;
            const color = category ? categoryColors[category] : theme.stroke.secondary;

            return (
              <path
                key={i}
                d={path}
                fill="none"
                stroke={color}
                strokeWidth={nodeDataMap[edge.from]?.level === 0 ? 2 : 1.5}
                opacity={0.6}
              />
            );
          })}

          {layout.nodes.map((layoutNode) => {
            const data = nodeDataMap[layoutNode.id];
            if (!data) return null;
            const isCategory = data.level === 1;
            return (
              <MindmapNode
                key={layoutNode.id}
                node={layoutNode}
                data={data}
                theme={theme}
                collapsed={!!collapsedCategories[layoutNode.id]}
                onToggle={isCategory ? () => toggleCategory(layoutNode.id) : undefined}
              />
            );
          })}
        </svg>
      </div>
      <div style={{ marginTop: 12 }}>
        <Text tone="tertiary" size="small">
          Architecture: Event-driven data infrastructure with AI workflow automation
        </Text>
      </div>
    </div>
  );
}
