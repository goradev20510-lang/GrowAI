import type { Metadata, Viewport } from "next";
import { Red_Hat_Display, Red_Hat_Mono, Red_Hat_Text } from "next/font/google";
import { Providers } from "@/components/providers";
import "./globals.css";

const display = Red_Hat_Display({ variable: "--font-red-hat-display", subsets: ["latin"] });
const text = Red_Hat_Text({ variable: "--font-red-hat-text", subsets: ["latin"] });
const mono = Red_Hat_Mono({ variable: "--font-red-hat-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "ReconcileAI. Every rupee, reconciled.", template: "%s · ReconcileAI" },
  description:
    "Accounts-receivable reconciliation for Indian businesses. Bank credits matched to invoices with TDS, part-payments and bulk payments handled, and a named human on every uncertain call.",
};

export const viewport: Viewport = { themeColor: "#0b1d43", colorScheme: "dark" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-IN" className={`${display.variable} ${text.variable} ${mono.variable}`}>
      <body className="min-h-dvh bg-void">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
