export default function MessageDashboard() {
  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="bg-white shadow rounded-lg p-6">
        <h1 className="text-3xl font-bold text-gray-900 mb-4">Customer Service</h1>
        <p className="text-gray-600 mb-6">
          Manage eBay messages with AI-powered drafting and translation.
        </p>
        <div className="bg-orange-50 border border-orange-200 rounded-lg p-6">
          <h3 className="font-semibold text-orange-900 mb-2">Coming in Phase 4-6</h3>
          <p className="text-orange-700">
            This feature will include:
          </p>
          <ul className="list-disc list-inside text-orange-700 mt-2 space-y-1">
            <li>Real-time eBay message sync (webhook + polling)</li>
            <li>Thread-based message viewing</li>
            <li>AI-powered message drafting</li>
            <li>Automatic language detection and translation</li>
            <li>Message flagging and search</li>
            <li>Direct message sending via eBay API</li>
          </ul>
        </div>
      </div>
    </div>
  )
}
