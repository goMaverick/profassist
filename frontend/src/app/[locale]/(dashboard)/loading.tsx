export default function DashboardLoading() {
  return (
    <div role="status" className="space-y-4" aria-live="polite">
      <span className="sr-only">Loading page</span>
      <div className="bg-muted h-8 w-48 rounded motion-safe:animate-pulse" />
      <div className="bg-muted h-40 rounded-lg motion-safe:animate-pulse" />
    </div>
  );
}
