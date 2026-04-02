import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { MembershipProvider } from "@/components/MembershipContext";
import { ConnectWallet } from "@/components/ConnectWallet";

export const metadata: Metadata = {
  title: "Videos",
  description: "Member-only video library",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-zinc-50 text-zinc-900 antialiased">
        <Providers>
          <MembershipProvider>
            <header className="sticky top-0 z-40 bg-white/80 backdrop-blur border-b border-zinc-200">
              <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
                <Link
                  href="/videos"
                  className="font-title font-bold text-xl tracking-tight"
                >
                  Videos
                </Link>
                <nav className="flex items-center gap-6">
                  <Link
                    href="/videos"
                    className="font-body text-sm text-zinc-600 hover:text-zinc-900"
                  >
                    Library
                  </Link>
                  <Link
                    href="/uploads"
                    className="font-body text-sm text-zinc-600 hover:text-zinc-900"
                  >
                    Upload
                  </Link>
                  <ConnectWallet />
                </nav>
              </div>
            </header>
            <main>{children}</main>
          </MembershipProvider>
        </Providers>
      </body>
    </html>
  );
}
