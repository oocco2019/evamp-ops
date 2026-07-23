# Customer Service (Message dashboard)

UI: `/messages` → `frontend/src/pages/MessageDashboard.tsx`.

On-page explanatory blurbs were removed; behaviour is documented here and in the related message docs.

## What the page does

- Manage **eBay** buyer/seller message threads with **AI-powered drafting** (including **DE** German compose).
- **Sending** to eBay is gated until send is enabled in app/settings behaviour (drafting can still work when send is off).
- The **thread list** is loaded from the **local database**. **Sync** buttons fetch new/updated messages from eBay into that DB (Quick sync / deeper sync options on the page).

## Related docs

- [MESSAGE_TRANSLATION.md](MESSAGE_TRANSLATION.md) – local translation / DE compose  
- [MESSAGE_ATTACHMENTS.md](MESSAGE_ATTACHMENTS.md) – attachments  
- [MESSAGE_SYNC_REVIEW.md](MESSAGE_SYNC_REVIEW.md) – sync behaviour review notes  
- [DEVELOPING.md](DEVELOPING.md) – quick tip for drafting / DE  
