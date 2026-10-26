import type { Metadata } from "next";
import { Inter, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/Sidebar";
import { AccessGate } from "@/components/AccessGate";
import { PageTransition } from "@/components/Motion";
import { FeedbackProvider } from "@/components/Feedback";
import { CommandPaletteProvider } from "@/components/CommandPalette";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const display = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-display", weight: ["600", "700", "800"] });

export const metadata: Metadata = {
  title: "MonoPlus · AI social media studio",
  description: "Turn a website URL into a month of on-brand, human-sounding social posts, carousels included.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${display.variable}`}>
      <body className="min-h-screen font-sans">
        <FeedbackProvider>
          <CommandPaletteProvider>
            <AccessGate>
              <div className="lg:flex">
                <Sidebar />
                <div className="min-w-0 flex-1">
                  <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-10 lg:py-8">
                    <PageTransition>{children}</PageTransition>
                  </main>
                </div>
              </div>
            </AccessGate>
          </CommandPaletteProvider>
        </FeedbackProvider>
      </body>
    </html>
  );
}
