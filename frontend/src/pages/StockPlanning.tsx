import { useState, useEffect, useCallback } from 'react'
import { inventoryStatusAPI, stockAPI, type SKU } from '../services/api'
import {
  buildOcSkuImportExports,
  downloadOcSkuImportZip,
} from '../utils/ocSkuImportExport'
import { stockUnitsFromOcInventory } from '../utils/stockPlanningInventory'

/** Persist planned units per SKU in this browser (survives refresh; same machine only). */
const UNITS_STORAGE_KEY = 'evampops.stockPlanning.unitsBySku'
const ITEMS_PER_CARTON_STORAGE_KEY = 'evampops.stockPlanning.itemsPerCarton'

function loadUnitsFromStorage(): Record<string, number> {
  try {
    const raw = localStorage.getItem(UNITS_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const out: Record<string, number> = {}
    for (const [k, v] of Object.entries(parsed)) {
      const n = typeof v === 'number' ? v : Number(v)
      if (Number.isFinite(n) && n >= 0) out[k] = Math.floor(n)
    }
    return out
  } catch {
    return {}
  }
}

function persistUnitsBySku(rows: { sku_code: string; units: number }[]) {
  const obj: Record<string, number> = {}
  for (const r of rows) {
    if (r.units > 0) obj[r.sku_code] = r.units
  }
  try {
    if (Object.keys(obj).length === 0) {
      localStorage.removeItem(UNITS_STORAGE_KEY)
    } else {
      localStorage.setItem(UNITS_STORAGE_KEY, JSON.stringify(obj))
    }
  } catch {
    // quota / private mode
  }
}

function loadItemsPerCartonFromStorage(): number {
  // OC inbound requires exact cartons; we keep this fixed at 4.
  return 4
}

function persistItemsPerCarton(value: number) {
  // Fixed at 4; persist for completeness in case you want to change later.
  try {
    localStorage.setItem(ITEMS_PER_CARTON_STORAGE_KEY, '4')
  } catch {
    // ignore
  }
}

const formatLocalDate = (d: Date): string => {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/** GBP profit per unit from Sales Analytics (same logic as /analytics/by-sku). */
async function fetchHistoricalProfitPerUnitGbp(lookbackDays: number): Promise<Map<string, number>> {
  const to = new Date()
  const fromDate = new Date(to)
  fromDate.setDate(fromDate.getDate() - (lookbackDays - 1))
  const from = formatLocalDate(fromDate)
  const toStr = formatLocalDate(to)
  const res = await stockAPI.getAnalyticsBySku({ from, to: toStr })
  const m = new Map<string, number>()
  for (const p of res.data) {
    let ppu = p.profit_per_unit != null ? Number(p.profit_per_unit) : NaN
    if (!Number.isFinite(ppu) || ppu <= 0) {
      if (p.quantity_sold > 0) {
        const total = parseFloat(p.profit)
        ppu = Number.isFinite(total) ? total / p.quantity_sold : NaN
      }
    }
    if (Number.isFinite(ppu) && ppu > 0) {
      m.set(p.sku_code, ppu)
    }
  }
  return m
}

interface PlanRow {
  sku_code: string
  title: string
  landed_cost: number
  profit_per_unit: number
  units: number
  /** Realized avg profit per unit (GBP) from sales analytics for the lookback window. */
  analytics_profit_per_unit_gbp: number | null
}

export default function StockPlanning() {
  const [skus, setSkus] = useState<SKU[]>([])
  const [planRows, setPlanRows] = useState<PlanRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [showMessageModal, setShowMessageModal] = useState(false)
  const [orderMessage, setOrderMessage] = useState('')
  const [generatingMessage, setGeneratingMessage] = useState(false)
  const [generatingOcInbound, setGeneratingOcInbound] = useState(false)
  const [fillingFromOc, setFillingFromOc] = useState(false)
  const [exportNotice, setExportNotice] = useState<string | null>(null)
  const [analyticsLookbackDays, setAnalyticsLookbackDays] = useState(90)
  const [itemsPerCarton, setItemsPerCarton] = useState<number>(() => loadItemsPerCartonFromStorage())

  const loadSkus = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await stockAPI.listSKUs()
      const sorted = [...res.data].sort((a, b) => a.sku_code.localeCompare(b.sku_code))
      const savedUnits = loadUnitsFromStorage()
      setSkus(sorted)
      setPlanRows(
        sorted.map((s) => ({
          sku_code: s.sku_code,
          title: s.title,
          landed_cost: Number(s.landed_cost) || 0,
          profit_per_unit: Number(s.profit_per_unit) || 0,
          units: savedUnits[s.sku_code] ?? 0,
          analytics_profit_per_unit_gbp: null,
        }))
      )
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load SKUs')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSkus()
  }, [loadSkus])

  // Merge Sales Analytics profit/unit (GBP) whenever SKUs load or lookback changes — does not reset units.
  useEffect(() => {
    if (skus.length === 0) return
    let cancelled = false
    ;(async () => {
      try {
        const profitMap = await fetchHistoricalProfitPerUnitGbp(analyticsLookbackDays)
        if (cancelled) return
        setPlanRows((prev) => {
          if (prev.length === 0) {
            const savedUnits = loadUnitsFromStorage()
            return skus.map((s) => ({
              sku_code: s.sku_code,
              title: s.title,
              landed_cost: Number(s.landed_cost) || 0,
              profit_per_unit: Number(s.profit_per_unit) || 0,
              units: savedUnits[s.sku_code] ?? 0,
              analytics_profit_per_unit_gbp: profitMap.get(s.sku_code) ?? null,
            }))
          }
          return prev.map((r) => ({
            ...r,
            analytics_profit_per_unit_gbp: profitMap.get(r.sku_code) ?? null,
          }))
        })
      } catch {
        // non-fatal
      }
    })()
    return () => {
      cancelled = true
    }
  }, [skus, analyticsLookbackDays])

  const updateUnits = (skuCode: string, units: number) => {
    setPlanRows((prev) => {
      const next = prev.map((row) =>
        row.sku_code === skuCode ? { ...row, units: Math.max(0, units) } : row
      )
      persistUnitsBySku(next)
      return next
    })
  }

  // Landed cost is stored in USD. Line extension in USD = landed_cost × units.
  // GBP uses fixed rate: 1 GBP = USD_PER_GBP USD (so GBP = USD / USD_PER_GBP).
  const USD_PER_GBP = 1.35

  const calculateCostUSD = (row: PlanRow) => row.landed_cost * row.units
  const calculateCostGBP = (row: PlanRow) => calculateCostUSD(row) / USD_PER_GBP
  /**
   * Est. profit in GBP: prefer realized avg from Sales Analytics (same methodology as Analytics → by SKU).
   * Otherwise manual SKU `profit_per_unit` with ×0.8 planning haircut.
   */
  const calculateProfit = (row: PlanRow) => {
    const u = row.units
    if (u <= 0) return 0
    const hist = row.analytics_profit_per_unit_gbp
    if (hist != null && hist > 0) {
      return u * hist
    }
    return u * row.profit_per_unit * 0.8
  }

  const totalUnits = planRows.reduce((sum, r) => sum + r.units, 0)
  const totalCostUSD = planRows.reduce((sum, r) => sum + calculateCostUSD(r), 0)
  const totalCostGBP = totalCostUSD / USD_PER_GBP
  const totalProfit = planRows.reduce((sum, r) => sum + calculateProfit(r), 0)

  // Only show rows with units > 0 in summary
  const activeRows = planRows.filter((r) => r.units > 0)

  const handleCopyPlan = () => {
    if (activeRows.length === 0) return
    const lines = activeRows.map(
      (r) =>
        `${r.sku_code}\t${r.title}\t${r.units}\t${calculateCostUSD(r).toFixed(2)}\t${calculateCostGBP(r).toFixed(2)}`
    )
    const text = `SKU\tTitle\tUnits\tCost USD\tCost GBP\n${lines.join('\n')}\n\nTotal: ${totalUnits} units, USD: ${totalCostUSD.toFixed(2)}, GBP: ${totalCostGBP.toFixed(2)}`
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleClearAll = () => {
    setPlanRows((prev) => {
      const next = prev.map((row) => ({ ...row, units: 0 }))
      persistUnitsBySku(next)
      return next
    })
  }

  const handleGenerateOrderMessage = async () => {
    if (activeRows.length === 0) return
    setGeneratingMessage(true)
    setError(null)
    try {
      const items = activeRows.map((r) => ({
        sku_code: r.sku_code,
        title: r.title,
        quantity: r.units,
      }))
      const res = await stockAPI.generateOrderMessage(items)
      setOrderMessage(res.data.message)
      setShowMessageModal(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to generate message')
    } finally {
      setGeneratingMessage(false)
    }
  }

  const handleCopyMessage = () => {
    navigator.clipboard.writeText(orderMessage)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleFillUnitsFromOcStock = async () => {
    setFillingFromOc(true)
    setError(null)
    try {
      const [invRes, mapRes] = await Promise.all([
        inventoryStatusAPI.listInventory(),
        inventoryStatusAPI.listSkuMappings(),
      ])
      const totals = stockUnitsFromOcInventory(mapRes.data, invRes.data)
      setPlanRows((prev) => {
        const next = prev.map((row) => {
          const k = row.sku_code.trim().toLowerCase()
          return totals[k] !== undefined ? { ...row, units: totals[k]! } : row
        })
        persistUnitsBySku(next)
        return next
      })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load OC inventory')
    } finally {
      setFillingFromOc(false)
    }
  }

  const handleGenerateOcInbound = async () => {
    if (activeRows.length === 0) return
    setGeneratingOcInbound(true)
    setError(null)
    setExportNotice(null)
    try {
      const mappingsRes = await inventoryStatusAPI.listSkuMappings()
      const result = await buildOcSkuImportExports(
        activeRows.map((r) => ({ sku_code: r.sku_code, units: r.units })),
        mappingsRes.data,
        itemsPerCarton
      )
      const warnings: string[] = []
      if (result.unknownPrefix.length > 0) {
        warnings.push(
          `Skipped SKUs (expected leading letters then digits in SKU code): ${result.unknownPrefix.join(', ')}.`
        )
      }
      if (result.missingMapping.length > 0) {
        warnings.push(
          `No OC MFSKUID in Inventory status for: ${result.missingMapping.join(', ')}. Run Pull latest data there (or sync SKU mappings).`
        )
      }
      if (result.ambiguousMapping.length > 0) {
        warnings.push(
          `Some SKUs have multiple OC service_region mappings; export used the first mapping: ${result.ambiguousMapping.join(', ')}.`
        )
      }
      if (result.files.length === 0) {
        setError(
          warnings.join(' ') || 'Nothing to export — add units and ensure OC mappings exist for those SKUs.'
        )
        return
      }
      await downloadOcSkuImportZip(result)
      if (warnings.length > 0) {
        setExportNotice(warnings.join('\n'))
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'OC inbound export failed')
    } finally {
      setGeneratingOcInbound(false)
    }
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-6">Stock Order</h1>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error}
        </div>
      )}
      {exportNotice && (
        <div className="mb-4 p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 text-sm whitespace-pre-wrap">
          {exportNotice}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Total Units</p>
          <p className="text-2xl font-bold text-gray-900">{totalUnits}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Total Cost (GBP)</p>
          <p className="text-2xl font-bold text-gray-900">{totalCostGBP.toFixed(2)}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Total Cost (USD)</p>
          <p className="text-2xl font-bold text-gray-900">{totalCostUSD.toFixed(2)}</p>
        </div>
        <div className="bg-white shadow rounded-lg p-4">
          <p className="text-sm text-gray-500">Est. profit (GBP)</p>
          <p className="text-2xl font-bold text-green-600">{totalProfit.toFixed(2)}</p>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="flex flex-wrap gap-2 mb-4">
        <button
          type="button"
          onClick={handleFillUnitsFromOcStock}
          disabled={loading || planRows.length === 0 || fillingFromOc}
          className="px-4 py-2 bg-indigo-600 text-white rounded hover:bg-indigo-700 disabled:opacity-50 text-sm font-medium"
          title="Sets Units to OrangeConnex available + in transit per SKU (Inventory status). Pull latest data there first if counts look stale. SKUs with no OC mapping or row are left unchanged."
        >
          {fillingFromOc ? 'Loading…' : 'Fill units from OC stock'}
        </button>
        <button
          type="button"
          onClick={handleGenerateOrderMessage}
          disabled={activeRows.length === 0 || generatingMessage}
          className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
        >
          {generatingMessage ? 'Generating...' : 'Generate supplier order'}
        </button>
        <button
          type="button"
          onClick={handleGenerateOcInbound}
          disabled={activeRows.length === 0 || generatingOcInbound}
          className="px-4 py-2 bg-emerald-700 text-white rounded hover:bg-emerald-800 disabled:opacity-50 text-sm font-medium"
          title="Excel files per SKU letter-prefix group. Uses OC MFSKUID from Inventory status mappings."
        >
          {generatingOcInbound ? 'Building…' : 'Generate OC inbound'}
        </button>
        <button
          type="button"
          onClick={handleCopyPlan}
          disabled={activeRows.length === 0}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
        >
          {copied ? 'Copied!' : 'Copy plan to clipboard'}
        </button>
        <button
          type="button"
          onClick={handleClearAll}
          disabled={totalUnits === 0}
          className="px-4 py-2 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 disabled:opacity-50 text-sm font-medium"
        >
          Clear all
        </button>
      </div>
      <div className="mb-6 text-sm text-gray-700 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2">
          <span className="text-gray-600">Profit lookback (Sales Analytics)</span>
          <select
            className="h-9 w-28 appearance-none rounded border border-gray-300 bg-white bg-[length:12px_12px] bg-[right_0.6rem_center] bg-no-repeat pl-2 pr-8 text-sm text-gray-900"
            style={{
              backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 24 24' stroke='%236b7280'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' stroke-width='2' d='M19 9l-7 7-7-7'/%3E%3C/svg%3E")`,
            }}
            value={analyticsLookbackDays}
            onChange={(e) => setAnalyticsLookbackDays(Number(e.target.value))}
          >
            <option value={30}>30 days</option>
            <option value={90}>90 days</option>
            <option value={180}>180 days</option>
            <option value={365}>365 days</option>
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span>Items per carton for Generate supplier order</span>
          <input
            type="number"
            min={4}
            max={4}
            step={1}
            value={itemsPerCarton}
            onChange={(e) => {
              const next = parseInt(e.target.value, 10) || 4
              setItemsPerCarton(next)
              persistItemsPerCarton(next)
            }}
            className="h-9 w-28 rounded border border-gray-300 bg-white px-2 text-right text-sm text-gray-900"
          />
        </label>
      </div>

      {/* Order Message Modal */}
      {showMessageModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="p-4 border-b border-gray-200 flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-800">Supplier Order Message</h3>
              <button
                type="button"
                onClick={() => setShowMessageModal(false)}
                className="text-gray-500 hover:text-gray-700"
              >
                &times;
              </button>
            </div>
            <div className="p-4 flex-1 overflow-y-auto">
              <textarea
                value={orderMessage}
                onChange={(e) => setOrderMessage(e.target.value)}
                className="w-full h-64 rounded border border-gray-300 px-3 py-2 text-sm font-mono"
                placeholder="Order message..."
              />
            </div>
            <div className="p-4 border-t border-gray-200 flex gap-2 justify-end">
              <button
                type="button"
                onClick={handleCopyMessage}
                className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 text-sm font-medium"
              >
                {copied ? 'Copied!' : 'Copy to clipboard'}
              </button>
              <button
                type="button"
                onClick={() => setShowMessageModal(false)}
                className="px-4 py-2 bg-gray-100 text-gray-700 rounded hover:bg-gray-200 text-sm font-medium"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* SKU Table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-6 text-gray-500">Loading SKUs...</div>
        ) : planRows.length === 0 ? (
          <div className="p-6 text-gray-500">No SKUs found. Add SKUs in the SKU Manager first.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead>
                <tr className="bg-gray-50">
                  <th className="px-4 py-3 text-left font-medium text-gray-700">SKU</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-700">Title</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Landed Cost (USD)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Units</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Cost (GBP)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Cost (USD)</th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700" title="From Sales Analytics for the lookback window">
                    Avg £/unit (hist.)
                  </th>
                  <th className="px-4 py-3 text-right font-medium text-gray-700">Est. profit (GBP)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {planRows.map((row) => {
                  const costUSD = calculateCostUSD(row)
                  const costGBP = calculateCostGBP(row)
                  const profit = calculateProfit(row)
                  return (
                    <tr
                      key={row.sku_code}
                      className={row.units > 0 ? 'bg-blue-50' : 'hover:bg-gray-50'}
                    >
                      <td className="px-4 py-2 font-medium text-gray-900">{row.sku_code}</td>
                      <td className="px-4 py-2 text-gray-700 max-w-xs truncate" title={row.title}>
                        {row.title}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-600">
                        {row.landed_cost.toFixed(2)}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <input
                          type="number"
                          min={0}
                          value={row.units || ''}
                          onChange={(e) =>
                            updateUnits(row.sku_code, parseInt(e.target.value, 10) || 0)
                          }
                          className="w-20 rounded border border-gray-300 px-2 py-1 text-right text-sm"
                          placeholder="0"
                        />
                      </td>
                      <td className="px-4 py-2 text-right text-gray-700">
                        {row.units > 0 ? costGBP.toFixed(2) : '-'}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-700">
                        {row.units > 0 ? costUSD.toFixed(2) : '-'}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-600 text-xs">
                        {row.analytics_profit_per_unit_gbp != null && row.analytics_profit_per_unit_gbp > 0
                          ? row.analytics_profit_per_unit_gbp.toFixed(4)
                          : '—'}
                      </td>
                      <td className="px-4 py-2 text-right text-green-600 font-medium">
                        {row.units > 0 ? profit.toFixed(2) : '-'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              {totalUnits > 0 && (
                <tfoot>
                  <tr className="bg-gray-100 font-semibold">
                    <td className="px-4 py-3" colSpan={3}>
                      Totals
                    </td>
                    <td className="px-4 py-3 text-right">{totalUnits}</td>
                    <td className="px-4 py-3 text-right">{totalCostGBP.toFixed(2)}</td>
                    <td className="px-4 py-3 text-right">{totalCostUSD.toFixed(2)}</td>
                    <td className="px-4 py-3 text-right">—</td>
                    <td className="px-4 py-3 text-right text-green-600">{totalProfit.toFixed(2)}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
