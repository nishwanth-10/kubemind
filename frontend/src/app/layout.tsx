import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { Providers } from './providers';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });
const mono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-mono' });

export const metadata: Metadata = {
  title: 'KubeMind AI | Infrastructure Intelligence',
  description: 'AI-powered Kubernetes observability with real-time anomaly detection, dependency mapping, and predictive analytics.',
  keywords: ['Kubernetes', 'AI', 'observability', 'infrastructure', 'monitoring', 'anomaly detection'],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} ${mono.variable} font-sans bg-black text-white min-h-screen overflow-x-hidden antialiased`}>
        {/* Animated ambient background */}
        <div className="fixed inset-0 pointer-events-none overflow-hidden">
          {/* Gradient orbs */}
          <div className="absolute top-[-10%] left-[-5%] w-[600px] h-[600px] bg-white/[0.02] rounded-full blur-[120px] animate-float" style={{ animationDelay: '0s' }} />
          <div className="absolute top-[30%] right-[-10%] w-[500px] h-[500px] bg-white/[0.015] rounded-full blur-[120px] animate-float" style={{ animationDelay: '-2s' }} />
          <div className="absolute bottom-[-20%] left-[20%] w-[700px] h-[700px] bg-white/[0.01] rounded-full blur-[150px] animate-float" style={{ animationDelay: '-4s' }} />

          {/* Grid overlay */}
          <div className="absolute inset-0 grid-bg opacity-50" />

          {/* Animated particles */}
          <div className="absolute top-[20%] left-[15%] w-1.5 h-1.5 rounded-full bg-white/[0.12]" style={{ animation: 'particle-1 8s ease-in-out infinite' }} />
          <div className="absolute top-[40%] right-[25%] w-2 h-2 rounded-full bg-white/[0.10]" style={{ animation: 'particle-2 10s ease-in-out infinite' }} />
          <div className="absolute top-[60%] left-[40%] w-1 h-1 rounded-full bg-white/[0.12]" style={{ animation: 'particle-3 7s ease-in-out infinite' }} />
          <div className="absolute top-[15%] right-[35%] w-1.5 h-1.5 rounded-full bg-white/[0.10]" style={{ animation: 'particle-1 9s ease-in-out infinite', animationDelay: '-3s' }} />
          <div className="absolute bottom-[30%] left-[10%] w-2 h-2 rounded-full bg-white/[0.08]" style={{ animation: 'particle-2 11s ease-in-out infinite', animationDelay: '-5s' }} />
        </div>

        <div className="relative z-10">
          <Providers>{children}</Providers>
        </div>
      </body>
    </html>
  );
}
