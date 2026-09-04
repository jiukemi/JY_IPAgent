/** Compare session paths that may be relative vs absolute / slash vs backslash. */
export function sameSessionPath(a?: string | null, b?: string | null): boolean {
  if (!a || !b) return true
  const norm = (p: string) =>
    p
      .trim()
      .replace(/\\/g, '/')
      .replace(/\/+$/, '')
      .toLowerCase()
  const na = norm(a)
  const nb = norm(b)
  if (na === nb) return true
  return na.endsWith('/' + nb) || nb.endsWith('/' + na) || na.endsWith(nb) || nb.endsWith(na)
}
