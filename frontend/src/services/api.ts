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
}

// Health check
export const healthCheck = () => api.get('/health')

export default api
