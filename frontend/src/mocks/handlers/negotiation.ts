import { http, HttpResponse } from 'msw';

const ALL_SESSIONS = [
  {
    session_id: 'sess-001', rfq_id: 'rfq-001', match_id: 'match-001',
    buyer_enterprise_id: 'ent-001', seller_enterprise_id: 'ent-002',
    buyer_name: 'Tata Steel Ltd', seller_name: 'JSW Steel Ltd',
    status: 'ACTIVE', round_count: 5, agreed_price: null, agreed_currency: null, agreed_terms: null,
    offers: [], created_at: '2026-04-01T12:00:00Z', completed_at: null,
    expires_at: '2026-04-08T12:00:00Z', schema_failure_count: 0, stall_counter: 0,
  },
  {
    session_id: 'sess-002', rfq_id: 'rfq-002', match_id: 'match-002',
    buyer_enterprise_id: 'ent-001', seller_enterprise_id: 'ent-003',
    buyer_name: 'Tata Steel Ltd', seller_name: 'SAIL Corp',
    status: 'AGREED', round_count: 12, agreed_price: 4050000, agreed_currency: 'INR', agreed_terms: {},
    offers: [], created_at: '2026-03-31T09:00:00Z', completed_at: '2026-03-31T15:00:00Z',
    expires_at: '2026-04-07T09:00:00Z', schema_failure_count: 0, stall_counter: 0,
  },
  {
    session_id: 'sess-003', rfq_id: 'rfq-003', match_id: 'match-003',
    buyer_enterprise_id: 'ent-004', seller_enterprise_id: 'ent-001',
    buyer_name: 'Hindalco Ltd', seller_name: 'Tata Steel Ltd',
    status: 'WALK_AWAY', round_count: 8, agreed_price: null, agreed_currency: null, agreed_terms: null,
    offers: [], created_at: '2026-03-30T14:00:00Z', completed_at: '2026-03-30T18:00:00Z',
    expires_at: '2026-04-06T14:00:00Z', schema_failure_count: 0, stall_counter: 2,
  },
  {
    session_id: 'sess-004', rfq_id: 'rfq-001', match_id: 'match-004',
    buyer_enterprise_id: 'ent-001', seller_enterprise_id: 'ent-005',
    buyer_name: 'Tata Steel Ltd', seller_name: 'Arcelor Mittal India',
    status: 'TIMEOUT', round_count: 20, agreed_price: null, agreed_currency: null, agreed_terms: null,
    offers: [], created_at: '2026-04-02T16:00:00Z', completed_at: '2026-04-03T16:00:00Z',
    expires_at: '2026-04-09T16:00:00Z', schema_failure_count: 0, stall_counter: 0,
  },
  {
    session_id: 'sess-005', rfq_id: 'rfq-002', match_id: 'match-005',
    buyer_enterprise_id: 'ent-001', seller_enterprise_id: 'ent-006',
    buyer_name: 'Tata Steel Ltd', seller_name: 'Jindal Stainless',
    status: 'ACTIVE', round_count: 3, agreed_price: null, agreed_currency: null, agreed_terms: null,
    offers: [], created_at: '2026-04-02T10:00:00Z', completed_at: null,
    expires_at: '2026-04-09T10:00:00Z', schema_failure_count: 0, stall_counter: 0,
  },
  {
    session_id: 'sess-006', rfq_id: 'rfq-003', match_id: 'match-006',
    buyer_enterprise_id: 'ent-007', seller_enterprise_id: 'ent-001',
    buyer_name: 'Ambuja Cements', seller_name: 'Tata Steel Ltd',
    status: 'AGREED', round_count: 10, agreed_price: 3800000, agreed_currency: 'INR', agreed_terms: {},
    offers: [], created_at: '2026-03-29T11:00:00Z', completed_at: '2026-03-29T17:00:00Z',
    expires_at: '2026-04-05T11:00:00Z', schema_failure_count: 0, stall_counter: 0,
  },
];

const MOCK_SESSION_DETAIL = {
  ...ALL_SESSIONS[0],
  offers: [
    { offer_id: 'off-001', session_id: 'sess-001', round_number: 1, proposer_role: 'SELLER', price: 44000, currency: 'INR', terms: { delivery: '45 days' }, confidence: 0.7, is_human_override: false, created_at: '2026-04-01T12:01:00Z' },
    { offer_id: 'off-002', session_id: 'sess-001', round_number: 2, proposer_role: 'BUYER', price: 38000, currency: 'INR', terms: { delivery: '30 days' }, confidence: 0.65, is_human_override: false, created_at: '2026-04-01T12:02:00Z' },
    { offer_id: 'off-003', session_id: 'sess-001', round_number: 3, proposer_role: 'SELLER', price: 42800, currency: 'INR', terms: { delivery: '40 days' }, confidence: 0.68, is_human_override: false, created_at: '2026-04-01T12:03:00Z' },
    { offer_id: 'off-004', session_id: 'sess-001', round_number: 4, proposer_role: 'BUYER', price: 39500, currency: 'INR', terms: { delivery: '30 days' }, confidence: 0.72, is_human_override: false, created_at: '2026-04-01T12:04:00Z' },
    { offer_id: 'off-005', session_id: 'sess-001', round_number: 5, proposer_role: 'SELLER', price: 41500, currency: 'INR', terms: { delivery: '35 days' }, confidence: 0.78, is_human_override: false, created_at: '2026-04-01T12:05:00Z' },
  ],
};

export const negotiationHandlers = [
  // GET all sessions (list)
  http.get('*/v1/sessions', ({ request }) => {
    const url = new URL(request.url);
    const statusFilter = url.searchParams.get('status');
    let filtered = ALL_SESSIONS;
    if (statusFilter) {
      filtered = filtered.filter(s => s.status === statusFilter);
    }
    return HttpResponse.json({
      status: 'success',
      data: filtered,
    });
  }),

  // GET session details
  http.get('*/v1/sessions/:session_id', ({ params }) => {
    const session = ALL_SESSIONS.find(s => s.session_id === params.session_id);
    if (!session) {
      return HttpResponse.json({ status: 'error', detail: 'Session not found' }, { status: 404 });
    }
    // Return with offers for detail view
    if (params.session_id === 'sess-001') {
      return HttpResponse.json({ status: 'success', data: MOCK_SESSION_DETAIL });
    }
    return HttpResponse.json({ status: 'success', data: { ...session, offers: [] } });
  }),

  // POST turn
  http.post('*/v1/sessions/:session_id/turn', () => HttpResponse.json({
    status: 'success',
    data: {
      offer_id: `off-${Date.now()}`, session_id: 'sess-001', round_number: 6,
      proposer_role: 'SELLER', price: 41500, currency: 'INR',
      terms: { delivery: '35 days' }, confidence: 0.82,
      is_human_override: false, created_at: new Date().toISOString(),
    },
  })),

  // POST override
  http.post('*/v1/sessions/:session_id/override', () => HttpResponse.json({
    status: 'success',
    data: {
      offer_id: `off-override-${Date.now()}`, session_id: 'sess-001', round_number: 6,
      proposer_role: 'BUYER', price: 40500, currency: 'INR',
      terms: { delivery: '30 days' }, confidence: null,
      is_human_override: true, created_at: new Date().toISOString(),
    },
  })),

  // POST terminate
  http.post('*/v1/sessions/:session_id/terminate', ({ params }) => HttpResponse.json({
    status: 'success',
    data: { terminated: true, session_id: params.session_id },
  })),
];
