import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/context/AuthContext";
import { LanguageProvider } from "@/context/LanguageContext";
import { getServerAuth } from "@/lib/supabase/server";
import { AuthModal } from "@/components/AuthModal";
import { DomPatchGuard } from "@/components/DomPatchGuard";
import { ToastProvider } from "@/components/ui/Toast";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
  display: "swap",
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "PortfolioMaster",
  description: "Investment watchlist, real-time market data, and target tracking",
  other: {
    google: "notranslate",
  },
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const { user } = await getServerAuth();
  return (
    <html
      lang="en"
      translate="no"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased notranslate`}
    >
      <body className="min-h-full flex flex-col notranslate">
        <DomPatchGuard />
        <LanguageProvider>
          <ToastProvider>
            <AuthProvider initialUser={user}>
              {children}
              <AuthModal />
            </AuthProvider>
          </ToastProvider>
        </LanguageProvider>
      </body>
    </html>
  );
}

