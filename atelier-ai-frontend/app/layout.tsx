import type { Metadata } from "next";
import "./globals.css";
import "./styles/debug.css";

export const metadata: Metadata = {
  title: "OpenEvent - AI Event Manager",
  description: "AI-powered event booking assistant",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
