// The build the server is running now. Compared with the one a tab was loaded from (UpdateBanner).
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ id: process.env.NEXT_PUBLIC_BUILD_ID ?? "" }, { headers: { "Cache-Control": "no-store" } });
}
