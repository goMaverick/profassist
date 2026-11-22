import { CarbonShell } from "@/components/profassist/carbon-shell";
import { AuthGuard } from "@/components/layout/auth-guard";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <CarbonShell>{children}</CarbonShell>
    </AuthGuard>
  );
}
