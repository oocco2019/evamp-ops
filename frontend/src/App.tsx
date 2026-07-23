import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { BrowserRouter as Router, Routes, Route, Link, Navigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useBranding } from './hooks/useBranding'
import { settingsAPI } from './services/api'
import { linkifyParts } from './utils/linkify'

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
  const queryClient = useQueryClient()
  const [notes, setNotes] = useState('')
  const [lastSaved, setLastSaved] = useState<string | null>(null)
  const [savedFlash, setSavedFlash] = useState(false)
  const [editing, setEditing] = useState(false)
  const hydratedRef = useRef(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const notepadQuery = useQuery({
    queryKey: ['app-notepad'],
    queryFn: async () => (await settingsAPI.getNotepad()).data,
  })

  useEffect(() => {
    if (!notepadQuery.data || hydratedRef.current) return
    const value = notepadQuery.data.body ?? ''
    setNotes(value)
    setLastSaved(value)
    hydratedRef.current = true
    if (!value.trim()) setEditing(true)
  }, [notepadQuery.data])

  useEffect(() => {
    if (!editing) return
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
    el.focus()
  }, [notes, editing, notepadQuery.isLoading])

  const saveNotes = useMutation({
    mutationFn: async (body: string) => (await settingsAPI.updateNotepad({ body })).data,
    onSuccess: (data, body) => {
      queryClient.setQueryData(['app-notepad'], data)
      setLastSaved(body)
      setSavedFlash(true)
      window.setTimeout(() => setSavedFlash(false), 1500)
    },
  })

  useEffect(() => {
    if (!hydratedRef.current || lastSaved === null || notes === lastSaved) return
    const timer = window.setTimeout(() => {
      saveNotes.mutate(notes)
    }, 500)
    return () => window.clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- save on notes change only
  }, [notes, lastSaved])

  const fieldClass =
    'w-full min-h-[calc(100vh-14rem)] border border-gray-300 rounded-lg px-4 py-3 text-sm text-gray-900 leading-relaxed'

  return (
    <div className="max-w-3xl mx-auto px-4 py-12 sm:px-6">
      <h1 className="text-3xl font-bold text-gray-900 text-center mb-10">{appName}</h1>

      <section className="bg-white border border-gray-200 rounded-xl shadow-sm p-6">
        <div className="flex items-baseline justify-between gap-4 mb-2">
          <h2 className="text-lg font-semibold text-gray-900">Notepad</h2>
          {saveNotes.isPending ? (
            <span className="text-sm text-gray-500">Saving…</span>
          ) : savedFlash ? (
            <span className="text-sm text-green-600">Saved</span>
          ) : null}
        </div>
        {editing ? (
          <textarea
            ref={textareaRef}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => setEditing(false)}
            disabled={notepadQuery.isLoading}
            placeholder="Notes, todos, links…"
            className={`${fieldClass} placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500
              disabled:bg-gray-50 disabled:text-gray-400 resize-none overflow-hidden`}
          />
        ) : (
          <div
            role="button"
            tabIndex={0}
            onClick={() => setEditing(true)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                setEditing(true)
              }
            }}
            className={`${fieldClass} whitespace-pre-wrap cursor-text focus:outline-none focus:ring-2 focus:ring-blue-500`}
          >
            {notes ? (
              linkifyParts(notes).map((part, i) =>
                part.type === 'url' ? (
                  <a
                    key={i}
                    href={part.value}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 underline break-all"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {part.value}
                  </a>
                ) : (
                  <span key={i}>{part.value}</span>
                )
              )
            ) : (
              <span className="text-gray-400">Notes, todos, links…</span>
            )}
          </div>
        )}
        {saveNotes.isError ? (
          <p className="mt-2 text-sm text-red-600">Could not save. Keep typing to retry.</p>
        ) : null}
      </section>
    </div>
  )
}

export default App
