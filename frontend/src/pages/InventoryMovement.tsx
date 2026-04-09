import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
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

type MovementSource = 'recorded' | 'oc_api'

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
    queryKey: ['debug-snapshot-history-db'],
    queryFn: async () => (await inventoryStatusAPI.debugSnapshotHistoryDb()).data,
    enabled: false,
  })

  return (
    <div className="mb-4 p-3 bg-slate-50 border border-slate-200 rounded text-sm">
      <div className="font-medium text-slate-800 mb-1">Diagnostics</div>
      <p className="text-slate-600 mb-2">
        Inspect verbatim OC responses and what we stored. Endpoints (same auth as the app):{' '}
        <code className="text-xs break-all">GET /api/inventory-status/debug/snapshot-history-db</code> — rows in{' '}
        <code className="text-xs">oc_sku_inventory_history</code> (one batch time per Pull latest data).{' '}
        <code className="text-xs break-all">GET /api/inventory-status/debug-raw</code> — StockSnapshot v2 + SKU query.{' '}
        <code className="text-xs break-all">GET /api/inventory-status/debug/oc-movement-raw?mfskuid=YOUR_MFSKUID</code> —
        GetStockMovement (optional <code className="text-xs">from</code>/<code className="text-xs">to</code> dates).
      </p>
      <button
        type="button"
        onClick={() => void dbDbg.refetch()}
        className="text-sm px-3 py-1 bg-slate-200 rounded hover:bg-slate-300"
      >
        Load DB snapshot stats (JSON)
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
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset>('1m')
  const [from, setFrom] = useState(() => lastNDaysFrom(30))
  const [to, setTo] = useState(() => todayIso())
  const [sellerSku, setSellerSku] = useState('')
  const [skuCode, setSkuCode] = useState('')
  const [dataSource, setDataSource] = useState<MovementSource>('oc_api')

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

  const historyQuery = useQuery({
    queryKey: ['inventory-history', from, to, sellerSku, skuCode],
    queryFn: async () =>
      (
        await inventoryStatusAPI.listInventoryHistory({
          from,
          to,
          ...(sellerSku.trim() ? { seller_skuid: sellerSku.trim() } : {}),
          ...(skuCode.trim() ? { sku_code: skuCode.trim() } : {}),
          limit: 20_000,
        })
      ).data,
    enabled: dataSource === 'recorded',
  })

  const ocQuery = useQuery({
    queryKey: ['oc-stock-movement', from, to, sellerSku, skuCode],
    queryFn: async () =>
      (
        await inventoryStatusAPI.listOcStockMovement({
          from,
          to,
          ...(sellerSku.trim() ? { seller_skuid: sellerSku.trim() } : {}),
          ...(skuCode.trim() ? { sku_code: skuCode.trim() } : {}),
        })
      ).data,
    enabled: dataSource === 'oc_api',
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
    const rows = ocQuery.data?.rows ?? []
    const net = rows.reduce((s, r) => s + r.quantity, 0)
    const days = calendarDaysInclusive(from, to)
    const avgDaily = net / days
    const totalAvail = invRows.reduce((s, r) => s + r.available, 0)
    let coverDays: number | null = null
    if (avgDaily < -0.0001 && totalAvail >= 0) {
      coverDays = totalAvail / -avgDaily
    }
    return { net, days, avgDaily, totalAvail, coverDays }
  }, [ocQuery.data?.rows, from, to, invRows])

  const chartPoints = useMemo(() => {
    const rows = historyQuery.data?.rows ?? []
    const agg = new Map<string, number>()
    for (const r of rows) {
      const t = r.recorded_at
      agg.set(t, (agg.get(t) ?? 0) + r.available)
    }
    return [...agg.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([recorded_at, available]) => ({
        recorded_at,
        label: new Date(recorded_at).toLocaleString(undefined, {
          month: 'short',
          day: 'numeric',
          hour: '2-digit',
          minute: '2-digit',
        }),
        available,
      }))
  }, [historyQuery.data?.rows])

  const ocChartPoints = useMemo(() => {
    const rows = ocQuery.data?.rows ?? []
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
  }, [ocQuery.data?.rows])

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

  const loading = dataSource === 'recorded' ? historyQuery.isLoading : ocQuery.isLoading
  const isError = dataSource === 'recorded' ? historyQuery.isError : ocQuery.isError
  const errMsg =
    dataSource === 'recorded'
      ? historyQuery.error instanceof Error
        ? historyQuery.error.message
        : 'Failed to load history'
      : ocQuery.error instanceof Error
        ? ocQuery.error.message
        : 'Failed to load OC movement'

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
        Current <strong>levels</strong> come from the last OC inventory sync. <strong>Movement</strong> from the OC API
        shows real stock changes (so you can separate sell-through from simply having no listing activity). Leave seller
        SKU and SKU code empty to <strong>combine all SKUs</strong>. Use filters to focus one SKU.{' '}
        <strong>Recorded</strong> snapshots only exist for past sync times (not full OC history).
      </p>

      <DiagnosticsPanel />

      <div className="flex flex-wrap items-end gap-3 mb-6 p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <label className="text-sm">
          <span className="text-gray-600 block mb-1">Source</span>
          <select
            value={dataSource}
            onChange={(e) => setDataSource(e.target.value as MovementSource)}
            className="rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm min-w-[14rem]"
          >
            <option value="oc_api">OC API (GetStockMovement)</option>
            <option value="recorded">Recorded (sync snapshots)</option>
          </select>
        </label>
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
            if (dataSource === 'recorded') void historyQuery.refetch()
            else void ocQuery.refetch()
          }}
          className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
        >
          Refresh
        </button>
      </div>

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

      {dataSource === 'oc_api' && ocQuery.data && !ocQuery.isLoading && (
        <div className="mb-6 p-4 bg-emerald-50 border border-emerald-200 rounded-lg text-sm">
          <h2 className="text-sm font-semibold text-emerald-900 mb-2">Restock-oriented movement (selected period)</h2>
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
            Scope: <code className="bg-emerald-100 px-1 rounded">{ocQuery.data.scope}</code> — {ocQuery.data.mfskuid_count}{' '}
            MFSKUID(s).{' '}
            {ocQuery.data.truncated ? (
              <span className="text-amber-800">
                Table truncated to {ocQuery.data.line_limit?.toLocaleString()} most recent lines.
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

      {dataSource === 'recorded' && historyQuery.data && (
        <p className="text-xs text-gray-500 mb-2">
          {historyQuery.data.note} Showing {historyQuery.data.row_count} row(s) for {historyQuery.data.from_date} →{' '}
          {historyQuery.data.to_date}.
        </p>
      )}

      {dataSource === 'oc_api' && ocQuery.data && (
        <p className="text-xs text-gray-500 mb-2">
          {ocQuery.data.note} {ocQuery.data.row_count.toLocaleString()} line(s), {ocQuery.data.from_date} →{' '}
          {ocQuery.data.to_date}.
        </p>
      )}

      {dataSource === 'recorded' && chartPoints.length > 0 && (
        <div className="mb-8 bg-white border border-gray-200 rounded-lg p-4 h-72">
          <h2 className="text-sm font-medium text-gray-700 mb-2">
            Available {combinedSkuScope ? '(all SKUs combined, sum by sync time)' : '(filtered, sum by sync time)'}
          </h2>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartPoints} margin={{ top: 8, right: 16, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="available" name="Available" stroke="#2563eb" dot={false} strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {dataSource === 'oc_api' && ocChartPoints.length > 0 && (
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

      {dataSource === 'recorded' && (
        <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200 mb-8">
          <div className="p-3 border-b border-gray-200 flex justify-between items-center">
            <h2 className="text-lg font-semibold text-gray-800">Recorded observations</h2>
            {historyQuery.data?.row_count === 0 && !historyQuery.isLoading && (
              <span className="text-sm text-amber-700">
                No history yet — run <strong>Pull latest data</strong> on Inventory status periodically.
              </span>
            )}
          </div>
          <div className="overflow-x-auto max-h-[min(70vh,720px)] overflow-y-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Recorded (UTC)</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">SKU</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Seller SKU</th>
                  <th className="px-3 py-2 text-left font-medium text-gray-700">Region</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Avail</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Δ Avail</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">In transit</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Δ Transit</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Received</th>
                  <th className="px-3 py-2 text-right font-medium text-gray-700">Δ Recv</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {(historyQuery.data?.rows ?? []).map((r, i) => (
                  <tr key={`${r.recorded_at}-${r.mfskuid}-${r.service_region}-${i}`} className="hover:bg-gray-50">
                    <td className="px-3 py-1.5 text-gray-800 whitespace-nowrap font-mono text-xs">
                      {new Date(r.recorded_at).toISOString().replace('T', ' ').slice(0, 19)}Z
                    </td>
                    <td className="px-3 py-1.5 text-gray-800">{r.sku_code ?? '—'}</td>
                    <td className="px-3 py-1.5 font-mono text-xs">{r.seller_skuid ?? '—'}</td>
                    <td className="px-3 py-1.5 text-gray-600">{r.service_region}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{r.available}</td>
                    <td
                      className={`px-3 py-1.5 text-right tabular-nums font-medium ${
                        r.delta_available == null
                          ? 'text-gray-400'
                          : r.delta_available > 0
                            ? 'text-green-700'
                            : r.delta_available < 0
                              ? 'text-red-700'
                              : 'text-gray-700'
                      }`}
                    >
                      {formatDelta(r.delta_available)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{r.in_transit}</td>
                    <td
                      className={`px-3 py-1.5 text-right tabular-nums ${
                        r.delta_in_transit == null
                          ? 'text-gray-400'
                          : r.delta_in_transit > 0
                            ? 'text-green-700'
                            : r.delta_in_transit < 0
                              ? 'text-red-700'
                              : 'text-gray-700'
                      }`}
                    >
                      {formatDelta(r.delta_in_transit)}
                    </td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{r.received}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums text-gray-700">{formatDelta(r.delta_received)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {dataSource === 'oc_api' && (
        <div className="bg-white shadow rounded-lg overflow-hidden border border-gray-200">
          <div className="p-3 border-b border-gray-200 flex justify-between items-center">
            <h2 className="text-lg font-semibold text-gray-800">OC movement lines</h2>
            {ocQuery.data?.row_count === 0 && !ocQuery.isLoading && (
              <span className="text-sm text-gray-600">No movements in this range.</span>
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
                {(ocQuery.data?.rows ?? []).map((r, i) => (
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
      )}
    </div>
  )
}
