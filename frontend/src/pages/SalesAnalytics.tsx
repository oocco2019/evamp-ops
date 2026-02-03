import { useState, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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
import { stockAPI, type AnalyticsSummary, type AnalyticsBySkuPoint, type AnalyticsByCountryPoint } from '../services/api'

const last90DaysFrom = () => {
  const d = new Date()
  d.setDate(d.getDate() - 90)
  return d.toISOString().slice(0, 10)
}
const defaultTo = () => new Date().toISOString().slice(0, 10)
const GBP_TO_EUR_RATE = 1.16

const SKU_SORT_STORAGE_KEY = 'salesAnalytics.skuSort'
const COUNTRY_SORT_STORAGE_KEY = 'salesAnalytics.countrySort'

type SkuSortKey = 'sku_code' | 'quantity_sold' | 'profit'
type CountrySortKey = 'country' | 'quantity_sold' | 'profit'

function loadSkuSort(): { key: SkuSortKey; dir: 'asc' | 'desc' } {
  try {
    const raw = localStorage.getItem(SKU_SORT_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { key?: string; dir?: string }
      const key = parsed?.key
      const dir = parsed?.dir
      if (
        (key === 'sku_code' || key === 'quantity_sold' || key === 'profit') &&
        (dir === 'asc' || dir === 'desc')
      ) {
        return { key, dir }
      }
    }
  } catch {
    // ignore
  }
  return { key: 'quantity_sold', dir: 'desc' }
}

function loadCountrySort(): { key: CountrySortKey; dir: 'asc' | 'desc' } {
  try {
    const raw = localStorage.getItem(COUNTRY_SORT_STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as { key?: string; dir?: string }
      const key = parsed?.key
      const dir = parsed?.dir
      if (
        (key === 'country' || key === 'quantity_sold' || key === 'profit') &&
        (dir === 'asc' || dir === 'desc')
      ) {
        return { key, dir }
      }
    }
  } catch {
    // ignore
  }
  return { key: 'quantity_sold', dir: 'desc' }
}

export default function SalesAnalytics() {
  const queryClient = useQueryClient()
  const [from, setFrom] = useState(last90DaysFrom)
  const [to, setTo] = useState(defaultTo)
  const [groupBy, setGroupBy] = useState<'day' | 'week' | 'month'>('day')
  const [country, setCountry] = useState('')
  const [sku, setSku] = useState('')
  const [tableSort, setTableSort] = useState<{ key: SkuSortKey; dir: 'asc' | 'desc' }>(loadSkuSort)
  const [countrySort, setCountrySort] = useState<{ key: CountrySortKey; dir: 'asc' | 'desc' }>(loadCountrySort)
  const [filterOptions, setFilterOptions] = useState<{ countries: string[]; skus: string[] } | null>(null)

  useEffect(() => {
    let cancelled = false
    stockAPI.runImport('incremental').then(() => {
      if (!cancelled) {
        queryClient.invalidateQueries({ queryKey: ['analytics'] })
      }
    }).catch(() => {
      // Background import failed; keep showing current data
    })
    return () => { cancelled = true }
  }, [queryClient])

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

  const handleSort = (key: SkuSortKey) => {
    setTableSort((prev) => {
      const next = {
        key,
        dir: prev.key === key ? (prev.dir === 'asc' ? 'desc' : 'asc') : (key === 'quantity_sold' || key === 'profit' ? 'desc' : 'asc'),
      }
      try {
        localStorage.setItem(SKU_SORT_STORAGE_KEY, JSON.stringify(next))
      } catch {
        // ignore
      }
      return next
    })
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

  const handleCountrySort = (key: CountrySortKey) => {
    setCountrySort((prev) => {
      const next = {
        key,
        dir: prev.key === key ? (prev.dir === 'asc' ? 'desc' : 'asc') : 'desc',
      }
      try {
        localStorage.setItem(COUNTRY_SORT_STORAGE_KEY, JSON.stringify(next))
      } catch {
        // ignore
      }
      return next
    })
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
              <p className="text-sm text-gray-500" title="Total profit in the selected period (GBP / EUR), after 30% tax on profit.">Profit</p>
              <p className="text-2xl font-bold text-gray-900">
                {byCountry && byCountry.length > 0 ? (() => {
                  const totalGbp = byCountry.reduce(
                    (sum, row) => sum + (Number(row.profit) || 0),
                    0
                  )
                  const totalEur = totalGbp * GBP_TO_EUR_RATE
                  return (
                    <>
                      £{totalGbp.toFixed(2)}
                      <span className="text-lg font-normal text-gray-600 ml-2">
                        / €{totalEur.toFixed(2)}
                      </span>
                    </>
                  )
                })() : (
                  '—'
                )}
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
                      <td className="px-4 py-2 text-right text-gray-700">£{Number(row.profit).toFixed(2)}</td>
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
                        £{(typeof row.profit === 'string' ? Number(row.profit) : (row.profit ?? 0)).toFixed(2)}
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
