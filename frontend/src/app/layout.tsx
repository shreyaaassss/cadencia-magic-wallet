import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { AuthProvider } from '@/context/AuthContext';
import { WalletProviderWrapper } from '@/components/providers/WalletProviderWrapper';
import { CadenciaWalletProvider } from '@/context/WalletContext';
import { QueryProvider } from '@/components/providers/QueryProvider';
import { MSWProvider } from '@/components/providers/MSWProvider';
import { Toaster } from '@/components/ui/sonner';

const inter = Inter({ subsets: ['latin'] });

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
        <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300;1,400;1,500&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,300&family=JetBrains+Mono:wght@300;400&display=swap" rel="stylesheet" />
      </head>
      <body className={`${inter.className} bg-background text-foreground antialiased`} suppressHydrationWarning>
        <MSWProvider>
          <QueryProvider>
            <AuthProvider>
              <WalletProviderWrapper>
                <CadenciaWalletProvider>
                  {children}
                  <Toaster position="bottom-right" theme="dark" />
                </CadenciaWalletProvider>
              </WalletProviderWrapper>
            </AuthProvider>
          </QueryProvider>
        </MSWProvider>
      </body>
    </html>
  );
}
