import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { inventoryStatusAPI } from '../services/api'

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

/** Inclusive last N calendar days (same as Sales Analytics). */
const lastNDaysFrom = (n: number) => offsetDaysFromToday(n - 1)

type PeriodPreset = 'today' | '7d' | '1m' | '3m' | '6m' | '1y' | 'custom'

function formatDelta(n: number | null): string {
  if (n === null || n === undefined) return '—'
  if (n === 0) return '0'
  return n > 0 ? `+${n}` : String(n)
}

function calendarDaysInclusive(fromIso: string, toIso: string): number {
  const a = new Date(`${fromIso}T12:00:00`)
  const b = new Date(`${toIso}T12:00:00`)
  return Math.max(1, Math.round((b.getTime() - a.getTime()) / 86_400_000) + 1)
}

function formatNum(n: number): string {
  if (!Number.isFinite(n)) return '—'
  return n >= 10 ? Math.round(n).toLocaleString() : n.toFixed(1)
}

/** OC returns times like 2024-07-15T19:48:37+0800 — take YYYY-MM-DD for daily rollups. */
function ocDateKey(updateTime: string): string | null {
  const s = (updateTime || '').trim()
  if (s.length >= 10 && /^\d{4}-\d{2}-\d{2}/.test(s)) {
    return s.slice(0, 10)
  }
  return null
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
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset>('1m')
  const [from, setFrom] = useState(() => lastNDaysFrom(30))
  const [to, setTo] = useState(() => todayIso())
  const [sellerSku, setSellerSku] = useState('')
  const [skuCode, setSkuCode] = useState('')

  const combinedSkuScope = !sellerSku.trim() && !skuCode.trim()

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
    queryKey: ['stock-movement', from, to, sellerSku, skuCode],
    queryFn: async () =>
      (
        await inventoryStatusAPI.listStockMovement({
          from,
          to,
          ...(sellerSku.trim() ? { seller_skuid: sellerSku.trim() } : {}),
          ...(skuCode.trim() ? { sku_code: skuCode.trim() } : {}),
        })
      ).data,
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
    },
  })

  const invRows = useMemo(() => {
    const rows = inventoryQuery.data ?? []
    const ss = sellerSku.trim()
    const sc = skuCode.trim().toLowerCase()
    if (ss) return rows.filter((r) => (r.seller_skuid || '').trim() === ss)
    if (sc) {
      const mfSet = new Set(
        (mappingsQuery.data ?? [])
          .filter((m) => (m.sku_code || '').trim().toLowerCase() === sc)
          .map((m) => (m.mfskuid || '').toLowerCase())
          .filter(Boolean)
      )
      return rows.filter((r) => mfSet.has((r.mfskuid || '').toLowerCase()))
    }
    return rows
  }, [inventoryQuery.data, sellerSku, skuCode, mappingsQuery.data])

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

  const stockBarData = useMemo(() => {
    return [...invRows]
      .sort((a, b) => b.available - a.available)
      .slice(0, 14)
      .map((r) => {
        const label =
          skuCodeByMfskuid.get((r.mfskuid || '').toLowerCase()) || r.seller_skuid || r.mfskuid || '?'
        return {
          name: String(label).slice(0, 22),
          available: r.available,
        }
      })
  }, [invRows, skuCodeByMfskuid])

  const restockInsight = useMemo(() => {
    const rows = movementQuery.data?.rows ?? []
    const net = rows.reduce((s, r) => s + r.quantity, 0)
    const days = calendarDaysInclusive(from, to)
    const avgDaily = net / days
    const totalAvail = invRows.reduce((s, r) => s + r.available, 0)
    let coverDays: number | null = null
    if (avgDaily < -0.0001 && totalAvail >= 0) {
      coverDays = totalAvail / -avgDaily
    }
    return { net, days, avgDaily, totalAvail, coverDays }
  }, [movementQuery.data?.rows, from, to, invRows])

  const ocChartPoints = useMemo(() => {
    const rows = movementQuery.data?.rows ?? []
    const agg = new Map<string, number>()
    for (const r of rows) {
      const dk = ocDateKey(r.update_time)
      if (!dk) continue
      agg.set(dk, (agg.get(dk) ?? 0) + r.quantity)
    }
    return [...agg.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([day, net_qty]) => ({
        day,
        label: day,
        net_qty,
      }))
  }, [movementQuery.data?.rows])

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
        → <strong>Pull latest data</strong>. This page is only for <strong>movement history</strong> from OrangeConnex.
      </p>

      <DiagnosticsPanel />

      <p className="text-sm text-gray-600 mb-3 max-w-3xl">
        <strong>Charts and table below</strong> read from EvampOps storage (not live OC). OrangeConnex only exposes
        movement for roughly the <strong>last 12 months</strong>; anything we have synced earlier stays in the database
        for reporting. Use <strong>Incremental sync</strong> regularly so new lines are captured before they fall
        outside OC&apos;s API window.
      </p>

      <div className="flex flex-wrap items-end gap-3 mb-6 p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <label className="text-sm">
          <span className="text-gray-600 block mb-1">Period</span>
          <select
            value={periodPreset}
            onChange={(e) => applyPeriodPreset(e.target.value as PeriodPreset)}
            className="rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm min-w-[11rem]"
          >
            <option value="today">Today</option>
            <option value="7d">Last 7 days</option>
            <option value="1m">Last month</option>
            <option value="3m">Last 3 months</option>
            <option value="6m">Last 6 months</option>
            <option value="1y">Last year</option>
            <option value="custom">Custom</option>
          </select>
        </label>
        <label className="text-sm">
          <span className="text-gray-600 block mb-1">From</span>
          <input
            type="date"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value)
              setPeriodPreset('custom')
            }}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>
        <label className="text-sm">
          <span className="text-gray-600 block mb-1">To</span>
          <input
            type="date"
            value={to}
            onChange={(e) => {
              setTo(e.target.value)
              setPeriodPreset('custom')
            }}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>
        <label className="text-sm">
          <span className="text-gray-600 block mb-1">Seller SKU</span>
          <input
            type="text"
            value={sellerSku}
            onChange={(e) => setSellerSku(e.target.value)}
            list="inv-move-seller-skus"
            placeholder="All SKUs if empty"
            className="rounded border border-gray-300 px-2 py-1 text-sm w-48"
          />
          <datalist id="inv-move-seller-skus">
            {sellerOptions.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        </label>
        <label className="text-sm">
          <span className="text-gray-600 block mb-1">SKU code</span>
          <input
            type="text"
            value={skuCode}
            onChange={(e) => setSkuCode(e.target.value)}
            placeholder="All if empty"
            className="rounded border border-gray-300 px-2 py-1 text-sm w-36"
          />
        </label>
        <button
          type="button"
          onClick={() => {
            void inventoryQuery.refetch()
            void movementQuery.refetch()
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

      {inventoryQuery.isLoading && <p className="text-gray-500 text-sm mb-2">Loading stock levels…</p>}

      <div className="mb-6 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="text-xs text-gray-500 uppercase tracking-wide">Available (filtered)</div>
          <div className="text-2xl font-semibold tabular-nums text-gray-900">{stockStats.totalAvail.toLocaleString()}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="text-xs text-gray-500 uppercase tracking-wide">In transit</div>
          <div className="text-2xl font-semibold tabular-nums text-gray-900">{stockStats.totalTransit.toLocaleString()}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="text-xs text-gray-500 uppercase tracking-wide">Seller lines</div>
          <div className="text-2xl font-semibold tabular-nums text-gray-900">{stockStats.lines}</div>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-3 shadow-sm">
          <div className="text-xs text-gray-500 uppercase tracking-wide">No available stock</div>
          <div className="text-2xl font-semibold tabular-nums text-amber-800">{stockStats.oosLines}</div>
        </div>
      </div>

      {stockBarData.length > 0 && (
        <div className="mb-6 bg-white border border-gray-200 rounded-lg p-4 h-64">
          <h2 className="text-sm font-medium text-gray-700 mb-2">Available by SKU (top {stockBarData.length})</h2>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={stockBarData} layout="vertical" margin={{ top: 4, right: 8, left: 8, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
              <YAxis type="category" dataKey="name" width={120} tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="available" name="Available" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {movementQuery.data && !movementQuery.isLoading && (
        <div className="mb-6 p-4 bg-emerald-50 border border-emerald-200 rounded-lg text-sm">
          <h2 className="text-sm font-semibold text-emerald-900 mb-2">Restock-oriented movement (selected period, from DB)</h2>
          <p className="text-emerald-800 mb-2">
            Net quantity change: <strong>{formatDelta(restockInsight.net)}</strong> over {restockInsight.days} day(s) (
            ~{formatNum(restockInsight.avgDaily)} / day). Current available (same filter as above):{' '}
            <strong>{restockInsight.totalAvail.toLocaleString()}</strong>.
            {restockInsight.coverDays != null && restockInsight.coverDays > 0 && restockInsight.coverDays < 10_000 ? (
              <>
                {' '}
                Rough days of cover at average outflow: <strong>{formatNum(restockInsight.coverDays)}</strong> (only
                meaningful when net change is negative / outbound).
              </>
            ) : (
              <span className="text-emerald-700"> No stable outbound pace to estimate cover (net change not negative).</span>
            )}
          </p>
          <p className="text-xs text-emerald-800">
            Scope: <code className="bg-emerald-100 px-1 rounded">{movementQuery.data.scope}</code> —{' '}
            {movementQuery.data.mfskuid_count} MFSKUID(s).{' '}
            {movementQuery.data.truncated ? (
              <span className="text-amber-800">
                Table truncated to {movementQuery.data.line_limit?.toLocaleString()} most recent lines.
              </span>
            ) : null}
          </p>
        </div>
      )}

      {combinedSkuScope && (
        <p className="text-sm text-gray-600 mb-3">
          <strong>All SKUs combined:</strong> movement and charts aggregate every mapped SKU. Narrow with seller SKU or SKU
          code if the request is slow.
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

      {ocChartPoints.length > 0 && (
        <div className="mb-8 bg-white border border-gray-200 rounded-lg p-4 h-72">
          <h2 className="text-sm font-medium text-gray-700 mb-2">
            Net quantity change by day {combinedSkuScope ? '(all SKUs combined)' : '(filtered)'}
          </h2>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={ocChartPoints} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="net_qty" name="Net qty" stroke="#059669" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
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
