"use client";

import { useEffect, useRef, type ReactNode } from "react";

export function AdvisorDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const dialog = ref.current;
    dialog?.showModal();
    return () => { dialog?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} aria-label={title} onCancel={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }} className="advisor-dialog">
    <div className="flex items-center justify-between gap-4 border-b border-slate-200 p-5">
      <h2 className="text-lg font-semibold">{title}</h2>
      <button autoFocus className="rounded-lg border border-slate-200 px-3 py-2 text-sm" onClick={onClose} type="button" aria-label={`关闭${title}`}>关闭</button>
    </div>
    <div className="min-h-0 overflow-y-auto p-5">{children}</div>
  </dialog>;
}
