export default function SalesAnalytics() {
  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-3xl font-bold text-gray-900 mb-4">Sales Analytics</h1>
        <p className="text-gray-600 mb-6">
          Interactive sales dashboard with filtering and charts.
        </p>
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <h3 className="font-semibold text-blue-900 mb-2">Coming in Phase 3</h3>
          <p className="text-blue-700">
            This feature will include:
          </p>
          <ul className="list-disc list-inside text-blue-700 mt-2 space-y-1">
            <li>Interactive bar charts with sales data</li>
            <li>Filter by date range, country, and SKU</li>
            <li>Daily, weekly, monthly, and yearly aggregation</li>
            <li>Stacked views by SKU or country</li>
            <li>Summary panel with key metrics</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
