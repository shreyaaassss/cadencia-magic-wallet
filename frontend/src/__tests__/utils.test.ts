/**
 * Unit tests for frontend utility functions.
 * Tests: formatCurrency, formatDate, formatDateTime, truncateAddress, cn.
 */

import { cn, formatCurrency, formatDate, formatDateTime, truncateAddress } from '@/lib/utils';

// ═══════════════════════════════════════════════════════════════════════════
// formatCurrency
// ═══════════════════════════════════════════════════════════════════════════

describe('formatCurrency', () => {
  it('formats INR with Indian number grouping', () => {
    const result = formatCurrency(1250000);
    expect(result).toContain('12,50,000');
  });

  it('formats zero correctly', () => {
    const result = formatCurrency(0);
    expect(result).toContain('0');
  });

  it('formats small amounts', () => {
    const result = formatCurrency(500);
    expect(result).toContain('500');
  });

  it('handles negative amounts', () => {
    const result = formatCurrency(-5000);
    expect(result).toContain('5,000');
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// formatDate
// ═══════════════════════════════════════════════════════════════════════════

describe('formatDate', () => {
  it('formats ISO date string to IST', () => {
    const result = formatDate('2026-06-10T12:00:00Z');
    expect(result).toMatch(/10.*Jun.*2026/);
  });

  it('handles midnight UTC correctly in IST', () => {
    // Midnight UTC is 5:30 AM IST — still same date
    const result = formatDate('2026-06-10T00:00:00Z');
    expect(result).toMatch(/10.*Jun.*2026/);
  });

  it('handles late UTC correctly in IST', () => {
    // 11:30 PM UTC is 5:00 AM next day IST
    const result = formatDate('2026-06-10T23:30:00Z');
    expect(result).toMatch(/11.*Jun.*2026/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// formatDateTime
// ═══════════════════════════════════════════════════════════════════════════

describe('formatDateTime', () => {
  it('includes time in output', () => {
    const result = formatDateTime('2026-06-10T14:30:00Z');
    // 14:30 UTC = 8:00 PM IST
    expect(result).toMatch(/10.*Jun.*2026/);
    expect(result).toMatch(/[0-9]{1,2}:[0-9]{2}/); // has time
  });

  it('uses IST timezone', () => {
    // 00:00 UTC = 05:30 IST
    const result = formatDateTime('2026-01-15T00:00:00Z');
    expect(result).toMatch(/5:30/);
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// truncateAddress
// ═══════════════════════════════════════════════════════════════════════════

describe('truncateAddress', () => {
  it('truncates long Algorand address', () => {
    const addr = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const result = truncateAddress(addr);
    expect(result).toContain('...');
    expect(result.length).toBeLessThan(addr.length);
  });

  it('returns short strings unchanged', () => {
    expect(truncateAddress('ABC')).toBe('ABC');
  });

  it('handles empty string', () => {
    expect(truncateAddress('')).toBe('');
  });

  it('respects custom char count', () => {
    const addr = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    const result = truncateAddress(addr, 4);
    expect(result).toBe('ABCD...WXYZ');
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// cn (classname merge)
// ═══════════════════════════════════════════════════════════════════════════

describe('cn', () => {
  it('merges class strings', () => {
    expect(cn('foo', 'bar')).toBe('foo bar');
  });

  it('handles conditional classes', () => {
    const active = true;
    expect(cn('base', active && 'active')).toBe('base active');
    expect(cn('base', !active && 'active')).toBe('base');
  });

  it('deduplicates tailwind classes', () => {
    expect(cn('p-4', 'p-6')).toBe('p-6');
  });

  it('handles undefined and null', () => {
    expect(cn('foo', undefined, null, 'bar')).toBe('foo bar');
  });
});
