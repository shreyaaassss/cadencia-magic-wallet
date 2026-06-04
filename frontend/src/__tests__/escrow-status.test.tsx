import { render, screen } from '@testing-library/react';
import { StatusBadge } from '@/components/shared/StatusBadge';

describe('Escrow Status Badges', () => {
  const escrowStatuses = [
    { status: 'PENDING_APPROVAL', expected: 'Pending Approval' },
    { status: 'DEPLOYED', expected: 'Deployed' },
    { status: 'FUNDED', expected: 'Funded' },
    { status: 'DISPATCHED', expected: 'Dispatched' },
    { status: 'RELEASED', expected: 'Released' },
    { status: 'REFUNDED', expected: 'Refunded' },
    { status: 'REJECTED', expected: 'Rejected' },
    { status: 'FROZEN', expected: 'Frozen' },
  ];

  escrowStatuses.forEach(({ status, expected }) => {
    it(`renders correct badge for escrow status ${status}`, () => {
      render(<StatusBadge status={status} />);
      expect(screen.getByText(expected)).toBeInTheDocument();
    });
  });

  it('PENDING_APPROVAL has amber styling', () => {
    const { container } = render(<StatusBadge status="PENDING_APPROVAL" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('amber');
  });

  it('RELEASED has green styling', () => {
    const { container } = render(<StatusBadge status="RELEASED" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('green');
  });

  it('FROZEN has red styling', () => {
    const { container } = render(<StatusBadge status="FROZEN" />);
    const badge = container.querySelector('span');
    expect(badge?.className).toContain('red');
  });
});
