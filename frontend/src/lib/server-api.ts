/**
 * Server-side API client for calling the FastAPI backend.
 * This module is used by Next.js API routes to proxy requests.
 * IMPORTANT: This file should only be imported in server-side code (API routes, Server Components).
 */

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export class BackendApiError extends Error {
  constructor(
    public status: number,
    public statusText: string,
    public data?: unknown,
    /** Response headers, so callers can forward e.g. `Retry-After`. */
    public headers?: Headers,
  ) {
    super(`Backend API error: ${status} ${statusText}`);
    this.name = "BackendApiError";
  }
}

interface RequestOptions extends RequestInit {
  params?: Record<string, string>;
  /** Return raw text instead of parsing as JSON */
  raw?: boolean;
}

/**
 * Like {@link backendFetch}, but also returns the backend's HTTP status code so
 * callers can mirror it instead of hard-coding a response status.
 */
export async function backendFetchWithStatus<T>(
  endpoint: string,
  options: RequestOptions = {},
): Promise<{ data: T; status: number }> {
  const { params, body, raw, ...fetchOptions } = options;

  let url = `${BACKEND_URL}${endpoint}`;

  if (params) {
    const searchParams = new URLSearchParams(params);
    url += `?${searchParams.toString()}`;
  }

  // Determine content type - don't set for FormData (browser will set with boundary)
  const headers: Record<string, string> = {};
  if (body instanceof FormData) {
    // Let the browser set Content-Type with the multipart boundary
  } else {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, {
    ...fetchOptions,
    headers: {
      ...headers,
      ...fetchOptions.headers,
    },
    body,
  });

  if (!response.ok) {
    let errorData;
    try {
      errorData = await response.json();
    } catch {
      errorData = null;
    }
    throw new BackendApiError(response.status, response.statusText, errorData, response.headers);
  }

  // Handle empty responses
  const text = await response.text();
  if (!text) {
    return { data: null as T, status: response.status };
  }

  return {
    data: (raw ? text : JSON.parse(text)) as T,
    status: response.status,
  };
}

/**
 * Make a request to the FastAPI backend.
 * This should only be called from Next.js API routes or Server Components.
 */
export async function backendFetch<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { data } = await backendFetchWithStatus<T>(endpoint, options);
  return data;
}

/**
 * Forward authorization header from the incoming request to the backend.
 */
export function getAuthHeaders(authHeader: string | null): Record<string, string> {
  if (!authHeader) {
    return {};
  }
  return { Authorization: authHeader };
}
