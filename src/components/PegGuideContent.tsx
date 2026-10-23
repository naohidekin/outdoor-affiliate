import ArticleContent from "./ArticleContent";
import PegProductSelector from "./PegProductSelector";
import { publicPegVariants, splitPegGuide } from "../lib/pegs/selector.ts";
import { PEG_VARIANTS } from "../lib/pegs/variants.ts";
import type { TrackingProduct } from "../lib/affiliateProduct.ts";

const variants = publicPegVariants(PEG_VARIANTS);

/** Only the peg article opts into this marker; other article rendering stays unchanged. */
export default function PegGuideContent({ content, trackingProducts }: { content: string; trackingProducts?: TrackingProduct[] }) {
  const [before, after] = splitPegGuide(content);
  return (
    <>
      <ArticleContent content={before} products={[]} trackingProducts={trackingProducts} showProductFallback={false} />
      <PegProductSelector variants={variants} />
      <ArticleContent content={after} products={[]} trackingProducts={trackingProducts} showProductFallback={false} />
    </>
  );
}
