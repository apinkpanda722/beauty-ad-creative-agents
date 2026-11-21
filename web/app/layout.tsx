import type { Metadata } from "next";
import type { ReactNode } from "react";
import localFont from "next/font/local";
import { BRAND } from "../lib/brand";
import "./globals.css";
import "./tokens.css";
import "./shell.css";

const pretendard = localFont({
  src: "../node_modules/pretendard/dist/web/variable/woff2/PretendardVariable.woff2",
  variable: "--font-pretendard",
  weight: "45 920",
  display: "swap",
});

export const metadata: Metadata = { title: BRAND.name };

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="ko" className={pretendard.variable}><body>{children}</body></html>;
}
