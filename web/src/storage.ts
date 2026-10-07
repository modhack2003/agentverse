export function readStorage(key: string, session = false): string | null {
  try { return (session ? sessionStorage : localStorage).getItem(key) } catch { return null }
}
export function writeStorage(key: string, value: string, session = false) {
  try { (session ? sessionStorage : localStorage).setItem(key, value) } catch { /* Current-session state still works. */ }
}
export function removeStorage(key: string, session = false) {
  try { (session ? sessionStorage : localStorage).removeItem(key) } catch { /* No saved session to clear. */ }
}
