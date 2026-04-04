/** API 常返回字符串数字；直接 .toFixed 会抛 TypeError */
export function toFixedSafe(value: unknown, digits: number, fallback = '-'): string {
  const n = Number(value)
  return Number.isFinite(n) ? n.toFixed(digits) : fallback
}

export function formatMoneySafe(value: unknown): string {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return n.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}
