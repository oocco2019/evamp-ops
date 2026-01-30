export default function SKUManager() {
  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-3xl font-bold text-gray-900 mb-4">SKU Manager</h1>
        <p className="text-gray-600 mb-6">
          Manage your product catalog with costs and profit calculations.
        </p>
        <div className="bg-purple-50 border border-purple-200 rounded-lg p-6">
          <h3 className="font-semibold text-purple-900 mb-2">Coming in Phase 2</h3>
          <p className="text-purple-700">
            This feature will include:
          </p>
          <ul className="list-disc list-inside text-purple-700 mt-2 space-y-1">
            <li>Add, edit, and delete SKUs</li>
            <li>Track landed cost, postage price, and profit per unit</li>
            <li>Inline editing with validation</li>
            <li>Search and filter functionality</li>
            <li>Support for multiple currencies</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
