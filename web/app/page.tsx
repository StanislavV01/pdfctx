import Link from "next/link";
import { SiteHeader } from "@/components/SiteHeader";
import { MODE } from "@/lib/api";

const FEATURES = [
  {
    title: "A metrics table you can audit",
    body: "Pick revenue, capex, EPS, free cash flow… and the years. pdfctx reads them from the filings' own tables and links every cell to its page and row. Values it cannot find stay empty. No model guesses numbers.",
  },
  {
    title: "Built for your AI agent",
    body: "Connect Claude, Cursor or your own agent over MCP or REST with an API key. It gets the exact table row or paragraph with page and box, using about a tenth of the tokens of whole pages.",
  },
  {
    title: "Real filings, scans included",
    body: "Borderless SEC tables are read row by row, two-column layouts in reading order, and scanned pages through OCR. Every read is logged, so you can see what your agent was shown.",
  },
];

export default function Landing() {
  return (
    <>
      <SiteHeader />
      <main className="mx-auto max-w-6xl px-6">
        <section className="grid items-center gap-10 py-16 lg:grid-cols-[1fr_1.1fr]">
          <div className="space-y-6">
            <p className="text-sm font-medium uppercase tracking-wider text-amber-600">For financial filings</p>
            <h1 className="text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
              Every number with its source row.
            </h1>
            <p className="text-lg text-zinc-600 dark:text-zinc-400">
              Upload 10-Ks, 10-Qs and annual reports. Get a metrics table where each value links to its line in
              the filing. Give your AI agent the same cited access over MCP.
            </p>
            <div className="flex gap-3">
              <Link
                href={MODE === "cloud" ? "/signin" : "/app"}
                className="rounded-lg bg-zinc-900 px-5 py-2.5 font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
              >
                {MODE === "cloud" ? "Start free: 50 pages" : "Open the app"}
              </Link>
              {MODE === "cloud" && (
                <Link href="/pricing" className="rounded-lg border px-5 py-2.5 font-medium dark:border-zinc-700">
                  Pricing
                </Link>
              )}
            </div>
          </div>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/demo.png"
            alt="pdfctx: a search over 3M's 2018 10-K with the capex row highlighted on page 49"
            className="w-full rounded-xl border border-zinc-200 shadow-lg dark:border-zinc-800"
          />
        </section>

        <section className="grid gap-6 pb-16 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border border-zinc-200 p-5 dark:border-zinc-800">
              <h2 className="mb-2 font-semibold">{f.title}</h2>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">{f.body}</p>
            </div>
          ))}
        </section>

        <section className="mb-20 rounded-xl bg-zinc-100 p-6 text-sm text-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
          <p className="font-semibold">Measured in the open</p>
          <p className="mt-1">
            On FinanceBench (150 questions over 84 SEC filings), pdfctx puts the evidence page in its top 10 for 67%
            of questions, against 51% for page-level search, and hands the agent ~11× fewer tokens. Method, numbers and what did not work are in{" "}
            <a className="underline" href="https://github.com/StanislavV01/pdfctx#results-financebench">
              the repository
            </a>
            .
          </p>
        </section>
      </main>
    </>
  );
}
