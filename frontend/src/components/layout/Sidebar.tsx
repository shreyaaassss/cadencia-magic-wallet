'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard, ShoppingCart, Handshake, Landmark, Banknote,
  ClipboardList, Settings, ShieldCheck, LogOut, Building2, Store,
  ShoppingBag, PackageSearch,
} from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { cn } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';

// Define nav items with role visibility
type NavItem = {
  label: string;
  href: string;
  icon: React.ElementType;
  /** Which trade roles can see this item. undefined = everyone */
  roles?: ('BUYER' | 'SELLER' | 'BOTH' | 'ADMIN')[];
};

const navItems: NavItem[] = [
  { label: 'Dashboard',       href: ROUTES.DASHBOARD,       icon: LayoutDashboard },
  { label: 'Marketplace',     href: ROUTES.MARKETPLACE,     icon: ShoppingCart,    roles: ['BUYER'] },
  { label: 'Seller Profile',  href: ROUTES.SELLER_PROFILE,  icon: Store,           roles: ['SELLER'] },
  { label: 'Catalogue',       href: '/marketplace/catalogue', icon: PackageSearch,  roles: ['SELLER'] },
  { label: 'Negotiations',    href: ROUTES.NEGOTIATIONS,    icon: Handshake },
  { label: 'Escrow',          href: ROUTES.ESCROW,          icon: Landmark },
  { label: 'Treasury',        href: ROUTES.TREASURY,        icon: Banknote },
  { label: 'Compliance',      href: ROUTES.COMPLIANCE,      icon: ClipboardList },
  { label: 'Settings',        href: ROUTES.SETTINGS,        icon: Settings },
];

const adminItem: NavItem = { label: 'Admin', href: ROUTES.ADMIN, icon: ShieldCheck, roles: ['ADMIN'] };

const TRADE_ROLE_BADGE: Record<string, { label: string; className: string }> = {
  BUYER:  { label: 'Buyer',          className: 'bg-blue-50 text-blue-700 border-blue-200' },
  SELLER: { label: 'Seller',         className: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  BOTH:   { label: 'Buyer & Seller', className: 'bg-amber-50 text-amber-700 border-amber-200' },
};

export function Sidebar() {
  const pathname = usePathname();
  const { enterprise, user, logout, isAdmin, isBuyer, isSeller } = useAuth();

  const tradeRole = enterprise?.trade_role;

  // Filter nav items based on user's trade role
  const visibleItems = navItems.filter((item) => {
    // Admin users only see Dashboard from regular nav
    if (isAdmin) return item.href === ROUTES.DASHBOARD;
    // Items without role restrictions are shown to everyone
    if (!item.roles) return true;
    // 'BOTH' trade_role can see both BUYER and SELLER items
    if (tradeRole === 'BOTH') {
      return item.roles.includes('BUYER') || item.roles.includes('SELLER') || item.roles.includes('BOTH');
    }
    // BUYER trade_role: only see items marked for BUYER
    if (tradeRole === 'BUYER') {
      return item.roles.includes('BUYER');
    }
    // SELLER trade_role: only see items marked for SELLER
    if (tradeRole === 'SELLER') {
      return item.roles.includes('SELLER');
    }
    // Fallback: show all non-admin items
    return !item.roles.includes('ADMIN');
  });

  // Add admin item if user is admin
  const allItems = isAdmin ? [...visibleItems, adminItem] : visibleItems;

  return (
    <aside className="w-60 min-h-screen bg-white border-r border-hairline flex flex-col shrink-0">

      {/* Enterprise header */}
      <div className="p-4 border-b border-hairline">
        <div className="flex items-center gap-2 mb-2">
          <div className="bg-surface-soft rounded-md p-1.5">
            <Building2 className="h-4 w-4 text-ink" />
          </div>
          <span className="text-sm font-medium text-ink truncate">
            {enterprise?.legal_name ?? 'Cadencia'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {enterprise?.kyc_status && (
            <StatusBadge status={enterprise.kyc_status} size="sm" />
          )}
          {tradeRole && TRADE_ROLE_BADGE[tradeRole] && (
            <span className={cn(
              'inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium border',
              TRADE_ROLE_BADGE[tradeRole].className,
            )}>
              {TRADE_ROLE_BADGE[tradeRole].label}
            </span>
          )}
        </div>
      </div>

      {/* Nav items */}
      <nav className="flex-1 p-3 space-y-0.5">
        {allItems.map(({ label, href, icon: Icon }) => {
          const isActive = pathname === href || pathname.startsWith(href + '/');
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-surface-soft text-ink font-medium'
                  : 'text-body hover:bg-surface-soft hover:text-ink'
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* User footer */}
      <div className="p-3 border-t border-hairline">
        <div className="flex items-center justify-between px-2 py-1.5">
          <div className="min-w-0">
            <p className="text-sm font-medium text-ink truncate">
              {user?.full_name ?? 'User'}
            </p>
            <p className="text-xs text-muted-foreground truncate">
              {user?.email ?? ''}
            </p>
          </div>
          <button
            onClick={logout}
            className="ml-2 p-1.5 rounded-md text-muted-foreground hover:text-destructive hover:bg-surface-soft transition-colors shrink-0"
            title="Sign out"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>

    </aside>
  );
}
