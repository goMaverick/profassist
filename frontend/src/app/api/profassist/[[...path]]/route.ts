import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

async function proxy(request: NextRequest, path: string[]) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const suffix = path.length ? `/${path.join("/")}` : "";
  const qs = request.nextUrl.searchParams.toString();
  const url = `${BACKEND_URL}/api/v1/profassist${suffix}${qs ? `?${qs}` : ""}`;
  const headers: Record<string, string> = { Authorization: `Bearer ${accessToken}` };
  const contentType = request.headers.get("content-type");
  if (contentType) headers["Content-Type"] = contentType;
  const org = request.headers.get("x-organization-id");
  if (org) headers["X-Organization-Id"] = org;
  const init: RequestInit = { method: request.method, headers };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = Buffer.from(await request.arrayBuffer());
  }
  const response = await fetch(url, init);
  const body = await response.arrayBuffer();
  const outgoing = new NextResponse(body, { status: response.status });
  const type = response.headers.get("content-type");
  if (type) outgoing.headers.set("content-type", type);
  const disposition = response.headers.get("content-disposition");
  if (disposition) outgoing.headers.set("content-disposition", disposition);
  return outgoing;
}

type Ctx = { params: Promise<{ path?: string[] }> };

async function handle(request: NextRequest, ctx: Ctx) {
  const { path = [] } = await ctx.params;
  return proxy(request, path);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
