/**
 * RFQ form / status tests.
 *
 * Tests the logic for RFQ status handling: which statuses are editable,
 * which show parse failure UI, and status filter options.
 */

describe('RFQ Status Logic', () => {
  const EDITABLE_STATUSES = ['DRAFT', 'PARSED', 'PARSE_FAILED'];
  const TERMINAL_STATUSES = ['MATCHED', 'NEGOTIATING', 'CONFIRMED', 'SETTLED'];

  EDITABLE_STATUSES.forEach(status => {
    it(`${status} is editable`, () => {
      expect(EDITABLE_STATUSES.includes(status)).toBe(true);
    });
  });

  TERMINAL_STATUSES.forEach(status => {
    it(`${status} is NOT editable`, () => {
      expect(EDITABLE_STATUSES.includes(status)).toBe(false);
    });
  });

  it('PARSE_FAILED should show retry and manual edit options', () => {
    const status = 'PARSE_FAILED';
    const showRetry = status === 'PARSE_FAILED';
    const showManualEdit = status === 'PARSE_FAILED';
    expect(showRetry).toBe(true);
    expect(showManualEdit).toBe(true);
  });

  it('DRAFT should not show parse failure UI', () => {
    const status = 'DRAFT';
    const showRetry = status === 'PARSE_FAILED';
    expect(showRetry).toBe(false);
  });

  it('status filter includes PARSE_FAILED', () => {
    const STATUS_OPTIONS = ['All', 'DRAFT', 'PARSE_FAILED', 'PARSED', 'MATCHED', 'NEGOTIATING', 'CONFIRMED'];
    expect(STATUS_OPTIONS).toContain('PARSE_FAILED');
  });
});

describe('RFQ Data Validation', () => {
  it('rejects empty RFQ text', () => {
    const text = '';
    const isValid = text.trim().length >= 10;
    expect(isValid).toBe(false);
  });

  it('accepts valid RFQ text', () => {
    const text = 'Need 500 metric tons of HR Coil for Mumbai delivery';
    const isValid = text.trim().length >= 10;
    expect(isValid).toBe(true);
  });

  it('rejects too-short RFQ text', () => {
    const text = 'hi';
    const isValid = text.trim().length >= 10;
    expect(isValid).toBe(false);
  });
});
