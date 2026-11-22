export class ProfassistError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function pa<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const isForm = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !isForm && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`/api/profassist${path}`, { ...init, headers });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = (await response.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* empty or binary */
    }
    throw new ProfassistError(detail, response.status);
  }
  const type = response.headers.get("content-type") || "";
  if (!type.includes("json")) {
    return (await response.blob()) as T;
  }
  const text = await response.text();
  return (text ? JSON.parse(text) : null) as T;
}

export interface Course {
  id: string;
  code: string;
  title: string;
  term: string;
}

export async function firstCourse(): Promise<Course | null> {
  const data = await pa<{ items: Course[] }>("/courses");
  return data.items[0] ?? null;
}
