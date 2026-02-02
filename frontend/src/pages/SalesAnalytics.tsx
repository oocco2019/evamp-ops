import { useState, useEffect, useCallback } from 'react'
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
import { stockAPI, type AnalyticsSummary, type AnalyticsBySkuPoint } from '../services/api'

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
  const [data, setData] = useState<AnalyticsSummary | null>(null)
  const [bySku, setBySku] = useState<AnalyticsBySkuPoint[] | null>(null)
  const [tableSort, setTableSort] = useState<{ key: 'sku_code' | 'quantity_sold'; dir: 'asc' | 'desc' }>({
    key: 'quantity_sold',
    dir: 'desc',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filterOptions, setFilterOptions] = useState<{ countries: string[]; skus: string[] } | null>(null)

  const fetchSummary = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = {
        from,
        to,
        country: country.trim() || undefined,
        sku: sku.trim() || undefined,
      }
      const [summaryRes, bySkuRes] = await Promise.all([
        stockAPI.getAnalyticsSummary({ ...params, group_by: groupBy }),
        stockAPI.getAnalyticsBySku(params),
      ])
      setData(summaryRes.data)
      setBySku(bySkuRes.data)
    } catch (e: unknown) {
      setData(null)
      setBySku(null)
      setError(e instanceof Error ? e.message : 'Failed to load analytics')
    } finally {
      setLoading(false)
    }
  }, [from, to, groupBy, country, sku])

  useEffect(() => {
    let cancelled = false
    stockAPI.getAnalyticsFilterOptions().then((res) => {
      if (!cancelled) setFilterOptions(res.data)
    }).catch(() => {
      if (!cancelled) setFilterOptions({ countries: [], skus: [] })
    })
    return () => { cancelled = true }
  }, [])

  useEffect(() => {
    fetchSummary()
  }, [fetchSummary])

  const formatPeriod = (p: string) => {
    if (groupBy === 'month') return p.slice(0, 7)
    if (groupBy === 'week') return p.slice(0, 10)
    return p
  }

  const chartData = data?.series.map((s) => ({
    period: formatPeriod(s.period),
    units: s.units_sold,
  })) ?? []

  const handleSort = (key: 'sku_code' | 'quantity_sold') => {
    setTableSort((prev) => ({
      key,
      dir: prev.key === key ? (prev.dir === 'asc' ? 'desc' : 'asc') : 'asc',
    }))
  }

  const sortedBySku = bySku
    ? [...bySku].sort((a, b) => {
        const mult = tableSort.dir === 'asc' ? 1 : -1
        if (tableSort.key === 'sku_code') {
          return mult * a.sku_code.localeCompare(b.sku_code)
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

          <div className="bg-white shadow rounded-lg p-4 overflow-x-auto">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Sales by SKU</h2>
            <p className="text-sm text-gray-500 mb-3">
              Profit = quantity sold × profit per unit (set in SKU Manager).
            </p>
            {!bySku || bySku.length === 0 ? (
              <p className="text-gray-500 text-sm">No data for the selected filters.</p>
            ) : (
              <table className="min-w-full divide-y divide-gray-200 text-sm">
                <thead>
                  <tr className="bg-gray-50">
                    <th className="px-4 py-2 text-left font-medium text-gray-700">
                      <button
                        type="button"
                        onClick={() => handleSort('sku_code')}
                        className="inline-flex items-center gap-1 hover:text-gray-900 focus:outline-none"
                      >
                        SKU
                        {tableSort.key === 'sku_code' ? (
                          tableSort.dir === 'asc' ? (
                            <span className="text-xs" aria-hidden>▲</span>
                          ) : (
                            <span className="text-xs" aria-hidden>▼</span>
                          )
                        ) : (
                          <span className="text-xs text-gray-400" aria-hidden>▲▼</span>
                        )}
                      </button>
                    </th>
                    <th className="px-4 py-2 text-right font-medium text-gray-700">
                      <button
                        type="button"
                        onClick={() => handleSort('quantity_sold')}
                        className="inline-flex items-center justify-end gap-1 w-full hover:text-gray-900 focus:outline-none"
                      >
                        Quantity sold
                        {tableSort.key === 'quantity_sold' ? (
                          tableSort.dir === 'asc' ? (
                            <span className="text-xs" aria-hidden>▲</span>
                          ) : (
                            <span className="text-xs" aria-hidden>▼</span>
                          )
                        ) : (
                          <span className="text-xs text-gray-400" aria-hidden>▲▼</span>
                        )}
                      </button>
                    </th>
                    <th className="px-4 py-2 text-right font-medium text-gray-700">Profit</th>
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

      {!data && !loading && !error && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-6 text-center text-gray-500">
          Loading analytics...
        </div>
      )}
    </div>
  )
}
