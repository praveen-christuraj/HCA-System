import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { Alert } from '../common/Ui'
import { logUiAction } from '../../utils/actionLogger'

const Feedback = createContext(null)

export function EntryDialog({ title, children, footer, onCancel }) {
  const ref = useRef(null)
  useEffect(() => {
    const previous = document.activeElement
    const node = ref.current
    node?.querySelector('input, select, textarea, button')?.focus()
    const trap = event => {
      if (event.key === 'Escape') { event.preventDefault(); return }
      if (event.key !== 'Tab') return
      const els = [...node.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]')]
      if (!els.length) return
      if (event.shiftKey && document.activeElement === els[0]) { event.preventDefault(); els.at(-1).focus() }
      else if (!event.shiftKey && document.activeElement === els.at(-1)) { event.preventDefault(); els[0].focus() }
    }
    node?.addEventListener('keydown', trap)
    return () => { node?.removeEventListener('keydown', trap); previous?.focus?.() }
  }, [])
  return <div className="dialog-backdrop"><section ref={ref} className="dialog dialog-lg" role="dialog" aria-modal="true" aria-labelledby="entry-dialog-title">
    <header className="dialog-head"><h2 id="entry-dialog-title" className="dialog-title">{title}</h2></header>
    <div className="dialog-body">{children}</div>
    <footer className="dialog-foot">{footer || <button className="btn btn-secondary" onClick={onCancel}>Cancel</button>}</footer>
  </section></div>
}

export default function EntryFeedback({ children }) {
  const [message, setMessage] = useState(null)
  const [confirmation, setConfirmation] = useState(null)
  const resolve = useRef(null)
  const confirm = useCallback(options => new Promise(done => {
    resolve.current = done; setConfirmation(options)
  }), [])
  useEffect(() => () => resolve.current?.(false), [])
  const toast = useMemo(() => Object.fromEntries(['warning', 'error', 'success'].map(tone => [tone, (text, opts) => setMessage({ tone, text, title: opts?.title || 'Operation Entry' })])), [])
  const close = answer => {
    logUiAction('Operation Entry', answer ? 'Confirm Action' : 'Cancel Action', { action: confirmation?.title })
    resolve.current?.(answer); resolve.current = null; setConfirmation(null)
  }
  return <Feedback.Provider value={{ confirm, toast }}>{children}
    {confirmation && <EntryDialog title={confirmation.title || 'Confirm action'} footer={<>
      <button className="btn btn-secondary" onClick={() => close(false)}>Cancel</button>
      <button className="btn btn-primary" onClick={() => close(true)}>{confirmation.confirmLabel || 'Confirm'}</button>
    </>}><p>{confirmation.message}</p></EntryDialog>}
    {message && <EntryDialog title={message.title} onCancel={() => setMessage(null)}><Alert tone={message.tone === 'error' ? 'danger' : message.tone}>{message.text}</Alert></EntryDialog>}
  </Feedback.Provider>
}
export const useConfirm = () => useContext(Feedback).confirm
export const useToast = () => useContext(Feedback).toast
