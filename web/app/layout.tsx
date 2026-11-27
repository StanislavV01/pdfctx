import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "pdfctx",
  description: "Structure-aware, citable PDF retrieval for AI agents",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <header className="border-b border-zinc-200 dark:border-zinc-800">
          <nav className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3 text-sm">
            <Link href="/" className="font-semibold tracking-tight">
              📑 pdfctx
            </Link>
            <Link href="/" className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">
              Documents
            </Link>
            <Link href="/audit" className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100">
              Audit log
            </Link>
            <a
              href="https://github.com/StanislavV01/pdfctx"
              className="ml-auto text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
            >
              GitHub
            </a>
          </nav>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
