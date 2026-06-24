/**
 * API client for backend communication
 */
import axios, { isAxiosError } from 'axios'

/**
 * Empty base URL = same-origin requests to `/api/...` (works with Vite dev proxy).
 * Set VITE_API_URL only when the API is on another origin (e.g. production).
 */
const API_BASE_URL = import.meta.env.VITE_API_URL ?? ''

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

/** FastAPI often puts a human-readable message in `detail`; surface it in Error.message for UI. */
function appendFastApiDetailToAxiosError(error: unknown): void {
  if (!isAxiosError(error)) return
  const data = error.response?.data as { detail?: unknown } | undefined
  const detail = data?.detail
  if (detail === undefined || detail === null) return
  let extra: string
  if (typeof detail === 'string') {
    extra = detail
  } else if (Array.isArray(detail)) {
    extra = detail
      .map((item) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          return String((item as { msg: string }).msg)
        }
        return JSON.stringify(item)
      })
      .join('; ')
  } else {
    extra = JSON.stringify(detail)
  }
  if (extra && !error.message.includes(extra)) {
    error.message = `${error.message}: ${extra}`
  }
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    appendFastApiDetailToAxiosError(error)
    return Promise.reject(error)
  }
)

// Types
export interface APICredential {
  id: number
  service_name: string
  key_name: string
  is_active: boolean
}

export interface AIModelSetting {
  id: number
  provider: string
  model_name: string
  is_default: boolean
  temperature?: number
  max_tokens?: number
}

export interface Warehouse {
  id: number
  shortname: string
  address: string
  country_code: string
}

export interface EmailTemplate {
  id: number
  name: string
  recipient_email: string
  subject: string
  body: string
}

export interface OCConnection {
  id: number
  name: string
  region: string
  environment: 'stage' | 'prod'
  oauth_base_url: string
  api_base_url: string
  signature_mode: 'path_only' | 'path_and_body'
  is_active: boolean
  updated_at: string
}

export interface InventoryStatusSummary {
  connection: OCConnection | null
  credentials_present: string[]
  has_required_credentials: boolean
  mapping_count: number
  last_sync_at: string | null
}

export interface OCSkuMapping {
  id: number
  sku_code: string
  seller_skuid: string
  reference_skuid: string
  mfskuid: string
  service_region: string | null
  last_synced_at: string
}

export interface OCSkuInventoryRow {
  id: number
  seller_skuid: string | null
  mfskuid: string
  service_region: string
  available: number
  in_transit: number
  received: number
  reserved_allocated: number
  reserved_hold: number
  reserved_vas: number
  suspend: number
  unfulfillable: number
  sold_3m_units: number
  sold_1m_units: number
  synced_at: string
}

/** OC GetStockMovement lines persisted in DB (POST /sync-stock-movement). */
export interface OCStockMovementRow {
  update_time: string
  mfskuid: string
  sku_code: string | null
  seller_skuid: string | null
  service_region: string
  inventory_status: string
  movement_id: string
  quantity: number
  actual_count: number | null
  reason: string | null
  order_number: string | null
}

export interface OCStockMovementResponse {
  rows: OCStockMovementRow[]
  from_date: string
  to_date: string
  row_count: number
  scope: 'filtered' | 'all_mapped_skus'
  mfskuid_count: number
  truncated: boolean
  line_limit: number | null
  note: string
}

/** Stock chart series from GetStockMovement (AVL actual_count). `in_transit` is always 0. */
export interface InventoryHistoryPoint {
  recorded_at: string
  available: number
  in_transit: number
  stockout: boolean
}

export interface InventoryHistorySeries {
  points: InventoryHistoryPoint[]
  from_date: string
  to_date: string
  opening_available: number
  opening_in_transit: number
  mfskuid_count: number
  scope: string
  note?: string | null
}

/** GET /api/inventory-status/stock-forecast — weighted burn over last 90 in-stock days; all mapped SKUs. */
export interface StockForecastRow {
  seller_skuid: string
  mfskuid: string
  sku_name: string
  service_region: string
  current_available: number
  burn_rate_per_day: number | null
  in_stock_days_used: number
  days_of_cover: number | null
  estimated_oos_date: string | null
  confidence: string
  total_sales_in_window: number | null
}

export interface StockForecastBundle {
  forecasts: StockForecastRow[]
  generated_at: string
  note: string
}

/** GET /api/inventory-status/debug-raw — StockSnapshot v2 + SKU query verbatim. */
export interface OCRawDebugResponse {
  connection: Record<string, unknown>
  snapshot_request: Record<string, unknown>
  snapshot_response: Record<string, unknown>
  sku_query_request: Record<string, unknown>
  sku_query_response: Record<string, unknown>
}

/** GET /api/inventory-status/debug/oc-movement-raw — GetStockMovement verbatim. */
export interface OCDebugMovementRawResponse {
  connection: Record<string, unknown>
  movement_endpoint: string
  movement_request: Record<string, unknown>
  movement_response: Record<string, unknown>
  flattened_row_count: number
  response_ok: boolean
  note: string
}

/** GET /api/inventory-status/debug/stock-movement-db — persisted movement row stats. */
export interface StoredMovementDbDebugResponse {
  connection_id: number
  total_rows: number
  earliest_update_utc: string | null
  latest_update_utc: string | null
  note: string
}

export interface OCInboundOrderRow {
  seller_inbound_number: string
  oc_inbound_number: string | null
  status: string | null
  warehouse_code: string | null
  region: string | null
  shipping_method: string | null
  sku_qty: number
  put_away_qty: number
  /** Parsed from OC when available (UTC-ish). */
  inbound_at: string | null
  /** When this row was last written from OC sync. */
  synced_at: string | null
  /** YYYY-MM-DD HH:MM:SS from OC raw, computed on the server (UTC). */
  create_time?: string | null
  putaway_time?: string | null
  arrived_time?: string | null
  /** User-entered tracking URL; not overwritten by OC sync. Shown as "Custom" in Courier column. */
  custom_courier_url?: string | null
  /** User-entered tracking number; not overwritten by OC sync. Shown in Tracking # column. */
  custom_tracking_number?: string | null
  /** Present when list was requested with include_raw=true: full OC row JSON from sync. */
  raw?: Record<string, unknown> | null
}

export interface InboundOrderStatusSlice {
  status: string
  count: number
}

export interface InboundOrderStatusSummary {
  from_date: string
  to_date: string
  total_orders: number
  slices: InboundOrderStatusSlice[]
  last_sync_at: string | null
}

/** GET /api/inventory-status/inbound-orders/lookup — full cached row + raw OC JSON for transparency. */
export interface InboundOrderLookup {
  request_method: string
  request_url: string
  oc_inbound_number: string
  seller_inbound_number: string | null
  status: string | null
  warehouse_code: string | null
  region: string | null
  shipping_method: string | null
  sku_qty: number
  put_away_qty: number
  inbound_at_db: string | null
  synced_at_db: string | null
  create_time: string | null
  putaway_time: string | null
  arrived_time: string | null
  has_raw_payload: boolean
  raw_oc_payload: Record<string, unknown> | null
  transparency: string
}

export interface InboundSyncResponse {
  synced: number
  message: string
  full: boolean
}

/** GET/PUT /api/inventory-status/inbound-orders/status-filter — persisted Status column filter. */
export interface InboundStatusFilter {
  excluded: string[]
}

// Settings API
export const settingsAPI = {
  // API Credentials
  createCredential: (data: {
    service_name: string
    key_name: string
    value: string
  }) => api.post<APICredential>('/api/settings/credentials', data),

  listCredentials: (service_name?: string) =>
    api.get<APICredential[]>('/api/settings/credentials', {
      params: service_name ? { service_name } : {},
    }),

  testCredentials: (service_name: string) =>
    api.get(`/api/settings/credentials/test/${service_name}`),

  deleteCredential: (id: number) =>
    api.delete(`/api/settings/credentials/${id}`),

  // AI Models
  createAIModel: (data: {
    provider: string
    model_name: string
    is_default: boolean
    temperature?: number
    max_tokens?: number
  }) => api.post<AIModelSetting>('/api/settings/ai-models', data),

  listAIModels: () => api.get<AIModelSetting[]>('/api/settings/ai-models'),

  getDefaultAIModel: () =>
    api.get<AIModelSetting>('/api/settings/ai-models/default'),

  setDefaultAIModel: (id: number) =>
    api.patch<AIModelSetting>(`/api/settings/ai-models/${id}/set-default`),

  deleteAIModel: (id: number) => api.delete(`/api/settings/ai-models/${id}`),

  // Warehouses
  createWarehouse: (data: {
    shortname: string
    address: string
    country_code: string
  }) => api.post<Warehouse>('/api/settings/warehouses', data),

  listWarehouses: () => api.get<Warehouse[]>('/api/settings/warehouses'),

  getWarehouse: (id: number) =>
    api.get<Warehouse>(`/api/settings/warehouses/${id}`),

  updateWarehouse: (
    id: number,
    data: { shortname: string; address: string; country_code: string }
  ) => api.put<Warehouse>(`/api/settings/warehouses/${id}`, data),

  deleteWarehouse: (id: number) =>
    api.delete(`/api/settings/warehouses/${id}`),

  // Email Templates (CS11)
  listEmailTemplates: () =>
    api.get<EmailTemplate[]>('/api/settings/email-templates'),
  createEmailTemplate: (data: {
    name: string
    recipient_email: string
    subject: string
    body: string
  }) => api.post<EmailTemplate>('/api/settings/email-templates', data),
  updateEmailTemplate: (
    id: number,
    data: { name: string; recipient_email: string; subject: string; body: string }
  ) => api.put<EmailTemplate>(`/api/settings/email-templates/${id}`, data),
  deleteEmailTemplate: (id: number) =>
    api.delete(`/api/settings/email-templates/${id}`),
}

// Stock API (eBay + SKUs)
export interface SKU {
  sku_code: string
  title: string
  landed_cost?: number
  postage_price?: number
  profit_per_unit?: number
  currency: string
}

export interface ImportResult {
  orders_added: number
  orders_updated: number
  line_items_added: number
  line_items_updated: number
  last_import?: string
  error?: string
}

export interface ShopifyStatus {
  connected: boolean
  shop_domain: string | null
  has_token: boolean
  source: 'env' | 'database' | 'none'
}

export interface AnalyticsSummaryPoint {
  period: string
  order_count: number
  units_sold: number
}

export interface AnalyticsSummary {
  series: AnalyticsSummaryPoint[]
  totals: { order_count: number; units_sold: number }
}

export interface AnalyticsMonthlyProfitPoint {
  period: string
  label: string
  profit_gbp: string
  profit_eur: string
  is_partial: boolean
}

export interface AnalyticsBySkuPoint {
  sku_code: string
  quantity_sold: number
  profit_per_unit: number | null
  profit: string
  profit_eur?: string | null
}

export interface AnalyticsByCountryPoint {
  country: string
  quantity_sold: number
  profit: string
  profit_eur?: string | null
}

/** Matches GET /api/stock/analytics/order-details (same profit rules as by-sku). */
export interface OrderDetailRow {
  ebay_order_id: string
  order_date: string
  country: string
  sku: string
  quantity: number
  total_due_seller: string | null
  total_due_seller_currency: string | null
  order_currency: string | null
  price_total: string | null
  tax_total: string | null
  line_total: string | null
  price_gbp: string
  line_landed_gbp: string
  line_postage_gbp: string
  line_cost_gbp: string
  order_cost_gbp: string
  vat_gbp: string
  order_gross_profit_gbp: string | null
  profit_tax_rate: number
  order_net_profit_gbp: string | null
  allocation_share: string
  line_gross_profit_gbp: string | null
  line_net_profit_gbp: string | null
}

export interface OrderDetailsTotals {
  row_count: number
  units: number
  sum_line_cost_gbp: string
  sum_line_net_profit_gbp: string
  sum_line_gross_profit_gbp: string
  sum_order_payout_gbp: string
}

export interface OrderDetailsResponse {
  rows: OrderDetailRow[]
  totals: OrderDetailsTotals
}

export interface LenderSummaryHeadline {
  units_sold: number
  gross_revenue_gbp: string
  gross_profit_pre_tax_gbp: string
  gross_margin_percent: string
}

export interface LenderSummaryWeekly {
  week_start: string
  week_label: string
  units: number
  revenue_gbp: string
  gross_profit_gbp: string
  margin_percent: string
}

export interface LenderSummaryRollingPeriod {
  label: string
  window_days: number
  period_start: string
  period_end: string
  units: number
  revenue_gbp: string
  gross_profit_gbp: string
  margin_percent: string
}

export interface LenderSummaryGeography {
  label: string
  code: string
  units: number
  revenue_gbp: string
  gross_profit_gbp: string
  pct_of_total_revenue: string
}

export interface LenderSummaryMethodology {
  usd_to_gbp_rate: number
  eur_to_gbp_rate: number
  uk_vat_default_rate: number
  generated_at_utc: string
  company_footer_note: string
}

export interface LenderSummaryPayload {
  period_from: string
  period_to: string
  generated_at_utc: string
  disclosure: string
  headline: LenderSummaryHeadline
  weekly: LenderSummaryWeekly[]
  rolling_periods: LenderSummaryRollingPeriod[]
  geography: LenderSummaryGeography[]
  methodology: LenderSummaryMethodology
}

export interface OrderLineItemRow {
  id: number
  ebay_line_item_id: string
  sku: string
  quantity: number
  currency: string | null
  line_item_cost: number | null
  discounted_line_item_cost: number | null
  line_total: number | null
  tax_amount: number | null
}

export interface OrderWithLines {
  order_id: number
  sales_channel: string
  ebay_order_id: string
  date: string
  country: string
  last_modified: string
  cancel_status: string | null
  buyer_username: string | null
  order_currency: string | null
  price_subtotal: number | null
  price_total: number | null
  tax_total: number | null
  delivery_cost: number | null
  price_discount: number | null
  fee_total: number | null
  total_fee_basis_amount: number | null
  total_marketplace_fee: number | null
  total_due_seller: number | null
  total_due_seller_currency: string | null
  ad_fees_total: number | null
  ad_fees_currency: string | null
  ad_fees_breakdown: { fee_type?: string; transaction_memo?: string; amount?: string; currency?: string }[] | null
  order_payment_status: string | null
  sales_record_reference: string | null
  ebay_collect_and_remit_tax: boolean | null
  line_items: OrderLineItemRow[]
}

export interface VelocityResult {
  sku: string
  units_sold: number
  days: number
  units_per_day: number
}

export interface POLineItemResp {
  id: number
  sku_code: string
  quantity: number
}

export interface PurchaseOrder {
  id: number
  status: string
  order_date: string
  order_value: string
  lead_time_days: number
  actual_delivery_date: string | null
  line_items: POLineItemResp[]
}

export const stockAPI = {
  getEbayAuthUrl: () => api.get<{ url: string; state: string }>('/api/stock/ebay/auth-url'),
  getEbayStatus: () => api.get<{ connected: boolean }>('/api/stock/ebay/status'),
  getEbayCallbackUrl: () =>
    api.get<{ callback_url: string; hint: string }>('/api/stock/ebay/callback-url'),
  getShopifyStatus: () => api.get<ShopifyStatus>('/api/stock/shopify/status'),
  saveShopify: (data: { shop: string; access_token: string }) =>
    api.put<ShopifyStatus>('/api/stock/shopify', data),
  clearShopify: () => api.delete('/api/stock/shopify'),
  runImport: (mode: 'full' | 'incremental', importShopify: boolean = true) =>
    api.post<ImportResult>('/api/stock/import', { mode, import_shopify: importShopify }),

  listSKUs: (search?: string) =>
    api.get<SKU[]>('/api/stock/skus', { params: search ? { search } : {} }),
  createSKU: (data: Partial<SKU> & { sku_code: string; title: string }) =>
    api.post<SKU>('/api/stock/skus', data),
  getSKU: (sku_code: string) => api.get<SKU>(`/api/stock/skus/${sku_code}`),
  updateSKU: (sku_code: string, data: Partial<SKU>) =>
    api.put<SKU>(`/api/stock/skus/${sku_code}`, data),
  deleteSKU: (sku_code: string) => api.delete(`/api/stock/skus/${sku_code}`),

  getAnalyticsFilterOptions: () =>
    api.get<{ countries: string[]; skus: string[] }>('/api/stock/analytics/filter-options'),

  getAnalyticsSummary: (params: {
    from: string
    to: string
    group_by?: 'day' | 'week' | 'month'
    country?: string
    sku?: string
  }) => api.get<AnalyticsSummary>('/api/stock/analytics/summary', { params }),

  getAnalyticsBySku: (params: {
    from: string
    to: string
    country?: string
    sku?: string
  }) => api.get<AnalyticsBySkuPoint[]>('/api/stock/analytics/by-sku', { params }),

  getAnalyticsByCountry: (params: {
    from: string
    to: string
    sku?: string
  }) => api.get<AnalyticsByCountryPoint[]>('/api/stock/analytics/by-country', { params }),

  getAnalyticsMonthlyProfit: (params?: { year?: number }) =>
    api.get<AnalyticsMonthlyProfitPoint[]>('/api/stock/analytics/monthly-profit', { params }),

  getAnalyticsMonthlyProfitYears: () =>
    api.get<{ years: number[] }>('/api/stock/analytics/monthly-profit-years'),

  getOrderDetails: (params: {
    from: string
    to: string
    country?: string
    sku?: string
  }) => api.get<OrderDetailsResponse>('/api/stock/analytics/order-details', { params }),

  getLenderSummary: (params: { from: string; to: string }) =>
    api.get<LenderSummaryPayload>('/api/lender-summary', { params }),

  getLatestOrders: (limit = 10) =>
    api.get<OrderWithLines[]>('/api/stock/orders/latest', { params: { limit } }),

  backfillOrderEarnings: () =>
    api.post<{ orders_updated: number; orders_skipped: number; error?: string }>(
      '/api/stock/orders/backfill-order-earnings'
    ),

  getVelocity: (sku: string, from: string, to: string) =>
    api.get<VelocityResult>('/api/stock/planning/velocity', {
      params: { sku, from, to },
    }),

  listPurchaseOrders: (status?: string) =>
    api.get<PurchaseOrder[]>('/api/stock/purchase-orders', {
      params: status ? { status } : {},
    }),
  createPurchaseOrder: (data: {
    order_date: string
    order_value: string
    lead_time_days?: number
    status?: string
    line_items: { sku_code: string; quantity: number }[]
  }) => api.post<PurchaseOrder>('/api/stock/purchase-orders', data),
  getPurchaseOrder: (id: number) =>
    api.get<PurchaseOrder>(`/api/stock/purchase-orders/${id}`),
  updatePurchaseOrder: (
    id: number,
    params?: { status?: string; actual_delivery_date?: string }
  ) => api.put<PurchaseOrder>(`/api/stock/purchase-orders/${id}`, null, { params }),
  deletePurchaseOrder: (id: number) =>
    api.delete(`/api/stock/purchase-orders/${id}`),

  generateOrderMessage: (items: { sku_code: string; title: string; quantity: number }[]) =>
    api.post<{ message: string; total_units: number; countries: string[] }>(
      '/api/stock/generate-order-message',
      { items }
    ),
}

// Messages API (Phase 4-6). media: eBay attachment types IMAGE, DOC, PDF, TXT
export interface MessageMediaItem {
  mediaName: string
  mediaType: string
  mediaUrl: string | null
}

export interface MessageResp {
  message_id: string
  thread_id: string
  sender_type: string
  sender_username: string | null
  subject: string | null
  content: string
  media?: MessageMediaItem[] | null
  is_read: boolean
  detected_language: string | null
  translated_content: string | null
  ebay_created_at: string
  created_at: string
}

export interface ThreadSummary {
  thread_id: string
  buyer_username: string | null
  ebay_order_id: string | null
  ebay_item_id: string | null
  sku: string | null
  created_at: string
  message_count: number
  unread_count: number
  is_flagged: boolean
  last_message_preview: string | null
}

export interface ThreadDetail {
  thread_id: string
  buyer_username: string | null
  ebay_order_id: string | null
  ebay_item_id: string | null
  sku: string | null
  tracking_number: string | null
  is_flagged: boolean
  created_at: string
  messages: MessageResp[]
}

export interface AIInstruction {
  id: number
  type: 'global' | 'sku'
  sku_code: string | null
  item_details: string | null
  instructions: string
  created_at: string
  updated_at: string
}

export const messagesAPI = {
  listThreads: (params?: { filter?: 'unread' | 'flagged'; search?: string; sender_type?: 'customer' | 'ebay' }) =>
    api.get<ThreadSummary[]>('/api/messages/threads', {
      params: params ?? {},
    }),
  getThread: (threadId: string) =>
    api.get<ThreadDetail>(`/api/messages/threads/${threadId}`),
  markThreadRead: (threadId: string) =>
    api.post<void>(`/api/messages/threads/${threadId}/mark-read`),
  draftReply: (threadId: string, extra_instructions?: string) =>
    api.post<{ draft: string }>(`/api/messages/threads/${threadId}/draft`, {
      extra_instructions: extra_instructions || undefined,
    }),
  draftGerman: (
    threadId: string,
    data?: { seed_text?: string; extra_instructions?: string }
  ) =>
    api.post<{ draft: string }>(`/api/messages/threads/${threadId}/draft-german`, {
      seed_text: data?.seed_text || undefined,
      extra_instructions: data?.extra_instructions || undefined,
    }),
  sendReply: (threadId: string, content: string, draftContent?: string, messageMedia?: MessageMediaItem[]) =>
    api.post<{ success: boolean; message: string }>(
      `/api/messages/threads/${threadId}/send`,
      { content, draft_content: draftContent ?? undefined, message_media: messageMedia ?? undefined }
    ),
  uploadMessageMedia: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post<MessageMediaItem>('/api/messages/upload-media', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },
  /** Refetch messages for this thread from eBay (single API call). Use after send instead of full sync. */
  refreshThread: (threadId: string, timeoutMs = 30000) =>
    api.post<void>(`/api/messages/threads/${threadId}/refresh`, {}, { timeout: timeoutMs }),
  /** Incremental: default 90s. Full backfill: 5 min (align reverse-proxy timeouts in production). */
  sync: (timeoutMs = 90000, full = false) =>
    api.post<{
      message: string
      synced: number
      threads_synced?: number
      ebay_threads_synced?: number
      ebay_messages_synced?: number
      interrupted?: boolean
    }>(
      '/api/messages/sync',
      {},
      { timeout: full ? 300000 : timeoutMs, params: { full: full ? 'true' : undefined } }
    ),
  toggleFlag: (threadId: string, isFlagged: boolean) =>
    api.patch<{ thread_id: string; is_flagged: boolean }>(
      `/api/messages/threads/${threadId}/flag`,
      { is_flagged: isFlagged }
    ),
  getFlaggedCount: () =>
    api.get<{ flagged_count: number }>('/api/messages/flagged-count'),
  getSyncStatus: () =>
    api.get<{ last_sync_at: string | null; is_syncing: boolean; total_unread_count: number }>('/api/messages/sync-status'),

  // Translation (CS07, CS08)
  detectLanguage: (text: string) =>
    api.post<{ language_code: string; language_name: string }>('/api/messages/detect-language', { text }),
  translate: (text: string, source_lang: string, target_lang: string) =>
    api.post<{ translated: string; back_translated: string }>('/api/messages/translate', {
      text,
      source_lang,
      target_lang,
    }),
  /** Translate all non-English messages in thread and persist to DB */
  translateThread: (threadId: string) =>
    api.post<{ translated_count: number; detected_language: string }>(
      `/api/messages/threads/${threadId}/translate-all`
    ),

  // AI Instructions (CS06)
  listAIInstructions: (type?: 'global' | 'sku') =>
    api.get<AIInstruction[]>('/api/messages/ai-instructions', {
      params: type ? { type } : {},
    }),
  createAIInstruction: (data: {
    type: 'global' | 'sku'
    sku_code?: string
    item_details?: string
    instructions: string
  }) => api.post<AIInstruction>('/api/messages/ai-instructions', data),
  getAIInstruction: (id: number) =>
    api.get<AIInstruction>(`/api/messages/ai-instructions/${id}`),
  updateAIInstruction: (
    id: number,
    data: { item_details?: string; instructions?: string }
  ) => api.put<AIInstruction>(`/api/messages/ai-instructions/${id}`, data),
  deleteAIInstruction: (id: number) =>
    api.delete(`/api/messages/ai-instructions/${id}`),
  /** Generate global instruction from message history; result appears in list. */
  generateGlobalInstruction: () =>
    api.post<{ success: boolean; message: string; instructions?: string }>(
      '/api/messages/generate-global-instruction'
    ),
}

// Get video ID from an eBay listing (item number or URL)
export interface VideoIdResponse {
  item_number: string
  video_ids: string[]
  title: string | null
}

export interface AddVideoToSkuResponse {
  sku: string
  video_ids: string[]
}

export type AddVideoToSkuEvent =
  | { type: 'progress'; message: string }
  | { type: 'listing_count'; count: number }
  | { type: 'done'; sku: string; updated: number; failed: string[]; total: number }
  | { type: 'error'; detail: string }

export type AddVideoToListingsEvent =
  | { type: 'progress'; message: string }
  | { type: 'done'; updated: number; failed: string[]; total: number }
  | { type: 'error'; detail: string }

export const listingVideoAPI = {
  getVideoId: (itemNumberOrUrl: string) =>
    api.get<VideoIdResponse>('/api/listing-video/video-id', {
      params: { item_number: itemNumberOrUrl.trim() },
    }),
  addVideoToSku: (videoId: string, sku: string, marketplaceId?: string) =>
    api.post<AddVideoToSkuResponse>('/api/listing-video/add-video-to-sku', {
      video_id: videoId.trim(),
      sku: sku.trim(),
      marketplace_id: marketplaceId?.trim() || undefined,
    }),
  /** Stream add-video-to-sku progress; calls onEvent for each NDJSON line. marketplaceId e.g. EBAY_US, EBAY_GB. */
  addVideoToSkuStream: async (
    videoId: string,
    sku: string,
    onEvent: (ev: AddVideoToSkuEvent) => void,
    marketplaceId?: string
  ): Promise<void> => {
    const url = `${API_BASE_URL.replace(/\/$/, '')}/api/listing-video/add-video-to-sku`
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        video_id: videoId.trim(),
        sku: sku.trim(),
        marketplace_id: marketplaceId?.trim() || undefined,
      }),
      credentials: 'include',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      onEvent({ type: 'error', detail: (err as { detail?: string }).detail || res.statusText })
      return
    }
    const reader = res.body?.getReader()
    if (!reader) {
      onEvent({ type: 'error', detail: 'No response body' })
      return
    }
    const dec = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const ev = JSON.parse(line) as AddVideoToSkuEvent
          onEvent(ev)
          if (ev.type === 'done' || ev.type === 'error') return
        } catch {
          // skip malformed line
        }
      }
    }
    if (buf.trim()) {
      try {
        const ev = JSON.parse(buf) as AddVideoToSkuEvent
        onEvent(ev)
      } catch {
        onEvent({ type: 'error', detail: 'Incomplete response' })
      }
    }
  },
  /** Stream add-video-to-listings (Trading API ReviseFixedPriceItem); for CSV/legacy listings. */
  addVideoToListingsStream: async (
    videoId: string,
    itemIds: string[],
    onEvent: (ev: AddVideoToListingsEvent) => void
  ): Promise<void> => {
    const url = `${API_BASE_URL.replace(/\/$/, '')}/api/listing-video/add-video-to-listings`
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_id: videoId.trim(), item_ids: itemIds }),
      credentials: 'include',
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      onEvent({ type: 'error', detail: (err as { detail?: string }).detail || res.statusText })
      return
    }
    const reader = res.body?.getReader()
    if (!reader) {
      onEvent({ type: 'error', detail: 'No response body' })
      return
    }
    const dec = new TextDecoder()
    let buf = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const ev = JSON.parse(line) as AddVideoToListingsEvent
          onEvent(ev)
          if (ev.type === 'done' || ev.type === 'error') return
        } catch {
          // skip
        }
      }
    }
    if (buf.trim()) {
      try {
        const ev = JSON.parse(buf) as AddVideoToListingsEvent
        onEvent(ev)
      } catch {
        onEvent({ type: 'error', detail: 'Incomplete response' })
      }
    }
  },
}

export const inventoryStatusAPI = {
  getSummary: () => api.get<InventoryStatusSummary>('/api/inventory-status/summary'),
  upsertConnection: (data: {
    name: string
    region: string
    environment: 'stage' | 'prod'
    oauth_base_url: string
    api_base_url: string
    signature_mode: 'path_only' | 'path_and_body'
    is_active: boolean
  }) => api.put<OCConnection>('/api/inventory-status/connection', data),
  testConnection: () =>
    api.post<{ ok: boolean; detail: string; region?: string; environment?: string; service_count?: number }>(
      '/api/inventory-status/test-connection',
      {}
    ),
  getAuthorizeUrl: (data: { redirect_uri: string; state?: string }) =>
    api.post<{ authorize_url: string }>('/api/inventory-status/oauth/authorize-url', data),
  exchangeCode: (data: { code: string; redirect_uri: string }) =>
    api.post<{ access_token_received: boolean; refresh_token_stored: boolean; expires_in?: number }>(
      '/api/inventory-status/oauth/exchange-code',
      data
    ),
  syncSkuMappings: () =>
    api.post<{ synced: number; skipped: number; inventory_rows: number }>('/api/inventory-status/sync-sku-mappings', {}),
  listSkuMappings: (sku?: string) =>
    api.get<OCSkuMapping[]>('/api/inventory-status/sku-mappings', {
      params: sku ? { sku } : {},
    }),
  listInventory: () => api.get<OCSkuInventoryRow[]>('/api/inventory-status/inventory'),
  /** Stock chart series from movement DB (GET /inventory-history); optional SKU filters. */
  getInventoryHistory: (params: {
    from?: string
    to?: string
    seller_skuid?: string
    sku_code?: string
    mfskuid?: string
    service_region?: string
  }) =>
    api.get<InventoryHistorySeries>('/api/inventory-status/inventory-history', {
      params: {
        ...(params.from ? { from: params.from } : {}),
        ...(params.to ? { to: params.to } : {}),
        ...(params.seller_skuid ? { seller_skuid: params.seller_skuid } : {}),
        ...(params.sku_code ? { sku_code: params.sku_code } : {}),
        ...(params.mfskuid ? { mfskuid: params.mfskuid } : {}),
        ...(params.service_region ? { service_region: params.service_region } : {}),
      },
    }),
  /** Linear-weighted run-out forecast for all OC mappings (no query params). */
  getStockForecast: () => api.get<StockForecastBundle>('/api/inventory-status/stock-forecast'),
  /** Stored movement lines (GET); fill with syncStockMovementFromOc first. */
  listStockMovement: (params: {
    from?: string
    to?: string
    seller_skuid?: string
    sku_code?: string
    mfskuid?: string
    line_limit?: number
  }) =>
    api.get<OCStockMovementResponse>('/api/inventory-status/stock-movement', {
      params: {
        ...(params.from ? { from: params.from } : {}),
        ...(params.to ? { to: params.to } : {}),
        ...(params.seller_skuid ? { seller_skuid: params.seller_skuid } : {}),
        ...(params.sku_code ? { sku_code: params.sku_code } : {}),
        ...(params.mfskuid ? { mfskuid: params.mfskuid } : {}),
        ...(params.line_limit != null ? { line_limit: params.line_limit } : {}),
      },
    }),
  /** Pull GetStockMovement from OC into DB (long ranges can take minutes). */
  syncStockMovementFromOc: (params?: { from?: string; to?: string; incremental?: boolean }) =>
    api.post<{
      fetched: number
      inserted: number
      from_date: string
      to_date: string
      mfskuid_count: number
      scope: string
      clamped?: boolean
    }>('/api/inventory-status/sync-stock-movement', undefined, {
      params: {
        ...(params?.from ? { from: params.from } : {}),
        ...(params?.to ? { to: params.to } : {}),
        ...(params?.incremental ? { incremental: true } : {}),
      },
      timeout: 300_000,
    }),
  /** Verbatim OC JSON: snapshot v2 + SKU query (does not include GetStockMovement). */
  debugRawOc: (params?: { service_region?: string; mfskuid?: string }) =>
    api.get<OCRawDebugResponse>('/api/inventory-status/debug-raw', { params: params ?? {} }),
  /** Verbatim GetStockMovement request/response for one MFSKUID (~7d window). */
  debugOcMovementRaw: (params: { mfskuid: string; from?: string; to?: string }) =>
    api.get<OCDebugMovementRawResponse>('/api/inventory-status/debug/oc-movement-raw', {
      params: {
        mfskuid: params.mfskuid,
        ...(params.from ? { from: params.from } : {}),
        ...(params.to ? { to: params.to } : {}),
      },
    }),
  debugStockMovementDb: () =>
    api.get<StoredMovementDbDebugResponse>('/api/inventory-status/debug/stock-movement-db'),
  /** Cached counts from DB; run syncInboundOrders to refresh from OC. */
  getInboundOrderStatusSummary: () =>
    api.get<InboundOrderStatusSummary>('/api/inventory-status/inbound-orders/status-summary'),
  /** Pull inbound orders from OC into DB. Incremental by default; full=true backfills from 2024-01-01 (slow). */
  syncInboundOrders: (full = false) =>
    api.post<InboundSyncResponse>(
      '/api/inventory-status/inbound-orders/sync',
      {},
      { params: { full: full ? 'true' : undefined }, timeout: 300_000 }
    ),
  listInboundOrders: (params?: { months_back?: number; include_raw?: boolean }) => {
    const { months_back, include_raw } = params ?? {}
    return api.get<OCInboundOrderRow[]>('/api/inventory-status/inbound-orders', {
      params: {
        ...(months_back != null ? { months_back } : {}),
        ...(include_raw ? { include_raw: true } : {}),
      },
    })
  },
  getInboundStatusFilter: () =>
    api.get<InboundStatusFilter>('/api/inventory-status/inbound-orders/status-filter'),
  putInboundStatusFilter: (data: { excluded: string[] }) =>
    api.put<InboundStatusFilter>('/api/inventory-status/inbound-orders/status-filter', data),
  putInboundCustomCourier: (data: {
    oc_inbound_number?: string | null
    seller_inbound_number?: string | null
    url: string | null
  }) =>
    api.put<{ oc_inbound_number: string | null; seller_inbound_number: string; custom_courier_url: string | null }>(
      '/api/inventory-status/inbound-orders/custom-courier',
      data
    ),
  putInboundCustomTracking: (data: {
    oc_inbound_number?: string | null
    seller_inbound_number?: string | null
    tracking_number: string | null
  }) =>
    api.put<{
      oc_inbound_number: string | null
      seller_inbound_number: string
      custom_tracking_number: string | null
    }>('/api/inventory-status/inbound-orders/custom-tracking', data),
  /** One cached inbound by OC number; includes full raw_oc_payload and computed times. */
  lookupInboundOrder: (ocInboundNumber: string) =>
    api.get<InboundOrderLookup>('/api/inventory-status/inbound-orders/lookup', {
      params: { oc_inbound_number: ocInboundNumber },
    }),
}

// Health check
export const healthCheck = () => api.get('/health')

export default api
