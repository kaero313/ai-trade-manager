export function resolveFirstTargetSymbol(rawValue: string | undefined): string | null {
  if (!rawValue) {
    return null
  }

  try {
    const parsed = JSON.parse(rawValue) as unknown
    if (!Array.isArray(parsed)) {
      return null
    }
    const first = parsed
      .map((item) => String(item).trim().toUpperCase())
      .find((item) => item.length > 0)
    return first ?? null
  } catch {
    return null
  }
}
