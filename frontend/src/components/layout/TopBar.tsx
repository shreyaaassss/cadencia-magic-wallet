'use client';

import { usePathname } from 'next/navigation';
import { Bell, Settings, Wallet, LogOut, Circle, Menu } from 'lucide-react';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { useAuth } from '@/hooks/useAuth';
import { useHealthStatus } from '@/hooks/useHealthStatus';
import { ThemeToggle } from '@/components/shared/ThemeToggle';
import { ROUTES } from '@/lib/constants';
import Link from 'next/link';

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/settings': 'Settings',
  '/settings/wallet': 'Wallet Management',
  '/marketplace': 'Marketplace',
  '/marketplace/profile': 'Seller Profile',
  '/marketplace/catalogue': 'Product Catalogue',
  '/negotiations': 'Negotiations',
  '/escrow': 'Escrow & Settlements',
  '/compliance': 'Compliance & Audit',
  '/admin': 'Admin Panel',
};

const healthDisplay: Record<string, { fill: string; text: string; label: string }> = {
  healthy:  { fill: 'fill-green-600 text-green-600',         text: 'text-muted-foreground', label: 'Operational' },
  degraded: { fill: 'fill-amber-500 text-amber-500',         text: 'text-muted-foreground', label: 'Degraded' },
  down:     { fill: 'fill-destructive text-destructive',      text: 'text-muted-foreground', label: 'Down' },
  unknown:  { fill: 'fill-muted-foreground text-muted-foreground', text: 'text-muted-foreground', label: 'Checking...' },
};

export function TopBar({ onMenuClick }: { onMenuClick?: () => void } = {}) {
  const pathname = usePathname();
  const { user, enterprise, logout } = useAuth();
  const { status } = useHealthStatus();

  const title = PAGE_TITLES[pathname] ?? 'Cadencia';
  const initials = user?.full_name
    ? user.full_name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2)
    : 'U';

  const hd = healthDisplay[status] ?? healthDisplay.unknown;

  return (
    <header className="h-14 sm:h-16 border-b border-hairline bg-background flex items-center justify-between px-3 sm:px-6 shrink-0">

      <div className="flex items-center gap-2">
        {onMenuClick && (
          <Button variant="ghost" size="icon" className="h-8 w-8 md:hidden" onClick={onMenuClick}>
            <Menu className="h-5 w-5" />
          </Button>
        )}
        <h1 className="text-sm sm:text-base font-medium text-ink truncate">{title}</h1>
      </div>

      <div className="flex items-center gap-2 sm:gap-3">

        {/* Health indicator */}
        <div className="hidden sm:flex items-center gap-1.5">
          <Circle className={`h-2 w-2 ${hd.fill}`} />
          <span className={`text-xs ${hd.text}`}>{hd.label}</span>
        </div>

        {/* Theme toggle */}
        <ThemeToggle />

        {/* Notifications */}
        <Button variant="ghost" size="icon" className="h-8 w-8 relative">
          <Bell className="h-4 w-4 text-muted-foreground" />
        </Button>

        {/* Enterprise name */}
        <span className="text-sm text-muted-foreground hidden md:block">
          {enterprise?.legal_name}
        </span>

        {/* User dropdown */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-8 w-8 rounded-full">
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-surface-soft text-ink text-xs font-medium border border-hairline">
                  {initials}
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="end"
            className="w-56"
          >
            <DropdownMenuLabel>
              <p className="text-sm font-medium text-ink">{user?.full_name ?? 'User'}</p>
              <p className="text-xs text-muted-foreground font-normal">{user?.email ?? ''}</p>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild className="cursor-pointer">
              <Link href={ROUTES.SETTINGS} className="flex items-center gap-2">
                <Settings className="h-4 w-4" />
                Settings
              </Link>
            </DropdownMenuItem>
            <DropdownMenuItem asChild className="cursor-pointer">
              <Link href={ROUTES.WALLET} className="flex items-center gap-2">
                <Wallet className="h-4 w-4" />
                Wallet
              </Link>
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={logout}
              className="cursor-pointer text-destructive focus:text-destructive flex items-center gap-2"
            >
              <LogOut className="h-4 w-4" />
              Sign Out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>

      </div>
    </header>
  );
}
