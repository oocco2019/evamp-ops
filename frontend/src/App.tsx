import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom'
import Settings from './pages/Settings'
import SalesAnalytics from './pages/SalesAnalytics'
import SKUManager from './pages/SKUManager'
import MessageDashboard from './pages/MessageDashboard'

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-gray-50">
        {/* Navigation */}
        <nav className="bg-white shadow-sm">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex justify-between h-16">
              <div className="flex">
                <div className="flex-shrink-0 flex items-center">
                  <h1 className="text-xl font-bold text-gray-900">EvampOps</h1>
                </div>
                <div className="hidden sm:ml-6 sm:flex sm:space-x-8">
                  <Link
                    to="/analytics"
                    className="border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                  >
                    Sales Analytics
                  </Link>
                  <Link
                    to="/skus"
                    className="border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                  >
                    SKUs
                  </Link>
                  <Link
                    to="/messages"
                    className="border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                  >
                    Messages
                  </Link>
                  <Link
                    to="/settings"
                    className="border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 inline-flex items-center px-1 pt-1 border-b-2 text-sm font-medium"
                  >
                    Settings
                  </Link>
                </div>
              </div>
            </div>
          </div>
        </nav>

        {/* Main content */}
        <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/analytics" element={<SalesAnalytics />} />
            <Route path="/skus" element={<SKUManager />} />
            <Route path="/messages" element={<MessageDashboard />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </Router>
  )
}

function Home() {
  return (
    <div className="px-4 py-6 sm:px-0">
      <div className="border-4 border-dashed border-gray-200 rounded-lg p-8">
        <h2 className="text-2xl font-bold text-gray-900 mb-4">Welcome to EvampOps</h2>
        <p className="text-gray-600 mb-4">
          Your integrated platform for stock management and customer service.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
          <Link
            to="/settings"
            className="block p-6 bg-blue-50 border border-blue-200 rounded-lg hover:bg-blue-100"
          >
            <h3 className="text-lg font-semibold text-blue-900 mb-2">Get Started</h3>
            <p className="text-blue-700">
              Configure your API credentials and AI settings to begin.
            </p>
          </Link>
          <Link
            to="/analytics"
            className="block p-6 bg-green-50 border border-green-200 rounded-lg hover:bg-green-100"
          >
            <h3 className="text-lg font-semibold text-green-900 mb-2">Sales Analytics</h3>
            <p className="text-green-700">
              View sales data and trends with interactive charts.
            </p>
          </Link>
          <Link
            to="/skus"
            className="block p-6 bg-purple-50 border border-purple-200 rounded-lg hover:bg-purple-100"
          >
            <h3 className="text-lg font-semibold text-purple-900 mb-2">Manage SKUs</h3>
            <p className="text-purple-700">
              Organize your product catalog with costs and profit margins.
            </p>
          </Link>
          <Link
            to="/messages"
            className="block p-6 bg-orange-50 border border-orange-200 rounded-lg hover:bg-orange-100"
          >
            <h3 className="text-lg font-semibold text-orange-900 mb-2">Customer Service</h3>
            <p className="text-orange-700">
              Manage eBay messages with AI-powered drafting.
            </p>
          </Link>
        </div>
      </div>
    </div>
  )
}

export default App
