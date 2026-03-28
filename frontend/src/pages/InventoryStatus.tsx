import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import {
  inventoryStatusAPI,
  stockAPI,
  type OCInboundOrderRow,
  type OCSkuInventoryRow,
  type OCSkuMapping,
} from '../services/api'

function inboundGetCi(obj: Record<string, unknown>, ...names: string[]): unknown {
  const lower = Object.fromEntries(Object.entries(obj).map(([k, v]) => [k.toLowerCase(), v]))
  for (const n of names) {
    const v = lower[n.toLowerCase()]
    if (v !== undefined && v !== null) return v
  }
  return undefined
}

/** OC detail uses skulist / SKUList with sellerSKUID, skuquantity, etc. */
function getInboundSkuListParts(raw: OCInboundOrderRow['raw']): string[] {
  if (!raw || typeof raw !== 'object') return []
  const list = inboundGetCi(raw as Record<string, unknown>, 'skulist', 'SKUList', 'skuList')
  if (!Array.isArray(list)) return []
  const parts: string[] = []
  for (const item of list) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    const sku =
      inboundGetCi(o, 'sellerSKUID', 'sellerSkuid', 'ocskuid', 'OCSKUID', 'mfSkuId', 'MFSKUID') ?? ''
    const qty = inboundGetCi(o, 'skuquantity', 'skuQuantity', 'SKUQuantity', 'sku_qty')
    const sid = String(sku).trim()
    const q = qty !== undefined && qty !== null && qty !== '' ? String(qty) : ''
    if (sid || q) parts.push(sid && q ? `${sid} × ${q}` : sid || q)
  }
  return parts
}

function formatInboundSkuList(raw: OCInboundOrderRow['raw']): string {
  const parts = getInboundSkuListParts(raw)
  return parts.length ? parts.join('; ') : '—'
}

function InboundSkuListCell({ raw }: { raw: OCInboundOrderRow['raw'] }) {
  const parts = getInboundSkuListParts(raw)
  if (parts.length === 0) return '—'
  return (
    <span className="inline-flex flex-wrap items-baseline gap-y-0.5">
      {parts.map((p, i) => (
        <span key={i} className="whitespace-nowrap">
          {p}
          {i < parts.length - 1 ? <span className="text-gray-400">; </span> : null}
        </span>
      ))}
    </span>
  )
}

/** `YYYY-MM-DD HH:MM:SS` in local time, matching OC portal list style. */
function formatOcDateTimeLocal(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** OC often sends `2026-03-18 09:50:01` (space, no T) — JS parsing is unreliable without normalizing. */
function normalizeOcTimestampString(s: string): string {
  let t = s.trim()
  if (!t) return t
  // "YYYY-MM-DD HH:MM:SS" or with fractional seconds
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(t)) {
    t = t.replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})/, '$1T$2')
  }
  if (t.endsWith('Z')) t = `${t.slice(0, -1)}+00:00`
  if (t.endsWith('+0000')) t = `${t.slice(0, -5)}+00:00`
  return t
}

function formatOcTimestamp(value: unknown): string {
  if (value === undefined || value === null || value === '') return '—'
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (value > 1e11) return formatOcDateTimeLocal(new Date(value))
    if (value > 1e9) return formatOcDateTimeLocal(new Date(value * 1000))
  }
  let s = String(value).trim()
  if (!s) return '—'
  s = normalizeOcTimestampString(s)
  const d = new Date(s)
  if (!Number.isNaN(d.getTime())) return formatOcDateTimeLocal(d)
  return '—'
}

type InboundWalkEntry = { keyLower: string; value: unknown }

/** Depth-first walk: OC nests times under varying objects. */
function walkInboundRaw(obj: unknown, depth = 0): InboundWalkEntry[] {
  if (depth > 8 || obj === null || obj === undefined) return []
  if (typeof obj !== 'object') return []
  if (Array.isArray(obj)) {
    return obj.flatMap((item) => walkInboundRaw(item, depth + 1))
  }
  const o = obj as Record<string, unknown>
  const out: InboundWalkEntry[] = []
  for (const [k, v] of Object.entries(o)) {
    out.push({ keyLower: k.toLowerCase(), value: v })
    if (v && typeof v === 'object') {
      out.push(...walkInboundRaw(v, depth + 1))
    }
  }
  return out
}

function pickWalkedValue(entries: InboundWalkEntry[], test: (keyLower: string) => boolean): unknown {
  for (const { keyLower, value } of entries) {
    if (!test(keyLower)) continue
    if (value === undefined || value === null || value === '') continue
    if (typeof value === 'object' && !Array.isArray(value)) continue
    return value
  }
  return undefined
}

function discoverCreateFromWalk(entries: InboundWalkEntry): unknown {
  const tries = [
    (k: string) =>
      k === 'createtime' ||
      k === 'create_time' ||
      k === 'createdtime' ||
      k === 'gmtcreate' ||
      k === 'gmt_create',
    (k: string) => (k.includes('create') || k.includes('gmt')) && (k.includes('time') || k.includes('date')),
    (k: string) => k.includes('inbound') && k.includes('create'),
  ]
  for (const t of tries) {
    const v = pickWalkedValue(entries, t)
    if (v !== undefined) return v
  }
  return undefined
}

function discoverPutawayFromWalk(entries: InboundWalkEntry): unknown {
  const tries = [
    (k: string) =>
      k === 'putawaytime' ||
      k === 'put_away_time' ||
      k === 'completeputawaytime' ||
      (k.includes('putaway') && k.includes('time')),
    (k: string) => k.includes('putaway') && !k.includes('qty') && !k.includes('quantity'),
  ]
  for (const t of tries) {
    const v = pickWalkedValue(entries, t)
    if (v !== undefined) return v
  }
  return undefined
}

function discoverArrivedFromWalk(entries: InboundWalkEntry): unknown {
  const tries = [
    (k: string) =>
      (k.includes('arrival') || k.includes('arrived') || k.includes('actualarrival')) &&
      !k.includes('estimate') &&
      !k.includes('eta'),
    (k: string) => k === 'arrivaltime' || k === 'arrivedtime',
  ]
  for (const t of tries) {
    const v = pickWalkedValue(entries, t)
    if (v !== undefined) return v
  }
  return undefined
}

/** OC UI uses `--` for missing times in the create/putaway column. */
function ocPortalDash(formatted: string): string {
  return formatted === '—' || formatted.trim() === '' ? '--' : formatted
}

/** Create time: explicit keys, then deep scan, then DB `inbound_at` from sync. */
function formatInboundCreateTime(raw: OCInboundOrderRow['raw'], inboundAtIso: string | null | undefined): string {
  if (!raw || typeof raw !== 'object') {
    return inboundAtIso ? formatOcTimestamp(inboundAtIso) : '—'
  }
  const o = raw as Record<string, unknown>
  let v: unknown = inboundGetCi(
    o,
    'createTime',
    'create_time',
    'createdTime',
    'inboundCreateTime',
    'inboundcreatetime',
    'createDate',
    'createdDate',
    'gmtCreate',
    'gmt_create',
  )
  if (v === undefined || v === null || v === '') {
    v = discoverCreateFromWalk(walkInboundRaw(raw))
  }
  if ((v === undefined || v === null || v === '') && inboundAtIso) {
    v = inboundAtIso
  }
  return formatOcTimestamp(v)
}

function formatInboundPutawayTime(raw: OCInboundOrderRow['raw']): string {
  if (!raw || typeof raw !== 'object') return '—'
  const o = raw as Record<string, unknown>
  let v: unknown = inboundGetCi(
    o,
    'putAwayTime',
    'putawayTime',
    'putawaytime',
    'putAwayDateTime',
    'completePutawayTime',
    'putawayDate',
    'completePutawayDateTime',
  )
  if (v === undefined || v === null || v === '') {
    v = discoverPutawayFromWalk(walkInboundRaw(raw))
  }
  return formatOcTimestamp(v)
}

/**
 * Arrived: explicit keys, deep scan, then batchList[].arrivalTime (epoch ms).
 */
function formatInboundArrivedTime(raw: OCInboundOrderRow['raw']): string {
  if (!raw || typeof raw !== 'object') return '—'
  const o = raw as Record<string, unknown>
  let v: unknown = inboundGetCi(
    o,
    'arrivedTime',
    'arrivalTime',
    'arrivedtime',
    'arrivedDateTime',
    'actualArrivalTime',
    'actualArrivalDateTime',
  )
  if (v === undefined || v === null || v === '') {
    v = discoverArrivedFromWalk(walkInboundRaw(raw))
  }
  if (v === undefined || v === null || v === '') {
    const bl = inboundGetCi(o, 'batchList', 'batchlist')
    if (Array.isArray(bl)) {
      const ms: number[] = []
      for (const item of bl) {
        if (!item || typeof item !== 'object') continue
        const row = item as Record<string, unknown>
        const at = row.arrivalTime ?? inboundGetCi(row, 'arrivaltime')
        if (typeof at === 'number' && at > 0) ms.push(at)
      }
      if (ms.length) v = Math.min(...ms)
    }
  }
  return formatOcTimestamp(v)
}

/** Unique tracking numbers from trackingList (ignores carton number). */
function formatInboundTrackingNumbers(raw: OCInboundOrderRow['raw']): string {
  if (!raw || typeof raw !== 'object') return '—'
  const list = inboundGetCi(raw as Record<string, unknown>, 'trackingList', 'trackinglist')
  if (!Array.isArray(list)) return '—'
  const seen = new Set<string>()
  const nums: string[] = []
  for (const item of list) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    const tn = inboundGetCi(o, 'trackingNumber', 'trackingnumber')
    if (tn === undefined || tn === null) continue
    const s = String(tn).trim()
    if (!s) continue
    const key = s.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    nums.push(s)
  }
  return nums.length ? nums.join(', ') : '—'
}

type InboundTrackingPair = { carrier: string; tracking: string }

/** One row per unique tracking #; carrier label for ParcelsApp link. */
function getInboundTrackingPairs(raw: OCInboundOrderRow['raw']): InboundTrackingPair[] {
  if (!raw || typeof raw !== 'object') return []
  const list = inboundGetCi(raw as Record<string, unknown>, 'trackingList', 'trackinglist')
  if (!Array.isArray(list)) return []
  const out: InboundTrackingPair[] = []
  const seen = new Set<string>()
  for (const item of list) {
    if (!item || typeof item !== 'object') continue
    const o = item as Record<string, unknown>
    const tn = inboundGetCi(o, 'trackingNumber', 'trackingnumber')
    if (tn === undefined || tn === null) continue
    const tracking = String(tn).trim()
    if (!tracking) continue
    const key = tracking.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    const carrierRaw = inboundGetCi(o, 'carrier', 'Carrier')
    const carrier =
      carrierRaw != null && String(carrierRaw).trim() !== '' ? String(carrierRaw).trim() : 'Track'
    out.push({ carrier, tracking })
  }
  return out
}

/** Map OC region / warehouse prefix to ISO country for ParcelsApp hint (optional query). */
function inferInboundCountryIso(
  region: string | null | undefined,
  warehouseCode: string | null | undefined
): string | null {
  const r = (region ?? '').trim().toUpperCase()
  if (r === 'UK') return 'GB'
  if (['DE', 'US', 'AU', 'FR', 'IT'].includes(r)) return r
  const w = (warehouseCode ?? '').trim().toUpperCase()
  const prefix = w.includes('-') ? w.split('-')[0] : w
  if (prefix === 'UK') return 'GB'
  if (['DE', 'US', 'AU', 'FR', 'IT'].includes(prefix)) return prefix
  return null
}

/** ParcelsApp universal tracking URL; optional country helps destination hint. */
function parcelsAppTrackingUrl(tracking: string, countryIso: string | null): string {
  const path = `https://parcelsapp.com/en/tracking/${encodeURIComponent(tracking)}`
  if (!countryIso) return path
  return `${path}?country=${encodeURIComponent(countryIso)}`
}

/** OrangeConnex seller portal inbound detail (UK fulfillment host for all regions). */
function ocInboundDetailUrl(ocInboundNumber: string): string | null {
  const order = ocInboundNumber.trim()
  if (!order) return null
  return `https://fulfillment-uk.orangeconnex.com/inbound/detail?orderNumber=${encodeURIComponent(order)}`
}

const ETA_OVERRIDE_STORAGE_KEY = 'evampops.inventoryStatus.inboundEtaOverrides'

function loadEtaOverrides(): Record<string, string> {
  try {
    const raw = localStorage.getItem(ETA_OVERRIDE_STORAGE_KEY)
    if (!raw) return {}
    const p = JSON.parse(raw) as Record<string, unknown>
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(p)) {
      if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) out[k] = v
    }
    return out
  } catch {
    return {}
  }
}

function persistEtaOverrides(next: Record<string, string>) {
  try {
    if (Object.keys(next).length === 0) {
      localStorage.removeItem(ETA_OVERRIDE_STORAGE_KEY)
    } else {
      localStorage.setItem(ETA_OVERRIDE_STORAGE_KEY, JSON.stringify(next))
    }
  } catch {
    // ignore
  }
}

function formatYmd(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** Parse display/create strings such as `YYYY-MM-DD HH:MM:SS` (local). */
function parseInboundDisplayToDate(s: string): Date | null {
  const t = s.trim()
  if (!t || t === '—' || t === '--') return null
  const n = normalizeOcTimestampString(t)
  const d = new Date(n)
  return Number.isNaN(d.getTime()) ? null : d
}

/** ETA date (calendar day) = create + 3 months. */
function defaultEtaYmdFromCreateDisplay(createDisplay: string): string {
  const d = parseInboundDisplayToDate(createDisplay)
  if (!d) return ''
  const eta = new Date(d)
  eta.setMonth(eta.getMonth() + 3)
  return formatYmd(eta)
}

/** Whole days from create to putaway (lead time). */
function formatOrderTimeDays(createDisplay: string, putawayDisplay: string): string {
  const c = parseInboundDisplayToDate(createDisplay)
  const p = parseInboundDisplayToDate(putawayDisplay)
  if (!c || !p) return '—'
  const days = Math.round((p.getTime() - c.getTime()) / 86400000)
  return String(days)
}

function inboundRowStableKey(row: OCInboundOrderRow, idx: number): string {
  const oc = row.oc_inbound_number?.trim()
  if (oc) return oc
  const s = row.seller_inbound_number?.trim()
  if (s) return `seller:${s}`
  return `idx:${idx}`
}

function normalizeInboundStatus(row: OCInboundOrderRow): string {
  const s = row.status?.trim()
  return s || '—'
}

function getUniqueInboundStatuses(orders: OCInboundOrderRow[]): string[] {
  const set = new Set<string>()
  for (const r of orders) set.add(normalizeInboundStatus(r))
  return Array.from(set).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
}

function getInboundCreateTimeMs(row: OCInboundOrderRow): number | null {
  const s = row.create_time ?? formatInboundCreateTime(row.raw, row.inbound_at)
  const d = parseInboundDisplayToDate(s)
  return d ? d.getTime() : null
}

function getInboundArrivedTimeMs(row: OCInboundOrderRow): number | null {
  const s = row.arrived_time ?? formatInboundArrivedTime(row.raw)
  const d = parseInboundDisplayToDate(s)
  return d ? d.getTime() : null
}

function parseYmdToSortMs(ymd: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(ymd)) return null
  const d = new Date(`${ymd}T12:00:00`)
  return Number.isNaN(d.getTime()) ? null : d.getTime()
}

function getInboundEtaSortMs(
  row: OCInboundOrderRow,
  rowKey: string,
  etaOverrides: Record<string, string>
): number | null {
  const createDisplay = row.create_time ?? formatInboundCreateTime(row.raw, row.inbound_at)
  const defaultYmd = defaultEtaYmdFromCreateDisplay(createDisplay)
  const ymd = etaOverrides[rowKey] ?? defaultYmd
  if (!ymd) return null
  return parseYmdToSortMs(ymd)
}

type InboundSortKey = 'sku_list' | 'create_time' | 'eta' | 'arrived'

const INBOUND_SORT_STORAGE_KEY = 'evampops.inventoryStatus.inboundSort'
const INBOUND_SKU5_FILTER_STORAGE_KEY = 'evampops.inventoryStatus.inboundSkuCountMin5'
const SKU_FILTER_STORAGE_KEY = 'evampops.inventoryStatus.skuFilter'
const INVENTORY_SORT_STORAGE_KEY = 'evampops.inventoryStatus.inventorySort'
const STATUS_EXCLUDED_LOCAL_KEY = 'evampops.inventoryStatus.inboundStatusExcluded'

type InventorySortKey =
  | 'seller_skuid'
  | 'available'
  | 'in_transit'
  | 'reserved_allocated'
  | 'sold_3m_units'
  | 'sold_1m_units'

const INVENTORY_SORT_KEYS: readonly InventorySortKey[] = [
  'seller_skuid',
  'available',
  'in_transit',
  'reserved_allocated',
  'sold_3m_units',
  'sold_1m_units',
]

function loadSkuFilter(): string {
  try {
    const v = localStorage.getItem(SKU_FILTER_STORAGE_KEY)
    return typeof v === 'string' ? v : ''
  } catch {
    return ''
  }
}

function persistSkuFilter(value: string) {
  try {
    if (value.trim() === '') localStorage.removeItem(SKU_FILTER_STORAGE_KEY)
    else localStorage.setItem(SKU_FILTER_STORAGE_KEY, value)
  } catch {
    // ignore
  }
}

function loadInventorySort(): { key: InventorySortKey; dir: 'asc' | 'desc' } {
  try {
    const raw = localStorage.getItem(INVENTORY_SORT_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { key?: string; dir?: string }
      const key = parsed?.key
      const dir = parsed?.dir
      if (
        typeof key === 'string' &&
        INVENTORY_SORT_KEYS.includes(key as InventorySortKey) &&
        (dir === 'asc' || dir === 'desc')
      ) {
        return { key: key as InventorySortKey, dir }
      }
    }
  } catch {
    // ignore
  }
  return { key: 'seller_skuid', dir: 'asc' }
}

function persistInventorySort(next: { key: InventorySortKey; dir: 'asc' | 'desc' }) {
  try {
    localStorage.setItem(INVENTORY_SORT_STORAGE_KEY, JSON.stringify(next))
  } catch {
    // ignore
  }
}

function loadStatusExcludedLocal(): Set<string> {
  try {
    const raw = localStorage.getItem(STATUS_EXCLUDED_LOCAL_KEY)
    if (!raw) return new Set()
    const arr = JSON.parse(raw) as unknown
    if (!Array.isArray(arr)) return new Set()
    return new Set(arr.filter((x): x is string => typeof x === 'string'))
  } catch {
    return new Set()
  }
}

function persistStatusExcludedLocal(excluded: Set<string>) {
  try {
    const sorted = [...excluded].sort()
    if (sorted.length === 0) localStorage.removeItem(STATUS_EXCLUDED_LOCAL_KEY)
    else localStorage.setItem(STATUS_EXCLUDED_LOCAL_KEY, JSON.stringify(sorted))
  } catch {
    // ignore
  }
}

function loadInboundSort(): { key: InboundSortKey; dir: 'asc' | 'desc' } {
  try {
    const raw = localStorage.getItem(INBOUND_SORT_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { key?: string; dir?: string }
      const key = parsed?.key
      const dir = parsed?.dir
      if (
        (key === 'sku_list' || key === 'create_time' || key === 'eta' || key === 'arrived') &&
        (dir === 'asc' || dir === 'desc')
      ) {
        return { key, dir }
      }
    }
  } catch {
    // ignore
  }
  return { key: 'create_time', dir: 'desc' }
}

function loadSku5Filter(): boolean {
  try {
    return localStorage.getItem(INBOUND_SKU5_FILTER_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

const INBOUND_STATUS_CHART_COLORS = [
  '#2563eb',
  '#16a34a',
  '#ca8a04',
  '#dc2626',
  '#9333ea',
  '#0891b2',
  '#ea580c',
  '#64748b',
  '#4f46e5',
  '#db2777',
]

export default function InventoryStatus() {
  const qc = useQueryClient()
  const [skuFilter, setSkuFilter] = useState(() => loadSkuFilter())
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [etaOverrides, setEtaOverrides] = useState<Record<string, string>>(() => loadEtaOverrides())
  const [inboundSort, setInboundSort] = useState<{ key: InboundSortKey; dir: 'asc' | 'desc' }>(loadInboundSort)
  const [skuCountFilterMin5, setSkuCountFilterMin5] = useState<boolean>(loadSku5Filter)
  const [statusExcluded, setStatusExcluded] = useState<Set<string>>(() => loadStatusExcludedLocal())
  const [statusExcludedDraft, setStatusExcludedDraft] = useState<Set<string>>(() => new Set())
  const statusExcludedRef = useRef(statusExcluded)
  statusExcludedRef.current = statusExcluded
  const statusExcludedDraftRef = useRef(statusExcludedDraft)
  statusExcludedDraftRef.current = statusExcludedDraft
  const statusFilterHydratedRef = useRef(false)
  const lastSavedExcludedRef = useRef<string | null>(null)
  const [statusFilterOpen, setStatusFilterOpen] = useState(false)
  const statusFilterButtonRef = useRef<HTMLButtonElement>(null)
  const statusFilterPanelRef = useRef<HTMLDivElement>(null)
  const [statusFilterPos, setStatusFilterPos] = useState({ top: 0, left: 0 })
  const [inventorySort, setInventorySort] = useState<{ key: InventorySortKey; dir: 'asc' | 'desc' }>(
    loadInventorySort
  )
  const summaryQuery = useQuery({
    queryKey: ['inventory-status', 'summary'],
    queryFn: async () => (await inventoryStatusAPI.getSummary()).data,
  })

  const mappingsQuery = useQuery({
    queryKey: ['inventory-status', 'mappings', skuFilter],
    queryFn: async () => (await inventoryStatusAPI.listSkuMappings(skuFilter.trim() || undefined)).data,
  })
  const inventoryQuery = useQuery({
    queryKey: ['inventory-status', 'inventory'],
    queryFn: async () => (await inventoryStatusAPI.listInventory()).data,
  })
  const inboundStatusSummaryQuery = useQuery({
    queryKey: ['inventory-status', 'inbound-status-summary'],
    queryFn: async () => (await inventoryStatusAPI.getInboundOrderStatusSummary()).data,
  })
  const inboundOrdersQuery = useQuery({
    queryKey: ['inventory-status', 'inbound-orders', 6, 'full'],
    queryFn: async () =>
      (await inventoryStatusAPI.listInboundOrders({ months_back: 6, include_raw: true })).data,
  })
  const inboundStatusFilterQuery = useQuery({
    queryKey: ['inventory-status', 'inbound-status-filter'],
    queryFn: async () => (await inventoryStatusAPI.getInboundStatusFilter()).data,
  })

  const saveInboundStatusFilterMutation = useMutation({
    mutationFn: (excluded: string[]) =>
      inventoryStatusAPI.putInboundStatusFilter({ excluded }).then((r) => r.data),
    onSuccess: (data) => {
      qc.setQueryData(['inventory-status', 'inbound-status-filter'], data)
      lastSavedExcludedRef.current = JSON.stringify([...data.excluded].sort())
    },
  })

  /** Same steps as server-scheduled refresh + Sales Analytics background import: incremental eBay + OC syncs. */
  const executeInventoryPull = useCallback(async () => {
    await stockAPI.runImport('incremental')
    await inventoryStatusAPI.syncSkuMappings()
    await inventoryStatusAPI.syncInboundOrders(false)
  }, [])

  const suppressPullNoticeRef = useRef(false)

  const pullLatestDataMutation = useMutation({
    mutationFn: executeInventoryPull,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['inventory-status'] })
      qc.invalidateQueries({ queryKey: ['analytics'] })
    },
    onSuccess: () => {
      if (suppressPullNoticeRef.current) {
        suppressPullNoticeRef.current = false
        return
      }
      setError(null)
      setNotice(
        'Latest data pulled: eBay orders (incremental import), OrangeConnex SKU mappings + inventory snapshot, and inbound cache (incremental).'
      )
    },
    onError: (e: unknown) => {
      if (suppressPullNoticeRef.current) {
        suppressPullNoticeRef.current = false
        return
      }
      setError(e instanceof Error ? e.message : 'Pull latest data failed')
    },
  })

  const openStatusFilter = useCallback(() => {
    setStatusExcludedDraft(new Set(statusExcluded))
    setStatusFilterOpen(true)
  }, [statusExcluded])

  const closeStatusFilter = useCallback(() => {
    setStatusExcluded(new Set(statusExcludedDraftRef.current))
    setStatusFilterOpen(false)
  }, [])

  const syncInboundMutation = useMutation({
    mutationFn: (full: boolean) => inventoryStatusAPI.syncInboundOrders(full),
    onSuccess: (res) => {
      const data = res.data
      setError(null)
      setNotice(
        `Inbound cache updated: ${data.synced} order(s) from OC (${data.full ? 'full backfill' : 'incremental'}).`
      )
      qc.invalidateQueries({ queryKey: ['inventory-status', 'inbound-status-summary'] })
      qc.invalidateQueries({ queryKey: ['inventory-status', 'inbound-orders'] })
    },
    onError: (e: unknown) => {
      setError(e instanceof Error ? e.message : 'Inbound sync failed')
    },
  })

  const summary = summaryQuery.data
  const mappings: OCSkuMapping[] = mappingsQuery.data ?? []
  const inventoryRows: OCSkuInventoryRow[] = inventoryQuery.data ?? []
  const inboundOrders: OCInboundOrderRow[] = inboundOrdersQuery.data ?? []
  const uniqueInboundStatuses = useMemo(() => getUniqueInboundStatuses(inboundOrders), [inboundOrders])

  const inboundRowsAfterSku = useMemo(() => {
    const base = inboundOrders.map((row, idx) => ({
      row,
      rowKey: inboundRowStableKey(row, idx),
    }))
    return skuCountFilterMin5 ? base.filter(({ row }) => row.sku_qty >= 5) : base
  }, [inboundOrders, skuCountFilterMin5])

  const inboundRowsForTable = useMemo(() => {
    const filtered = inboundRowsAfterSku.filter(({ row }) => !statusExcluded.has(normalizeInboundStatus(row)))
    const { key, dir } = inboundSort

    const sorted = [...filtered].sort((a, b) => {
      const { row: ra, rowKey: ka } = a
      const { row: rb, rowKey: kb } = b

      if (key === 'sku_list') {
        const sa = formatInboundSkuList(ra.raw).replace(/[—-]/g, '').trim()
        const sb = formatInboundSkuList(rb.raw).replace(/[—-]/g, '').trim()
        const c = sa.localeCompare(sb, undefined, { sensitivity: 'base' })
        return dir === 'asc' ? c : -c
      }

      const cmpNullableMs = (x: number | null, y: number | null): number => {
        if (x === null && y === null) return 0
        if (x === null) return 1
        if (y === null) return -1
        const diff = x - y
        return dir === 'asc' ? diff : -diff
      }

      if (key === 'create_time') {
        return cmpNullableMs(getInboundCreateTimeMs(ra), getInboundCreateTimeMs(rb))
      }
      if (key === 'arrived') {
        return cmpNullableMs(getInboundArrivedTimeMs(ra), getInboundArrivedTimeMs(rb))
      }
      if (key === 'eta') {
        return cmpNullableMs(
          getInboundEtaSortMs(ra, ka, etaOverrides),
          getInboundEtaSortMs(rb, kb, etaOverrides)
        )
      }
      return 0
    })

    return sorted
  }, [inboundRowsAfterSku, statusExcluded, inboundSort, etaOverrides])

  useEffect(() => {
    const unique = new Set(uniqueInboundStatuses)
    setStatusExcluded((prev) => {
      const next = new Set(prev)
      for (const x of [...next]) {
        if (!unique.has(x)) next.delete(x)
      }
      return next
    })
  }, [uniqueInboundStatuses])

  useEffect(() => {
    persistStatusExcludedLocal(statusExcluded)
  }, [statusExcluded])

  useEffect(() => {
    if (statusFilterHydratedRef.current) return
    if (inboundStatusFilterQuery.isError) {
      statusFilterHydratedRef.current = true
      lastSavedExcludedRef.current = JSON.stringify([...statusExcludedRef.current].sort())
      return
    }
    if (!inboundStatusFilterQuery.isSuccess || inboundStatusFilterQuery.data === undefined) return
    statusFilterHydratedRef.current = true
    setStatusExcluded(new Set(inboundStatusFilterQuery.data.excluded))
    lastSavedExcludedRef.current = JSON.stringify([...inboundStatusFilterQuery.data.excluded].sort())
  }, [
    inboundStatusFilterQuery.isSuccess,
    inboundStatusFilterQuery.isError,
    inboundStatusFilterQuery.data,
  ])

  useEffect(() => {
    if (!statusFilterHydratedRef.current) return
    const serialized = JSON.stringify([...statusExcluded].sort())
    if (serialized === lastSavedExcludedRef.current) return
    const t = window.setTimeout(() => {
      saveInboundStatusFilterMutation.mutate([...statusExcluded])
    }, 400)
    return () => window.clearTimeout(t)
  }, [statusExcluded, saveInboundStatusFilterMutation])

  useLayoutEffect(() => {
    if (!statusFilterOpen) return
    const update = () => {
      const btn = statusFilterButtonRef.current
      if (!btn) return
      const r = btn.getBoundingClientRect()
      setStatusFilterPos({ top: r.bottom + 4, left: r.left })
    }
    update()
    window.addEventListener('scroll', update, true)
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', update, true)
      window.removeEventListener('resize', update)
    }
  }, [statusFilterOpen])

  useEffect(() => {
    if (!statusFilterOpen) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (statusFilterButtonRef.current?.contains(t)) return
      if (statusFilterPanelRef.current?.contains(t)) return
      closeStatusFilter()
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [statusFilterOpen, closeStatusFilter])

  const handleInboundSort = (sortKey: InboundSortKey) => {
    setInboundSort((prev) => {
      const next = {
        key: sortKey,
        dir:
          prev.key === sortKey
            ? prev.dir === 'asc'
              ? 'desc'
              : 'asc'
            : sortKey === 'sku_list'
              ? 'asc'
              : 'desc',
      }
      try {
        localStorage.setItem(INBOUND_SORT_STORAGE_KEY, JSON.stringify(next))
      } catch {
        // ignore
      }
      return next
    })
  }

  const toggleSkuCountMin5Filter = () => {
    setSkuCountFilterMin5((v) => {
      const next = !v
      try {
        if (next) localStorage.setItem(INBOUND_SKU5_FILTER_STORAGE_KEY, '1')
        else localStorage.removeItem(INBOUND_SKU5_FILTER_STORAGE_KEY)
      } catch {
        // ignore
      }
      return next
    })
  }

  /** Top horizontal scrollbar above the table header, synced with the table body scroll. */
  const inboundTableScrollRef = useRef<HTMLDivElement>(null)
  const inboundTopScrollRef = useRef<HTMLDivElement>(null)
  const inboundScrollSyncLock = useRef(false)
  const [inboundScrollContentWidth, setInboundScrollContentWidth] = useState(0)
  const [inboundNeedsHorizontalScroll, setInboundNeedsHorizontalScroll] = useState(false)

  const updateInboundScrollMetrics = () => {
    const el = inboundTableScrollRef.current
    if (!el) return
    const apply = () => {
      const sw = el.scrollWidth
      const cw = el.clientWidth
      setInboundScrollContentWidth(sw)
      setInboundNeedsHorizontalScroll(sw > cw + 2)
    }
    apply()
    // Table width can settle after fonts/layout; second frame catches flex/min-width cases.
    requestAnimationFrame(() => {
      requestAnimationFrame(apply)
    })
  }

  useLayoutEffect(() => {
    updateInboundScrollMetrics()
  }, [inboundRowsForTable])

  useEffect(() => {
    const el = inboundTableScrollRef.current
    if (!el) return
    const ro = new ResizeObserver(() => updateInboundScrollMetrics())
    ro.observe(el)
    window.addEventListener('resize', updateInboundScrollMetrics)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', updateInboundScrollMetrics)
    }
  }, [inboundRowsForTable])

  const syncInboundTopFromMain = () => {
    if (inboundScrollSyncLock.current) return
    const main = inboundTableScrollRef.current
    const top = inboundTopScrollRef.current
    if (!main || !top) return
    inboundScrollSyncLock.current = true
    top.scrollLeft = main.scrollLeft
    requestAnimationFrame(() => {
      inboundScrollSyncLock.current = false
    })
  }

  const syncInboundMainFromTop = () => {
    if (inboundScrollSyncLock.current) return
    const main = inboundTableScrollRef.current
    const top = inboundTopScrollRef.current
    if (!main || !top) return
    inboundScrollSyncLock.current = true
    main.scrollLeft = top.scrollLeft
    requestAnimationFrame(() => {
      inboundScrollSyncLock.current = false
    })
  }

  useEffect(() => {
    if (!inboundNeedsHorizontalScroll) return
    const main = inboundTableScrollRef.current
    const top = inboundTopScrollRef.current
    if (main && top) top.scrollLeft = main.scrollLeft
  }, [inboundNeedsHorizontalScroll, inboundScrollContentWidth])

  const hasRequiredCredentials = summary?.has_required_credentials ?? false
  const sortedInventoryRows = [...inventoryRows].sort((a, b) => {
    const mult = inventorySort.dir === 'asc' ? 1 : -1
    if (inventorySort.key === 'seller_skuid') {
      return mult * (a.seller_skuid || '').localeCompare(b.seller_skuid || '')
    }
    return mult * ((a[inventorySort.key] as number) - (b[inventorySort.key] as number))
  })
  const handleInventorySort = (key: InventorySortKey) => {
    setInventorySort((prev) => {
      const next: { key: InventorySortKey; dir: 'asc' | 'desc' } = {
        key,
        dir:
          prev.key === key ? (prev.dir === 'asc' ? 'desc' : 'asc') : key === 'seller_skuid' ? 'asc' : 'desc',
      }
      persistInventorySort(next)
      return next
    })
  }

  const setInboundEtaOverride = (rowKey: string, ymd: string | null, computedDefaultYmd: string) => {
    setEtaOverrides((prev) => {
      const next = { ...prev }
      if (ymd === null || ymd === '') {
        delete next[rowKey]
      } else if (ymd === computedDefaultYmd) {
        delete next[rowKey]
      } else {
        next[rowKey] = ymd
      }
      persistEtaOverrides(next)
      return next
    })
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Inventory status</h1>
      <p className="text-sm text-gray-600 mb-6">
        Read-only OrangeConnex visibility inside the platform.
      </p>

      {notice && <div className="mb-4 rounded border border-green-200 bg-green-50 p-3 text-sm text-green-800">{notice}</div>}
      {error && <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">{error}</div>}
      {summaryQuery.isError && (
        <div className="mb-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          Backend was likely restarted or is temporarily unavailable. Buttons remain enabled; retry when backend is up.
        </div>
      )}
      {!hasRequiredCredentials && (
        <div className="mb-4 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
          Missing OC credentials (client_id, client_secret, refresh_token) in Settings &gt; OC Integration.
        </div>
      )}

      <div className="mb-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => pullLatestDataMutation.mutate()}
          className="px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
          disabled={pullLatestDataMutation.isPending}
          title="Incremental eBay import, OrangeConnex SKU mappings + inventory snapshot, and inbound cache (same as automatic refresh)"
        >
          {pullLatestDataMutation.isPending ? 'Pulling latest data…' : 'Pull latest data'}
        </button>
        <p className="text-sm text-gray-600 max-w-2xl">
          Refreshes eBay orders, OC inventory, and inbound cache. The backend runs the same incremental pull on a schedule
          (default every <span className="font-mono">15</span> minutes; configurable via{' '}
          <span className="font-mono">INVENTORY_REFRESH_INTERVAL_MINUTES</span>, <span className="font-mono">0</span> to
          disable). Sold columns use the same date windows as Sales Analytics (30 / 90 inclusive days).
        </p>
      </div>

      <section className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex flex-wrap items-end gap-2 mb-3">
          <h2 className="text-lg font-semibold text-gray-800 mr-4">SKU mappings</h2>
          <label className="text-sm text-gray-700">
            SKU filter
            <input
              className="ml-2 rounded border border-gray-300 px-2 py-1"
              value={skuFilter}
              onChange={(e) => {
                const v = e.target.value
                setSkuFilter(v)
                persistSkuFilter(v)
              }}
              placeholder="e.g. uke01"
            />
          </label>
          <span className="text-sm text-gray-500">Rows: {summary?.mapping_count ?? 0}</span>
        </div>
        {mappingsQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading mappings...</p>
        ) : mappings.length === 0 ? (
          <p className="text-sm text-gray-500">No mappings yet. Use <strong>Pull latest data</strong> above.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm border border-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">SKU</th>
                  <th className="px-3 py-2 text-left">Seller SKU</th>
                  <th className="px-3 py-2 text-left">Reference SKU</th>
                  <th className="px-3 py-2 text-left">MFSKUID</th>
                  <th className="px-3 py-2 text-left">Region</th>
                  <th className="px-3 py-2 text-left">Synced</th>
                </tr>
              </thead>
              <tbody>
                {mappings.map((row) => (
                  <tr key={row.id} className="border-t border-gray-100">
                    <td className="px-3 py-2">{row.sku_code}</td>
                    <td className="px-3 py-2">{row.seller_skuid}</td>
                    <td className="px-3 py-2">{row.reference_skuid}</td>
                    <td className="px-3 py-2 font-mono">{row.mfskuid}</td>
                    <td className="px-3 py-2">{row.service_region || '—'}</td>
                    <td className="px-3 py-2">{new Date(row.last_synced_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="bg-white rounded-lg border border-gray-200 p-4 mt-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">OC inventory snapshot</h2>
        {inventoryQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading inventory...</p>
        ) : inventoryRows.length === 0 ? (
          <p className="text-sm text-gray-500">No inventory rows yet. Use <strong>Pull latest data</strong> above.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm border border-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th
                    className="px-3 py-2 text-left cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('seller_skuid')}
                  >
                    Seller SKU {inventorySort.key === 'seller_skuid' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('available')}
                  >
                    Available {inventorySort.key === 'available' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('in_transit')}
                  >
                    In transit {inventorySort.key === 'in_transit' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('reserved_allocated')}
                  >
                    Reserved alloc {inventorySort.key === 'reserved_allocated' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('sold_3m_units')}
                  >
                    Sold last 3 months {inventorySort.key === 'sold_3m_units' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-right cursor-pointer hover:text-gray-900"
                    onClick={() => handleInventorySort('sold_1m_units')}
                  >
                    Sold last 1 month {inventorySort.key === 'sold_1m_units' && (inventorySort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedInventoryRows.map((row) => (
                  <tr key={row.seller_skuid || `inv-${row.id}`} className="border-t border-gray-100">
                    <td className="px-3 py-2 font-mono">{row.seller_skuid || '—'}</td>
                    <td className="px-3 py-2 text-right">{row.available}</td>
                    <td className="px-3 py-2 text-right">{row.in_transit}</td>
                    <td className="px-3 py-2 text-right">{row.reserved_allocated}</td>
                    <td className="px-3 py-2 text-right">{row.sold_3m_units}</td>
                    <td className="px-3 py-2 text-right">{row.sold_1m_units}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="bg-white rounded-lg border border-gray-200 p-4 mt-6">
        <div className="flex flex-wrap items-center gap-2 mb-2">
          <h2 className="text-lg font-semibold text-gray-800">Inbound orders by status</h2>
          <button
            type="button"
            onClick={() => syncInboundMutation.mutate(false)}
            disabled={syncInboundMutation.isPending}
            className="text-sm px-2 py-1 rounded border border-gray-300 text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            title="Incremental sync from OrangeConnex into the database (fast after first full load)"
          >
            {syncInboundMutation.isPending ? 'Syncing from OC…' : 'Sync from OC'}
          </button>
          <button
            type="button"
            onClick={() => syncInboundMutation.mutate(true)}
            disabled={syncInboundMutation.isPending}
            className="text-sm px-2 py-1 rounded border border-amber-300 text-amber-900 hover:bg-amber-50 disabled:opacity-50"
            title="Full backfill from 2024-01-01 (many API calls; check server logs)"
          >
            Full backfill (2024+)
          </button>
        </div>
        <p className="text-sm text-gray-600 mb-3">
          Chart and table read from the <strong>local cache</strong>. Use <strong>Sync from OC</strong> to pull updates
          (incremental after the first run). <strong>Full backfill</strong> re-fetches from 2024-01-01 UTC (slow; server
          logs each 7-day chunk). All OC warehouse locations are included when the API returns them.
        </p>
        {inboundStatusSummaryQuery.data?.last_sync_at && (
          <p className="text-xs text-gray-500 mb-6 font-mono">
            Cache last updated: {new Date(inboundStatusSummaryQuery.data.last_sync_at).toLocaleString()}
          </p>
        )}
        {inboundStatusSummaryQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading cached status distribution…</p>
        ) : inboundStatusSummaryQuery.isError ? (
          <p className="text-sm text-red-700">
            {inboundStatusSummaryQuery.error instanceof Error
              ? inboundStatusSummaryQuery.error.message
              : 'Failed to load status summary'}
          </p>
        ) : !inboundStatusSummaryQuery.data?.slices.length ? (
          <div className="text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded p-3">
            No cached inbound orders yet. Click <strong>Sync from OC</strong> (or <strong>Full backfill</strong> for
            complete history from 2024). Watch the backend log for chunk progress.
          </div>
        ) : (
          <div className="flex flex-col lg:flex-row lg:items-start gap-6 mt-2">
            <div className="h-80 w-full max-w-md mx-auto lg:mx-0 pt-2">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart margin={{ top: 28, right: 8, bottom: 8, left: 8 }}>
                  <Pie
                    data={inboundStatusSummaryQuery.data.slices.map((s) => ({
                      name: s.status,
                      value: s.count,
                    }))}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    label={({ name, value }) => `${name}: ${value}`}
                  >
                    {inboundStatusSummaryQuery.data.slices.map((_, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={INBOUND_STATUS_CHART_COLORS[index % INBOUND_STATUS_CHART_COLORS.length]}
                      />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value: number) => [value, 'Orders']} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="text-sm text-gray-600 space-y-1">
              <p>
                <span className="text-gray-500">Total orders in range:</span>{' '}
                <span className="font-semibold text-gray-900">{inboundStatusSummaryQuery.data.total_orders}</span>
              </p>
              <p>
                <span className="text-gray-500">Range:</span>{' '}
                <span className="font-mono">
                  {inboundStatusSummaryQuery.data.from_date} → {inboundStatusSummaryQuery.data.to_date}
                </span>
              </p>
            </div>
          </div>
        )}
      </section>

      <section className="bg-white rounded-lg border border-gray-200 p-4 mt-6 max-w-full min-w-0 overflow-x-hidden">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Inbound orders</h2>
        <p className="text-sm text-gray-600 mb-3">
          Evamp-ops workflows always involve these OC marketplaces together: `UK`, `DE`, `US`, `AU`. Rows come from the
          same cache as above (last ~6 months by date). Create / putaway / arrived are parsed from that cache on the
          server. The <span className="font-mono text-xs">CREATE TIME/PUTAWAY TIME</span> column matches OC: create on
          the first line, putaway on the second (<code className="text-xs bg-gray-100 px-1 rounded">--</code> when
          unknown). <strong>Tracking #</strong> comes from OC <span className="font-mono text-xs">trackingList</span>.
          <strong> ETA</strong> (after SKU list) defaults to create date + 3 months (local); edit to override—overrides
          are saved in this browser and shown with a green background. <strong>Courier</strong> links open{' '}
          <span className="font-mono text-xs">parcelsapp.com</span> with the tracking number (country hint from region /
          warehouse when available). <strong>Order time (days)</strong> is whole days from create to putaway. Run{' '}
          <strong>Sync from OC</strong> to refresh data; if times stay empty, the API may not include those fields for
          your tenant. Click column headers to sort (▲/▼); <strong>CREATE TIME/PUTAWAY</strong> sorts by{' '}
          <em>create</em> time only. Click <strong>SKU count</strong> to keep only orders with SKU count ≥ 5 (header
          uses the same mint highlight as an edited ETA).
        </p>
        {inboundOrdersQuery.isLoading ? (
          <p className="text-sm text-gray-500">Loading inbound orders...</p>
        ) : inboundOrders.length === 0 ? (
          <p className="text-sm text-gray-500">No inbound orders found for UK/DE/US/AU in the last 6 months.</p>
        ) : (
          <>
            <div className="w-full max-w-full min-w-0 rounded-lg border border-gray-200 overflow-hidden">
              {inboundNeedsHorizontalScroll && inboundScrollContentWidth > 0 && (
                <div
                  ref={inboundTopScrollRef}
                  role="presentation"
                  className="overflow-x-scroll overflow-y-hidden border-b border-gray-200 bg-gray-50 min-h-[14px] py-1"
                  onScroll={syncInboundMainFromTop}
                  aria-label="Scroll inbound table horizontally"
                >
                  <div style={{ width: inboundScrollContentWidth, height: 1 }} />
                </div>
              )}
              <div
                ref={inboundTableScrollRef}
                className={`w-full max-w-full min-w-0 overflow-x-auto bg-white ${
                  inboundNeedsHorizontalScroll
                    ? '[scrollbar-width:none] [&::-webkit-scrollbar]:h-0'
                    : ''
                }`}
                onScroll={syncInboundTopFromMain}
              >
            <table className="w-full min-w-0 text-sm border-collapse">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 py-2 text-left">OC inbound no.</th>
                  <th className="px-3 py-2 text-left align-top">
                    <button
                      ref={statusFilterButtonRef}
                      type="button"
                      disabled={inboundStatusFilterQuery.isLoading && !inboundStatusFilterQuery.isError}
                      className={`inline-flex max-w-full items-center gap-1 rounded border px-1.5 py-0.5 text-left text-sm font-medium disabled:cursor-wait disabled:opacity-70 ${
                        statusExcluded.size > 0
                          ? 'border-gray-200 bg-[#DFFFEA] text-gray-900 hover:bg-[#cef9e0]'
                          : 'border-transparent text-gray-900 hover:bg-gray-100'
                      }`}
                      onClick={() => (statusFilterOpen ? closeStatusFilter() : openStatusFilter())}
                      aria-expanded={statusFilterOpen}
                      aria-haspopup="listbox"
                      title={
                        inboundStatusFilterQuery.isLoading && !inboundStatusFilterQuery.isError
                          ? 'Loading saved filter from server…'
                          : 'Filter rows by status. Changes apply when you close this menu. Saved on the server when online, and in this browser for next visit.'
                      }
                    >
                      Status
                      <span className="text-[10px] leading-none text-gray-500" aria-hidden>
                        ▼
                      </span>
                      {saveInboundStatusFilterMutation.isPending ? (
                        <span className="text-[10px] text-gray-500">Saving…</span>
                      ) : null}
                    </button>
                    {statusFilterOpen ? (
                      <div
                        ref={statusFilterPanelRef}
                        role="listbox"
                        aria-label="Status filter"
                        className="fixed z-[100] w-[min(20rem,calc(100vw-1.5rem))] rounded-md border border-gray-200 bg-white py-2 shadow-lg"
                        style={{ top: statusFilterPos.top, left: statusFilterPos.left }}
                        onMouseDown={(e) => e.stopPropagation()}
                      >
                        <div className="flex flex-wrap gap-x-3 gap-y-1 border-b border-gray-100 px-3 pb-2">
                          <button
                            type="button"
                            className="text-xs text-blue-600 hover:underline"
                            onClick={() => setStatusExcludedDraft(new Set())}
                          >
                            Select all
                          </button>
                          <button
                            type="button"
                            className="text-xs text-blue-600 hover:underline"
                            onClick={() => setStatusExcludedDraft(new Set(uniqueInboundStatuses))}
                          >
                            Deselect all
                          </button>
                        </div>
                        <div className="max-h-64 overflow-y-auto px-2 pt-1">
                          {uniqueInboundStatuses.map((s) => {
                            const visible = !statusExcludedDraft.has(s)
                            return (
                              <label
                                key={s}
                                className="flex cursor-pointer items-start gap-2 rounded px-2 py-1 text-sm hover:bg-gray-50"
                              >
                                <span
                                  className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-gray-300 bg-white text-xs font-semibold text-emerald-600"
                                  aria-hidden
                                >
                                  {visible ? '✓' : ''}
                                </span>
                                <input
                                  type="checkbox"
                                  checked={visible}
                                  onChange={() => {
                                    setStatusExcludedDraft((prev) => {
                                      const next = new Set(prev)
                                      if (next.has(s)) next.delete(s)
                                      else next.add(s)
                                      return next
                                    })
                                  }}
                                  className="sr-only"
                                />
                                <span
                                  className={`min-w-0 break-words ${visible ? 'font-medium text-gray-900' : 'text-gray-500'}`}
                                >
                                  {s}
                                </span>
                              </label>
                            )
                          })}
                        </div>
                      </div>
                    ) : null}
                  </th>
                  <th
                    className={`px-3 py-2 text-left cursor-pointer select-none rounded-md border text-gray-900 ${
                      skuCountFilterMin5
                        ? 'bg-[#DFFFEA] border-gray-200 font-medium hover:bg-[#cef9e0]'
                        : 'border-transparent hover:bg-gray-100'
                    }`}
                    onClick={toggleSkuCountMin5Filter}
                    title="Click to show only orders with SKU count ≥ 5. Click again to show all."
                  >
                    SKU count{skuCountFilterMin5 ? ' ≥5' : ''}
                  </th>
                  <th className="px-3 py-2 text-left">Put away qty</th>
                  <th
                    className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-gray-800 cursor-pointer select-none hover:bg-gray-100"
                    onClick={() => handleInboundSort('create_time')}
                    title="Sort by create time (first line). Putaway line is not used for sorting."
                  >
                    CREATE TIME/PUTAWAY TIME{' '}
                    {inboundSort.key === 'create_time' && (inboundSort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-left whitespace-nowrap cursor-pointer select-none hover:bg-gray-100"
                    onClick={() => handleInboundSort('arrived')}
                  >
                    Arrived {inboundSort.key === 'arrived' && (inboundSort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-left max-w-[14rem] cursor-pointer select-none hover:bg-gray-100"
                    onClick={() => handleInboundSort('sku_list')}
                  >
                    SKU list {inboundSort.key === 'sku_list' && (inboundSort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th
                    className="px-3 py-2 text-left whitespace-nowrap cursor-pointer select-none hover:bg-gray-100"
                    onClick={() => handleInboundSort('eta')}
                  >
                    ETA {inboundSort.key === 'eta' && (inboundSort.dir === 'asc' ? '▲' : '▼')}
                  </th>
                  <th className="px-3 py-2 text-left max-w-[9rem]">Courier</th>
                  <th className="px-3 py-2 text-left max-w-[11rem]">Tracking #</th>
                  <th className="px-3 py-2 text-left whitespace-nowrap">Order time (days)</th>
                </tr>
              </thead>
              <tbody>
                {inboundRowsForTable.length === 0 ? (
                  <tr>
                    <td
                      colSpan={11}
                      className="px-3 py-6 text-center text-sm text-amber-900 bg-amber-50/80 border-t border-amber-100"
                    >
                      {inboundRowsAfterSku.length === 0 && skuCountFilterMin5 ? (
                        <>
                          No rows match <strong>SKU count ≥ 5</strong>. Click the <strong>SKU count</strong> header
                          again to show all orders.
                        </>
                      ) : (
                        <>
                          No rows match the selected <strong>Status</strong> values. Use the <strong>Status</strong>{' '}
                          filter above and check at least one value (or <strong>Select all</strong>).
                        </>
                      )}
                    </td>
                  </tr>
                ) : null}
                {inboundRowsForTable.map(({ row, rowKey }) => {
                  const createDisplay = row.create_time ?? formatInboundCreateTime(row.raw, row.inbound_at)
                  const putawayDisplay = row.putaway_time ?? formatInboundPutawayTime(row.raw)
                  const defaultEtaYmd = defaultEtaYmdFromCreateDisplay(createDisplay)
                  const etaOverride = etaOverrides[rowKey]
                  const etaInputValue = etaOverride ?? defaultEtaYmd
                  const etaIsEdited = etaOverride !== undefined
                  const trackingPairs = getInboundTrackingPairs(row.raw)
                  const countryIso = inferInboundCountryIso(row.region, row.warehouse_code)
                  const ocInboundNo = row.oc_inbound_number?.trim()
                  const ocDetailHref = ocInboundNo ? ocInboundDetailUrl(ocInboundNo) : null
                  return (
                  <tr
                    key={rowKey}
                    className="border-t border-gray-100"
                  >
                    <td className="px-3 py-2 font-mono">
                      {ocDetailHref ? (
                        <a
                          href={ocDetailHref}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline"
                          title="Open inbound in OrangeConnex fulfillment portal"
                        >
                          {ocInboundNo}
                        </a>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td className="px-3 py-2">{row.status || '—'}</td>
                    <td className="px-3 py-2">{row.sku_qty}</td>
                    <td className="px-3 py-2">{row.put_away_qty}</td>
                    <td className="px-3 py-2 text-xs text-gray-800 align-top whitespace-nowrap">
                      <div className="font-mono tabular-nums leading-snug">
                        <div>
                          {ocPortalDash(row.create_time ?? formatInboundCreateTime(row.raw, row.inbound_at))}
                        </div>
                        <div className="text-gray-700">
                          {ocPortalDash(row.putaway_time ?? formatInboundPutawayTime(row.raw))}
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-700 whitespace-nowrap font-mono tabular-nums">
                      {ocPortalDash(row.arrived_time ?? formatInboundArrivedTime(row.raw))}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-800 align-top max-w-[14rem]">
                      <InboundSkuListCell raw={row.raw} />
                    </td>
                    <td className="px-3 py-2 align-top">
                      <input
                        type="date"
                        className={`text-xs font-mono rounded border px-1 py-0.5 max-w-[11rem] ${
                          etaIsEdited ? 'bg-[#DFFFEA] border-gray-200' : 'border-gray-200 bg-white'
                        }`}
                        value={etaInputValue || ''}
                        onChange={(e) =>
                          setInboundEtaOverride(rowKey, e.target.value || null, defaultEtaYmd)
                        }
                        title="Defaults to create time + 3 months. Edit to override; green = saved override."
                      />
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-800 align-top max-w-[9rem]">
                      {trackingPairs.length === 0 ? (
                        '—'
                      ) : (
                        <span className="inline-flex flex-wrap items-baseline gap-y-0.5">
                          {trackingPairs.map((p, i) => (
                            <span
                              key={p.tracking}
                              className="inline-flex items-baseline whitespace-nowrap"
                            >
                              <a
                                href={parcelsAppTrackingUrl(p.tracking, countryIso)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-blue-600 hover:underline"
                                title={
                                  countryIso
                                    ? `Track on ParcelsApp (country hint: ${countryIso})`
                                    : 'Track on ParcelsApp'
                                }
                              >
                                {p.carrier}
                              </a>
                              {i < trackingPairs.length - 1 ? (
                                <span className="text-gray-400" aria-hidden>
                                  ,{' '}
                                </span>
                              ) : null}
                            </span>
                          ))}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-800 align-top max-w-[11rem] break-words">
                      {formatInboundTrackingNumbers(row.raw)}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-800 whitespace-nowrap font-mono tabular-nums">
                      {formatOrderTimeDays(createDisplay, putawayDisplay)}
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
              </div>
            </div>
          </>
        )}
      </section>
    </div>
  )
}
