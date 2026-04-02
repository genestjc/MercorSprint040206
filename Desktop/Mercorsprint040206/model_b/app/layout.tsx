import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import { Providers } from "./providers";
import { ConnectWallet } from "@/components/ConnectWallet";

export const metadata: Metadata = {
  title: "Members — Videos",
  description: "Premium video library for members.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <Providers>
          <header className="site-header">
            <Link href="/videos" className="brand">
              MEMBERS
            </Link>
            <nav>
              <Link href="/videos">Videos</Link>
              <Link href="/uploads">Uploads</Link>
            </nav>
            <div className="right">
              <ConnectWallet />
            </div>
          </header>
          {children}
        </Providers>
      </body>
    </html>
  );
}
