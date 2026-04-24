import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import { inventoryStatusAPI } from '../services/api'
import { buildDailyStockLevelsFromHistory } from '../utils/inventoryHistoryFormat'

const formatLocalDate = (d: Date): string => {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const todayIso = () => formatLocalDate(new Date())

const offsetDaysFromToday = (daysAgo: number) => {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  return formatLocalDate(d)
}

function formatOosDayLabel(iso: string): string {
  const [y, m, d] = iso.split('-').map((v) => Number(v))
  if (!y || !m || !d) return iso
  return new Date(y, m - 1, d).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

function daysCoverTextClass(doc: number | null | undefined): string {
  if (doc == null || Number.isNaN(doc)) return 'text-slate-700'
  if (doc < 14) return 'text-red-700 font-medium'
  if (doc <= 30) return 'text-amber-800 font-medium'
  return 'text-emerald-800 font-medium'
}

/** Inclusive last N calendar days (same as Sales Analytics). */
const lastNDaysFrom = (n: number) => offsetDaysFromToday(n - 1)

type PeriodPreset = 'today' | '7d' | '1m' | '3m' | '6m' | '1y' | 'custom'

function formatDelta(n: number | null): string {
  if (n === null || n === undefined) return '—'
  if (n === 0) return '0'
  return n > 0 ? `+${n}` : String(n)
}

function DiagnosticsPanel() {
  const dbDbg = useQuery({
    queryKey: ['debug-stock-movement-db'],
    queryFn: async () => (await inventoryStatusAPI.debugStockMovementDb()).data,
    enabled: false,
  })

  return (
    <div className="mb-4 p-3 bg-slate-50 border border-slate-200 rounded text-sm">
      <div className="font-medium text-slate-800 mb-1">Diagnostics</div>
      <p className="text-slate-600 mb-2">
        Verbatim OC JSON and DB stats.{' '}
        <code className="text-xs break-all">GET /api/inventory-status/debug/stock-movement-db</code> — persisted movement
        rows. <code className="text-xs break-all">GET /api/inventory-status/debug-raw</code> — StockSnapshot v2 + SKU
        query.{' '}
        <code className="text-xs break-all">GET /api/inventory-status/debug/oc-movement-raw?mfskuid=…</code> — single
        GetStockMovement call.
      </p>
      <button
        type="button"
        onClick={() => void dbDbg.refetch()}
        className="text-sm px-3 py-1 bg-slate-200 rounded hover:bg-slate-300"
      >
        Load movement DB stats (JSON)
      </button>
      {dbDbg.isFetching && <span className="ml-2 text-slate-500">Loading…</span>}
      {dbDbg.data && (
        <pre className="mt-2 text-xs overflow-auto max-h-48 bg-white p-2 border rounded">{JSON.stringify(dbDbg.data, null, 2)}</pre>
      )}
      {dbDbg.isError && (
        <p className="text-red-600 text-xs mt-1">{dbDbg.error instanceof Error ? dbDbg.error.message : 'Request failed'}</p>
      )}
    </div>
  )
}

export default function InventoryMovement() {
  const queryClient = useQueryClient()
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset>('1y')
  const [from, setFrom] = useState(() => lastNDaysFrom(365))
  const [to, setTo] = useState(() => todayIso())
  /** `all` = every mapped seller SKU (aggregated). Otherwise OC seller SKU id. */
  const [skuSelect, setSkuSelect] = useState<string>('all')

  const applyPeriodPreset = (preset: PeriodPreset) => {
    const today = todayIso()
    let newFrom = from
    let newTo = to
    if (preset === 'today') {
      newFrom = today
      newTo = today
    } else if (preset === '7d') {
      newFrom = lastNDaysFrom(7)
      newTo = today
    } else if (preset === '1m') {
      newFrom = lastNDaysFrom(30)
      newTo = today
    } else if (preset === '3m') {
      newFrom = lastNDaysFrom(90)
      newTo = today
    } else if (preset === '6m') {
      newFrom = lastNDaysFrom(180)
      newTo = today
    } else if (preset === '1y') {
      newFrom = lastNDaysFrom(365)
      newTo = today
    }
    setFrom(newFrom)
    setTo(newTo)
    setPeriodPreset(preset)
  }

  const mappingsQuery = useQuery({
    queryKey: ['sku-mappings', 'inventory-movement'],
    queryFn: async () => (await inventoryStatusAPI.listSkuMappings()).data,
  })

  const inventoryQuery = useQuery({
    queryKey: ['inventory-status', 'movement-dashboard'],
    queryFn: async () => (await inventoryStatusAPI.listInventory()).data,
  })

  const movementQuery = useQuery({
    queryKey: ['stock-movement', from, to, skuSelect],
    queryFn: async () =>
      (
        await inventoryStatusAPI.listStockMovement({
          from,
          to,
          ...(skuSelect !== 'all' ? { seller_skuid: skuSelect } : {}),
        })
      ).data,
  })

  const inventoryHistoryQuery = useQuery({
    queryKey: ['inventory-history', from, to, skuSelect],
    queryFn: async () =>
      (
        await inventoryStatusAPI.getInventoryHistory({
          from,
          to,
          ...(skuSelect !== 'all' ? { seller_skuid: skuSelect } : {}),
        })
      ).data,
  })

  const stockForecastQuery = useQuery({
    queryKey: ['stock-forecast'],
    queryFn: async () => (await inventoryStatusAPI.getStockForecast()).data,
  })

  type SyncStockMovementMode = { mode: 'incremental' } | { mode: 'range' }

  const syncFromOcMutation = useMutation({
    mutationFn: async (opts: SyncStockMovementMode) => {
      if (opts.mode === 'incremental') {
        const res = await inventoryStatusAPI.syncStockMovementFromOc({ incremental: true })
        return res.data
      }
      const res = await inventoryStatusAPI.syncStockMovementFromOc({ from, to })
      return res.data
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['stock-movement'] })
      await queryClient.invalidateQueries({ queryKey: ['inventory-history'] })
      await queryClient.invalidateQueries({ queryKey: ['stock-forecast'] })
    },
  })

  const rawHistoryPoints = inventoryHistoryQuery.data?.points ?? []
  const dailyStockChartData = useMemo(
    () => buildDailyStockLevelsFromHistory(rawHistoryPoints, from, to),
    [inventoryHistoryQuery.data?.points, from, to],
  )

  const invRows = useMemo(() => {
    const rows = inventoryQuery.data ?? []
    if (skuSelect === 'all') return rows
    return rows.filter((r) => (r.seller_skuid || '').trim() === skuSelect)
  }, [inventoryQuery.data, skuSelect])

  const skuCodeByMfskuid = useMemo(() => {
    const m = new Map<string, string>()
    for (const row of mappingsQuery.data ?? []) {
      const mf = (row.mfskuid || '').trim().toLowerCase()
      if (mf && !m.has(mf)) m.set(mf, (row.sku_code || '').trim())
    }
    return m
  }, [mappingsQuery.data])

  const stockStats = useMemo(() => {
    let totalAvail = 0
    let totalTransit = 0
    let oos = 0
    for (const r of invRows) {
      totalAvail += r.available
      totalTransit += r.in_transit
      if (r.available <= 0) oos += 1
    }
    return {
      lines: invRows.length,
      totalAvail,
      totalTransit,
      oosLines: oos,
    }
  }, [invRows])

  const sellerOptions = useMemo(() => {
    const m = mappingsQuery.data ?? []
    const seen = new Set<string>()
    const out: string[] = []
    for (const row of m) {
      const s = (row.seller_skuid || '').trim()
      if (s && !seen.has(s)) {
        seen.add(s)
        out.push(s)
      }
    }
    return out.sort((a, b) => a.localeCompare(b))
  }, [mappingsQuery.data])

  const loading = movementQuery.isLoading
  const isError = movementQuery.isError
  const errMsg =
    movementQuery.error instanceof Error ? movementQuery.error.message : 'Failed to load movement data'

  const sortedInvTable = useMemo(() => {
    return [...invRows].sort((a, b) => a.available - b.available).slice(0, 40)
  }, [invRows])

  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="flex flex-wrap items-baseline justify-between gap-4 mb-4">
        <h1 className="text-3xl font-bold text-gray-900">Stock & movement</h1>
        <Link to="/inventory-status" className="text-sm text-blue-600 hover:underline">
          Inventory status (OC sync)
        </Link>
      </div>

      <p className="text-gray-600 mb-4 max-w-3xl">
        <strong>Current stock levels</strong> (available, in transit) live on{' '}
        <Link to="/inventory-status" className="text-blue-600 hover:underline">
          Inventory status
        </Link>{' '}
        → <strong>Pull latest data</strong>.         The <strong>stock chart</strong> uses persisted GetStockMovement rows (
        <code className="text-xs">actual_count</code>, AVL only); sync movement below to fill history. This page
        also lists raw <strong>movement lines</strong> for audit.
      </p>

      <DiagnosticsPanel />

      <p className="text-sm text-gray-600 mb-6 max-w-3xl">
        Stock levels by day (from movement data in PostgreSQL — same filter card layout as Sales Analytics). Table below
        shows the same feed in detail.
      </p>

      <div className="bg-white shadow rounded-lg p-4 mb-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Filters</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Period</label>
            <select
              value={periodPreset}
              onChange={(e) => applyPeriodPreset(e.target.value as PeriodPreset)}
              className="w-full rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm"
            >
              <option value="today">Today</option>
              <option value="7d">Last 7 days</option>
              <option value="1m">Last month</option>
              <option value="3m">Last 3 months</option>
              <option value="6m">Last 6 months</option>
              <option value="1y">Last year</option>
              <option value="custom">Custom</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">From</label>
            <input
              type="date"
              value={from}
              onChange={(e) => {
                setFrom(e.target.value)
                setPeriodPreset('custom')
              }}
              className="w-full rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">To</label>
            <input
              type="date"
              value={to}
              onChange={(e) => {
                setTo(e.target.value)
                setPeriodPreset('custom')
              }}
              className="w-full rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SKU</label>
            <select
              value={skuSelect}
              onChange={(e) => setSkuSelect(e.target.value)}
              className="w-full rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm"
            >
              <option value="all">All</option>
              {sellerOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 mt-4">
          <button
            type="button"
            onClick={() => {
              void inventoryQuery.refetch()
              void movementQuery.refetch()
              void inventoryHistoryQuery.refetch()
              void stockForecastQuery.refetch()
            }}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
          >
            Refresh
          </button>
          <button
            type="button"
            disabled={syncFromOcMutation.isPending}
            onClick={() => syncFromOcMutation.mutate({ mode: 'range' })}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {syncFromOcMutation.isPending ? 'Syncing…' : 'Sync range from OC'}
          </button>
          <button
            type="button"
            disabled={syncFromOcMutation.isPending}
            onClick={() => syncFromOcMutation.mutate({ mode: 'incremental' })}
            className="px-4 py-2 border border-indigo-600 text-indigo-700 text-sm rounded hover:bg-indigo-50 disabled:opacity-50"
          >
            Incremental sync
          </button>
        </div>
        {inventoryHistoryQuery.isLoading && <p className="mt-2 text-sm text-gray-500">Loading chart data…</p>}
      </div>
      {syncFromOcMutation.isError && (
        <p className="text-red-600 text-sm mb-2">
          {syncFromOcMutation.error instanceof Error ? syncFromOcMutation.error.message : 'Sync failed'}
        </p>
      )}
      {syncFromOcMutation.isSuccess && syncFromOcMutation.data && (
        <p className="text-green-800 text-sm mb-2">
          Fetched {syncFromOcMutation.data.fetched}, inserted {syncFromOcMutation.data.inserted} (
          {syncFromOcMutation.data.from_date} → {syncFromOcMutation.data.to_date}).
          {syncFromOcMutation.data.clamped ? (
            <span className="block mt-1 text-amber-800">
              Range was limited to the last 12 months (OrangeConnex API constraint). Effective window is shown above.
            </span>
          ) : null}
        </p>
      )}

      {inventoryHistoryQuery.isError && (
        <p className="text-red-600 text-sm mb-4">
          {inventoryHistoryQuery.error instanceof Error
            ? inventoryHistoryQuery.error.message
            : 'Failed to load inventory history'}
        </p>
      )}

      {inventoryHistoryQuery.data?.note && (
        <p className="text-xs text-gray-500 mb-2 max-w-3xl">{inventoryHistoryQuery.data.note}</p>
      )}

      {stockForecastQuery.isError && (
        <p className="text-red-600 text-sm mb-4">
          {stockForecastQuery.error instanceof Error
            ? stockForecastQuery.error.message
            : 'Failed to load stock forecast'}
        </p>
      )}

      {stockForecastQuery.data && !stockForecastQuery.isError && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white overflow-hidden shadow-sm">
          <div className="px-4 py-3 border-b border-slate-200 bg-slate-50">
            <h2 className="text-lg font-semibold text-slate-800">Stock run-out forecast</h2>
          </div>
          <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
            <table className="min-w-full text-sm text-left">
              <caption className="sr-only">Stock run-out by mapping, shortest cover first</caption>
              <thead>
                <tr className="text-gray-600 border-b border-gray-200 bg-white">
                  <th className="py-2 pl-4 pr-3 font-medium">SKU</th>
                  <th className="py-2 pr-3 font-medium">Region</th>
                  <th className="py-2 pr-3 font-medium text-right">Available</th>
                  <th className="py-2 pr-3 font-medium text-right">Burn rate/day</th>
                  <th className="py-2 pr-3 font-medium text-right">Days of cover</th>
                  <th className="py-2 pr-3 font-medium">Est. run-out</th>
                  <th className="py-2 pr-4 font-medium">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {stockForecastQuery.data.forecasts.map((f) => (
                  <tr
                    key={`${f.seller_skuid}-${f.mfskuid}-${f.service_region}`}
                    className="border-b border-gray-50 hover:bg-slate-50/80"
                  >
                    <td className="py-2 pl-4 pr-3 font-mono text-xs">{f.sku_name || f.seller_skuid}</td>
                    <td className="py-2 pr-3">{f.service_region}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">{f.current_available}</td>
                    <td className="py-2 pr-3 text-right tabular-nums">
                      {f.burn_rate_per_day != null ? f.burn_rate_per_day.toFixed(2) : '—'}
                    </td>
                    <td
                      className={`py-2 pr-3 text-right tabular-nums ${daysCoverTextClass(f.days_of_cover)}`}
                    >
                      {f.days_of_cover != null ? f.days_of_cover.toFixed(1) : '—'}
                    </td>
                    <td className="py-2 pr-3">
                      {f.estimated_oos_date ? formatOosDayLabel(f.estimated_oos_date) : '—'}
                    </td>
                    <td className="py-2 pr-4 text-xs text-slate-700">
                      {f.confidence === 'normal' ? (
                        'normal'
                      ) : (
                        <span className="inline-block rounded-full bg-slate-200 px-2 py-0.5 font-medium text-slate-800">
                          {f.confidence}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!inventoryHistoryQuery.isError && dailyStockChartData.length > 0 && (
        <div className="bg-white shadow rounded-lg p-4 mb-6">
          <h2 className="text-lg font-semibold text-gray-800 mb-4">Stock level by day</h2>
          <p className="text-sm text-gray-600 mb-4">
            Available stock from GetStockMovement (<code className="text-xs">actual_count</code>, AVL bucket only),
            grouped by event time — not eBay sales.{' '}
            {skuSelect === 'all' ? (
              <strong>All</strong>
            ) : (
              <>
                Seller SKU <span className="font-mono">{skuSelect}</span>
              </>
            )}
            . One point per calendar day (local); levels carry forward after the first sample in range.{' '}
            <span className="text-gray-500">
              {rawHistoryPoints.length.toLocaleString()} chart point(s) from movement rows in this filter.
            </span>
          </p>
          {rawHistoryPoints.length === 0 && !inventoryHistoryQuery.isLoading && (
            <p className="text-sm text-amber-900 bg-amber-50 border border-amber-200 rounded-lg p-3 mb-4">
              No movement samples in this range — line stays at 0. Run <strong>Sync range from OC</strong> or{' '}
              <strong>Incremental sync</strong>, then <strong>Refresh</strong>.
            </p>
          )}
          {rawHistoryPoints.length === 1 && !inventoryHistoryQuery.isLoading && (
            <p className="text-sm text-slate-700 bg-slate-50 border border-slate-200 rounded-lg p-3 mb-4">
              Only one time bucket in this window: earlier days show 0 until that event; from its date through{' '}
              <strong>to</strong> levels carry forward (step). More points appear as you sync wider movement history.
            </p>
          )}
          <ResponsiveContainer width="100%" height={360}>
            <LineChart data={dailyStockChartData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="period" tick={{ fontSize: 11 }} interval="preserveStartEnd" minTickGap={24} />
              <YAxis tick={{ fontSize: 12 }} allowDecimals={false} domain={[0, 'auto']} />
              <Tooltip
                formatter={(value: number) => [value, 'Available']}
                labelFormatter={(label) => `Day: ${label}`}
              />
              <ReferenceLine y={0} stroke="#cbd5e1" strokeDasharray="4 4" />
              <Line
                type="stepAfter"
                dataKey="available"
                name="Available"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
          <div className="overflow-x-auto border-t border-gray-100 pt-4 mt-4 max-h-64 overflow-y-auto">
            <table className="min-w-full text-sm text-left">
              <caption className="sr-only">Daily stock levels for the chart</caption>
              <thead>
                <tr className="text-gray-500 border-b border-gray-200">
                  <th className="py-2 pr-4 font-medium">Day (local)</th>
                  <th className="py-2 font-medium text-right">Available</th>
                </tr>
              </thead>
              <tbody>
                {dailyStockChartData.map((row) => (
                  <tr key={row.period} className="border-b border-gray-50">
                    <td className="py-1.5 pr-4 font-mono text-xs">{row.period}</td>
                    <td className="py-1.5 text-right tabular-nums">{row.available}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {!inventoryHistoryQuery.isLoading &&
        dailyStockChartData.length === 0 &&
        !inventoryHistoryQuery.isError && (
          <div className="mb-6 p-4 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-900">
            Invalid date range (from must be on or before to), or adjust filters.
          </div>
        )}

      {!mappingsQuery.isLoading && sellerOptions.length === 0 && (
        <div className="mb-6 p-4 bg-slate-50 border border-slate-200 rounded-lg text-sm text-slate-700">
          Add OrangeConnex SKU mappings on{' '}
          <Link to="/inventory-status" className="text-blue-600 hover:underline">
            Inventory status
          </Link>{' '}
          so a seller SKU can be chosen for the stock cycle chart.
        </div>
      )}

      {inventoryQuery.isLoading && <p className="text-gray-500 text-sm mb-2">Loading stock levels…</p>}

      <div className="mb-6 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="text-xs text-gray-500 uppercase tracking-wide">Available</div>
          <div className="text-2xl font-semibold tabular-nums text-gray-900">{stockStats.totalAvail.toLocaleString()}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="text-xs text-gray-500 uppercase tracking-wide">In transit</div>
          <div className="text-2xl font-semibold tabular-nums text-gray-900">{stockStats.totalTransit.toLocaleString()}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="text-xs text-gray-500 uppercase tracking-wide">SKU count</div>
          <div className="text-2xl font-semibold tabular-nums text-gray-900">{stockStats.lines}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="text-xs text-gray-500 uppercase tracking-wide">SKU not available</div>
          <div className="text-2xl font-semibold tabular-nums text-amber-800">{stockStats.oosLines}</div>
        </div>
      </div>

      {skuSelect === 'all' && (
        <p className="text-sm text-gray-600 mb-3">
          <strong>SKU: All</strong> — chart and tables sum every mapped seller SKU. Choose one SKU to see that line only.
        </p>
      )}

      {loading && <p className="text-gray-500 text-sm">Loading movement…</p>}
      {isError && <p className="text-red-600 text-sm mb-4">{errMsg}</p>}

      {movementQuery.data && (
        <p className="text-xs text-gray-500 mb-2">
          {movementQuery.data.note} {movementQuery.data.row_count.toLocaleString()} line(s), {movementQuery.data.from_date}{' '}
          → {movementQuery.data.to_date}.
        </p>
      )}

      <div className="mb-8 bg-white shadow rounded-lg overflow-hidden border border-gray-200">
        <div className="p-3 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-800">Stock levels (lowest first)</h2>
          <p className="text-xs text-gray-500 mt-1">From last Pull latest data. {sortedInvTable.length} row(s) shown.</p>
        </div>
        <div className="overflow-x-auto max-h-64 overflow-y-auto">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-3 py-2 text-left font-medium text-gray-700">SKU code</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700">Seller SKU</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700">Region</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700">Available</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700">In transit</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {sortedInvTable.map((r) => (
                <tr key={`${r.id}-${r.seller_skuid}-${r.service_region}`} className="hover:bg-gray-50">
                  <td className="px-3 py-1.5 text-gray-800">
                    {skuCodeByMfskuid.get((r.mfskuid || '').toLowerCase()) || '—'}
                  </td>
                  <td className="px-3 py-1.5 font-mono text-xs">{r.seller_skuid ?? '—'}</td>
                  <td className="px-3 py-1.5 text-gray-600">{r.service_region}</td>
                  <td
                    className={`px-3 py-1.5 text-right tabular-nums font-medium ${
                      r.available <= 0 ? 'text-red-700' : 'text-gray-900'
                    }`}
                  >
                    {r.available}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{r.in_transit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
          <div className="p-3 border-b border-gray-200 flex justify-between items-center">
            <h2 className="text-lg font-semibold text-gray-800">Stored movement lines</h2>
            {movementQuery.data?.row_count === 0 && !movementQuery.isLoading && (
              <span className="text-sm text-gray-600">
                No rows in this range — run <strong>Sync range from OC</strong> or <strong>Incremental sync</strong>.
              </span>
            )}
          </div>
          <div className="overflow-x-auto max-h-[min(70vh,720px)] overflow-y-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Updated</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">SKU</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Seller SKU</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Region</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Status</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Qty</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">After</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Reason</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Order</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Movement ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(movementQuery.data?.rows ?? []).map((r, i) => (
                  <tr key={`${r.movement_id}-${r.update_time}-${i}`} className="hover:bg-gray-50">
                    <td className="px-3 py-1.5 text-gray-800 whitespace-nowrap font-mono text-xs">{r.update_time || '—'}</td>
                    <td className="px-3 py-1.5 text-gray-800">{r.sku_code ?? '—'}</td>
                    <td className="px-3 py-1.5 font-mono text-xs">{r.seller_skuid ?? '—'}</td>
                    <td className="px-3 py-1.5 text-gray-600">{r.service_region}</td>
                    <td className="px-3 py-1.5 text-gray-600">{r.inventory_status}</td>
                    <td
                      className={`px-3 py-1.5 text-right tabular-nums font-medium ${
                        r.quantity > 0 ? 'text-green-700' : r.quantity < 0 ? 'text-red-700' : 'text-gray-700'
                      }`}
                    >
                      {formatDelta(r.quantity)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{r.actual_count ?? '—'}</td>
                    <td className="px-3 py-1.5 text-gray-700 max-w-xs truncate" title={r.reason ?? ''}>
                      {r.reason ?? '—'}
                    </td>
                    <td className="px-3 py-1.5 font-mono text-xs">{r.order_number ?? '—'}</td>
                    <td className="px-3 py-1.5 font-mono text-xs">{r.movement_id || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
    </div>
  )
}
