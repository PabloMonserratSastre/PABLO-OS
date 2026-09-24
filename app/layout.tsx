import type { Metadata, Viewport } from "next";
import "./globals.css";

export const viewport: Viewport = { themeColor: "#e8f1fa" };

export const metadata: Metadata = {
  title: "PABLO OS",
  description: "Tu espacio personal de proyectos, conocimiento y ejecución.",
  other: {
    "codex-preview": "development",
  },
  icons: {
    icon: "/assets/pablo-logo-transparent.png",
    shortcut: "/assets/pablo-logo-transparent.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className="dark">
      <body className="antialiased">{children}</body>
    </html>
  );
}
