import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { settingsAPI } from '../services/api'

export const DEFAULT_APP_NAME = 'EvampOps'
export const DEFAULT_FAVICON = '/favicon.svg'

export function useBranding() {
  const query = useQuery({
    queryKey: ['app-branding'],
    queryFn: async () => (await settingsAPI.getBranding()).data,
    staleTime: 60_000,
  })

  const branding = query.data
  const appName = branding?.app_name?.trim() || DEFAULT_APP_NAME
  const faviconUrl =
    branding?.has_favicon && branding.favicon_url ? branding.favicon_url : DEFAULT_FAVICON
  const faviconMime = branding?.favicon_mime ?? null

  useEffect(() => {
    document.title = appName

    const applyLink = (rel: string) => {
      let link = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
      if (!link) {
        link = document.createElement('link')
        link.rel = rel
        document.head.appendChild(link)
      }
      link.href = faviconUrl
      if (faviconMime) {
        link.type = faviconMime
      } else if (faviconUrl.endsWith('.svg')) {
        link.type = 'image/svg+xml'
      } else {
        link.removeAttribute('type')
      }
    }

    applyLink('icon')
    applyLink('apple-touch-icon')
  }, [appName, faviconUrl, faviconMime])

  return {
    ...query,
    branding,
    appName,
    faviconUrl,
  }
}
