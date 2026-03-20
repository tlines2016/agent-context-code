import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { Info } from 'lucide-react'
import { cn } from '@/lib/utils'

interface InfoPopoverProps {
  title: string
  children: ReactNode
  className?: string
  triggerMode?: 'click' | 'hover'
  panelClassName?: string
  trigger?: ReactNode
}

export default function InfoPopover({
  title,
  children,
  className,
  triggerMode = 'click',
  panelClassName,
  trigger,
}: InfoPopoverProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLSpanElement>(null)
  const panelId = useId()

  useEffect(() => {
    if (!open || triggerMode !== 'click') return

    function handlePointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false)
      }
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setOpen(false)
    }

    window.addEventListener('mousedown', handlePointerDown)
    window.addEventListener('keydown', handleEscape)
    return () => {
      window.removeEventListener('mousedown', handlePointerDown)
      window.removeEventListener('keydown', handleEscape)
    }
  }, [open, triggerMode])

  return (
    <span
      ref={rootRef}
      className={cn('relative inline-flex items-center', className)}
      onMouseEnter={triggerMode === 'hover' ? () => setOpen(true) : undefined}
      onMouseLeave={triggerMode === 'hover' ? () => setOpen(false) : undefined}
    >
      {trigger ? (
        <button
          type="button"
          className="inline-flex items-center justify-center rounded text-slate-500 transition-colors hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          aria-label={`More info about ${title}`}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          onClick={() => setOpen((v) => !v)}
          onFocus={triggerMode === 'hover' ? () => setOpen(true) : undefined}
          onBlur={triggerMode === 'hover' ? () => setOpen(false) : undefined}
        >
          {trigger}
        </button>
      ) : (
        <button
          type="button"
          className="inline-flex items-center justify-center rounded-full text-slate-500 transition-colors hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500"
          aria-label={`More info about ${title}`}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          onClick={() => setOpen((v) => !v)}
          onFocus={triggerMode === 'hover' ? () => setOpen(true) : undefined}
          onBlur={triggerMode === 'hover' ? () => setOpen(false) : undefined}
        >
          <Info size={14} aria-hidden="true" />
        </button>
      )}
      {open && (
        <div
          id={panelId}
          role="dialog"
          aria-label={title}
          className={cn(
            'absolute left-0 top-full z-30 mt-2 w-80 rounded-md border border-slate-700 bg-slate-900/95 p-3 text-xs text-slate-300 shadow-xl backdrop-blur-sm',
            panelClassName,
          )}
        >
          <p className="mb-2 text-xs font-semibold text-slate-100">{title}</p>
          {children}
        </div>
      )}
    </span>
  )
}
