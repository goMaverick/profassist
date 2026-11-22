"use client";

import { useEffect, useState } from "react";
import { Banner, pa } from "@/components/profassist/bits";

interface Models {
  tracking_uri: string;
  reachable: boolean;
  message: string;
  models: Array<{ name: string; status: string; version: string | null }>;
}

export default function ModelsPage() {
  const [data, setData] = useState<Models | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    pa<Models>("/admin/models")
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, []);

  return (
    <div className="flex max-w-3xl flex-col gap-4 text-sm">
      {error && <Banner>{error}</Banner>}
      {data && (
        <section className="border-foreground/10 rounded-xl border p-4">
          <h2 className="text-lg font-medium">Registered models</h2>
          <p className="text-foreground/70 mt-2">{data.message}</p>
          <p className="text-foreground/50 mt-1 text-xs">{data.tracking_uri}</p>
          <ul className="mt-4 flex flex-col gap-2">
            {data.models.map((model) => (
              <li key={model.name} className="border-foreground/10 flex justify-between rounded-lg border px-3 py-2">
                <span>{model.name}</span>
                <span className="text-foreground/60">
                  {model.status.replaceAll("_", " ")}
                  {model.version ? ` · v${model.version}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
