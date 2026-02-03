import { useState, useEffect, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { stockAPI, type AnalyticsSummary, type AnalyticsBySkuPoint, type AnalyticsByCountryPoint, type OrderWithLines } from '../services/api'

const last90DaysFrom = () => {
  const d = new Date()
  d.setDate(d.getDate() - 90)
  return d.toISOString().slice(0, 10)
}
const defaultTo = () => new Date().toISOString().slice(0, 10)

export default function SalesAnalytics() {
  const [from, setFrom] = useState(last90DaysFrom)
  const [to, setTo] = useState(defaultTo)
  const [groupBy, setGroupBy] = useState<'day' | 'week' | 'month'>('day')
  const [country, setCountry] = useState('')
  const [sku, setSku] = useState('')
  const [tableSort, setTableSort] = useState<{ key: 'sku_code' | 'quantity_sold' | 'profit'; dir: 'asc' | 'desc' }>({
    key: 'quantity_sold',
    dir: 'desc',
  })
  const [countrySort, setCountrySort] = useState<{ key: 'country' | 'quantity_sold' | 'profit'; dir: 'asc' | 'desc' }>({
    key: 'quantity_sold',
    dir: 'desc',
  })
  const [filterOptions, setFilterOptions] = useState<{ countries: string[]; skus: string[] } | null>(null)

  const {
    data: analyticsData,
    isLoading: loading,
    error: analyticsError,
    refetch: refetchAnalytics,
  } = useQuery({
    queryKey: ['analytics', from, to, groupBy, country, sku],
    queryFn: async () => {
      const params = {
        from,
        to,
        country: country.trim() || undefined,
        sku: sku.trim() || undefined,
      }
      const [summaryRes, bySkuRes, byCountryRes] = await Promise.all([
        stockAPI.getAnalyticsSummary({ ...params, group_by: groupBy }),
        stockAPI.getAnalyticsBySku(params),
        stockAPI.getAnalyticsByCountry({ from, to, sku: sku.trim() || undefined }),
      ])
      return {
        data: summaryRes.data,
        bySku: bySkuRes.data,
        byCountry: byCountryRes.data,
      }
    },
  })
  const data = analyticsData?.data ?? null
  const bySku = analyticsData?.bySku ?? null
  const byCountry = analyticsData?.byCountry ?? null
  const error = analyticsError ? (analyticsError instanceof Error ? analyticsError.message : 'Failed to load analytics') : null
  const [latestOrders, setLatestOrders] = useState<OrderWithLines[] | null>(null)
  const [latestOrdersLoading, setLatestOrdersLoading] = useState(false)
  const [latestOrdersError, setLatestOrdersError] = useState<string | null>(null)
  const [latestOrdersLimit, setLatestOrdersLimit] = useState(50)
  const [backfillEarningsLoading, setBackfillEarningsLoading] = useState(false)
  const [backfillEarningsResult, setBackfillEarningsResult] = useState<{ orders_updated: number; orders_skipped: number; error?: string } | null>(null)

  const fetchLatestOrders = useCallback(async () => {
    setLatestOrdersLoading(true)
    setLatestOrdersError(null)
    try {
      const res = await stockAPI.getLatestOrders(latestOrdersLimit)
      setLatestOrders(res.data)
    } catch (e: unknown) {
      setLatestOrders(null)
      setLatestOrdersError(e instanceof Error ? e.message : 'Failed to load orders')
    } finally {
      setLatestOrdersLoading(false)
    }
  }, [latestOrdersLimit])

  useEffect(() => {
    fetchLatestOrders()
  }, [fetchLatestOrders])

  useEffect(() => {
    let cancelled = false
    stockAPI.getAnalyticsFilterOptions().then((res) => {
      if (!cancelled) setFilterOptions(res.data)
    }).catch(() => {
      if (!cancelled) setFilterOptions({ countries: [], skus: [] })
    })
    return () => { cancelled = true }
  }, [])

  const formatPeriod = (p: string) => {
    if (groupBy === 'month') return p.slice(0, 7)
    if (groupBy === 'week') return p.slice(0, 10)
    return p
  }

  const chartData = data?.series.map((s) => ({
    period: formatPeriod(s.period),
    units: s.units_sold,
  })) ?? []

  const handleSort = (key: 'sku_code' | 'quantity_sold' | 'profit') => {
    setTableSort((prev) => ({
      key,
      dir: prev.key === key ? (prev.dir === 'asc' ? 'desc' : 'asc') : (key === 'quantity_sold' || key === 'profit' ? 'desc' : 'asc'),
    }))
  }

  const sortedBySku = bySku
    ? [...bySku].sort((a, b) => {
        const mult = tableSort.dir === 'asc' ? 1 : -1
        if (tableSort.key === 'sku_code') {
          return mult * a.sku_code.localeCompare(b.sku_code)
        }
        if (tableSort.key === 'profit') {
          return mult * (Number(a.profit) - Number(b.profit))
        }
        return mult * (a.quantity_sold - b.quantity_sold)
      })
    : []

  const handleCountrySort = (key: 'country' | 'quantity_sold' | 'profit') => {
    setCountrySort((prev) => ({
      key,
      dir: prev.key === key ? (prev.dir === 'asc' ? 'desc' : 'asc') : 'desc',
    }))
  }

  const sortedByCountry = byCountry
    ? [...byCountry].sort((a, b) => {
        const mult = countrySort.dir === 'asc' ? 1 : -1
        if (countrySort.key === 'country') {
          return mult * a.country.localeCompare(b.country)
        }
        if (countrySort.key === 'profit') {
          return mult * (Number(a.profit) - Number(b.profit))
        }
        return mult * (a.quantity_sold - b.quantity_sold)
      })
    : []

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-4">Sales Analytics</h1>
      <p className="text-gray-600 mb-6">
        View units sold by period (default: last 90 days). Filters apply automatically.
      </p>

      <div className="bg-white shadow rounded-lg p-4 mb-6">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Filters</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">From</label>
            <input
              type="date"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">To</label>
            <input
              type="date"
              value={to}
              onChange={(e) => setTo(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Group by</label>
            <select
              value={groupBy}
              onChange={(e) => setGroupBy(e.target.value as 'day' | 'week' | 'month')}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="day">Day</option>
              <option value="week">Week</option>
              <option value="month">Month</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Country</label>
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {(filterOptions?.countries ?? []).map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">SKU</label>
            <select
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">All</option>
              {(filterOptions?.skus ?? []).map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>
        {loading && (
          <p className="mt-2 text-sm text-gray-500">Loading...</p>
        )}
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error}
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
            <div className="bg-white shadow rounded-lg p-4">
              <p className="text-sm text-gray-500" title="Sum of quantities across all line items.">Units sold</p>
              <p className="text-2xl font-bold text-gray-900">{data.totals.units_sold}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-4">
              <p className="text-sm text-gray-500" title="Total profit in the selected period (GBP), after 30% tax on profit.">Profit</p>
              <p className="text-2xl font-bold text-gray-900">
                {byCountry && byCountry.length > 0
                  ? `£${(byCountry.reduce((sum, row) => sum + Number(row.profit), 0)).toFixed(2)}`
                  : '—'}
              </p>
            </div>
          </div>

          <div className="bg-white shadow rounded-lg p-4 mb-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Units sold by period</h2>
            {chartData.length === 0 ? (
              <p className="text-gray-500 text-sm">No data for the selected filters.</p>
            ) : (
              <ResponsiveContainer width="100%" height={360}>
                <BarChart
                  data={chartData}
                  margin={{ top: 10, right: 10, left: 0, bottom: 0 }}
                  barSize={12}
                  barCategoryGap={4}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip
                    formatter={(value: number) => [value, '']}
                    labelFormatter={(label) => `Period: ${label}`}
                  />
                  <Legend />
                  <Bar dataKey="units" name="Units sold" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          <div className="bg-white shadow rounded-lg p-4 overflow-x-auto mb-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Sales by Country</h2>
            {!byCountry || byCountry.length === 0 ? (
              <p className="text-gray-500 text-sm">No data for the selected filters.</p>
            ) : (
              <table className="min-w-full divide-y divide-gray-200 text-sm table-fixed">
                <colgroup>
                  <col className="w-1/2" />
                  <col className="w-1/4" />
                  <col className="w-1/4" />
                </colgroup>
                <thead>
                  <tr className="bg-gray-50">
                    <th
                      className="px-4 py-2 text-left font-medium text-gray-700 cursor-pointer hover:text-gray-900"
                      onClick={() => handleCountrySort('country')}
                    >
                      Country {countrySort.key === 'country' && (countrySort.dir === 'asc' ? '▲' : '▼')}
                    </th>
                    <th
                      className="px-4 py-2 text-right font-medium text-gray-700 cursor-pointer hover:text-gray-900"
                      onClick={() => handleCountrySort('quantity_sold')}
                    >
                      Quantity sold {countrySort.key === 'quantity_sold' && (countrySort.dir === 'asc' ? '▲' : '▼')}
                    </th>
                    <th
                      className="px-4 py-2 text-right font-medium text-gray-700 cursor-pointer hover:text-gray-900"
                      onClick={() => handleCountrySort('profit')}
                    >
                      Profit {countrySort.key === 'profit' && (countrySort.dir === 'asc' ? '▲' : '▼')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {sortedByCountry.map((row) => (
                    <tr key={row.country} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-medium text-gray-900">{row.country}</td>
                      <td className="px-4 py-2 text-right text-gray-700">{row.quantity_sold}</td>
                      <td className="px-4 py-2 text-right text-gray-700">{Number(row.profit).toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="bg-white shadow rounded-lg p-4 overflow-x-auto">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Sales by SKU</h2>
            <p className="text-sm text-gray-500 mb-3">
              Profit = quantity sold × profit per unit (set in SKU Manager).
            </p>
            {!bySku || bySku.length === 0 ? (
              <p className="text-gray-500 text-sm">No data for the selected filters.</p>
            ) : (
              <table className="min-w-full divide-y divide-gray-200 text-sm table-fixed">
                <colgroup>
                  <col className="w-1/2" />
                  <col className="w-1/4" />
                  <col className="w-1/4" />
                </colgroup>
                <thead>
                  <tr className="bg-gray-50">
                    <th
                      className="px-4 py-2 text-left font-medium text-gray-700 cursor-pointer hover:text-gray-900"
                      onClick={() => handleSort('sku_code')}
                    >
                      SKU {tableSort.key === 'sku_code' && (tableSort.dir === 'asc' ? '▲' : '▼')}
                    </th>
                    <th
                      className="px-4 py-2 text-right font-medium text-gray-700 cursor-pointer hover:text-gray-900"
                      onClick={() => handleSort('quantity_sold')}
                    >
                      Quantity sold {tableSort.key === 'quantity_sold' && (tableSort.dir === 'asc' ? '▲' : '▼')}
                    </th>
                    <th
                      className="px-4 py-2 text-right font-medium text-gray-700 cursor-pointer hover:text-gray-900"
                      onClick={() => handleSort('profit')}
                    >
                      Profit {tableSort.key === 'profit' && (tableSort.dir === 'asc' ? '▲' : '▼')}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {sortedBySku.map((row) => (
                    <tr key={row.sku_code} className="hover:bg-gray-50">
                      <td className="px-4 py-2 font-medium text-gray-900">{row.sku_code}</td>
                      <td className="px-4 py-2 text-right text-gray-700">{row.quantity_sold}</td>
                      <td className="px-4 py-2 text-right text-gray-700">
                        {typeof row.profit === 'string'
                          ? Number(row.profit).toFixed(2)
                          : (row.profit ?? 0).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}

      {/* Latest orders – all retrievable fields with explicit headers */}
      <div className="bg-white shadow rounded-lg p-4 overflow-x-auto mb-6">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
          <h2 className="text-lg font-semibold text-gray-800">Latest orders</h2>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={backfillEarningsLoading}
              onClick={async () => {
                setBackfillEarningsResult(null)
                setBackfillEarningsLoading(true)
                try {
                  const res = await stockAPI.backfillOrderEarnings()
                  setBackfillEarningsResult(res.data)
                  await fetchLatestOrders()
                } catch (e: unknown) {
                  setBackfillEarningsResult({ orders_updated: 0, orders_skipped: 0, error: e instanceof Error ? e.message : 'Failed' })
                } finally {
                  setBackfillEarningsLoading(false)
                }
              }}
              className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {backfillEarningsLoading ? 'Backfilling...' : 'Backfill Order earnings'}
            </button>
            {backfillEarningsResult && (
              <span className="text-sm text-gray-600">
                Updated {backfillEarningsResult.orders_updated}, skipped {backfillEarningsResult.orders_skipped}
                {backfillEarningsResult.error ? ` — ${backfillEarningsResult.error}` : ''}
              </span>
            )}
            <div className="flex items-center gap-2">
              <label className="text-sm text-gray-600">Show</label>
              <select
                value={latestOrdersLimit}
                onChange={(e) => setLatestOrdersLimit(Number(e.target.value))}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
              >
                <option value={25}>25</option>
                <option value={50}>50</option>
                <option value={100}>100</option>
              </select>
              <span className="text-sm text-gray-600">orders</span>
            </div>
          </div>
        </div>
        {latestOrdersError && (
          <p className="text-sm text-red-600 mb-2">{latestOrdersError}</p>
        )}
        {latestOrdersLoading ? (
          <p className="text-gray-500 text-sm">Loading orders...</p>
        ) : !latestOrders || latestOrders.length === 0 ? (
          <p className="text-gray-500 text-sm">No orders.</p>
        ) : (
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead>
              <tr className="bg-gray-50">
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Order ID</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">eBay Order ID</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Order Date</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Country</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Last Modified</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Cancel Status</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Buyer Username</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Order Currency</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Price Subtotal</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Price Total</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Tax Total</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Delivery Cost</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Price Discount</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Fee Total</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Total Fee Basis Amount</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Total Marketplace Fee</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Total Due Seller (Order Earnings)</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Total Due Seller Currency</th>
                <th className="px-3 py-2 text-right font-medium text-gray-700 whitespace-nowrap">Ad fees</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Ad fees breakdown</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Order Payment Status</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Sales Record Ref</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">eBay Collect and Remit Tax</th>
                <th className="px-3 py-2 text-left font-medium text-gray-700 whitespace-nowrap">Line items (all fields)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {latestOrders.map((order) => (
                <tr key={order.order_id} className="hover:bg-gray-50">
                  <td className="px-3 py-2 font-mono text-gray-900">{order.order_id}</td>
                  <td className="px-3 py-2 font-mono text-gray-900">{order.ebay_order_id}</td>
                  <td className="px-3 py-2 text-gray-700">{order.date}</td>
                  <td className="px-3 py-2 text-gray-700">{order.country}</td>
                  <td className="px-3 py-2 text-gray-600">{order.last_modified.replace('T', ' ').slice(0, 19)}</td>
                  <td className="px-3 py-2 text-gray-700">{order.cancel_status ?? '—'}</td>
                  <td className="px-3 py-2 text-gray-700">{order.buyer_username ?? '—'}</td>
                  <td className="px-3 py-2 text-gray-700">{order.order_currency ?? '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700">{order.price_subtotal != null ? Number(order.price_subtotal).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700">{order.price_total != null ? Number(order.price_total).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700">{order.tax_total != null ? Number(order.tax_total).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700">{order.delivery_cost != null ? Number(order.delivery_cost).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700">{order.price_discount != null ? Number(order.price_discount).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700">{order.fee_total != null ? Number(order.fee_total).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700">{order.total_fee_basis_amount != null ? Number(order.total_fee_basis_amount).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-right text-gray-700">{order.total_marketplace_fee != null ? Number(order.total_marketplace_fee).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-right font-medium text-gray-900">{order.total_due_seller != null ? Number(order.total_due_seller).toFixed(2) : '—'}</td>
                  <td className="px-3 py-2 text-gray-700">{order.total_due_seller_currency ?? '—'}</td>
                  <td className="px-3 py-2 text-right font-medium text-gray-900" title="Ad fees (NON_SALE_CHARGE from Finances API). Run Backfill to populate.">
                    {order.ad_fees_total != null ? `${Number(order.ad_fees_total).toFixed(2)} ${order.ad_fees_currency ?? ''}`.trim() : '—'}
                  </td>
                  <td className="px-3 py-2 text-gray-700 max-w-xs">
                    {order.ad_fees_breakdown && order.ad_fees_breakdown.length > 0
                      ? order.ad_fees_breakdown
                          .map((b) => `${b.transaction_memo || b.fee_type || 'Fee'}: ${b.amount} ${(b.currency || '').trim()}`.trim())
                          .join('; ')
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-gray-700">{order.order_payment_status ?? '—'}</td>
                  <td className="px-3 py-2 text-gray-700">{order.sales_record_reference ?? '—'}</td>
                  <td className="px-3 py-2 text-gray-700">{order.ebay_collect_and_remit_tax == null ? '—' : order.ebay_collect_and_remit_tax ? 'Yes' : 'No'}</td>
                  <td className="px-3 py-2 text-gray-700 max-w-md">
                    {order.line_items.length === 0
                      ? '—'
                      : order.line_items.map((li) => [
                          `ID: ${li.id}`,
                          `eBay Line Item ID: ${li.ebay_line_item_id}`,
                          `SKU: ${li.sku}`,
                          `Quantity: ${li.quantity}`,
                          li.currency != null ? `Currency: ${li.currency}` : null,
                          li.line_item_cost != null ? `Line Item Cost: ${Number(li.line_item_cost).toFixed(2)}` : null,
                          li.discounted_line_item_cost != null ? `Discounted Line Item Cost: ${Number(li.discounted_line_item_cost).toFixed(2)}` : null,
                          li.line_total != null ? `Line Total: ${Number(li.line_total).toFixed(2)}` : null,
                          li.tax_amount != null ? `Tax Amount: ${Number(li.tax_amount).toFixed(2)}` : null,
                        ].filter(Boolean).join(' | ')).join('; ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {!data && !loading && !error && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center text-gray-500">
          Loading analytics...
        </div>
      )}
    </div>
  )
}
