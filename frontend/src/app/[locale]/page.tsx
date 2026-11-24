import { redirect } from "next/navigation";

/**
 * Marketing landing page removed - the root goes straight to sign-in.
 * `localePrefix: "as-needed"` means `/login` is the canonical path (no `/{locale}` prefix).
 */
export default function RootPage() {
  redirect("/login");
}
