import { lazy, Suspense } from 'react'
import { BrowserRouter as Router, Routes, Route, Link, Navigate } from 'react-router-dom'
import { useBranding } from './hooks/useBranding'

const Settings = lazy(() => import('./pages/Settings'))
const SalesAnalytics = lazy(() => import('./pages/SalesAnalytics'))
const StockPlanning = lazy(() => import('./pages/StockPlanning'))
const MessageDashboard = lazy(() => import('./pages/MessageDashboard'))
const InventoryStatus = lazy(() => import('./pages/InventoryStatus'))
const OrderDetails = lazy(() => import('./pages/OrderDetails'))
const AIInstructions = lazy(() => import('./pages/AIInstructions'))

const NAV_LINK =
  'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700 inline-flex items-center px-1 pt-1 border-b-2 text-[1.1375rem] font-medium'

function App() {
  const { faviconUrl } = useBranding()

  return (
    <Router>
      <div className="min-h-screen bg-gray-50">
        {/* Navigation */}
        <nav className="bg-white shadow-sm">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div className="flex h-16 items-center gap-6">
              <Link to="/" className="flex-shrink-0 flex items-center">
                <img src={faviconUrl} alt="" className="h-8 w-8 object-contain rounded" />
              </Link>
              <div className="flex flex-wrap gap-x-8 gap-y-1">
                <Link to="/analytics" className={NAV_LINK}>
                  Sales Analytics
                </Link>
                <Link to="/messages" className={NAV_LINK}>
                  Messages
                </Link>
                <Link to="/inventory" className={NAV_LINK}>
                  Inventory
                </Link>
                <Link to="/planning" className={NAV_LINK}>
                  Stock Order
                </Link>
                <Link to="/settings" className={NAV_LINK}>
                  Misc
                </Link>
              </div>
            </div>
          </div>
        </nav>

        {/* Main content */}
        <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
          <Suspense fallback={<PageLoader />}>
            <Routes>
              <Route path="/" element={<Home />} />
              <Route path="/analytics" element={<SalesAnalytics />} />
              <Route path="/lender-summary" element={<Navigate to="/settings?tab=lender" replace />} />
              <Route path="/order-details" element={<OrderDetails />} />
              <Route path="/planning" element={<StockPlanning />} />
              <Route path="/skus" element={<Navigate to="/settings?tab=skus" replace />} />
              <Route path="/inventory" element={<InventoryStatus />} />
              <Route path="/inventory-status" element={<Navigate to="/inventory" replace />} />
              <Route path="/inventory-movement" element={<Navigate to="/inventory" replace />} />
              <Route path="/messages" element={<MessageDashboard />} />
              <Route path="/ai-instructions" element={<AIInstructions />} />
              <Route path="/listing-video" element={<Navigate to="/settings?tab=video" replace />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </Router>
  )
}

function PageLoader() {
  return (
    <div className="flex items-center justify-center py-12">
      <div className="animate-pulse text-gray-500">Loading...</div>
    </div>
  )
}

function Home() {
  const { appName } = useBranding()

  return (
    <div className="px-4 py-24 sm:px-0 flex justify-center">
      <h1 className="text-3xl font-bold text-gray-900 text-center">{appName}</h1>
    </div>
  )
}

export default App
