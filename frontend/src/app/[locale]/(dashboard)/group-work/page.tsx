"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function GroupWorkRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/assignments");
  }, [router]);
  return <p>Opening Assignments…</p>;
}
