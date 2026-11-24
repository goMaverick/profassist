"use client";

import { useEffect, useState } from "react";

const DESKTOP_QUERY = "(min-width: 1024px)";

export function DesktopOnly({ children }: { children: React.ReactNode }) {
  // null = not measured yet on the client. Render a neutral placeholder so the
  // server and the first client paint agree (no hydration mismatch).
  const [isDesktop, setIsDesktop] = useState<boolean | null>(null);

  useEffect(() => {
    const query = window.matchMedia(DESKTOP_QUERY);
    const update = () => setIsDesktop(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  if (isDesktop === null) {
    return <div className="pa-desktop-gate" aria-busy="true" />;
  }

  if (!isDesktop) {
    return (
      <main className="pa-desktop-gate pa-desktop-gate--blocked" role="alert">
        <p>ProfAssist is desktop-only. Open it on a screen at least 1024px wide.</p>
      </main>
    );
  }

  return <>{children}</>;
}
