import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { stockAPI } from '../services/api'

const formatLocalDate = (d: Date): string => {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const todayIso = () => formatLocalDate(new Date())
/** Inclusive n-day window ending today; matches Sales Analytics presets (e.g. 3m = 90 days). */
const offsetDaysFromToday = (daysAgo: number) => {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  return formatLocalDate(d)
}
const lastNDaysFrom = (n: number) => offsetDaysFromToday(n - 1)

type Preset = '6m' | '3m' | 'custom'
const PERIOD_DAYS: Record<'6m' | '3m', number> = {
  '6m': 180,
  '3m': 90,
}

const COMPANY = {
  name: 'oocco limited',
  number: '12289754',
  address: 'C/O Glacier, Cannock Chase Enterprise Centre, Hednesford, United Kingdom, WS12 0QU',
  brand: 'evamp',
}

export default function LenderSummary() {
  const [from, setFrom] = useState(() => lastNDaysFrom(180))
  const [to, setTo] = useState(todayIso())
  const [preset, setPreset] = useState<Preset>('6m')

  useEffect(() => {
    document.body.classList.add('lender-print-mode')
    return () => {
      document.body.classList.remove('lender-print-mode')
    }
  }, [])

  const applyPreset = (p: Preset) => {
    setPreset(p)
    if (p === 'custom') return
    setTo(todayIso())
    setFrom(lastNDaysFrom(PERIOD_DAYS[p]))
  }

  const { data, isLoading, error } = useQuery({
    queryKey: ['lender-summary', from, to],
    queryFn: async () => (await stockAPI.getLenderSummary({ from, to })).data,
  })

  const genAt = data?.generated_at_utc
    ? new Date(data.generated_at_utc).toLocaleString()
    : '—'
  // Use unique `name` for x-axis (Recharts) — display label in tickFormatter / tooltip
  const chartRows =
    data?.weekly.map((w) => ({
      name: w.week_start,
      weekLabel: w.week_label,
      units: w.units,
      revenue: Number(w.revenue_gbp),
      profit: Number(w.gross_profit_gbp),
      margin: Number(w.margin_percent),
    })) ?? []
  const weekTickCount = chartRows.length
  /** Pixels so each week has room for two side-by-side bars; avoids Recharts throttling with interval>0. */
  const chartMinWidthPx = Math.max(100, weekTickCount * 36)
  const xAxisBottom = weekTickCount > 10 ? 78 : 28

  return (
    <div className="px-4 py-6 sm:px-0 lender-summary-print">
      <style>{`
        @media print {
          @page { size: A4; margin: 20mm; }
          body.lender-print-mode .no-print, body.lender-print-mode nav, body.lender-print-mode .lender-toolbar { display: none !important; }
          .lender-section-break { break-before: page; }
          .lender-summary-print { max-width: none !important; }
        }
      `}</style>

      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 mb-6">
        <div>
          <h1 className="text-3xl font-bold text-gray-900">Lender summary</h1>
          <p className="text-gray-600 mt-1">
            Pre-tax gross profit and volume (Sales Analytics may show after-tax &quot;profit&quot; on margin).
          </p>
        </div>
        <div className="lender-toolbar flex flex-wrap gap-2 no-print">
          <button
            type="button"
            onClick={() => window.print()}
            className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700"
          >
            Download PDF
          </button>
          <button
            type="button"
            onClick={() => window.print()}
            className="px-4 py-2 bg-white border border-gray-300 text-gray-800 rounded-md text-sm font-medium hover:bg-gray-50"
          >
            Print preview
          </button>
        </div>
      </div>

      <div className="bg-white shadow rounded-lg p-4 mb-6 no-print">
        <h2 className="text-lg font-semibold text-gray-800 mb-3">Filters</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Period</label>
            <select
              value={preset}
              onChange={(e) => applyPreset(e.target.value as Preset)}
              className="w-full rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm"
            >
              <option value="6m">Last 6 months</option>
              <option value="3m">Last 3 months</option>
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
                setPreset('custom')
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
                setPreset('custom')
              }}
              className="w-full rounded border border-gray-300 bg-white text-gray-900 px-3 py-2 text-sm"
            />
          </div>
        </div>
        <p className="mt-3 text-xs text-gray-500">
          Imported order data in this app is typically available for about the <strong>last six months</strong> (API
          retention). Choose a from/to range within that window; older dates may return empty or partial results.
        </p>
        {isLoading && <p className="mt-2 text-sm text-gray-500">Loading…</p>}
        {error && (
          <p className="mt-2 text-sm text-red-600">
            {error instanceof Error ? error.message : 'Failed to load report'}
          </p>
        )}
      </div>

      {data && (
        <>
          <section className="bg-white shadow rounded-lg p-6 mb-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Company & report</h2>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-sm text-gray-800">
              <dt className="text-gray-500">Company name</dt>
              <dd className="font-medium">{COMPANY.name}</dd>
              <dt className="text-gray-500">Company number</dt>
              <dd>{COMPANY.number}</dd>
              <dt className="text-gray-500">Registered office</dt>
              <dd>{COMPANY.address}</dd>
              <dt className="text-gray-500">Trading brand</dt>
              <dd>{COMPANY.brand}</dd>
              <dt className="text-gray-500">Report period</dt>
              <dd>
                {data.period_from} to {data.period_to}
              </dd>
              <dt className="text-gray-500">Report generated</dt>
              <dd>{genAt}</dd>
            </dl>
            <p className="mt-4 text-amber-900 bg-amber-50 border border-amber-200 rounded-md px-3 py-2 text-sm whitespace-pre-line leading-relaxed">
              {data.disclosure}
            </p>
          </section>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <div className="bg-white shadow rounded-lg p-4">
              <p className="text-sm text-gray-500">Units sold</p>
              <p className="text-2xl font-bold text-gray-900">{data.headline.units_sold}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-4">
              <p className="text-sm text-gray-500">Gross revenue (GBP)</p>
              <p className="text-2xl font-bold text-gray-900">£{data.headline.gross_revenue_gbp}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-4">
              <p className="text-sm text-gray-500" title="Pre-tax; see methodology">
                Gross profit, pre-tax (GBP)
              </p>
              <p className="text-2xl font-bold text-gray-900">£{data.headline.gross_profit_pre_tax_gbp}</p>
            </div>
            <div className="bg-white shadow rounded-lg p-4">
              <p className="text-sm text-gray-500">Gross margin</p>
              <p className="text-2xl font-bold text-gray-900">{data.headline.gross_margin_percent}%</p>
            </div>
          </div>

          <section className="lender-section-break bg-white shadow rounded-lg p-4 mb-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Weekly performance</h2>
            <p className="text-sm text-gray-500 mb-3">
              Only <strong>full</strong> Monday–Sunday weeks that fall entirely inside your selected from/to dates are
              shown. Weeks cut off by the range start or end are omitted so each bar is a comparable 7-day trading
              window. Headline totals still include all orders in the range.
            </p>
            {chartRows.length === 0 ? (
              <p className="text-gray-500 text-sm">No data in range.</p>
            ) : (
              <div className="space-y-8">
                <p className="text-xs text-gray-500 no-print">
                  Volume (units) and gross profit (GBP) use separate scales below so bar heights are not compared across
                  the two series.
                </p>
                {(
                  [
                    {
                      dataKey: 'units' as const,
                      heading: 'Units sold per week',
                      sub: 'Count of line-item quantities (same definition as Sales Analytics).',
                      yLabel: 'Units',
                      fill: '#3b82f6',
                      valueLabel: 'Units',
                      format: (v: number) => String(v),
                    },
                    {
                      dataKey: 'profit' as const,
                      heading: 'Gross profit (pre-tax) per week',
                      sub: 'Payout in GBP net of direct COGS and VAT (before Sales Analytics PROFIT_TAX on margin).',
                      yLabel: 'GBP',
                      fill: '#1d4ed8',
                      valueLabel: 'Gross profit',
                      format: (v: number) => `£${Number(v).toFixed(2)}`,
                    },
                  ] as const
                ).map((spec) => (
                  <div key={spec.dataKey} className="lender-weekly-chart">
                    <h3 className="text-sm font-semibold text-gray-900 mb-0.5">{spec.heading}</h3>
                    <p className="text-xs text-gray-500 mb-2">{spec.sub}</p>
                    <div className="w-full overflow-x-auto pb-1">
                      <div style={{ minWidth: chartMinWidthPx, height: 300 }}>
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart
                            data={chartRows}
                            margin={{ top: 8, right: 12, left: 8, bottom: xAxisBottom }}
                            barCategoryGap="10%"
                          >
                            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                            <XAxis
                              dataKey="name"
                              type="category"
                              tick={{ fontSize: 9 }}
                              interval={0}
                              height={xAxisBottom}
                              angle={weekTickCount > 6 ? -45 : 0}
                              textAnchor={weekTickCount > 6 ? 'end' : 'middle'}
                              tickFormatter={(v: string) => {
                                const row = chartRows.find((r) => r.name === v)
                                return row?.weekLabel ?? v
                              }}
                            />
                            <YAxis
                              tick={{ fontSize: 12 }}
                              width={48}
                              label={{ value: spec.yLabel, angle: -90, position: 'insideLeft' }}
                            />
                            <Tooltip
                              cursor={{ fill: 'rgba(15, 23, 42, 0.06)' }}
                              content={({ active, payload, label }) => {
                                if (!active || !payload?.length) return null
                                const nameKey = String(label)
                                const row = chartRows.find((r) => r.name === nameKey)
                                const weekTitle = row?.weekLabel ?? nameKey
                                const raw = payload[0]?.value
                                const num = typeof raw === 'number' ? raw : Number(raw)
                                return (
                                  <div className="rounded-md border border-gray-200 bg-white px-3 py-2 text-sm shadow-md">
                                    <p className="font-medium text-gray-900">{weekTitle}</p>
                                    <p className="mt-0.5 text-gray-700">
                                      {spec.valueLabel}: {spec.format(Number.isFinite(num) ? num : 0)}
                                    </p>
                                  </div>
                                )
                              }}
                            />
                            <Bar
                              dataKey={spec.dataKey}
                              name={spec.valueLabel}
                              fill={spec.fill}
                              maxBarSize={36}
                              isAnimationActive={false}
                              activeBar={false}
                            />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    </div>
                  </div>
                ))}
                <p className="text-xs text-gray-500 -mt-4 no-print">Scroll each chart horizontally if many weeks.</p>
              </div>
            )}
            <div className="mt-6">
              <div>
                <h3 className="text-sm font-semibold text-gray-800 mb-2">Recent periods (GBP)</h3>
                <p className="text-xs text-gray-500 mb-2">
                  Last N calendar days ending on {data.period_to} (same inclusion and profit rules as elsewhere on
                  this report).
                </p>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 text-sm">
                    <thead>
                      <tr className="bg-gray-50">
                        <th className="px-4 py-2 text-left font-medium text-gray-700">Period</th>
                        <th className="px-4 py-2 text-right font-medium text-gray-700">Units</th>
                        <th className="px-4 py-2 text-right font-medium text-gray-700">Revenue</th>
                        <th className="px-4 py-2 text-right font-medium text-gray-700">Gross profit (pre-tax)</th>
                        <th className="px-4 py-2 text-right font-medium text-gray-700">Gross margin %</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200">
                      {data.rolling_periods.map((r) => (
                        <tr key={r.label} className="hover:bg-gray-50">
                          <td className="px-4 py-2 text-gray-900">
                            {r.label}
                            <span className="text-gray-500 text-xs block sm:inline sm:ml-1">
                              ({r.period_start} to {r.period_end})
                            </span>
                          </td>
                          <td className="px-4 py-2 text-right text-gray-700 tabular-nums">{r.units}</td>
                          <td className="px-4 py-2 text-right text-gray-700">£{r.revenue_gbp}</td>
                          <td className="px-4 py-2 text-right text-gray-700">£{r.gross_profit_gbp}</td>
                          <td className="px-4 py-2 text-right text-gray-700">{r.margin_percent}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </section>

          <section className="lender-section-break bg-white shadow rounded-lg p-4 mb-6">
            <h2 className="text-lg font-semibold text-gray-800 mb-4">Geographic distribution</h2>
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead>
                <tr className="bg-gray-50">
                  <th className="px-4 py-2 text-left font-medium text-gray-700">Country</th>
                  <th className="px-4 py-2 text-right font-medium text-gray-700">Units</th>
                  <th className="px-4 py-2 text-right font-medium text-gray-700">Revenue (GBP)</th>
                  <th className="px-4 py-2 text-right font-medium text-gray-700">Gross profit (GBP)</th>
                  <th className="px-4 py-2 text-right font-medium text-gray-700">% of total revenue</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {data.geography.map((g) => (
                  <tr key={g.code} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-medium text-gray-900">{g.label}</td>
                    <td className="px-4 py-2 text-right text-gray-700">{g.units}</td>
                    <td className="px-4 py-2 text-right text-gray-700">£{g.revenue_gbp}</td>
                    <td className="px-4 py-2 text-right text-gray-700">£{g.gross_profit_gbp}</td>
                    <td className="px-4 py-2 text-right text-gray-700">{g.pct_of_total_revenue}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <footer className="text-sm text-gray-600 border-t border-gray-200 pt-6 mt-6 space-y-2">
            <h3 className="font-semibold text-gray-800">Methodology notes</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>
                Foreign exchange: USD→GBP {data.methodology.usd_to_gbp_rate}, EUR→GBP {data.methodology.eur_to_gbp_rate}{' '}
                (config values, not spot rates per transaction). UK VAT default rate: {data.methodology.uk_vat_default_rate}
                .
              </li>
              <li>
                Weekly charts and tables list only full Monday–Sunday weeks that sit fully inside the report dates.
                Headline figures use the full date range.
              </li>
              <li>Cancelled orders are excluded. Refund orders use the documented postage-only cost model.</li>
              <li>
                Data sources: eBay Finances API, Shopify Orders API, OrangeConnex inventory API, internal SKU master.
              </li>
            </ul>
            {data.methodology.company_footer_note?.trim() ? (
              <p className="text-gray-500 text-xs pt-2">{data.methodology.company_footer_note}</p>
            ) : null}
          </footer>
        </>
      )}

      {!data && !isLoading && !error && (
        <div className="text-gray-500">Select a period to load the report.</div>
      )}
    </div>
  )
}
