import type { Metadata } from 'next';
import './globals.css';
import { AuthProvider } from '@/context/AuthContext';
import { CadenciaWalletProvider } from '@/context/WalletContext';
import { QueryProvider } from '@/components/providers/QueryProvider';
import { MSWProvider } from '@/components/providers/MSWProvider';
import { Toaster } from '@/components/ui/sonner';

export const metadata: Metadata = {
  title: 'Cadencia — B2B Trade Platform',
  description: 'AI-powered B2B trade negotiation and settlement platform',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400&display=swap" rel="stylesheet" />
      </head>
      <body className="font-sans bg-background text-foreground antialiased" suppressHydrationWarning>
        <MSWProvider>
          <QueryProvider>
            <AuthProvider>
              <CadenciaWalletProvider>
                {children}
                <Toaster position="bottom-right" theme="light" />
              </CadenciaWalletProvider>
            </AuthProvider>
          </QueryProvider>
        </MSWProvider>
      </body>
    </html>
  );
}
