/**
 * Split plain text into text + http(s) URL segments for React rendering.
 * Trailing punctuation that is not part of the URL is left as plain text.
 */
const URL_RE = /https?:\/\/[^\s<>"'\\]+/gi
const TRAILING_PUNCT = /[.,;:!?)]+$/

export type LinkifyPart = { type: 'text'; value: string } | { type: 'url'; value: string }

export function linkifyParts(text: string): LinkifyPart[] {
  if (!text) return []
  const parts: LinkifyPart[] = []
  let lastIndex = 0
  const re = new RegExp(URL_RE.source, URL_RE.flags)
  let match: RegExpExecArray | null
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', value: text.slice(lastIndex, match.index) })
    }
    let url = match[0]
    const punct = url.match(TRAILING_PUNCT)
    if (punct) {
      url = url.slice(0, -punct[0].length)
      parts.push({ type: 'url', value: url })
      parts.push({ type: 'text', value: punct[0] })
    } else {
      parts.push({ type: 'url', value: url })
    }
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    parts.push({ type: 'text', value: text.slice(lastIndex) })
  }
  return parts
}
