import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { stockAPI, type OrderDetailsResponse } from '../services/api'

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

const lastNDaysFrom = (n: number) => offsetDaysFromToday(n - 1)

const defaultTo = () => todayIso()
const defaultFrom = () => lastNDaysFrom(90)

type PeriodPreset = 'today' | '7d' | '1m' | '3m' | '6m' | '1y' | 'custom'

function num(v: string | number | null | undefined): number {
  if (v === null || v === undefined) return NaN
  return typeof v === 'number' ? v : parseFloat(String(v))
}

function fmtGbp(v: string | number | null | undefined): string {
  const n = num(v)
  if (Number.isNaN(n)) return '—'
  return n.toLocaleString('en-GB', { style: 'currency', currency: 'GBP', minimumFractionDigits: 2 })
}

/** Format amounts stored in a given ISO 4217 currency (eBay marketplace / payout). */
function fmtMoney(v: string | number | null | undefined, currencyIso: string | null | undefined): string {
  const n = num(v)
  if (Number.isNaN(n)) return '—'
  const code = (currencyIso || 'GBP').trim().toUpperCase()
  if (!/^[A-Z]{3}$/.test(code)) {
    return `${n.toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${code || '?'}`
  }
  try {
    return n.toLocaleString(undefined, { style: 'currency', currency: code, minimumFractionDigits: 2 })
  } catch {
    return `${n.toFixed(2)} ${code}`
  }
}

function fmtShare(v: string | number | null | undefined): string {
  const n = num(v)
  if (Number.isNaN(n)) return '—'
  return `${(n * 100).toFixed(1)}%`
}

export default function OrderDetails() {
  const [from, setFrom] = useState(defaultFrom)
  const [to, setTo] = useState(defaultTo)
  const [periodPreset, setPeriodPreset] = useState<PeriodPreset>('3m')
  const [country, setCountry] = useState('')
  const [sku, setSku] = useState('')
  const [filterOptions, setFilterOptions] = useState<{ countries: string[]; skus: string[] } | null>(null)

  useEffect(() => {
    stockAPI.getAnalyticsFilterOptions().then((res) => {
      setFilterOptions(res.data)
    })
  }, [])

  const applyPeriodPreset = (preset: PeriodPreset) => {
    setPeriodPreset(preset)
    if (preset === 'custom') return
    const end = todayIso()
    let start = end
    if (preset === 'today') start = end
    else if (preset === '7d') start = lastNDaysFrom(7)
    else if (preset === '1m') start = lastNDaysFrom(30)
    else if (preset === '3m') start = lastNDaysFrom(90)
    else if (preset === '6m') start = lastNDaysFrom(180)
    else if (preset === '1y') start = lastNDaysFrom(365)
    setFrom(start)
    setTo(end)
  }

  const {
    data: resp,
    isPending,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ['order-details', from, to, country, sku],
    queryFn: async () => {
      const res = await stockAPI.getOrderDetails({
        from,
        to,
        ...(country ? { country } : {}),
        ...(sku ? { sku } : {}),
      })
      return res.data
    },
  })

  const data: OrderDetailsResponse | undefined = resp
  /** v5: prefer isPending; v4: only isLoading — avoids hiding the table on v5 background refetch. */
  const tableLoading =
    typeof isPending === 'boolean' ? isPending : Boolean(isLoading)

  const errMsg = (() => {
    if (!error) return null
    if (isAxiosError(error)) {
      const d = error.response?.data as { detail?: unknown } | undefined
      const det = d?.detail
      if (typeof det === 'string') return det
      if (Array.isArray(det)) return det.map((x) => JSON.stringify(x)).join('; ')
    }
    return error instanceof Error ? error.message : String(error)
  })()

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-2">Order details</h1>
      <p className="text-gray-600 mb-6">
        Per line: payout, buyer totals, landed and postage in GBP, order VAT, allocated gross and net profit
        (same rules as Sales Analytics by SKU). Use SKU filter to see totals for that SKU only.
      </p>

      <div className="bg-white shadow rounded-lg p-4 mb-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Filters</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
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
            <label className="block text-sm font-medium text-gray-700 mb-1">Country</label>
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              className="w-full rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {(filterOptions?.countries ?? []).map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SKU</label>
            <select
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              className="w-full rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {(filterOptions?.skus ?? []).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-800 hover:bg-gray-50"
          >
            Refresh
          </button>
        </div>
      </div>

      {errMsg && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">{errMsg}</div>
      )}

      {tableLoading && (
        <div className="text-gray-500 text-sm">Loading order lines…</div>
      )}

      {data && !tableLoading && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
            <div className="bg-white shadow rounded-lg p-3">
              <p className="text-xs text-gray-500">Rows</p>
              <p className="text-lg font-semibold text-gray-900">{data.totals.row_count}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-3">
              <p className="text-xs text-gray-500">Units</p>
              <p className="text-lg font-semibold text-gray-900">{data.totals.units}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-3">
              <p className="text-xs text-gray-500" title="Sum of seller payouts (each order counted once)">
                Payout sum
              </p>
              <p className="text-lg font-semibold text-gray-900">{fmtGbp(data.totals.sum_order_payout_gbp)}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-3">
              <p className="text-xs text-gray-500">Line cost (sum)</p>
              <p className="text-lg font-semibold text-gray-900">{fmtGbp(data.totals.sum_line_cost_gbp)}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-3">
              <p className="text-xs text-gray-500">Line gross profit (sum)</p>
              <p className="text-lg font-semibold text-gray-900">{fmtGbp(data.totals.sum_line_gross_profit_gbp)}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-3">
              <p className="text-xs text-gray-500">Line net profit (sum)</p>
              <p className="text-lg font-semibold text-emerald-800">{fmtGbp(data.totals.sum_line_net_profit_gbp)}</p>
            </div>
          </div>

          <div className="bg-white shadow rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200 text-xs">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-2 py-2 text-left font-medium text-gray-600 whitespace-nowrap">Date</th>
                    <th className="px-2 py-2 text-left font-medium text-gray-600 whitespace-nowrap">Order</th>
                    <th className="px-2 py-2 text-left font-medium text-gray-600">CC</th>
                    <th className="px-2 py-2 text-left font-medium text-gray-600">SKU</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600">Qty</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap" title="totalDueSeller (payout currency)">
                      Due seller
                    </th>
                    <th
                      className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap"
                      title="Buyer order total (marketplace currency)"
                    >
                      Buyer total
                    </th>
                    <th
                      className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap"
                      title="eBay tax_total e.g. sales tax / VAT collected (marketplace currency)"
                    >
                      Tax
                    </th>
                    <th className="px-2 py-2 text-left font-medium text-gray-600" title="Marketplace currency for buyer/tax/line totals">
                      Cur
                    </th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap" title="Line total (marketplace currency)">
                      Line total
                    </th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap" title="Order total in GBP">
                      Order GBP
                    </th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Landed GBP</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Post GBP</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Line cost</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Order cost</th>
                    <th
                      className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap"
                      title="UK: eBay tax, or VAT extracted from VAT-inclusive order GBP (÷6 at 20%) if eBay tax empty; £0 when refund (due seller ≤ 0)"
                    >
                      VAT
                    </th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Ord gross</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Tax %</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Ord net</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Share</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Line gross</th>
                    <th className="px-2 py-2 text-right font-medium text-gray-600 whitespace-nowrap">Line net</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 bg-white">
                  {data.rows.length === 0 ? (
                    <tr>
                      <td colSpan={22} className="px-4 py-8 text-center text-gray-500">
                        No rows for this range and filters.
                      </td>
                    </tr>
                  ) : (
                    data.rows.map((r, i) => (
                      <tr key={`${r.ebay_order_id}-${r.sku}-${i}`} className="hover:bg-gray-50">
                        <td className="px-2 py-1.5 whitespace-nowrap text-gray-800">{r.order_date}</td>
                        <td className="px-2 py-1.5 font-mono text-[11px] text-gray-800">{r.ebay_order_id}</td>
                        <td className="px-2 py-1.5 text-gray-700">{r.country}</td>
                        <td className="px-2 py-1.5 text-gray-900 max-w-[140px] truncate" title={r.sku}>
                          {r.sku}
                        </td>
                        <td className="px-2 py-1.5 text-right text-gray-800">{r.quantity}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">
                          {fmtMoney(r.total_due_seller, r.total_due_seller_currency || 'GBP')}
                        </td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">
                          {fmtMoney(r.price_total, r.order_currency)}
                        </td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">
                          {fmtMoney(r.tax_total, r.order_currency)}
                        </td>
                        <td className="px-2 py-1.5 text-gray-600">{r.order_currency ?? '—'}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">
                          {fmtMoney(r.line_total, r.order_currency)}
                        </td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.price_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.line_landed_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.line_postage_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.line_cost_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.order_cost_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.vat_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.order_gross_profit_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">
                          {(r.profit_tax_rate * 100).toFixed(0)}%
                        </td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.order_net_profit_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtShare(r.allocation_share)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap">{fmtGbp(r.line_gross_profit_gbp)}</td>
                        <td className="px-2 py-1.5 text-right whitespace-nowrap font-medium text-emerald-800">
                          {fmtGbp(r.line_net_profit_gbp)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
