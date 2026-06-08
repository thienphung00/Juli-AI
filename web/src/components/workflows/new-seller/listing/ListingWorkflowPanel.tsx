"use client";

import { useEffect, useState } from "react";
import { formatVND } from "@/lib/format";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";
import { useListingWorkflow } from "@/lib/workflows/new-seller/listing/use-listing-workflow";
import type { ListingPath } from "@/lib/workflows/new-seller/listing/state-machine";

const DEFAULT_CONSTRAINTS = {
  category: "Mỹ phẩm",
  maxCapitalVnd: 20_000_000,
  dropshipOnly: true,
};

export function ListingWorkflowPanel({
  personaId,
  onClose,
}: {
  personaId: PersonaId;
  onClose: () => void;
}) {
  const persona = loadPersona(personaId);
  const workflow = useListingWorkflow({
    personaId,
    shopId: persona.profile.shop_id,
  });

  const { state } = workflow;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      data-testid="listing-workflow"
      role="dialog"
      aria-modal="true"
      aria-labelledby="listing-workflow-title"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/50"
        aria-label="Đóng quy trình đăng sản phẩm"
        onClick={onClose}
      />
      <div
        className="card relative z-10 flex max-h-[90vh] w-full max-w-lg flex-col overflow-hidden"
        data-testid={`listing-step-${state.step}`}
      >
        <header className="border-b px-4 py-3" style={{ borderColor: "var(--border)" }}>
          <div className="flex items-center justify-between gap-2">
            <h2
              id="listing-workflow-title"
              className="text-base font-bold"
              style={{ color: "var(--foreground)" }}
            >
              Quy trình đăng sản phẩm
            </h2>
            <button
              type="button"
              className="text-sm"
              style={{ color: "var(--muted-foreground)" }}
              data-testid="listing-close"
              onClick={onClose}
            >
              Đóng
            </button>
          </div>
          <p className="text-muted mt-1 text-xs">
            Bước hiện tại: {stepLabel(state.step)}
          </p>
        </header>

        <div className="flex-1 overflow-y-auto p-4">
          {state.step === "path_selection" && (
            <PathSelectionStep onSelectPath={workflow.choosePath} />
          )}
          {state.step === "product_form" && (
            <ProductFormStep onSave={workflow.saveProductForm} initial={state.productForm} />
          )}
          {state.step === "constraints" && (
            <ConstraintsStep
              onSave={workflow.saveConstraints}
              initial={state.constraints}
            />
          )}
          {state.step === "opportunity_browse" && (
            <OpportunityBrowseStep
              opportunities={workflow.filteredOpportunities}
              selectedId={state.selectedOpportunityId}
              onSelect={workflow.pickOpportunity}
            />
          )}
          {state.step === "distributor_pick" && (
            <DistributorPickStep
              distributors={workflow.distributors}
              selectedId={state.selectedDistributorId}
              onSelect={workflow.pickDistributor}
              suggestedIds={
                state.path === "path_b" && workflow.selectedOpportunity
                  ? workflow.selectedOpportunity.suggested_supplier_ids
                  : undefined
              }
            />
          )}
          {state.step === "draft_review" && state.draft && (
            <DraftReviewStep draft={state.draft} />
          )}
          {state.step === "export_placeholder" && (
            <ExportPlaceholderStep productName={state.draft?.product_info.product_name} />
          )}
        </div>

        <footer
          className="flex gap-2 border-t px-4 py-3"
          style={{ borderColor: "var(--border)" }}
        >
          {workflow.canGoBack && (
            <button
              type="button"
              className="btn-secondary flex-1"
              data-testid="listing-back"
              onClick={workflow.goBack}
            >
              Quay lại
            </button>
          )}
          {state.step !== "export_placeholder" && state.step !== "path_selection" && (
            <button
              type="button"
              className="btn-primary flex-1"
              data-testid="listing-next"
              disabled={!workflow.canAdvanceFromStep()}
              onClick={workflow.goNext}
            >
              Tiếp theo
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}

function stepLabel(step: string): string {
  const labels: Record<string, string> = {
    path_selection: "Chọn lộ trình",
    product_form: "Thông tin sản phẩm",
    constraints: "Tiêu chí tìm cơ hội",
    opportunity_browse: "Duyệt cơ hội",
    distributor_pick: "Chọn nhà phân phối",
    draft_review: "Xem bản nháp",
    export_placeholder: "Xuất bản",
  };
  return labels[step] ?? step;
}

function PathSelectionStep({
  onSelectPath,
}: {
  onSelectPath: (path: ListingPath) => void;
}) {
  return (
    <div className="space-y-3" data-testid="listing-path-selection">
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        Bạn đã có nhà phân phối hay muốn khám phá cơ hội mới?
      </p>
      <button
        type="button"
        className="card w-full p-4 text-left"
        data-testid="listing-path-a"
        onClick={() => onSelectPath("path_a")}
      >
        <p className="font-medium">Lộ trình A — Đã có nhà phân phối</p>
        <p className="text-muted mt-1 text-sm">Nhập thông tin sản phẩm và chọn nhà cung cấp quen thuộc.</p>
      </button>
      <button
        type="button"
        className="card w-full p-4 text-left"
        data-testid="listing-path-b"
        onClick={() => onSelectPath("path_b")}
      >
        <p className="font-medium">Lộ trình B — Khám phá cơ hội</p>
        <p className="text-muted mt-1 text-sm">Lọc cơ hội theo vốn và danh mục, rồi chọn nhà phân phối phù hợp.</p>
      </button>
    </div>
  );
}

function ProductFormStep({
  onSave,
  initial,
}: {
  onSave: (form: {
    product_name: string;
    category: string;
    price: number;
    brand?: string;
    description?: string;
  }) => void;
  initial: {
    product_name: string;
    category: string;
    price: number;
    brand?: string;
    description?: string;
  } | null;
}) {
  const [productName, setProductName] = useState(
    initial?.product_name ?? "Serum Vitamin C 20ml",
  );
  const [category, setCategory] = useState(initial?.category ?? "Mỹ phẩm");
  const [price, setPrice] = useState(String(initial?.price ?? 189_000));
  const [brand, setBrand] = useState(initial?.brand ?? "Mai Linh Beauty");
  const [description, setDescription] = useState(
    initial?.description ??
      "Serum vitamin C giúp làm sáng da và giảm thâm nám.",
  );

  useEffect(() => {
    const parsedPrice = Number(price);
    if (productName.trim() && category.trim() && parsedPrice > 0) {
      onSave({
        product_name: productName.trim(),
        category: category.trim(),
        price: parsedPrice,
        brand: brand.trim() || undefined,
        description: description.trim() || undefined,
      });
    }
  }, [productName, category, price, brand, description, onSave]);

  return (
    <form className="space-y-3" data-testid="listing-product-form" onSubmit={(e) => e.preventDefault()}>
      <label className="block text-sm">
        Tên sản phẩm
        <input
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)" }}
          data-testid="listing-product-name"
          value={productName}
          onChange={(e) => setProductName(e.target.value)}
        />
      </label>
      <label className="block text-sm">
        Danh mục
        <input
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)" }}
          data-testid="listing-product-category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        />
      </label>
      <label className="block text-sm">
        Giá bán (VND)
        <input
          type="number"
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)" }}
          data-testid="listing-product-price"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
        />
      </label>
      <label className="block text-sm">
        Thương hiệu
        <input
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)" }}
          value={brand}
          onChange={(e) => setBrand(e.target.value)}
        />
      </label>
      <label className="block text-sm">
        Mô tả
        <textarea
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)" }}
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </label>
    </form>
  );
}

function ConstraintsStep({
  onSave,
  initial,
}: {
  onSave: (constraints: typeof DEFAULT_CONSTRAINTS) => void;
  initial: typeof DEFAULT_CONSTRAINTS | null;
}) {
  const [category, setCategory] = useState(initial?.category ?? DEFAULT_CONSTRAINTS.category);
  const [maxCapital, setMaxCapital] = useState(
    String(initial?.maxCapitalVnd ?? DEFAULT_CONSTRAINTS.maxCapitalVnd),
  );
  const [dropshipOnly, setDropshipOnly] = useState(
    initial?.dropshipOnly ?? DEFAULT_CONSTRAINTS.dropshipOnly,
  );

  useEffect(() => {
    const parsed = Number(maxCapital);
    if (category.trim() && parsed > 0) {
      onSave({
        category: category.trim(),
        maxCapitalVnd: parsed,
        dropshipOnly,
      });
    }
  }, [category, maxCapital, dropshipOnly, onSave]);

  return (
    <div className="space-y-3" data-testid="listing-constraints">
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        Thiết lập tiêu chí để lọc cơ hội phù hợp với shop của bạn.
      </p>
      <label className="block text-sm">
        Danh mục quan tâm
        <input
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)" }}
          data-testid="listing-constraints-category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
        />
      </label>
      <label className="block text-sm">
        Vốn tối đa (VND)
        <input
          type="number"
          className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
          style={{ borderColor: "var(--border)" }}
          data-testid="listing-constraints-capital"
          value={maxCapital}
          onChange={(e) => setMaxCapital(e.target.value)}
        />
      </label>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          data-testid="listing-constraints-dropship"
          checked={dropshipOnly}
          onChange={(e) => setDropshipOnly(e.target.checked)}
        />
        Chỉ cơ hội hỗ trợ dropship
      </label>
    </div>
  );
}

function OpportunityBrowseStep({
  opportunities,
  selectedId,
  onSelect,
}: {
  opportunities: { opportunity_id: string; product_name: string; category: string; margin_potential: number }[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="space-y-3" data-testid="listing-opportunity-browse">
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        {opportunities.length} cơ hội phù hợp với tiêu chí của bạn
      </p>
      <ul className="space-y-2">
        {opportunities.map((item) => (
          <li key={item.opportunity_id}>
            <button
              type="button"
              className="card w-full p-3 text-left"
              data-testid={`listing-opportunity-card-${item.opportunity_id}`}
              aria-pressed={selectedId === item.opportunity_id}
              onClick={() => onSelect(item.opportunity_id)}
              style={{
                outline:
                  selectedId === item.opportunity_id
                    ? "2px solid var(--primary-500, #6366f1)"
                    : undefined,
              }}
            >
              <p className="font-medium">{item.product_name}</p>
              <p className="text-muted text-xs">
                {item.category} · Biên lợi nhuận {(item.margin_potential * 100).toFixed(0)}%
              </p>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DistributorPickStep({
  distributors,
  selectedId,
  onSelect,
  suggestedIds,
}: {
  distributors: { distributor_id: string; name: string; category_coverage: string[] }[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  suggestedIds?: string[];
}) {
  const ordered = suggestedIds?.length
    ? [
        ...distributors.filter((d) => suggestedIds.includes(d.distributor_id)),
        ...distributors.filter((d) => !suggestedIds.includes(d.distributor_id)),
      ]
    : distributors;

  return (
    <div className="space-y-3" data-testid="listing-distributor-pick">
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        Chọn nhà phân phối để lấy hàng
      </p>
      <ul className="space-y-2">
        {ordered.map((item) => (
          <li key={item.distributor_id}>
            <button
              type="button"
              className="card w-full p-3 text-left"
              data-testid={`listing-distributor-${item.distributor_id}`}
              aria-pressed={selectedId === item.distributor_id}
              onClick={() => onSelect(item.distributor_id)}
              style={{
                outline:
                  selectedId === item.distributor_id
                    ? "2px solid var(--primary-500, #6366f1)"
                    : undefined,
              }}
            >
              <p className="font-medium">{item.name}</p>
              <p className="text-muted text-xs">{item.category_coverage.join(", ")}</p>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DraftReviewStep({
  draft,
}: {
  draft: {
    product_info: { product_name: string; category: string; price: number };
    readiness: { overall_score: number };
    compliance: { status: string };
    status: string;
  };
}) {
  return (
    <div className="space-y-3" data-testid="listing-draft-review">
      <p className="text-sm font-medium">{draft.product_info.product_name}</p>
      <dl className="space-y-1 text-sm">
        <div className="flex justify-between">
          <dt style={{ color: "var(--muted-foreground)" }}>Danh mục</dt>
          <dd>{draft.product_info.category}</dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--muted-foreground)" }}>Giá bán</dt>
          <dd>{formatVND(draft.product_info.price)}</dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--muted-foreground)" }}>Điểm sẵn sàng</dt>
          <dd data-testid="listing-readiness-score">{draft.readiness.overall_score}</dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--muted-foreground)" }}>Tuân thủ</dt>
          <dd data-testid="listing-compliance-status">{draft.compliance.status}</dd>
        </div>
        <div className="flex justify-between">
          <dt style={{ color: "var(--muted-foreground)" }}>Trạng thái</dt>
          <dd data-testid="listing-draft-status">{draft.status}</dd>
        </div>
      </dl>
    </div>
  );
}

function ExportPlaceholderStep({ productName }: { productName?: string }) {
  return (
    <div className="space-y-2" data-testid="listing-export-placeholder">
      <p className="text-sm font-medium">Bước xuất bản (sắp ra mắt)</p>
      <p className="text-sm" style={{ color: "var(--muted-foreground)" }}>
        {productName
          ? `Bản nháp "${productName}" sẽ được xuất CSV/JSON trong phiên bản tiếp theo.`
          : "Xuất CSV/JSON sẽ có trong issue #156."}
      </p>
    </div>
  );
}
