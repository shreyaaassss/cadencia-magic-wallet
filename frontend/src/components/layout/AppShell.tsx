'use client';

import { useState } from 'react';
import { Menu } from 'lucide-react';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { AuthGuard } from '@/components/shared/AuthGuard';
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';

export function AppShell({ children }: { children: React.ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <AuthGuard>
      <div className="flex h-screen overflow-hidden bg-background">
        {/* Desktop sidebar */}
        <div className="hidden md:flex md:shrink-0">
          <Sidebar />
        </div>

        <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
          <TopBar
            onMenuClick={() => setMobileOpen(true)}
          />
          <main className="flex-1 overflow-y-auto p-4 sm:p-6">
            {children}
          </main>
        </div>

        {/* Mobile sidebar drawer */}
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="p-0 w-60">
            <Sidebar onNavClick={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>
      </div>
    </AuthGuard>
  );
}
