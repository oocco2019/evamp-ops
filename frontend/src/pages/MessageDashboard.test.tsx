import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MessageDashboard from './MessageDashboard'

const mocks = vi.hoisted(() => ({
  messagesAPI: {
    listThreads: vi.fn(),
    getThread: vi.fn(),
    markThreadRead: vi.fn(),
    getFlaggedCount: vi.fn(),
    uploadMessageMedia: vi.fn(),
    sendReply: vi.fn(),
    refreshThread: vi.fn(),
    sync: vi.fn(),
    getSyncStatus: vi.fn(),
  },
  settingsAPI: {
    listEmailTemplates: vi.fn(),
  },
}))

vi.mock('../services/api', () => ({
  messagesAPI: mocks.messagesAPI,
  settingsAPI: mocks.settingsAPI,
}))

const threadSummary = {
  thread_id: 'thread-1',
  buyer_username: 'buyer1',
  ebay_order_id: 'order-1',
  ebay_item_id: 'item-1',
  sku: 'SKU-1',
  created_at: '2026-05-15T10:00:00Z',
  message_count: 1,
  unread_count: 0,
  is_flagged: false,
  last_message_preview: 'Hello',
}

const threadDetail = {
  thread_id: 'thread-1',
  buyer_username: 'buyer1',
  ebay_order_id: 'order-1',
  ebay_item_id: 'item-1',
  sku: 'SKU-1',
  tracking_number: null,
  is_flagged: false,
  created_at: '2026-05-15T10:00:00Z',
  messages: [
    {
      message_id: 'message-1',
      thread_id: 'thread-1',
      sender_type: 'buyer',
      sender_username: 'buyer1',
      subject: null,
      content: 'Hello',
      media: null,
      is_read: false,
      detected_language: 'en',
      translated_content: null,
      ebay_created_at: '2026-05-15T10:00:00Z',
      created_at: '2026-05-15T10:00:00Z',
    },
  ],
}

describe('MessageDashboard failed sends', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.messagesAPI.listThreads.mockResolvedValue({ data: [threadSummary] })
    mocks.messagesAPI.getThread.mockResolvedValue({ data: threadDetail })
    mocks.messagesAPI.markThreadRead.mockResolvedValue({ data: undefined })
    mocks.messagesAPI.getFlaggedCount.mockResolvedValue({ data: { flagged_count: 0 } })
    mocks.messagesAPI.uploadMessageMedia.mockResolvedValue({
      data: {
        mediaName: 'photo.png',
        mediaType: 'IMAGE',
        mediaUrl: 'https://example.com/photo.png',
      },
    })
    mocks.messagesAPI.sendReply.mockRejectedValue(new Error('Network down'))
    mocks.messagesAPI.refreshThread.mockResolvedValue({ data: undefined })
    mocks.messagesAPI.sync.mockResolvedValue({ data: { synced: 0, message: 'Synced' } })
    mocks.messagesAPI.getSyncStatus.mockResolvedValue({ data: { is_syncing: false } })
    mocks.settingsAPI.listEmailTemplates.mockResolvedValue({ data: [] })
  })

  it('preserves reply text, attachments, and error when send fails', async () => {
    const user = userEvent.setup()
    render(<MessageDashboard />)

    await user.click(await screen.findByRole('button', { name: /buyer1/i }))

    const replyBox = await screen.findByPlaceholderText('Type or use Draft reply...')
    await user.type(replyBox, '  Please confirm delivery.  ')

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['image bytes'], 'photo.png', { type: 'image/png' })
    fireEvent.change(fileInput, { target: { files: [file] } })
    await screen.findByText('photo.png')

    await user.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => {
      expect(mocks.messagesAPI.sendReply).toHaveBeenCalledWith(
        'thread-1',
        'Please confirm delivery.',
        undefined,
        [
          {
            mediaName: 'photo.png',
            mediaType: 'IMAGE',
            mediaUrl: 'https://example.com/photo.png',
          },
        ]
      )
    })
    await screen.findByText('Network down')
    await waitFor(() => {
      expect(screen.getByPlaceholderText('Type or use Draft reply...')).toHaveValue(
        '  Please confirm delivery.  '
      )
    })
    expect(screen.getByText('photo.png')).toBeInTheDocument()
  })
})
