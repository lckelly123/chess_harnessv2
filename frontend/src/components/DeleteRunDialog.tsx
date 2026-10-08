import { useEffect, useId, useRef, useState, type RefObject } from "react";

export type DeleteScope = "run" | "queue";

interface DeleteRunDialogProps {
  recordId: string;
  label: string;
  kind?: "match" | "run";
  queue?: { id: string; name?: string | null };
  fallbackFocus: RefObject<HTMLElement | null>;
  onDelete(scope: DeleteScope): Promise<void>;
  onCancel(): void;
}

export function DeleteRunDialog({ recordId, label, kind = "run", queue, fallbackFocus, onDelete, onCancel }: DeleteRunDialogProps) {
  const id = useId();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [pending, setPending] = useState<DeleteScope | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const trigger = document.activeElement;
    const dialog = dialogRef.current;
    const fallback = fallbackFocus.current;
    dialog?.showModal();
    return () => {
      dialog?.close();
      window.requestAnimationFrame(() => {
        if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus({ preventScroll: true });
        else fallback?.focus({ preventScroll: true });
      });
    };
  }, [fallbackFocus]);

  const remove = async (scope: DeleteScope) => {
    if (pending) return;
    setPending(scope);
    setError(null);
    try {
      await onDelete(scope);
      onCancel();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete this record. Try again.");
      setPending(null);
    }
  };

  return (
    <dialog className="delete-run-dialog" ref={dialogRef} aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onCancel={(event) => { event.preventDefault(); if (!pending) onCancel(); }}>
      <h2 id={`${id}-title`}>Delete {kind}?</h2>
      <p className="delete-run-dialog__record"><strong>{label}</strong><code>{recordId}</code></p>
      <div id={`${id}-description`}>
        {queue ? <><p>This run belongs to <strong>{queue.name || `Queue ${queue.id}`}</strong>. Delete just this run or the entire queue?</p><p>Deleting the queue removes all of its runs, including those outside the current filters.</p></> : null}
        <p>{kind === "match" ? "The match replay and recorded events will be permanently deleted." : "Saved results and model passes will be permanently deleted. The source positions will stay in your library."}</p>
      </div>
      {error ? <p className="delete-run-dialog__error" role="alert">{error}</p> : null}
      {pending ? <p role="status">{pending === "queue" ? "Deleting queue…" : `Deleting ${kind}…`}</p> : null}
      <div className="delete-run-dialog__actions">
        <button className="button button--secondary" type="button" disabled={!!pending} onClick={onCancel}>Cancel</button>
        <button className="button button--danger" type="button" disabled={!!pending} onClick={() => void remove("run")}>{kind === "match" ? "Delete match" : "Delete this run"}</button>
        {queue ? <button className="button button--danger" type="button" disabled={!!pending} onClick={() => void remove("queue")}>Delete entire queue</button> : null}
      </div>
    </dialog>
  );
}
