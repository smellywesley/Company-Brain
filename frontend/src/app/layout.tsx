import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { BrandingProvider } from "@/components/branding-provider";
import { AppShell } from "@/components/shell/AppShell";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Company Brain | Autonomous, Auditable AI Operations",
  description:
    "Company Brain ingests scattered enterprise knowledge into a living memory graph, proposes operational actions, vets them with an independent critic, and logs a cryptographically chained audit trail.",
  keywords: [
    "knowledge management",
    "AI agents",
    "knowledge graph",
    "workflow automation",
    "audit log",
    "enterprise AI",
  ],
  authors: [{ name: "Company Brain" }],
  openGraph: {
    title: "Company Brain | Autonomous, Auditable AI Operations",
    description:
      "A living memory graph that reasons over your company's knowledge and acts — with a human approval queue and a tamper-evident audit trail.",
    type: "website",
  },
  appleWebApp: {
    capable: true,
    title: "Company Brain",
    statusBarStyle: "black-translucent",
  },
};

export const viewport: Viewport = {
  themeColor: "#060708",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning className={inter.variable}>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <BrandingProvider>
            <AppShell>{children}</AppShell>
          </BrandingProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
