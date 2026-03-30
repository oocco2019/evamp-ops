/**
 * OrangeConnex SKU import template export (Stock Planning → OC inbound upload).
 * Template: public/SKUImportTemplateV1_EN.xlsx — we replace the first sheet's data rows only.
 */
import * as XLSX from 'xlsx'
import JSZip from 'jszip'

/**
 * SKU group key = leading letters before digits.
 * Examples: `bee01` -> `bee`, `dee12` -> `dee`, `xxx01` -> `xxx`.
 */
export function skuGroupKeyFromSkuCode(skuCode: string): string | null {
  const s = skuCode.trim()
  const m = s.match(/^([a-zA-Z]+)\d+/)
  if (!m) return null
  return m[1].toLowerCase()
}

/** OC template expects OC SKUID like OC0000031876013 */
export function normalizeOcSkuid(mfskuid: string): string {
  const s = mfskuid.trim()
  if (!s) return ''
  if (/^OC/i.test(s)) return s
  return `OC${s.replace(/^OC/i, '')}`
}

export interface MappingRow {
  sku_code: string
  seller_skuid: string
  mfskuid: string
  service_region: string | null
}

function pickMapping(mappings: MappingRow[], skuCode: string, skuGroupKey: string): MappingRow | null {
  const candidates = mappings.filter((m) => m.sku_code === skuCode)
  if (candidates.length === 0) return null
  if (candidates.length === 1) return candidates[0]
  const groupUpper = skuGroupKey.trim().toUpperCase()

  // Prefer an exact / substring-ish match between sku group and service_region.
  // This keeps existing behavior for aue/dee/uke/use, but also works for new prefixes
  // (bee/...) without hardcoding marketplace -> service_region mappings.
  const prefer = candidates.find((m) => {
    const sr = (m.service_region || '').trim().toUpperCase()
    if (!sr) return false
    return groupUpper.includes(sr) || sr.includes(groupUpper)
  })
  if (prefer) return prefer

  // If all candidates share the same service_region, any of them is fine.
  const firstSr = (candidates[0].service_region || '').trim()
  if (candidates.every((c) => (c.service_region || '').trim() === firstSr)) return candidates[0]

  // Ambiguous: fall back deterministically.
  return candidates[0]
}

export interface PlanLine {
  sku_code: string
  units: number
}

export function chunkQuantity(total: number, itemsPerCarton: number): number[] {
  const t = Math.floor(total)
  const cap = Math.max(1, Math.floor(itemsPerCarton))
  if (t <= 0) return []
  const out: number[] = []
  let remaining = t
  while (remaining > 0) {
    const n = Math.min(cap, remaining)
    out.push(n)
    remaining -= n
  }
  return out
}

export interface BuildExportResult {
  /** Per-prefix key (aue, dee, uke, use) → workbook bytes per region file */
  files: { marketLabel: string; fileName: string; buffer: Uint8Array }[]
  /** SKUs with units > 0 but no OC mapping */
  missingMapping: string[]
  /** SKUs whose prefix can't be determined as leading letters */
  unknownPrefix: string[]
  /** SKUs mapped to multiple OC service_region values; we used first deterministically */
  ambiguousMapping: string[]
}

/**
 * Build one filled template workbook per market that has at least one line with units > 0.
 */
export async function buildOcSkuImportExports(
  planLines: PlanLine[],
  mappings: MappingRow[],
  itemsPerCarton: number,
  templateUrl = '/SKUImportTemplateV1_EN.xlsx'
): Promise<BuildExportResult> {
  const active = planLines.filter((l) => l.units > 0)
  const missingMapping: string[] = []
  const unknownPrefix: string[] = []
  const ambiguousMapping: string[] = []
  const cartonSize = Math.max(1, Math.floor(itemsPerCarton))
  const invalidCartonQuantities: string[] = []

  // OC inbound requires exact carton sizes: if a SKU quantity doesn't divide evenly,
  // we must stop export and show the SKU codes.
  for (const line of active) {
    if (line.units % cartonSize !== 0) invalidCartonQuantities.push(line.sku_code)
  }

  const byGroup = new Map<string, PlanLine[]>()
  for (const line of active) {
    const groupKey = skuGroupKeyFromSkuCode(line.sku_code)
    if (!groupKey) {
      unknownPrefix.push(line.sku_code)
      continue
    }
    const list = byGroup.get(groupKey) ?? []
    list.push(line)
    byGroup.set(groupKey, list)
  }

  const res = await fetch(templateUrl)
  if (!res.ok) {
    throw new Error(`Template not found (${templateUrl}). Add SKUImportTemplateV1_EN.xlsx to /public.`)
  }
  const templateAb = await res.arrayBuffer()

  const files: BuildExportResult['files'] = []

  if (invalidCartonQuantities.length > 0) {
    throw new Error(
      `Carton must contain exactly ${cartonSize} items per SKU. Planned units are not divisible for: ${[
        ...new Set(invalidCartonQuantities),
      ].join(', ')}`
    )
  }

  for (const [skuGroupKey, lines] of byGroup) {
    if (!skuGroupKey || lines.length === 0) continue

    // Reset carton numbering per workbook (per SKU letter group file).
    let cartonIndex = 1

    const rowsForSheet: {
      seller_skuid: string
      oc_skuid: string
      quantity: number
      cartonNo: string
    }[] = []
    for (const line of lines) {
      const candidates = mappings.filter((m) => m.sku_code === line.sku_code)
      if (candidates.length > 1) {
        const distinctSr = new Set(candidates.map((c) => (c.service_region || '').trim()).filter(Boolean))
        if (distinctSr.size > 1) ambiguousMapping.push(line.sku_code)
      }

      const m = pickMapping(mappings, line.sku_code, skuGroupKey)
      if (!m || !m.mfskuid?.trim()) {
        missingMapping.push(line.sku_code)
        continue
      }

      const cartonQtys = chunkQuantity(line.units, cartonSize)
      if (cartonQtys.length === 0) continue

      for (const qty of cartonQtys) {
        const cartonNo = `A${String(cartonIndex).padStart(4, '0')}`
        cartonIndex += 1
        rowsForSheet.push({
          seller_skuid: (m.seller_skuid || line.sku_code).trim(),
          oc_skuid: normalizeOcSkuid(m.mfskuid),
          quantity: qty,
          cartonNo,
        })
      }
    }

    if (rowsForSheet.length === 0) continue

    const wb = XLSX.read(templateAb, { type: 'array' })
    const sheetName = wb.SheetNames[0] ?? 'SKU Import Template'
    const header = [
      '*Seller SKUID',
      '*OC SKUID',
      '*Quantity',
      '*Carton Number',
      'Note',
    ]
    const aoa: (string | number)[][] = [header]
    for (const r of rowsForSheet) {
      aoa.push([r.seller_skuid, r.oc_skuid, r.quantity, r.cartonNo, ''])
    }
    const ws = XLSX.utils.aoa_to_sheet(aoa)
    wb.Sheets[sheetName] = ws
    const buffer = XLSX.write(wb, { bookType: 'xlsx', type: 'array' }) as Uint8Array
    files.push({
      marketLabel: skuGroupKey.toUpperCase(),
      fileName: `OC_SKU_Import_${skuGroupKey.toUpperCase()}.xlsx`,
      buffer,
    })
  }

  return {
    files,
    missingMapping: [...new Set(missingMapping)],
    unknownPrefix: [...new Set(unknownPrefix)],
    ambiguousMapping: [...new Set(ambiguousMapping)],
  }
}

export async function downloadOcSkuImportZip(
  result: BuildExportResult,
  zipBaseName = 'OC_Inbound_SKU_Import'
): Promise<void> {
  if (result.files.length === 0) return
  if (result.files.length === 1) {
    const f = result.files[0]
    const blob = new Blob([f.buffer], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    triggerDownload(blob, f.fileName)
    return
  }
  const zip = new JSZip()
  for (const f of result.files) {
    zip.file(f.fileName, f.buffer)
  }
  const blob = await zip.generateAsync({ type: 'blob' })
  const stamp = new Date().toISOString().slice(0, 10)
  triggerDownload(blob, `${zipBaseName}_${stamp}.zip`)
}

function triggerDownload(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  a.click()
  URL.revokeObjectURL(url)
}
