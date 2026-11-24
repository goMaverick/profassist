import { APP_NAME } from "@/lib/constants";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main
      id="main"
      className="theme-light bg-background text-foreground relative flex min-h-screen flex-col"
    >
      <header className="flex h-16 items-center px-6 sm:px-10">
        <div className="font-display text-foreground inline-flex items-center gap-2 text-base font-bold tracking-tight">
          <span aria-hidden className="bg-brand inline-block h-2.5 w-2.5 rounded-full" />
          {APP_NAME}
        </div>
      </header>

      <div className="flex flex-1 items-center justify-center px-6 py-10 sm:px-10">
        <div className="w-full max-w-md has-[.login-shell]:max-w-5xl">{children}</div>
      </div>

      <footer className="text-foreground/50 px-6 py-6 font-mono text-[11px] tracking-wider uppercase sm:px-10">
        © {new Date().getFullYear()} {APP_NAME}
      </footer>
    </main>
  );
}
