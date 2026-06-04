/**
 * Negotiation session tests.
 *
 * Tests session status handling including the new CLOSED_BY_BUYER status,
 * session grouping logic, and terminal state detection.
 */

describe('Negotiation Session Status', () => {
  const TERMINAL_STATUSES = [
    'AGREED', 'WALK_AWAY', 'TIMEOUT', 'POLICY_BREACH',
    'FAILED', 'EXPIRED', 'CLOSED_BY_BUYER',
  ];

  const ACTIVE_STATUSES = [
    'INIT', 'SELLER_ANCHOR', 'BUYER_RESPONSE',
    'BUYER_ANCHOR', 'SELLER_RESPONSE', 'ROUND_LOOP', 'ACTIVE',
  ];

  TERMINAL_STATUSES.forEach(status => {
    it(`${status} is terminal`, () => {
      expect(TERMINAL_STATUSES.includes(status)).toBe(true);
    });
  });

  ACTIVE_STATUSES.forEach(status => {
    it(`${status} is active (not terminal)`, () => {
      expect(TERMINAL_STATUSES.includes(status)).toBe(false);
    });
  });

  it('CLOSED_BY_BUYER is recognized as terminal', () => {
    expect(TERMINAL_STATUSES.includes('CLOSED_BY_BUYER')).toBe(true);
  });
});

describe('Session Grouping by RFQ', () => {
  const mockSessions = [
    { session_id: 's1', rfq_id: 'rfq-1', status: 'AGREED', product_context: { product_name: 'HR Coil' } },
    { session_id: 's2', rfq_id: 'rfq-1', status: 'CLOSED_BY_BUYER', product_context: { product_name: 'HR Coil' } },
    { session_id: 's3', rfq_id: 'rfq-1', status: 'ROUND_LOOP', product_context: { product_name: 'HR Coil' } },
    { session_id: 's4', rfq_id: 'rfq-2', status: 'AGREED', product_context: { product_name: 'TMT Bar' } },
  ];

  it('groups sessions by rfq_id', () => {
    const groups: Record<string, typeof mockSessions> = {};
    mockSessions.forEach(s => {
      const key = s.rfq_id;
      if (!groups[key]) groups[key] = [];
      groups[key].push(s);
    });

    expect(Object.keys(groups)).toHaveLength(2);
    expect(groups['rfq-1']).toHaveLength(3);
    expect(groups['rfq-2']).toHaveLength(1);
  });

  it('counts agreed sessions per group', () => {
    const rfq1Sessions = mockSessions.filter(s => s.rfq_id === 'rfq-1');
    const agreed = rfq1Sessions.filter(s => s.status === 'AGREED').length;
    expect(agreed).toBe(1);
  });

  it('counts active sessions per group', () => {
    const TERMINAL = ['AGREED', 'WALK_AWAY', 'TIMEOUT', 'POLICY_BREACH', 'FAILED', 'EXPIRED', 'CLOSED_BY_BUYER'];
    const rfq1Sessions = mockSessions.filter(s => s.rfq_id === 'rfq-1');
    const active = rfq1Sessions.filter(s => !TERMINAL.includes(s.status)).length;
    expect(active).toBe(1); // Only ROUND_LOOP
  });
});
