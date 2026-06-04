import { render, screen } from '@testing-library/react';
import { StatusBadge } from '@/components/shared/StatusBadge';

describe('StatusBadge', () => {
  const knownStatuses = [
    { status: 'DRAFT', label: 'Draft' },
    { status: 'PARSED', label: 'Parsed' },
    { status: 'PARSE_FAILED', label: 'Parse Failed' },
    { status: 'MATCHED', label: 'Matched' },
    { status: 'NEGOTIATING', label: 'Negotiating' },
    { status: 'CONFIRMED', label: 'Confirmed' },
    { status: 'AGREED', label: 'Agreed' },
    { status: 'WALK_AWAY', label: /walk|not selected/i },
    { status: 'CLOSED_BY_BUYER', label: 'Buyer Selected Other' },
    { status: 'PENDING_APPROVAL', label: 'Pending Approval' },
    { status: 'DEPLOYED', label: 'Deployed' },
    { status: 'FUNDED', label: 'Funded' },
    { status: 'RELEASED', label: 'Released' },
    { status: 'REJECTED', label: 'Rejected' },
    { status: 'FROZEN', label: 'Frozen' },
    { status: 'REFUNDED', label: 'Refunded' },
  ];

  knownStatuses.forEach(({ status, label }) => {
    it(`renders correct badge for ${status}`, () => {
      render(<StatusBadge status={status} />);
      if (typeof label === 'string') {
        expect(screen.getByText(label)).toBeInTheDocument();
      } else {
        expect(screen.getByText(label)).toBeInTheDocument();
      }
    });
  });

  it('falls back gracefully for unknown status', () => {
    render(<StatusBadge status="UNKNOWN_STATUS" />);
    expect(screen.getByText('UNKNOWN_STATUS')).toBeInTheDocument();
  });

  it('supports md size', () => {
    const { container } = render(<StatusBadge status="AGREED" size="md" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('text-sm');
  });

  it('uses sm size by default', () => {
    const { container } = render(<StatusBadge status="AGREED" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('text-xs');
  });
});
