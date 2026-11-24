import { NextRequest, NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const accessToken = request.cookies.get("access_token")?.value;
  if (!accessToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${BACKEND_URL}/api/v1/rag/status/stream`, {
      headers: {
        Authorization: `Bearer ${accessToken}`,
        Accept: "text/event-stream",
      },
      cache: "no-store",
      signal: request.signal,
    });
  } catch {
    return NextResponse.json({ detail: "Failed to reach the backend" }, { status: 502 });
  }

  if (!upstream.ok) {
    let detail = `Backend error ${upstream.status}`;
    try {
      const payload = await upstream.json();
      if (payload && typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // Upstream did not send JSON; keep the generic status message.
    }
    return NextResponse.json({ detail }, { status: upstream.status });
  }

  if (!upstream.body) {
    return NextResponse.json({ detail: "Backend returned no stream" }, { status: 502 });
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "content-type": "text/event-stream",
      "cache-control": "no-cache",
      "x-accel-buffering": "no",
    },
  });
}
