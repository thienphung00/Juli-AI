import type { Distributor, Opportunity } from "@/lib/mock-data/listing-workflow/schemas";

export interface SellerContext {
  seller_id: string;
  shop_id: string;
}

export interface ManualFormContext extends SellerContext {
  source_type: "manual_form";
  product_name: string;
  category: string;
  price: number;
  brand?: string | null;
  variants?: string[];
  description?: string | null;
}

export interface UrlStubContext extends SellerContext {
  source_type: "url_stub";
  url_stub: string;
  price?: number;
  brand?: string | null;
}

export interface OpportunityCardContext extends SellerContext {
  source_type: "opportunity_card";
  opportunity: Opportunity;
  distributor: Distributor;
  price?: number;
}

export type ListingGenerationContext =
  | ManualFormContext
  | UrlStubContext
  | OpportunityCardContext;

export interface ExtractedProductFields {
  product_name: string;
  brand: string | null;
  category: string;
  price: number;
  variants: string[];
  description: string | null;
}
