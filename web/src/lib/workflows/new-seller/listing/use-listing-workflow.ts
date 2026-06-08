"use client";

import { useCallback, useMemo, useState } from "react";
import type { Distributor, Opportunity } from "@/lib/mock-data/listing-workflow/schemas";
import { loadDistributors, loadOpportunities } from "@/lib/mock-data/listing-workflow";
import { generateProductDraft } from "./generate";
import { filterOpportunities } from "./filter-opportunities";
import {
  advanceStep,
  canGoBack,
  goBackStep,
  INITIAL_LISTING_WORKFLOW_STATE,
  selectDistributor,
  selectOpportunity,
  selectPath,
  setDraft,
  updateConstraints,
  updateProductForm,
  type ListingPath,
  type ListingWorkflowState,
  type OpportunityConstraints,
  type ProductFormData,
} from "./state-machine";

function sellerIdFromPersona(personaId: string): string {
  return `seller_demo_${personaId}_001`;
}

export function useListingWorkflow(options: {
  personaId: string;
  shopId: string;
}) {
  const { personaId, shopId } = options;
  const sellerId = sellerIdFromPersona(personaId);

  const [state, setState] = useState<ListingWorkflowState>(
    INITIAL_LISTING_WORKFLOW_STATE,
  );

  const distributors = useMemo(() => loadDistributors(), []);
  const allOpportunities = useMemo(() => loadOpportunities(), []);

  const filteredOpportunities = useMemo(() => {
    if (!state.constraints) return [];
    return filterOpportunities(allOpportunities, state.constraints);
  }, [allOpportunities, state.constraints]);

  const selectedOpportunity = useMemo(
    () =>
      filteredOpportunities.find(
        (item) => item.opportunity_id === state.selectedOpportunityId,
      ) ?? null,
    [filteredOpportunities, state.selectedOpportunityId],
  );

  const selectedDistributor = useMemo(
    () =>
      distributors.find(
        (item) => item.distributor_id === state.selectedDistributorId,
      ) ?? null,
    [distributors, state.selectedDistributorId],
  );

  const reset = useCallback(() => {
    setState(INITIAL_LISTING_WORKFLOW_STATE);
  }, []);

  const choosePath = useCallback((path: ListingPath) => {
    setState((prev) => selectPath(prev, path));
  }, []);

  const saveProductForm = useCallback((form: ProductFormData) => {
    setState((prev) => updateProductForm(prev, form));
  }, []);

  const saveConstraints = useCallback((constraints: OpportunityConstraints) => {
    setState((prev) => updateConstraints(prev, constraints));
  }, []);

  const pickOpportunity = useCallback((opportunityId: string) => {
    setState((prev) => selectOpportunity(prev, opportunityId));
  }, []);

  const pickDistributor = useCallback((distributorId: string) => {
    setState((prev) => selectDistributor(prev, distributorId));
  }, []);

  const buildDraftForReview = useCallback(() => {
    if (state.path === "path_a" && state.productForm) {
      return generateProductDraft({
        source_type: "manual_form",
        seller_id: sellerId,
        shop_id: shopId,
        product_name: state.productForm.product_name,
        category: state.productForm.category,
        price: state.productForm.price,
        brand: state.productForm.brand ?? null,
        description: state.productForm.description ?? null,
      });
    }

    if (
      state.path === "path_b" &&
      selectedOpportunity &&
      selectedDistributor
    ) {
      return generateProductDraft({
        source_type: "opportunity_card",
        seller_id: sellerId,
        shop_id: shopId,
        opportunity: selectedOpportunity,
        distributor: selectedDistributor,
      });
    }

    return null;
  }, [
    sellerId,
    shopId,
    state.path,
    state.productForm,
    selectedOpportunity,
    selectedDistributor,
  ]);

  const goNext = useCallback(() => {
    setState((prev) => {
      const next = advanceStep(prev);
      if (next.step === "draft_review") {
        const draft =
          prev.path === "path_a" && prev.productForm
            ? generateProductDraft({
                source_type: "manual_form",
                seller_id: sellerId,
                shop_id: shopId,
                product_name: prev.productForm.product_name,
                category: prev.productForm.category,
                price: prev.productForm.price,
                brand: prev.productForm.brand ?? null,
                description: prev.productForm.description ?? null,
              })
            : prev.path === "path_b" &&
                prev.selectedOpportunityId &&
                prev.selectedDistributorId
              ? (() => {
                  const opportunity = allOpportunities.find(
                    (item) =>
                      item.opportunity_id === prev.selectedOpportunityId,
                  );
                  const distributor = distributors.find(
                    (item) =>
                      item.distributor_id === prev.selectedDistributorId,
                  );
                  if (!opportunity || !distributor) return null;
                  return generateProductDraft({
                    source_type: "opportunity_card",
                    seller_id: sellerId,
                    shop_id: shopId,
                    opportunity,
                    distributor,
                  });
                })()
              : null;

        if (draft) {
          return setDraft(next, draft);
        }
      }
      return next;
    });
  }, [allOpportunities, distributors, sellerId, shopId]);

  const goBack = useCallback(() => {
    setState((prev) => goBackStep(prev));
  }, []);

  const canAdvanceFromStep = useCallback((): boolean => {
    switch (state.step) {
      case "path_selection":
        return state.path !== null;
      case "product_form":
        return (
          state.productForm !== null &&
          state.productForm.product_name.trim().length > 0 &&
          state.productForm.category.trim().length > 0 &&
          state.productForm.price > 0
        );
      case "constraints":
        return state.constraints !== null;
      case "opportunity_browse":
        return state.selectedOpportunityId !== null;
      case "distributor_pick":
        return state.selectedDistributorId !== null;
      case "draft_review":
        return state.draft !== null;
      default:
        return false;
    }
  }, [state]);

  return {
    state,
    distributors,
    filteredOpportunities,
    selectedOpportunity,
    selectedDistributor,
    reset,
    choosePath,
    saveProductForm,
    saveConstraints,
    pickOpportunity,
    pickDistributor,
    goNext,
    goBack,
    canGoBack: canGoBack(state),
    canAdvanceFromStep,
    buildDraftForReview,
  };
}

export type ListingWorkflowController = ReturnType<typeof useListingWorkflow>;
