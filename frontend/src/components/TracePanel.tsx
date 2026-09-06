import { Check, CircleDot, X } from "lucide-react";
import type { TraceEvent } from "../api/contracts";

interface TracePanelProps {
  events: TraceEvent[];
  activePly: number;
  onSelectPly(ply: number): void;
}

function StatusIcon({ status }: { status: TraceEvent["status"] }) {
  if (status === "failed") return <X size={13} aria-hidden="true" />;
  if (status === "active") return <CircleDot size={13} aria-hidden="true" />;
  return <Check size={13} aria-hidden="true" />;
}

export function TracePanel({ events, activePly, onSelectPly }: TracePanelProps) {
  return (
    <section className="trace-panel">
      <header className="section-heading">
        <div>
          <h2>Decision trace</h2>
          <p>Public match events · detailed graph traces in LangSmith</p>
        </div>
        <span>{events.length} events</span>
      </header>
      <div className="trace-list" role="list" aria-label="Decision trace events">
        {events.length === 0 ? (
          <div className="empty-state">No trace event exists at this position.</div>
        ) : (
          events.map((event) => (
            <button
              className={`trace-event ${event.ply === activePly ? "trace-event--active" : ""}`}
              type="button"
              key={event.id}
              onClick={() => onSelectPly(event.ply)}
            >
              <span className={`trace-marker trace-marker--${event.status}`}><StatusIcon status={event.status} /></span>
              <span className="trace-copy">
                <span className="trace-meta">
                  <span>PLY {event.ply}</span>
                  <span>{event.player}</span>
                  <span>{event.phase}</span>
                </span>
                <strong>{event.summary}</strong>
                <span>{event.detail}</span>
              </span>
            </button>
          ))
        )}
      </div>
    </section>
  );
}
