import Image from "./fallback-image";

export async function GET(_request: Request, context: { params: Promise<{ slug: string }> }) {
  return Image(context);
}
