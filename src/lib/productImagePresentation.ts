import type { CSSProperties } from "react";

// Source-specific framing: do not carry a crop over to replacement product photos.
export function productImagePresentation(imageUrl: string): CSSProperties | undefined {
  if (imageUrl === "https://img.snowpeak.co.jp/img/item/SNP01/SNP0119A0108/SNP0119A0108_x_c101.jpg") {
    return { transform: "scale(1.8)", transformOrigin: "50% 50%" };
  }
  if (imageUrl === "https://img.snowpeak.co.jp/img/item/SNP01/SNP0115A0065/SNP0115A0065_x_c101.jpg") {
    // Emphasize the lamp body rather than the long suspension cord.
    return { transform: "scale(2.4)", transformOrigin: "50% 100%" };
  }
  return undefined;
}
