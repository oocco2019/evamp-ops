import { useState, useEffect, useCallback } from 'react'
import { messagesAPI, settingsAPI, type ThreadSummary, type ThreadDetail, type MessageResp, type EmailTemplate } from '../services/api'

/** Thread title: the buyer (person evamp talks to). Never show seller; fallback to order ID or "Unknown Buyer". */
function _threadTitle(
  buyerUsername: string | null,
  ebayOrderId: string | null,
  _threadId: string
): string {
  const buyer = (buyerUsername || '').trim()
  if (buyer && !buyer.toLowerCase().startsWith('evamp_')) return buyer
  return ebayOrderId || 'Unknown Buyer'
}

export default function MessageDashboard() {
  const [threads, setThreads] = useState<ThreadSummary[]>([])
  const [selectedThread, setSelectedThread] = useState<ThreadDetail | null>(null)
  const [sendingEnabled, setSendingEnabled] = useState(false)
  const [_draft, setDraft] = useState('')
  const [replyContent, setReplyContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'unread' | 'flagged'>('all')
  const [senderType, setSenderType] = useState<'all' | 'customer' | 'ebay'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [syncStatus, setSyncStatus] = useState<'idle' | 'syncing' | 'success' | 'error'>('idle')
  const [syncMessage, setSyncMessage] = useState<string>('')
  const [threadsStatus, setThreadsStatus] = useState<string>('')
  const [totalFlaggedCount, setTotalFlaggedCount] = useState(0)
  const [emailTemplates, setEmailTemplates] = useState<EmailTemplate[]>([])
  const [selectedEmailTemplate, setSelectedEmailTemplate] = useState<number | null>(null)
  const [showTranslation, setShowTranslation] = useState(false)
  const [translating, setTranslating] = useState(false)
  const [replyTranslation, setReplyTranslation] = useState<{ translated: string; backTranslated: string } | null>(null)
  const [translatingReply, setTranslatingReply] = useState(false)
  const [detectedLang, setDetectedLang] = useState<string>('en')

  const loadFlaggedCount = useCallback(async () => {
    try {
      const res = await messagesAPI.getFlaggedCount()
      setTotalFlaggedCount(res.data.flagged_count)
    } catch {
      // ignore
    }
  }, [])

  const loadEmailTemplates = useCallback(async () => {
    try {
      const res = await settingsAPI.listEmailTemplates()
      setEmailTemplates(res.data)
      if (res.data.length > 0 && selectedEmailTemplate === null) {
        setSelectedEmailTemplate(res.data[0].id)
      }
    } catch {
      // ignore
    }
  }, [selectedEmailTemplate])

  const loadSendingEnabled = useCallback(async () => {
    try {
      const res = await messagesAPI.getSendingEnabled()
      setSendingEnabled(res.data.sending_enabled)
    } catch {
      setSendingEnabled(false)
    }
  }, [])

  const loadThreads = useCallback(async () => {
    setLoading(true)
    setError(null)
    setThreadsStatus('Loading threads...')
    try {
      const params: { filter?: 'unread' | 'flagged'; search?: string; sender_type?: 'customer' | 'ebay' } = {}
      if (filter !== 'all') params.filter = filter
      if (searchQuery.trim()) params.search = searchQuery.trim()
      if (senderType !== 'all') params.sender_type = senderType
      const res = await messagesAPI.listThreads(params)
      setThreads(res.data)
      const searchNote = searchQuery.trim() ? ` matching "${searchQuery}"` : ''
      setThreadsStatus(`Loaded ${res.data.length} thread${res.data.length !== 1 ? 's' : ''}${searchNote}.`)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to load threads'
      setError(msg)
      setThreads([])
      const ax = e as { response?: { status?: number; data?: { detail?: string } } }
      const detail = ax.response?.data?.detail ?? ax.response?.status ?? ''
      setThreadsStatus(`Error: ${msg}${detail ? ` (${detail})` : ''}`)
    } finally {
      setLoading(false)
    }
  }, [filter, searchQuery, senderType])

  const loadThread = useCallback(async (threadId: string) => {
    setLoading(true)
    setError(null)
    setDraft('')
    setReplyContent('')
    setReplyTranslation(null)
    try {
      const res = await messagesAPI.getThread(threadId)
      setSelectedThread(res.data)
      
      // Check if translations exist in DB and auto-show them
      const hasTranslations = res.data.messages.some((m) => m.translated_content)
      setShowTranslation(hasTranslations)
      
      // Detect language from messages
      const nonEnglishMsg = res.data.messages.find(
        (m) => m.detected_language && m.detected_language !== 'en'
      )
      setDetectedLang(nonEnglishMsg?.detected_language || 'en')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load thread')
      setSelectedThread(null)
    } finally {
      setLoading(false)
    }
  }, [])

  const handleSync = async () => {
    setSyncing(true)
    setError(null)
    setSyncStatus('syncing')
    setSyncMessage('Syncing with eBay... this may take up to a minute.')
    try {
      const res = await messagesAPI.sync()
      setSyncStatus('success')
      setSyncMessage(res.data.message ?? `Synced: ${res.data.synced ?? 0} threads.`)
      loadThreads()
      loadFlaggedCount()
    } catch (e: unknown) {
      setSyncStatus('error')
      const ax = e as { response?: { status?: number; data?: { detail?: string }; statusText?: string }; code?: string }
      const detail = ax.response?.data?.detail ?? ax.response?.statusText ?? ''
      const statusCode = ax.response?.status ?? ''
      const errMsg = e instanceof Error ? e.message : 'Sync failed'
      const isTimeout = errMsg.toLowerCase().includes('timeout') || ax.code === 'ECONNABORTED'
      setSyncMessage(
        isTimeout
          ? 'Sync failed: Request timed out (90s). Backend may be unreachable or slow. Check backend is running and logs.'
          : `Sync failed: ${errMsg}${statusCode ? ` [HTTP ${statusCode}]` : ''}${detail ? ` — ${detail}` : ''}`
      )
      setError(isTimeout ? 'Request timed out. Check backend.' : errMsg)
    } finally {
      setSyncing(false)
    }
  }

  const handleDraft = async () => {
    if (!selectedThread) return
    setLoading(true)
    setError(null)
    try {
      const res = await messagesAPI.draftReply(selectedThread.thread_id)
      setDraft(res.data.draft)
      setReplyContent(res.data.draft)
    } catch (e: unknown) {
      const ax = e as { response?: { status?: number; data?: { detail?: string } } }
      const detail = ax.response?.data?.detail || ''
      const status = ax.response?.status
      const baseMsg = e instanceof Error ? e.message : 'Draft failed'

      // Provide helpful guidance for common AI configuration issues
      let errorMsg = detail || baseMsg
      if (detail.includes('No default AI model')) {
        errorMsg = 'AI not configured: Go to Settings > AI Models, add a model (e.g., Anthropic Claude), and set it as default.'
      } else if (detail.includes('No API key found')) {
        errorMsg = 'AI API key missing: Go to Settings > API Credentials and add your API key for the selected AI provider.'
      } else if (status === 500 && detail.includes('internal error')) {
        errorMsg = 'AI service error. Check that your API key is valid and has available credits.'
      }

      setError(errorMsg)
    } finally {
      setLoading(false)
    }
  }

  const handleSend = async () => {
    if (!selectedThread || !replyContent.trim()) return
    if (!sendingEnabled) return
    setLoading(true)
    setError(null)
    try {
      await messagesAPI.sendReply(selectedThread.thread_id, replyContent.trim())
      setReplyContent('')
      loadThread(selectedThread.thread_id)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Send failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadSendingEnabled()
    loadFlaggedCount()
    loadEmailTemplates()
  }, [loadSendingEnabled, loadFlaggedCount, loadEmailTemplates])

  useEffect(() => {
    loadThreads()
  }, [loadThreads])

  const handleToggleFlag = async (threadId: string, currentFlag: boolean) => {
    try {
      await messagesAPI.toggleFlag(threadId, !currentFlag)
      // Refresh thread and counts
      if (selectedThread && selectedThread.thread_id === threadId) {
        loadThread(threadId)
      }
      loadThreads()
      loadFlaggedCount()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to toggle flag')
    }
  }

  const handleWarehouseEmail = () => {
    if (!selectedThread || !selectedEmailTemplate) return
    const template = emailTemplates.find((t) => t.id === selectedEmailTemplate)
    if (!template) return

    // Replace variables in subject and body
    const variables: Record<string, string> = {
      '{tracking_number}': selectedThread.tracking_number || 'N/A',
      '{order_date}': selectedThread.created_at?.slice(0, 10) || 'N/A',
      '{delivery_country}': 'N/A', // Would need to get from order
      '{order_id}': selectedThread.ebay_order_id || 'N/A',
      '{buyer_username}': selectedThread.buyer_username || 'N/A',
    }

    let subject = template.subject
    let body = template.body
    for (const [key, value] of Object.entries(variables)) {
      subject = subject.replace(new RegExp(key.replace(/[{}]/g, '\\$&'), 'g'), value)
      body = body.replace(new RegExp(key.replace(/[{}]/g, '\\$&'), 'g'), value)
    }

    // Create mailto link
    const mailto = `mailto:${encodeURIComponent(template.recipient_email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
    window.open(mailto)
  }

  const handleTranslateThread = async () => {
    if (!selectedThread || translating) return
    setTranslating(true)
    setError(null)
    try {
      // Call backend to translate all messages and persist to DB
      const res = await messagesAPI.translateThread(selectedThread.thread_id)
      setDetectedLang(res.data.detected_language)
      
      // Reload thread to get updated translations from DB
      await loadThread(selectedThread.thread_id)
      setShowTranslation(true)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Translation failed')
    } finally {
      setTranslating(false)
    }
  }

  const handleTranslateReply = async () => {
    if (!replyContent.trim() || translatingReply || detectedLang === 'en') return
    setTranslatingReply(true)
    setError(null)
    try {
      const res = await messagesAPI.translate(replyContent, 'en', detectedLang)
      setReplyTranslation({
        translated: res.data.translated,
        backTranslated: res.data.back_translated,
      })
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Translation failed')
    } finally {
      setTranslatingReply(false)
    }
  }

  const handleSendTranslated = async () => {
    if (!replyTranslation || !selectedThread) return
    setReplyContent(replyTranslation.translated)
    setReplyTranslation(null)
  }

  return (
    <div className="px-4 py-6 sm:px-0">
      <h1 className="text-3xl font-bold text-gray-900 mb-4">Customer Service</h1>
      <p className="text-gray-600 mb-6">
        Manage eBay messages with AI-powered drafting. Sending is disabled until you enable it.
      </p>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-800 text-sm">
          {error}
        </div>
      )}

      <div className="mb-4 p-4 bg-gray-50 border border-gray-200 rounded-lg text-sm">
        <h3 className="font-medium text-gray-800 mb-2">Status</h3>
        <ul className="space-y-1 text-gray-700 font-mono">
          <li>
            <span className="text-gray-500">Threads:</span>{' '}
            {threadsStatus || 'Not loaded yet.'}
          </li>
          <li>
            <span className="text-gray-500">Sync:</span>{' '}
            {syncStatus === 'idle' && 'Idle. Click "Sync messages" to run.'}
            {syncStatus === 'syncing' && (
              <span className="text-blue-600">
                <span className="inline-block animate-spin mr-2">&#8635;</span>
                {syncMessage}
              </span>
            )}
            {syncStatus === 'success' && <span className="text-green-700">{syncMessage}</span>}
            {syncStatus === 'error' && <span className="text-red-700">{syncMessage}</span>}
          </li>
        </ul>
      </div>

      <div className="flex flex-wrap gap-2 mb-4 items-center">
        <button
          type="button"
          onClick={handleSync}
          disabled={syncing}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
        >
          {syncing ? 'Syncing...' : 'Sync messages'}
        </button>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as 'all' | 'unread' | 'flagged')}
          className="px-3 py-2 border border-gray-300 rounded text-sm bg-white"
        >
          <option value="all">All messages</option>
          <option value="unread">Unread only</option>
          <option value="flagged">Flagged only ({totalFlaggedCount})</option>
        </select>
        <select
          value={senderType}
          onChange={(e) => setSenderType(e.target.value as 'all' | 'customer' | 'ebay')}
          className="px-3 py-2 border border-gray-300 rounded text-sm bg-white"
        >
          <option value="all">All senders</option>
          <option value="customer">Customers only</option>
          <option value="ebay">eBay only</option>
        </select>
        {totalFlaggedCount > 0 && (
          <button
            type="button"
            onClick={() => setFilter(filter === 'flagged' ? 'all' : 'flagged')}
            className={`inline-flex items-center px-2.5 py-1.5 text-xs font-medium rounded cursor-pointer ${
              filter === 'flagged'
                ? 'bg-amber-500 text-white'
                : 'bg-amber-100 text-amber-800 hover:bg-amber-200'
            }`}
          >
            {totalFlaggedCount} flagged
          </button>
        )}
        <div className="flex-1" />
        <form
          onSubmit={(e) => {
            e.preventDefault()
            setSearchQuery(searchInput)
          }}
          className="flex gap-1"
        >
          <input
            type="text"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search messages..."
            className="px-3 py-2 border border-gray-300 rounded text-sm w-48"
          />
          <button
            type="submit"
            className="px-3 py-2 bg-gray-100 border border-gray-300 rounded text-sm hover:bg-gray-200"
          >
            Search
          </button>
          {searchQuery && (
            <button
              type="button"
              onClick={() => {
                setSearchInput('')
                setSearchQuery('')
              }}
              className="px-3 py-2 bg-gray-100 border border-gray-300 rounded text-sm hover:bg-gray-200"
              title="Clear search"
            >
              Clear
            </button>
          )}
        </form>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 bg-white shadow rounded-lg overflow-hidden">
          <h2 className="text-lg font-semibold text-gray-800 p-4 border-b border-gray-200">
            Threads
          </h2>
          {loading && !selectedThread ? (
            <p className="p-4 text-gray-500 text-sm">Loading...</p>
          ) : threads.length === 0 ? (
            <p className="p-4 text-gray-500 text-sm">
              {filter === 'all'
                ? 'No threads. Click "Sync messages" to pull messages from eBay.'
                : 'No messages found for the selected filter.'}
            </p>
          ) : (
            <ul className="divide-y divide-gray-200 max-h-[60vh] overflow-y-auto">
              {threads.map((t) => (
                <li key={t.thread_id}>
                  <button
                    type="button"
                    onClick={() => loadThread(t.thread_id)}
                    className={`w-full text-left p-4 hover:bg-gray-50 ${
                      selectedThread?.thread_id === t.thread_id ? 'bg-blue-50 border-l-4 border-blue-600' : ''
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <p className="font-medium text-gray-900 truncate flex items-center gap-2 min-w-0">
                        <span className="truncate">
                          {_threadTitle(t.buyer_username, t.ebay_order_id, t.thread_id)}
                        </span>
                        {t.unread_count > 0 && (
                          <span className="inline-flex items-center justify-center px-2 py-0.5 text-xs font-medium bg-blue-600 text-white rounded-full flex-shrink-0">
                            {t.unread_count}
                          </span>
                        )}
                      </p>
                      {t.is_flagged && (
                        <span className="text-amber-500 text-lg flex-shrink-0" title="Flagged">&#9873;</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mt-1">
                      {t.message_count} message{t.message_count !== 1 ? 's' : ''}
                      {t.sku ? ` · ${t.sku}` : ''}
                    </p>
                    {t.last_message_preview && (
                      <p className="text-sm text-gray-600 mt-1 truncate">{t.last_message_preview}</p>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="lg:col-span-2 bg-white shadow rounded-lg overflow-hidden flex flex-col">
          {!selectedThread ? (
            <div className="p-8 text-center text-gray-500">
              Select a thread or sync to load sample threads.
            </div>
          ) : (
            <>
              <div className="p-4 border-b border-gray-200">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold text-gray-800 flex items-center gap-2">
                    {selectedThread.is_flagged && <span className="text-amber-500">&#9873;</span>}
                    {_threadTitle(selectedThread.buyer_username, selectedThread.ebay_order_id, selectedThread.thread_id)}
                  </h2>
                  <div className="flex gap-2">
                    {emailTemplates.length > 0 && selectedThread.ebay_order_id && (
                      <div className="flex gap-1">
                        <select
                          value={selectedEmailTemplate ?? ''}
                          onChange={(e) => setSelectedEmailTemplate(Number(e.target.value))}
                          className="text-sm border border-gray-300 rounded px-2 py-1"
                        >
                          {emailTemplates.map((t) => (
                            <option key={t.id} value={t.id}>
                              {t.name}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={handleWarehouseEmail}
                          className="px-3 py-1.5 text-sm rounded font-medium bg-green-100 text-green-700 hover:bg-green-200"
                          title="Open email in mail app"
                        >
                          Warehouse Email
                        </button>
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => handleToggleFlag(selectedThread.thread_id, selectedThread.is_flagged)}
                      className={`px-3 py-1.5 text-sm rounded font-medium ${
                        selectedThread.is_flagged
                          ? 'bg-amber-100 text-amber-700 hover:bg-amber-200'
                          : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                    >
                      {selectedThread.is_flagged ? 'Unflag thread' : 'Flag thread'}
                    </button>
                  </div>
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-sm text-gray-600">
                  {selectedThread.ebay_order_id ? (
                    <span>
                      Order:{' '}
                      <a
                        href={`https://www.ebay.co.uk/mesh/ord/details?mode=SH&orderid=${selectedThread.ebay_order_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline"
                      >
                        {selectedThread.ebay_order_id}
                      </a>
                    </span>
                  ) : (
                    <span className="text-gray-400">No Order Linked</span>
                  )}
                  {selectedThread.ebay_item_id && (
                    <span>
                      Item:{' '}
                      <a
                        href={`https://www.ebay.co.uk/itm/${selectedThread.ebay_item_id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline"
                      >
                        {selectedThread.ebay_item_id}
                      </a>
                    </span>
                  )}
                  {selectedThread.sku && <span>SKU: {selectedThread.sku}</span>}
                  {selectedThread.tracking_number && (
                    <span>Tracking: {selectedThread.tracking_number}</span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-2">
                  <button
                    type="button"
                    onClick={handleTranslateThread}
                    disabled={translating}
                    className="px-3 py-1 text-xs bg-purple-100 text-purple-700 rounded hover:bg-purple-200 disabled:opacity-50"
                  >
                    {translating ? 'Translating...' : showTranslation ? 'Refresh Translation' : 'Translate Thread'}
                  </button>
                  {showTranslation && (
                    <button
                      type="button"
                      onClick={() => setShowTranslation(false)}
                      className="px-3 py-1 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
                    >
                      Hide Translation
                    </button>
                  )}
                  {detectedLang !== 'en' && (
                    <span className="text-xs text-purple-600">
                      Detected: {detectedLang.toUpperCase()}
                    </span>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto p-4 space-y-4 max-h-[40vh]">
                {selectedThread.messages.map((m) => (
                  <MessageBubble 
                    key={m.message_id} 
                    message={m} 
                    showTranslation={showTranslation}
                  />
                ))}
              </div>
              <div className="p-4 border-t border-gray-200 space-y-3">
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={handleDraft}
                    disabled={loading}
                    className="px-3 py-2 bg-gray-100 text-gray-800 rounded hover:bg-gray-200 disabled:opacity-50 text-sm font-medium"
                  >
                    {loading ? '...' : 'Draft reply'}
                  </button>
                </div>
                <div className="relative">
                  <textarea
                    value={replyContent}
                    onChange={(e) => setReplyContent(e.target.value)}
                    placeholder="Type or use Draft reply..."
                    rows={4}
                    maxLength={2000}
                    className={`w-full rounded border px-3 py-2 text-sm ${
                      replyContent.length > 2000 ? 'border-red-500' : 'border-gray-300'
                    }`}
                  />
                  <span
                    className={`absolute bottom-2 right-2 text-xs ${
                      replyContent.length > 1900
                        ? replyContent.length > 2000
                          ? 'text-red-600 font-medium'
                          : 'text-amber-600'
                        : 'text-gray-400'
                    }`}
                  >
                    {replyContent.length}/2000
                  </span>
                </div>
                {/* Translation for sending */}
                {detectedLang !== 'en' && replyContent.trim() && (
                  <div className="bg-purple-50 border border-purple-200 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-medium text-purple-700">
                        Translate reply to {detectedLang.toUpperCase()} before sending
                      </span>
                      <button
                        type="button"
                        onClick={handleTranslateReply}
                        disabled={translatingReply}
                        className="px-2 py-1 text-xs bg-purple-600 text-white rounded hover:bg-purple-700 disabled:opacity-50"
                      >
                        {translatingReply ? 'Translating...' : 'Translate for Sending'}
                      </button>
                    </div>
                    {replyTranslation && (
                      <div className="space-y-2 text-sm">
                        <div>
                          <p className="text-xs text-purple-600 font-medium">Translated ({detectedLang.toUpperCase()}):</p>
                          <p className="text-gray-800 bg-white p-2 rounded border">{replyTranslation.translated}</p>
                        </div>
                        <div>
                          <p className="text-xs text-purple-600 font-medium">Back-translation (for verification):</p>
                          <p className="text-gray-600 bg-white p-2 rounded border">{replyTranslation.backTranslated}</p>
                        </div>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={handleSendTranslated}
                            className="px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                          >
                            Use translated version
                          </button>
                          <button
                            type="button"
                            onClick={() => setReplyTranslation(null)}
                            className="px-3 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex justify-between items-center">
                  <span className="text-xs text-gray-500">
                    {sendingEnabled
                      ? 'Sending is enabled. Replies will go to eBay.'
                      : 'Sending is disabled. Enable ENABLE_MESSAGE_SENDING in .env when ready to test.'}
                  </span>
                  <button
                    type="button"
                    onClick={handleSend}
                    disabled={!sendingEnabled || !replyContent.trim() || replyContent.length > 2000 || loading}
                    title={
                      !sendingEnabled
                        ? 'Sending is disabled for testing. Set ENABLE_MESSAGE_SENDING=true when ready.'
                        : replyContent.length > 2000
                          ? 'Message exceeds 2000 character limit.'
                          : undefined
                    }
                    className="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm font-medium"
                  >
                    Send
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function MessageBubble({ message, showTranslation }: { message: MessageResp; showTranslation?: boolean }) {
  // Detect sender type
  const isEbay = message.sender_type === 'ebay'
  const isSeller =
    message.sender_type === 'seller' ||
    (message.sender_username?.toLowerCase().startsWith('evamp_') ?? false)

  // Style based on sender: eBay (amber, centered), seller (blue, right), buyer (gray, left)
  let bubbleClass = 'bg-gray-100 text-gray-900 ml-0 mr-auto'
  let metaClass = 'text-gray-500'
  let subjectClass = 'text-gray-800'

  if (isEbay) {
    bubbleClass = 'bg-amber-50 text-gray-900 mx-auto border border-amber-200'
    metaClass = 'text-amber-600'
    subjectClass = 'text-amber-800'
  } else if (isSeller) {
    bubbleClass = 'bg-[#0064D2] text-white ml-auto mr-0'
    metaClass = 'text-blue-100'
    subjectClass = 'text-white'
  }

  // Use stored translation from DB
  const translation = showTranslation ? message.translated_content : null

  return (
    <div className={`rounded-lg p-3 max-w-[85%] ${bubbleClass}`}>
      <p className={`text-xs mb-1 ${metaClass}`}>
        {message.sender_username || message.sender_type} · {message.ebay_created_at.slice(0, 16)}
      </p>
      {message.subject && (
        <p className={`text-sm font-medium mb-1 ${subjectClass}`}>{message.subject}</p>
      )}
      <p className="text-sm whitespace-pre-wrap">{message.content}</p>
      {translation && (
        <div className={`mt-2 pt-2 border-t ${isSeller ? 'border-blue-300' : 'border-gray-300'}`}>
          <p className={`text-xs mb-1 ${isSeller ? 'text-blue-200' : 'text-purple-600'}`}>Translation (English):</p>
          <p className={`text-sm whitespace-pre-wrap ${isSeller ? 'text-white' : 'text-gray-700'}`}>{translation}</p>
        </div>
      )}
    </div>
  )
}
