import "./globals.css";
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "OpenMetaData Onboarding UI",
  description: "Review schema-grounded onboarding questions and publish semantic bundles into TAG.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">
          <div className="frame">{children}</div>
        </div>
      </body>
    </html>
  );
}
