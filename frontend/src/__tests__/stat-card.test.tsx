import { render, screen } from '@testing-library/react';
import { StatCard } from '@/components/shared/StatCard';
import { FileText } from 'lucide-react';

describe('StatCard', () => {
  it('renders label and value', () => {
    render(<StatCard label="Active RFQs" value={5} icon={FileText} />);
    expect(screen.getByText('Active RFQs')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('handles zero values', () => {
    render(<StatCard label="Pending" value={0} icon={FileText} />);
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('renders string values', () => {
    render(<StatCard label="Total" value="$1,234" icon={FileText} />);
    expect(screen.getByText('$1,234')).toBeInTheDocument();
  });

  it('shows loading skeleton when isLoading', () => {
    const { container } = render(
      <StatCard label="Active" value={3} icon={FileText} isLoading />
    );
    // Should have pulse animation div
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('renders trend indicator', () => {
    render(
      <StatCard
        label="Test"
        value={10}
        icon={FileText}
        trend={{ value: '+5%', direction: 'up' }}
      />
    );
    expect(screen.getByText('+5%')).toBeInTheDocument();
  });

  it('is clickable when onClick provided', () => {
    const onClick = jest.fn();
    render(<StatCard label="Test" value={1} icon={FileText} onClick={onClick} />);
    const card = screen.getByText('Test').closest('div');
    card?.click();
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
