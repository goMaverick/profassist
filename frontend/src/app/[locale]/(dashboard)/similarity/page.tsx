"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SimilarityRedirect() {
  const router = useRouter();
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("id");
    router.replace(id ? `/integrity?tab=similarity&id=${encodeURIComponent(id)}` : "/integrity?tab=similarity");
  }, [router]);
  return <p>Opening Integrity…</p>;
}
