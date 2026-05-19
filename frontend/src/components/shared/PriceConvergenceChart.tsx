'use client';

import * as React from 'react';
import { formatCurrency } from '@/lib/utils';

interface PriceConvergenceChartProps {
  buyerOffers: number[];
  sellerOffers: number[];
}

export function PriceConvergenceChart({ buyerOffers, sellerOffers }: PriceConvergenceChartProps) {
  const [hoveredPoint, setHoveredPoint] = React.useState<{ x: number; y: number; price: number; label: string } | null>(null);

  const allPrices = [...buyerOffers, ...sellerOffers];
  if (allPrices.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-52 gap-3 text-muted-foreground">
        <svg className="h-12 w-12 opacity-20" viewBox="0 0 48 48" fill="none">
          <path d="M6 36 L14 24 L22 28 L30 16 L38 20 L42 12" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        <p className="text-sm">No offer data yet</p>
      </div>
    );
  }

  const svgW = 640;
  const svgH = 240;
  const padX = 72;
  const padY = 24;
  const chartW = svgW - padX * 2;
  const chartH = svgH - padY * 2;

  const buffer = (Math.max(...allPrices) - Math.min(...allPrices)) * 0.1 || Math.max(...allPrices) * 0.05;
  const minPrice = Math.min(...allPrices) - buffer;
  const maxPrice = Math.max(...allPrices) + buffer;
  const priceRange = maxPrice - minPrice || 1;
  const maxRounds = Math.max(buyerOffers.length, sellerOffers.length);
  const totalPoints = Math.max(maxRounds, 2);

  const toX = (idx: number) => padX + (idx / (totalPoints - 1)) * chartW;
  const toY = (price: number) => padY + chartH - ((price - minPrice) / priceRange) * chartH;

  // Build path strings
  const buyerPath = buyerOffers.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(p)}`).join(' ');
  const sellerPath = sellerOffers.map((p, i) => `${i === 0 ? 'M' : 'L'}${toX(i)},${toY(p)}`).join(' ');

  // ZOPA shaded region: between buyer and seller prices where they overlap
  const zopaPoints: string[] = [];
  const minLen = Math.min(buyerOffers.length, sellerOffers.length);
  if (minLen >= 2) {
    // Top edge: seller prices going forward
    sellerOffers.slice(0, minLen).forEach((p, i) => {
      zopaPoints.push(`${i === 0 ? 'M' : 'L'}${toX(i)},${toY(p)}`);
    });
    // Bottom edge: buyer prices going backward
    buyerOffers.slice(0, minLen).reverse().forEach((p, i) => {
      zopaPoints.push(`L${toX(minLen - 1 - i)},${toY(p)}`);
    });
    zopaPoints.push('Z');
  }

  // Y-axis ticks
  const yTicks = 5;
  const yLabels = Array.from({ length: yTicks }, (_, i) => {
    const price = minPrice + (priceRange / (yTicks - 1)) * i;
    return { price, y: toY(price) };
  });

  // Gap calculation
  const lastBuyer = buyerOffers[buyerOffers.length - 1];
  const lastSeller = sellerOffers[sellerOffers.length - 1];
  const gap = lastBuyer && lastSeller
    ? Math.abs(lastSeller - lastBuyer) / Math.min(lastBuyer, lastSeller) * 100
    : null;
  const gapColor = gap === null ? '#6b7280' : gap <= 2 ? '#22c55e' : gap <= 5 ? '#10b981' : gap <= 10 ? '#f59e0b' : '#ef4444';

  return (
    <div className="w-full space-y-3">
      {/* Gap summary bar */}
      {gap !== null && (
        <div className="flex items-center justify-between px-1 text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span className="font-medium" style={{ color: '#3b82f6' }}>S: {formatCurrency(lastSeller)}</span>
            <span className="text-muted-foreground/40">←</span>
            <span className="font-bold tabular-nums px-2 py-0.5 rounded text-[11px] border" style={{ color: gapColor, borderColor: gapColor + '40', backgroundColor: gapColor + '12' }}>
              {gap.toFixed(1)}% gap
            </span>
            <span className="text-muted-foreground/40">→</span>
            <span className="font-medium" style={{ color: '#10b981' }}>B: {formatCurrency(lastBuyer)}</span>
          </div>
          <span className="text-muted-foreground/50 text-[10px]">{Math.max(buyerOffers.length, sellerOffers.length)} rounds</span>
        </div>
      )}

      <div className="w-full overflow-x-auto rounded-lg border border-border bg-card/50">
        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          className="w-full h-auto min-w-[380px]"
          preserveAspectRatio="xMidYMid meet"
          onMouseLeave={() => setHoveredPoint(null)}
        >
          <defs>
            <linearGradient id="buyerGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.15" />
              <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
            </linearGradient>
            <linearGradient id="sellerGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#3b82f6" stopOpacity="0" />
              <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.15" />
            </linearGradient>
          </defs>

          {/* Grid lines */}
          {yLabels.map(({ price, y }) => (
            <g key={price}>
              <line x1={padX} y1={y} x2={svgW - padX} y2={y} stroke="hsl(var(--border))" strokeWidth="1" strokeDasharray="3 5" opacity="0.6" />
              <text x={padX - 10} y={y + 4} textAnchor="end" fontSize="10" fill="hsl(var(--muted-foreground))" opacity="0.7">
                {price >= 100000 ? `₹${(price / 100000).toFixed(1)}L` : `₹${(price / 1000).toFixed(0)}K`}
              </text>
            </g>
          ))}

          {/* X-axis labels */}
          {Array.from({ length: Math.min(maxRounds, 12) }, (_, i) => {
            const step = Math.max(1, Math.floor(maxRounds / 12));
            const idx = i * step;
            if (idx >= maxRounds) return null;
            return (
              <text key={i} x={toX(idx)} y={svgH - 6} textAnchor="middle" fontSize="9" fill="hsl(var(--muted-foreground))" opacity="0.6">
                R{idx + 1}
              </text>
            );
          })}

          {/* ZOPA shaded region */}
          {zopaPoints.length > 0 && (
            <path
              d={zopaPoints.join(' ')}
              fill="hsl(var(--primary))"
              fillOpacity="0.04"
              stroke="hsl(var(--primary))"
              strokeOpacity="0.15"
              strokeWidth="1"
              strokeDasharray="4 4"
            />
          )}

          {/* Seller fill area */}
          {sellerOffers.length > 1 && (
            <path
              d={`${sellerPath} L${toX(sellerOffers.length - 1)},${svgH - padY} L${toX(0)},${svgH - padY} Z`}
              fill="url(#sellerGrad)"
            />
          )}

          {/* Buyer fill area */}
          {buyerOffers.length > 1 && (
            <path
              d={`${buyerPath} L${toX(buyerOffers.length - 1)},${svgH - padY} L${toX(0)},${svgH - padY} Z`}
              fill="url(#buyerGrad)"
            />
          )}

          {/* Seller line */}
          {sellerOffers.length > 1 && (
            <path d={sellerPath} fill="none" stroke="#3b82f6" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          )}

          {/* Buyer line */}
          {buyerOffers.length > 1 && (
            <path d={buyerPath} fill="none" stroke="#10b981" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          )}

          {/* Seller dots */}
          {sellerOffers.map((p, i) => (
            <circle
              key={`s${i}`} cx={toX(i)} cy={toY(p)} r={i === sellerOffers.length - 1 ? 5 : 3.5}
              fill={i === sellerOffers.length - 1 ? '#3b82f6' : 'hsl(var(--card))'}
              stroke="#3b82f6" strokeWidth="2"
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHoveredPoint({ x: toX(i), y: toY(p), price: p, label: `Seller R${i + 1}` })}
            />
          ))}

          {/* Buyer dots */}
          {buyerOffers.map((p, i) => (
            <circle
              key={`b${i}`} cx={toX(i)} cy={toY(p)} r={i === buyerOffers.length - 1 ? 5 : 3.5}
              fill={i === buyerOffers.length - 1 ? '#10b981' : 'hsl(var(--card))'}
              stroke="#10b981" strokeWidth="2"
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setHoveredPoint({ x: toX(i), y: toY(p), price: p, label: `Buyer R${i + 1}` })}
            />
          ))}

          {/* Hover tooltip */}
          {hoveredPoint && (
            <g>
              <rect
                x={Math.min(hoveredPoint.x - 40, svgW - padX - 80)}
                y={hoveredPoint.y - 36}
                width="80" height="26" rx="5"
                fill="hsl(var(--card))" stroke="hsl(var(--border))" strokeWidth="1"
              />
              <text
                x={Math.min(hoveredPoint.x, svgW - padX - 40)}
                y={hoveredPoint.y - 18}
                textAnchor="middle" fontSize="9" fill="hsl(var(--muted-foreground))"
              >
                {hoveredPoint.label}
              </text>
              <text
                x={Math.min(hoveredPoint.x, svgW - padX - 40)}
                y={hoveredPoint.y - 8}
                textAnchor="middle" fontSize="10" fill="hsl(var(--foreground))" fontWeight="600"
              >
                {formatCurrency(hoveredPoint.price)}
              </text>
              <line
                x1={hoveredPoint.x} y1={hoveredPoint.y + 6}
                x2={hoveredPoint.x} y2={svgH - padY}
                stroke="hsl(var(--border))" strokeWidth="1" strokeDasharray="2 3"
              />
            </g>
          )}
        </svg>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6">
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 rounded" style={{ background: '#3b82f6' }} />
          <span className="text-xs text-muted-foreground">Seller</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 rounded" style={{ background: '#10b981' }} />
          <span className="text-xs text-muted-foreground">Buyer</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-1 rounded opacity-50" style={{ background: 'hsl(var(--primary))', border: '1px dashed hsl(var(--primary))' }} />
          <span className="text-xs text-muted-foreground">ZOPA</span>
        </div>
      </div>
    </div>
  );
}
