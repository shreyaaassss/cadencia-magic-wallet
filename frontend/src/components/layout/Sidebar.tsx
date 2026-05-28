'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import {
  LayoutDashboard, ShoppingCart, Handshake, Landmark, Banknote,
  ClipboardList, Settings, ShieldCheck, LogOut, Building2, Store,
  PackageSearch,
} from 'lucide-react';
import { useAuth } from '@/hooks/useAuth';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { cn } from '@/lib/utils';
import { ROUTES } from '@/lib/constants';
import { api } from '@/lib/api';

type NavItem = {
  label: string;
  href: string;
  icon: React.ElementType;
  roles?: ('BUYER' | 'SELLER' | 'BOTH' | 'ADMIN')[];
};

const navItems: NavItem[] = [
  { label: 'Dashboard',       href: ROUTES.DASHBOARD,       icon: LayoutDashboard },
  { label: 'Marketplace',     href: ROUTES.MARKETPLACE,     icon: ShoppingCart,    roles: ['BUYER'] },
  { label: 'Seller Profile',  href: ROUTES.SELLER_PROFILE,  icon: Store,           roles: ['SELLER'] },
  { label: 'Catalogue',       href: '/marketplace/catalogue', icon: PackageSearch,  roles: ['SELLER'] },
  { label: 'Negotiations',    href: ROUTES.NEGOTIATIONS,    icon: Handshake },
  { label: 'Escrow',          href: ROUTES.ESCROW,          icon: Landmark },
  { label: 'Treasury',        href: ROUTES.TREASURY,        icon: Banknote,    roles: ['ADMIN'] },
  { label: 'Compliance',      href: ROUTES.COMPLIANCE,      icon: ClipboardList, roles: ['ADMIN'] },
  { label: 'Settings',        href: ROUTES.SETTINGS,        icon: Settings },
];

const adminItem: NavItem = { label: 'Admin', href: ROUTES.ADMIN, icon: ShieldCheck, roles: ['ADMIN'] };

const TRADE_ROLE_BADGE: Record<string, { label: string; className: string }> = {
  BUYER:  { label: 'Buyer',          className: 'bg-blue-50 text-blue-700 border-blue-200' },
  SELLER: { label: 'Seller',         className: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  BOTH:   { label: 'Buyer & Seller', className: 'bg-amber-50 text-amber-700 border-amber-200' },
};

export function Sidebar({ onNavClick }: { onNavClick?: () => void } = {}) {
  const pathname = usePathname();
  const { enterprise, user, logout, isAdmin, isSeller } = useAuth();
  const tradeRole = enterprise?.trade_role;

  // Poll for pending escrow approvals (sellers only) — drives badge count
  const { data: escrows = [] } = useQuery<any[]>({
    queryKey: ['escrows-sidebar'],
    queryFn: () =>
      api.get('/v1/escrow').then(r => r.data.data).catch(() => []),
    refetchInterval: 10000,
    enabled: isSeller,
  });

  const pendingApprovals = isSeller
    ? escrows.filter((e: any) => e.status === 'PENDING_APPROVAL').length
    : 0;

  const visibleItems = navItems.filter((item) => {
    if (isAdmin) return item.href === ROUTES.DASHBOARD;
    if (!item.roles) return true;
    if (tradeRole === 'BOTH') {
      return item.roles.includes('BUYER') || item.roles.includes('SELLER') || item.roles.includes('BOTH');
    }
    if (tradeRole === 'BUYER') return item.roles.includes('BUYER');
    if (tradeRole === 'SELLER') return item.roles.includes('SELLER');
    return !item.roles.includes('ADMIN');
  });

  const allItems = isAdmin ? [...visibleItems, adminItem] : visibleItems;

  return (
    <aside className="w-60 min-h-screen bg-background border-r border-hairline flex flex-col shrink-0">

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
          const isEscrow = href === ROUTES.ESCROW;
          const badge = isEscrow && pendingApprovals > 0 ? pendingApprovals : 0;

          return (
            <Link
              key={href}
              href={href}
              onClick={onNavClick}
              className={cn(
                'flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                isActive
                  ? 'bg-surface-soft text-ink font-medium'
                  : 'text-body hover:bg-surface-soft hover:text-ink'
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="flex-1">{label}</span>
              {badge > 0 && (
                <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-[#0a2e0e] text-white dark:bg-[#5ab98a] dark:text-[#0a2e0e] leading-none">
                  {badge}
                </span>
              )}
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
