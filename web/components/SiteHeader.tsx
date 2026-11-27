import Link from "next/link";
import { MODE } from "@/lib/api";

export function SiteHeader() {
  return (
    <header className="border-b border-zinc-200 dark:border-zinc-800">
      <nav className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-3 text-sm">
        <Link href="/" className="font-semibold tracking-tight">
          📑 pdfctx
        </Link>
        {MODE === "cloud" && (
          <Link href="/pricing" className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">
            Pricing
          </Link>
        )}
        <a
          href="https://github.com/StanislavV01/pdfctx"
          className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          GitHub
        </a>
        <span className="ml-auto flex items-center gap-3">
          {MODE === "cloud" && (
            <Link href="/signin" className="text-zinc-600 hover:text-zinc-900 dark:text-zinc-300">
              Sign in
            </Link>
          )}
          <Link
            href={MODE === "cloud" ? "/signin" : "/app"}
            className="rounded-lg bg-zinc-900 px-3 py-1.5 font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
          >
            {MODE === "cloud" ? "Start free" : "Open app"}
          </Link>
        </span>
      </nav>
    </header>
  );
}
