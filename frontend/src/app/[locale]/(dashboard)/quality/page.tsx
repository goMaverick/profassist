"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Banner, pa } from "@/components/profassist/bits";

interface Calibrator {
  status: string;
  trained: boolean;
  level: string | null;
  p_keep: number | null;
  message: string;
}

export default function QualityPage() {
  const [data, setData] = useState<Calibrator | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    pa<Calibrator>("/calibrator")
      .then(setData)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Load failed"));
  }, []);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      {error && <Banner>{error}</Banner>}
      {data && (
        <div className="border-foreground/10 rounded-xl border p-5 text-sm">
          <p className="font-medium">Grade calibrator · {data.status.replace("_", " ")}</p>
          <p className="text-foreground/70 mt-2">{data.message}</p>
          <dl className="mt-4 grid grid-cols-2 gap-3">
            <div>
              <dt className="text-foreground/50 text-xs uppercase">Suggested level</dt>
              <dd className="mt-1">—</dd>
            </div>
            <div>
              <dt className="text-foreground/50 text-xs uppercase">p(you keep it)</dt>
              <dd className="mt-1">—</dd>
            </div>
          </dl>
          <p className="text-foreground/60 mt-4">
            Agreement, override rate and the calibration gap will appear here after a model is trained
            on your own marks. Until then the council level is only a suggestion.
          </p>
          <Link href="/grade" className="mt-4 inline-block underline">
            Go to review and grade
          </Link>
        </div>
      )}
    </div>
  );
}
