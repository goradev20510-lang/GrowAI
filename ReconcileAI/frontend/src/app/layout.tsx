import type { Metadata, Viewport } from "next";
import { DM_Sans, Inter, Geist_Mono } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

const dmSans = DM_Sans({ variable: "--font-dm-sans", subsets: ["latin"], axes: ["opsz"] });
const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "ReconcileAI. Every rupee, reconciled.", template: "%s · ReconcileAI" },
  description:
    "Accounts-receivable reconciliation for Indian businesses. Bank credits matched to invoices with TDS, part-payments and bulk payments handled, and a named human on every uncertain call.",
};

export const viewport: Viewport = { themeColor: "#000000", colorScheme: "dark" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-IN" className={`${dmSans.variable} ${inter.variable} ${geistMono.variable}`}>
      <body className="min-h-dvh bg-void">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
