"use client";

import type { ComponentProps } from "react";
import Link, { useLinkStatus } from "next/link";
import { useRouter } from "next/navigation";
import { LoaderCircle } from "lucide-react";

function NavigationPending() {
  const { pending } = useLinkStatus();
  return pending ? (
    <LoaderCircle aria-hidden="true" className="ml-auto size-4 shrink-0 motion-safe:animate-spin" />
  ) : null;
}

export function WorkspaceLink({
  children,
  href,
  ...props
}: Omit<ComponentProps<typeof Link>, "href" | "prefetch" | "onMouseEnter" | "onFocus"> & {
  href: string;
}) {
  const router = useRouter();
  return (
    <Link
      {...props}
      href={href}
      prefetch={false}
      onMouseEnter={() => router.prefetch(href)}
      onFocus={() => router.prefetch(href)}
    >
      {children}
      <NavigationPending />
    </Link>
  );
}
