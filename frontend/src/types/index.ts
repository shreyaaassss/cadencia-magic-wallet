// ─── Auth & Users ──────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'ADMIN' | 'MEMBER';
  enterprise_id: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  enterprise_id: string | null;
  user_id: string | null;
}

export interface Enterprise {
  id: string;
  legal_name: string;
  pan: string;
  gstin: string;
  trade_role: 'BUYER' | 'SELLER' | 'BOTH';
  kyc_status: 'NOT_SUBMITTED' | 'PENDING' | 'ACTIVE' | 'REJECTED';
  industry_vertical: string;
  geography: string;
  commodities: string[];
  min_order_value: number;
  max_order_value: number;
  algorand_wallet: string | null;
  agent_config: AgentConfig | null;
}

export interface AgentConfig {
  negotiation_style: 'AGGRESSIVE' | 'MODERATE' | 'CONSERVATIVE';
  max_rounds: number;
  auto_escalate: boolean;
  min_acceptable_price: number | null;
}

export interface ApiKey {
  id: string;
  label: string | null;
  created_at: string;
  last_used?: string | null;
}

export interface ApiKeyCreateResponse {
  id: string;
  key: string;
  label: string | null;
  created_at: string;
  message: string;
}

// ─── Wallet ────────────────────────────────────────────────────────────────

export interface WalletChallenge {
  challenge: string;
  enterprise_id: string;
  expires_at: string;
}

export interface WalletBalance {
  algorand_address: string;
  algo_balance_microalgo: number;
  algo_balance_algo: string;
  min_balance: number;
  available_balance: number;
  opted_in_apps: OptedInApp[];
}

export interface OptedInApp {
  app_id: number;
  app_name: string | null;
}

// ─── RFQ & Marketplace ─────────────────────────────────────────────────────

export type RFQStatus = 'DRAFT' | 'PARSING' | 'PARSED' | 'MATCHED' | 'NEGOTIATING' | 'CONFIRMED' | 'REJECTED';

export interface RFQ {
  id: string;
  raw_text: string;
  status: RFQStatus;
  parsed_fields: Record<string, string> | null;
  created_at: string;
}

export interface RFQSubmitResponse {
  rfq_id: string;
  status: string;
  message: string;
}

export interface SellerMatch {
  enterprise_id: string;
  enterprise_name: string;
  score: number;
  rank: number;
  capabilities?: string[];
}

export interface CapabilityProfile {
  industry: string;
  geographies: string[];
  products: string[];
  min_order_value: number;
  max_order_value: number;
  description: string;
  embedding_status: 'active' | 'queued' | 'failed' | 'outdated';
  last_embedded: string | null;
}

// ─── Negotiation Sessions ──────────────────────────────────────────────────

export type SessionStatus =
  | 'ACTIVE'
  | 'AGREED'
  | 'WALK_AWAY'
  | 'TIMEOUT'
  | 'POLICY_BREACH'
  | 'FAILED'
  | 'TERMINATED';

export interface NegotiationSession {
  session_id: string;
  rfq_id: string;
  match_id: string;
  buyer_enterprise_id: string;
  seller_enterprise_id: string;
  status: SessionStatus;
  agreed_price: number | null;
  agreed_currency: string | null;
  agreed_terms: Record<string, unknown> | null;
  round_count: number;
  offers: NegotiationOffer[];
  created_at: string;
  completed_at: string | null;
  expires_at: string;
  schema_failure_count: number;
  stall_counter: number;
  deal_quality_score?: Record<string, unknown> | null;
  product_context?: {
    product?: string;
    quantity?: number;
    budget_max?: number;
    budget_min?: number;
    budget_per_unit?: number;
  } | null;
  // Enriched by list endpoint
  buyer_name?: string;
  seller_name?: string;
}

export interface NegotiationOffer {
  offer_id: string;
  session_id: string;
  round_number: number;
  proposer_role: 'BUYER' | 'SELLER';
  price: number;
  currency: string;
  terms: Record<string, unknown>;
  confidence: number | null;
  is_human_override: boolean;
  agent_reasoning?: string;
  created_at: string;
}

// ─── Escrow ────────────────────────────────────────────────────────────────

export type EscrowStatus = 'PENDING_APPROVAL' | 'APPROVED' | 'DEPLOYED' | 'FUNDED' | 'DISPATCHED' | 'RELEASED' | 'REFUNDED' | 'FROZEN' | 'REJECTED' | 'NOT_DEPLOYED';

export interface Escrow {
  escrow_id: string;
  session_id: string;
  algo_app_id: number | null;
  algo_app_address: string | null;
  amount_microalgo: number;
  amount_algo: number;
  status: EscrowStatus;
  frozen: boolean;
  deploy_tx_id: string | null;
  fund_tx_id: string | null;
  release_tx_id: string | null;
  refund_tx_id: string | null;
  merkle_root: string | null;
  created_at: string;
  settled_at: string | null;
  buyer_algorand_address: string | null;
  seller_algorand_address: string | null;
  // Enriched fields
  buyer_name?: string;
  seller_name?: string;
}


export interface Settlement {
  settlement_id: string;
  escrow_id: string;
  milestone_index: number;
  amount_microalgo: number;
  tx_id: string;
  settled_at: string;
}

export interface DeployEscrowResponse {
  escrow_id: string;
  algo_app_id: number | null;
  algo_app_address: string | null;
  status: string;
  tx_id: string | null;
}

export interface BuildFundTxnResponse {
  unsigned_transactions: string[];
  group_id: string;
  transaction_count: number;
  description: string;
}

export interface SubmitSignedFundResponse {
  txid: string;
  confirmed_round: number;
}

// ─── Compliance ────────────────────────────────────────────────────────────

export interface AuditEntry {
  entry_id: string;
  escrow_id: string;
  sequence_no: number;
  event_type: string;
  payload_json: string;
  prev_hash: string;
  entry_hash: string;
  created_at: string;
}

export interface AuditLogPage {
  entries: AuditEntry[];
  next_cursor: string | null;
}

export interface AuditChainVerifyResponse {
  valid: boolean;
  entry_count: number;
  first_invalid_sequence_no: number | null;
}

export interface FEMARecord {
  record_id: string;
  escrow_id: string;
  form_type: '15CA' | '15CB';
  purpose_code: string;
  buyer_pan: string;
  seller_pan: string;
  amount_inr: number;
  amount_algo: number;
  fx_rate_inr_per_algo: number;
  merkle_root: string;
  generated_at: string;
}

export interface GSTRecord {
  record_id: string;
  escrow_id: string;
  hsn_code: string;
  buyer_gstin: string;
  seller_gstin: string;
  tax_type: 'IGST' | 'CGST_SGST';
  taxable_amount: number;
  igst_amount: number;
  cgst_amount: number;
  sgst_amount: number;
  total_tax: number;
  generated_at: string;
}

export interface ExportJob {
  job_id: string;
  status: string;
  redis_key: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

// ─── Admin ─────────────────────────────────────────────────────────────────

export interface AdminStats {
  total_enterprises: number;
  active_enterprises: number;
  total_users: number;
  active_sessions: number;
  total_escrow_value: number;
  pending_kyc: number;
  pending_escrows: number;
  llm_calls_today: number;
  avg_negotiation_rounds: number;
  success_rate: number;
}

export interface AdminEnterpriseItem {
  id: string;
  legal_name: string;
  kyc_status: string;
  trade_role: string;
  user_count: number;
  created_at: string;
}

export interface AdminUserItem {
  id: string;
  full_name: string;
  email: string;
  role: 'ADMIN' | 'MEMBER';
  enterprise_id: string;
  enterprise_name: string;
  status: 'ACTIVE' | 'SUSPENDED';
  last_login: string | null;
}

export interface AdminAgentItem {
  session_id: string;
  status: 'RUNNING' | 'PAUSED';
  current_round: number;
  model: string;
  latency_ms: number;
  buyer: string;
  seller: string;
  started_at: string;
}

export interface LLMLogItem {
  id: string;
  session_id: string;
  round: number;
  agent: 'BUYER' | 'SELLER';
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  latency_ms: number;
  status: 'SUCCESS' | 'TIMEOUT' | 'ERROR';
  created_at: string;
  prompt_summary: string;
  response_summary: string | null;
}

export interface PendingEscrowItem {
  escrow_id: string;
  session_id: string;
  buyer_name: string;
  seller_name: string;
  agreed_price_inr: number | null;
  amount_microalgo: number;
  amount_algo: number;
  status: string;
  created_at: string;
}

// ─── Treasury ──────────────────────────────────────────────────────────────

export interface FXRateInfo {
  INR_USD: string;
  updated_at: string;
}

export interface TreasuryDashboard {
  inr_pool_balance: string;
  usdc_pool_balance: string;
  algo_pool_balance_microalgo: number;
  algo_pool_balance_algo: string;
  current_fx_rate: FXRateInfo;
  total_value_inr: string;
  open_fx_positions: number;
}

export interface FXPositionItem {
  position_id: string;
  pair: string;
  direction: string;
  notional: string;
  entry_rate: string;
  current_rate: string;
  unrealized_pnl: string;
}

export interface FXExposure {
  open_positions: FXPositionItem[];
  total_unrealized_pnl: string;
  position_count: number;
}

export interface ForecastDay {
  date: string;
  projected_inr_balance: string;
  projected_usdc_balance: string;
}

export interface LiquidityForecast {
  forecast: ForecastDay[];
  runway_days: number;
  alert: string | null;
  current_inr_balance: string;
  current_usdc_balance: string;
  estimated_daily_burn_inr: string;
}

// ─── Health ────────────────────────────────────────────────────────────────

export interface HealthResponse {
  overall: string;
  services: Record<string, string>;
  timestamp: string;
}

// ─── API Response Envelope ─────────────────────────────────────────────────

export interface ApiResponse<T> {
  status: 'success' | 'error';
  data: T;
}

export interface ApiErrorResponse {
  status: 'error';
  detail: string;
}
