import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "pdfctx — every number with its source row",
  description:
    "Financial metrics and cited answers from 10-Ks and annual reports, for analysts and their AI agents.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
