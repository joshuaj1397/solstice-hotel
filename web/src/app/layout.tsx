import type { Metadata, Viewport } from "next";
import { Fraunces, Inter } from "next/font/google";
import { SiteHeader } from "@/components/SiteHeader";
import { Toaster } from "@/components/Toaster";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });
const fraunces = Fraunces({ variable: "--font-fraunces", subsets: ["latin"], axes: ["opsz"] });

export const metadata: Metadata = {
  title: { default: "Solstice Hotel Group", template: "%s · Solstice" },
  description: "Your Solstice stay, concierge and group bookings — powered by an on-premise AI concierge.",
};

export const viewport: Viewport = {
  // modern-web-guidance (dark-mode): declare both schemes before first paint to avoid a flash
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf7f1" },
    { media: "(prefers-color-scheme: dark)", color: "#121110" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${fraunces.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:m-2 focus:rounded focus:bg-surface focus:p-2">
          Skip to content
        </a>
        <SiteHeader />
        <main id="main" className="flex-1">
          {children}
        </main>
        <footer className="border-t border-line px-6 py-4 text-center text-xs text-muted">
          Solstice Hotel Group · Proof of concept. The concierge runs on a self-hosted Gemma 4 E2B model; guest data is never sent to a third-party AI API.
        </footer>
        <Toaster />
      </body>
    </html>
  );
}
