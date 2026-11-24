"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  ArrowRight,
  BookOpenCheck,
  ClipboardList,
  Eye,
  EyeOff,
  Layers,
  Loader2,
  Lock,
  Mail,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import { OAuthBlock } from "@/components/auth/oauth-buttons";
import { Button, Input, Label } from "@/components/ui";
import { useAuth } from "@/hooks";
import { ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { EMAIL_RE } from "@/lib/utils";

const FEATURES = [
  {
    icon: BookOpenCheck,
    title: "Course Designer",
    copy: "Course outlines with CLOs, weeks, and readings.",
  },
  {
    icon: Layers,
    title: "Material Designer",
    copy: "Cited slide decks built from your course notes.",
  },
  {
    icon: ClipboardList,
    title: "Assignment Designer",
    copy: "Briefs with rubrics and group settings.",
  },
  {
    icon: ShieldCheck,
    title: "Integrity",
    copy: "Group similarity evidence, with the decision left to you.",
  },
];

export function LoginForm() {
  const t = useTranslations("auth");
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [emailTouched, setEmailTouched] = useState(false);

  const emailValid = !email || EMAIL_RE.test(email);
  const showEmailError = emailTouched && !!email && !emailValid;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isLoading) return;
    setIsLoading(true);
    setError("");

    try {
      await login({ email, password });
      toast.success(t("loginSuccess"));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Login failed. Please try again.";
      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="login-shell mx-auto grid w-full max-w-md items-center gap-10 lg:max-w-none lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:gap-14">
      <aside className="border-foreground/10 from-brand/10 via-foreground/[0.02] relative hidden overflow-hidden rounded-3xl border bg-gradient-to-br to-transparent p-10 lg:flex lg:flex-col lg:gap-10">
        <div
          aria-hidden
          className="bg-brand/15 pointer-events-none absolute -top-24 -left-24 h-64 w-64 rounded-full blur-3xl"
        />

        <div className="relative space-y-6">
          <div className="flex items-center gap-3">
            <img
              src="/brand/uowd-logo.svg"
              alt="University of Wollongong in Dubai"
              className="h-10 w-auto"
            />
            <span aria-hidden className="bg-foreground/15 h-7 w-px" />
            <span className="font-display text-foreground/70 text-sm font-semibold tracking-tight">
              ProfAssist
            </span>
          </div>

          <div className="space-y-2">
            <span className="eyebrow text-foreground/50">The professor workspace</span>
            <h2 className="text-display-md text-foreground [&_em]:font-accent [&_em]:font-normal [&_em]:italic">
              Plan the term, <em>keep the judgment.</em>
            </h2>
          </div>
        </div>

        <ul className="relative space-y-5">
          {FEATURES.map(({ icon: Icon, title, copy }) => (
            <li key={title} className="flex gap-3.5">
              <span className="border-foreground/10 bg-background/70 text-foreground flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border">
                <Icon aria-hidden className="h-4 w-4" />
              </span>
              <div className="space-y-0.5">
                <p className="text-foreground text-sm font-medium">{title}</p>
                <p className="text-foreground/60 text-sm">{copy}</p>
              </div>
            </li>
          ))}
        </ul>

        <div className="border-foreground/10 relative space-y-4 border-t pt-6">
          <p className="text-foreground/60 inline-flex items-start gap-2 text-sm">
            <Sparkles aria-hidden className="text-brand mt-0.5 h-4 w-4 shrink-0" />
            Councils and memory keep context across sessions.
          </p>
          <p className="text-foreground/45 inline-flex items-center gap-2 font-mono text-[11px] tracking-wider uppercase">
            <ShieldCheck aria-hidden className="h-3.5 w-3.5" />
            AI drafts. You approve.
          </p>
        </div>
      </aside>

      <div className="w-full space-y-8">
        <div className="space-y-2">
          <img
            src="/brand/uowd-logo.svg"
            alt="University of Wollongong in Dubai"
            className="mb-4 h-10 w-auto lg:hidden"
          />
          <span className="eyebrow text-foreground/55">{t("welcomeBack")}</span>
          <h1 className="text-display-md text-foreground [&_em]:font-accent [&_em]:font-normal [&_em]:italic">
            Sign in to <em>your workspace.</em>
          </h1>
          <p className="text-foreground/65 text-sm">
            {t("noAccount")}{" "}
            <Link
              href={ROUTES.REGISTER}
              className="text-foreground hover:text-foreground/80 font-medium underline-offset-4 hover:underline"
            >
              {t("register")}
            </Link>
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <Label
              htmlFor="email"
              className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
            >
              {t("email")}
            </Label>
            <div className="relative">
              <Mail
                aria-hidden
                className="text-foreground/35 pointer-events-none absolute top-1/2 left-4 h-4 w-4 -translate-y-1/2"
              />
              <Input
                id="email"
                type="email"
                placeholder={t("emailPlaceholder")}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onBlur={() => setEmailTouched(true)}
                required
                disabled={isLoading}
                autoComplete="email"
                aria-invalid={showEmailError}
                aria-describedby={showEmailError ? "email-error" : undefined}
                className={`h-12 rounded-xl pl-11 ${showEmailError ? "border-destructive" : ""}`}
              />
            </div>
            {showEmailError && (
              <p id="email-error" className="text-destructive text-xs">
                {t("emailRequired")}
              </p>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label
                htmlFor="password"
                className="text-foreground/80 text-xs font-medium tracking-wider uppercase"
              >
                {t("password")}
              </Label>
              <Link
                href={ROUTES.FORGOT_PASSWORD}
                className="text-foreground/55 hover:text-foreground text-xs font-medium underline-offset-4 hover:underline"
              >
                {t("forgotShort")}
              </Link>
            </div>
            <div className="relative">
              <Lock
                aria-hidden
                className="text-foreground/35 pointer-events-none absolute top-1/2 left-4 h-4 w-4 -translate-y-1/2"
              />
              <Input
                id="password"
                type={showPassword ? "text" : "password"}
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={isLoading}
                autoComplete="current-password"
                className="h-12 rounded-xl pr-12 pl-11"
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                disabled={isLoading}
                aria-label={showPassword ? "Hide password" : "Show password"}
                aria-controls="password"
                aria-pressed={showPassword}
                className="text-foreground/45 hover:text-foreground focus-visible:ring-ring absolute top-1/2 right-2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-lg transition-colors focus-visible:ring-1 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"
              >
                {showPassword ? (
                  <EyeOff aria-hidden className="h-4 w-4" />
                ) : (
                  <Eye aria-hidden className="h-4 w-4" />
                )}
              </button>
            </div>
          </div>

          {error && (
            <div
              role="alert"
              aria-live="assertive"
              className="border-destructive/30 bg-destructive/5 text-destructive flex items-start gap-2 rounded-lg border px-3 py-2 text-sm"
            >
              <TriangleAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          <Button
            type="submit"
            disabled={isLoading}
            aria-busy={isLoading}
            className="bg-foreground text-background hover:bg-foreground/90 h-12 w-full rounded-full text-base font-medium"
          >
            {isLoading ? (
              <>
                <Loader2 aria-hidden className="animate-spin" />
                {t("loggingIn")}
              </>
            ) : (
              <>
                {t("login")}
                <ArrowRight aria-hidden />
              </>
            )}
          </Button>
        </form>

        <OAuthBlock label={t("orSignInWith")} />

        <div className="border-foreground/10 flex items-center gap-2 border-t pt-5">
          <ShieldCheck aria-hidden className="text-foreground/40 h-4 w-4 shrink-0" />
          <p className="text-foreground/45 font-mono text-[11px] tracking-wider uppercase">
            AI drafts. You approve.
          </p>
        </div>
      </div>
    </div>
  );
}
