import type { Metadata } from "next";
import "./globals.css";
import Header from "./Header";

export const metadata: Metadata = {
  title: "ClaimIQ — Claims Leakage Detection",
  description: "Claims leakage detection agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <Header />
          <main>{children}</main>
        </div>
      </body>
    </html>
  );
}
