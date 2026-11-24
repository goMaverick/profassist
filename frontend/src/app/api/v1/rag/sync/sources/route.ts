import { NextRequest, NextResponse } from "next/server";
import { backendFetch, backendFetchWithStatus, BackendApiError } from "@/lib/server-api";

export async function GET(request: NextRequest) {
  try {
    const accessToken = request.cookies.get("access_token")?.value;
    const headers: Record<string, string> = {};
    if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

    const qs = request.nextUrl.searchParams.toString();
    const data = await backendFetch(`/api/v1/rag/sync/sources${qs ? `?${qs}` : ""}`, { headers });
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const accessToken = request.cookies.get("access_token")?.value;
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

    const { data, status } = await backendFetchWithStatus("/api/v1/rag/sync/sources", {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    });
    return NextResponse.json(data, { status });
  } catch (error) {
    if (error instanceof BackendApiError) {
      return NextResponse.json({ detail: error.message }, { status: error.status });
    }
    return NextResponse.json({ detail: "Internal server error" }, { status: 500 });
  }
}
