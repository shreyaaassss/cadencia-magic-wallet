import type { Metadata } from 'next';
import './globals.css';
import { AuthProvider } from '@/context/AuthContext';
import { CadenciaWalletProvider } from '@/context/WalletContext';
import { QueryProvider } from '@/components/providers/QueryProvider';
import { MSWProvider } from '@/components/providers/MSWProvider';
import { ThemeProvider } from '@/components/providers/ThemeProvider';
import { WalletConnectProvider } from '@/components/providers/WalletConnectProvider';
import { Toaster } from '@/components/ui/sonner';

export const metadata: Metadata = {
  title: 'Cadencia — B2B Trade Platform',
  description: 'AI-powered B2B trade negotiation and settlement platform',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400&display=swap" rel="stylesheet" />
      </head>
      <body className="font-sans bg-background text-foreground antialiased" suppressHydrationWarning>
        <ThemeProvider>
          <MSWProvider>
            <QueryProvider>
              <WalletConnectProvider>
                <AuthProvider>
                  <CadenciaWalletProvider>
                    {children}
                    <Toaster position="bottom-right" />
                  </CadenciaWalletProvider>
                </AuthProvider>
              </WalletConnectProvider>
            </QueryProvider>
          </MSWProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
