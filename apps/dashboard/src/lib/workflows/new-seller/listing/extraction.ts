import type {
  ListingContent,
  ProductInfo,
} from "@/lib/mock-data/listing-workflow/schemas";
import type {
  ExtractedProductFields,
  ListingGenerationContext,
  ManualFormContext,
  OpportunityCardContext,
  UrlStubContext,
} from "./types";

const HOST_CATEGORY_HINTS: Array<{ pattern: RegExp; category: string }> = [
  { pattern: /beauty|cosmetic|mypham|skincare/i, category: "Mỹ phẩm" },
  { pattern: /fashion|thoi-trang|clothing|apparel/i, category: "Thời trang" },
  { pattern: /electronic|tech|dien-tu|gadget/i, category: "Điện tử" },
  { pattern: /food|thuc-pham|grocery/i, category: "Thực phẩm" },
];

function slugToTitle(slug: string): string {
  return slug
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .trim();
}

function inferCategoryFromUrl(urlStub: string): string {
  const lower = urlStub.toLowerCase();
  for (const hint of HOST_CATEGORY_HINTS) {
    if (hint.pattern.test(lower)) {
      return hint.category;
    }
  }
  return "Khác";
}

function extractProductNameFromUrl(urlStub: string): string {
  try {
    const parsed = new URL(
      urlStub.startsWith("http") ? urlStub : `https://${urlStub}`,
    );
    const segments = parsed.pathname
      .split("/")
      .map((segment) => segment.trim())
      .filter(Boolean);
    const lastSegment = segments[segments.length - 1];
    if (lastSegment) {
      return slugToTitle(decodeURIComponent(lastSegment));
    }
    return slugToTitle(parsed.hostname.replace(/^www\./, ""));
  } catch {
    const fallback = urlStub.split("/").filter(Boolean).pop() ?? urlStub;
    return slugToTitle(fallback);
  }
}

function extractFromManualForm(context: ManualFormContext): ExtractedProductFields {
  return {
    product_name: context.product_name.trim(),
    brand: context.brand?.trim() || null,
    category: context.category.trim(),
    price: context.price,
    variants: context.variants?.length ? [...context.variants] : ["Mặc định"],
    description: context.description?.trim() || null,
  };
}

function extractFromUrlStub(context: UrlStubContext): ExtractedProductFields {
  const product_name = extractProductNameFromUrl(context.url_stub);
  const category = inferCategoryFromUrl(context.url_stub);
  return {
    product_name,
    brand: context.brand?.trim() || null,
    category,
    price: context.price ?? 0,
    variants: ["Mặc định"],
    description: `Sản phẩm được trích xuất từ URL: ${context.url_stub}`,
  };
}

function extractFromOpportunityCard(
  context: OpportunityCardContext,
): ExtractedProductFields {
  const { opportunity, distributor } = context;
  const estimatedPrice =
    context.price ??
    Math.round(opportunity.margin_potential * 500_000 + opportunity.estimated_demand * 10_000);

  return {
    product_name: opportunity.product_name.trim(),
    brand: distributor.name.trim(),
    category: opportunity.category.trim(),
    price: estimatedPrice,
    variants: ["Mặc định"],
    description: `Cơ hội ${opportunity.product_name} từ nhà phân phối ${distributor.name}.`,
  };
}

export function extractProductFields(
  context: ListingGenerationContext,
): ExtractedProductFields {
  switch (context.source_type) {
    case "manual_form":
      return extractFromManualForm(context);
    case "url_stub":
      return extractFromUrlStub(context);
    case "opportunity_card":
      return extractFromOpportunityCard(context);
    default: {
      const exhaustive: never = context;
      throw new Error(`Unsupported source type: ${(exhaustive as { source_type: string }).source_type}`);
    }
  }
}

function buildHashtags(category: string, productName: string): string[] {
  const categoryTag = `#${category.toLowerCase().replace(/\s+/g, "")}`;
  const nameTag = `#${productName.split(" ")[0]?.toLowerCase() ?? "sanpham"}`;
  return [categoryTag, nameTag, "#tiktokshop"];
}

function buildSeoKeywords(productName: string, category: string): string[] {
  const words = productName
    .toLowerCase()
    .split(/\s+/)
    .filter((word) => word.length > 2);
  return [category.toLowerCase(), ...words.slice(0, 3)];
}

export function buildListingContent(fields: ExtractedProductFields): ListingContent {
  const title = `${fields.product_name} — ${fields.category}`;
  const description =
    fields.description ??
    `${fields.product_name} thuộc danh mục ${fields.category}. Chất lượng tốt, phù hợp bán trên TikTok Shop.`;

  return {
    title,
    description,
    bullet_points: [
      `Sản phẩm: ${fields.product_name}`,
      `Danh mục: ${fields.category}`,
      fields.brand ? `Thương hiệu: ${fields.brand}` : "Phù hợp người bán mới trên TikTok Shop",
    ],
    seo_keywords: buildSeoKeywords(fields.product_name, fields.category),
    hashtags: buildHashtags(fields.category, fields.product_name),
  };
}

export function buildProductInfo(fields: ExtractedProductFields): ProductInfo {
  return {
    product_name: fields.product_name,
    brand: fields.brand,
    category: fields.category,
    price: fields.price,
    variants: [...fields.variants],
    description: fields.description,
  };
}
