import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export default function Modal({ title, description, close, children }: { title: string; description?: string; close: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(close); closeRef.current = close
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const root = document.getElementById('root'), overflow = document.body.style.overflow
    if (root) root.inert = true
    document.body.style.overflow = 'hidden'
    const focusable = () => Array.from(ref.current?.querySelectorAll<HTMLElement>('button,input,textarea,select,a[href],[tabindex="0"]') || []).filter(element => !element.hasAttribute('disabled'))
    focusable()[0]?.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeRef.current()
      if (event.key === 'Tab') {
        const items = focusable(), first = items[0], last = items.at(-1)
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
      }
    }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); if (root) root.inert = false; document.body.style.overflow = overflow; previous?.focus() }
  }, [])
  return createPortal(<div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) close() }}>
    <div className="modal" ref={ref} role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal-heading"><div><h2 id="modal-title">{title}</h2>{description && <p>{description}</p>}</div><button className="icon-button" onClick={close} aria-label="Close dialog"><X size={20} /></button></div>
      {children}
    </div>
  </div>, document.body)
}
