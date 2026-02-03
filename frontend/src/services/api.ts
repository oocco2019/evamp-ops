/**
 * API client for backend communication
 */
import axios from 'axios'

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
})

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

export interface AnalyticsSummaryPoint {
  period: string
  order_count: number
  units_sold: number
}

export interface AnalyticsSummary {
  series: AnalyticsSummaryPoint[]
  totals: { order_count: number; units_sold: number }
}

export interface AnalyticsBySkuPoint {
  sku_code: string
  quantity_sold: number
  profit_per_unit: number | null
  profit: string
}

export interface AnalyticsByCountryPoint {
  country: string
  quantity_sold: number
  profit: string
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
  runImport: (mode: 'full' | 'incremental') =>
    api.post<ImportResult>('/api/stock/import', { mode }),

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

// Messages API (Phase 4-6)
export interface MessageResp {
  message_id: string
  thread_id: string
  sender_type: string
  sender_username: string | null
  subject: string | null
  content: string
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
  getSendingEnabled: () =>
    api.get<{ sending_enabled: boolean }>('/api/messages/sending-enabled'),
  listThreads: (params?: { filter?: 'unread' | 'flagged'; search?: string; sender_type?: 'customer' | 'ebay' }) =>
    api.get<ThreadSummary[]>('/api/messages/threads', {
      params: params ?? {},
    }),
  getThread: (threadId: string) =>
    api.get<ThreadDetail>(`/api/messages/threads/${threadId}`),
  draftReply: (threadId: string, extra_instructions?: string) =>
    api.post<{ draft: string }>(`/api/messages/threads/${threadId}/draft`, {
      extra_instructions: extra_instructions || undefined,
    }),
  sendReply: (threadId: string, content: string, draftContent?: string) =>
    api.post<{ success: boolean; message: string }>(
      `/api/messages/threads/${threadId}/send`,
      { content, draft_content: draftContent ?? undefined }
    ),
  sync: (timeoutMs = 90000) =>
    api.post<{ message: string; synced: number }>('/api/messages/sync', {}, { timeout: timeoutMs }),
  toggleFlag: (threadId: string, isFlagged: boolean) =>
    api.patch<{ thread_id: string; is_flagged: boolean }>(
      `/api/messages/threads/${threadId}/flag`,
      { is_flagged: isFlagged }
    ),
  getFlaggedCount: () =>
    api.get<{ flagged_count: number }>('/api/messages/flagged-count'),

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

// Health check
export const healthCheck = () => api.get('/health')

export default api
