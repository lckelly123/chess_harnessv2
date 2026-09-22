import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, CircleDot, ListTree, MessageSquareText, X } from "lucide-react";
import type { TraceEvent } from "../api/contracts";

interface TracePanelProps {
  events: TraceEvent[];
  activePly: number;
  onSelectPly(ply: number): void;
}

interface TraceGroup {
  ply: number;
  events: TraceEvent[];
}

const phaseLabels: Record<TraceEvent["phase"], string> = {
  observe: "Observation",
  plan: "Planning",
  act: "Move",
  verify: "Verification",
};

function StatusIcon({ status }: { status: TraceEvent["status"] }) {
  if (status === "failed") return <X size={13} aria-hidden="true" />;
  if (status === "active") return <CircleDot size={13} aria-hidden="true" />;
  return <Check size={13} aria-hidden="true" />;
}

function eventTime(timestamp: string) {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? timestamp : date.toLocaleString();
}

function EventMetadata({ event }: { event: TraceEvent }) {
  return (
    <dl className="event-metadata">
      <div><dt>Recorded</dt><dd><time dateTime={event.timestamp}>{eventTime(event.timestamp)}</time></dd></div>
      <div><dt>Position</dt><dd>Ply {event.ply} · {event.player}</dd></div>
      <div><dt>Phase</dt><dd>{event.phase}</dd></div>
      <div><dt>Status</dt><dd>{event.status}</dd></div>
      <div><dt>Event ID</dt><dd className="event-id">{event.id}</dd></div>
    </dl>
  );
}

function EventDetails({ event }: { event: TraceEvent }) {
  return (
    <details className="event-details">
      <summary>
        <span>{phaseLabels[event.phase]}</span>
        <strong>{event.summary}</strong>
        <ChevronDown size={14} aria-hidden="true" />
      </summary>
      <div className="event-details-body">
        <p>{event.detail || "No additional detail was recorded for this event."}</p>
        <EventMetadata event={event} />
      </div>
    </details>
  );
}

export function TracePanel({ events, activePly, onSelectPly }: TracePanelProps) {
  const [filter, setFilter] = useState<"moves" | "all">("moves");
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const list = listRef.current;
    const selected = list?.querySelector<HTMLElement>(`[data-ply="${activePly}"]`);
    if (!list || !selected) return;

    const listBounds = list.getBoundingClientRect();
    const selectedBounds = selected.getBoundingClientRect();
    // Keep the inspected move in view without moving the surrounding page.
    // Polling updates deliberately do not retrigger this effect, so browsing
    // earlier events does not fight the reader's own scroll position.
    if (selectedBounds.top < listBounds.top || selectedBounds.height > list.clientHeight) {
      list.scrollTop += selectedBounds.top - listBounds.top;
    } else if (selectedBounds.bottom > listBounds.bottom) {
      list.scrollTop += selectedBounds.bottom - listBounds.bottom;
    }
  }, [activePly, filter]);

  const grouped = new Map<number, TraceEvent[]>();
  // The API returns chronological events. Group by board position without
  // changing the order of events within a turn.
  for (const event of events) {
    const group = grouped.get(event.ply) ?? [];
    group.push(event);
    grouped.set(event.ply, group);
  }
  const groups: TraceGroup[] = [...grouped].sort(([a], [b]) => a - b)
    .map(([ply, groupEvents]) => ({ ply, events: groupEvents }));
  const selectedEvents = grouped.get(activePly) ?? [];
  const selectedMove = selectedEvents.filter((event) => event.phase === "act" && event.status === "complete").at(-1)
    ?? selectedEvents.filter((event) => event.phase === "act").at(-1);
  const selectedEvent = selectedMove ?? selectedEvents.at(-1);
  const relatedEvents = selectedEvents.filter((event) => event.id !== selectedEvent?.id);
  const moveCount = events.filter((event) => event.phase === "act").length;
  const timelineGroups = groups.map((group) => ({
    ...group,
    events: filter === "moves" ? group.events.filter((event) => event.phase === "act") : group.events,
  })).filter((group) => group.events.length > 0);

  return (
    <aside className="trace-panel" aria-label="Move analysis and decision trace">
      <section className="move-inspector" aria-labelledby="move-analysis-heading">
        <header className="section-heading">
          <h2 id="move-analysis-heading"><MessageSquareText size={18} aria-hidden="true" /> Move analysis</h2>
          <span className="inspector-position">{activePly === 0 ? "Initial position" : `Ply ${activePly}`}</span>
        </header>
        {selectedEvent ? (
          <div className="inspector-content" key={selectedEvent.id}>
            <div className="inspector-context">
              <span className={`player-color player-color--${selectedEvent.player}`} aria-hidden="true" />
              <span>{selectedEvent.player === "white" ? "White" : "Black"}</span>
              <span className={`inspector-status inspector-status--${selectedEvent.status}`}>
                <StatusIcon status={selectedEvent.status} />
                {selectedEvent.status === "active" ? "In progress" : selectedEvent.status === "failed" ? "Failed" : "Complete"}
              </span>
            </div>
            <h3 className="inspector-summary">{selectedEvent.summary}</h3>
            <p className="inspector-explanation">
              {selectedEvent.detail || "No explanation was recorded for this event."}
            </p>
            <details className="inspector-metadata">
              <summary>Event details <ChevronDown size={14} aria-hidden="true" /></summary>
              <EventMetadata event={selectedEvent} />
            </details>
            {relatedEvents.length > 0 ? (
              <details className="inspector-events">
                <summary>
                  <span>Other events at this ply <span className="event-count">{relatedEvents.length}</span></span>
                  <ChevronDown size={14} aria-hidden="true" />
                </summary>
                <ul>
                  {relatedEvents.map((event) => <li key={event.id}><EventDetails event={event} /></li>)}
                </ul>
              </details>
            ) : null}
          </div>
        ) : (
          <div className="trace-empty inspector-empty">
            <MessageSquareText size={24} aria-hidden="true" />
            <h3>{activePly === 0 ? "The starting position" : "No analysis at this position"}</h3>
            <p>{activePly === 0
              ? "Select a move on the replay timeline to read the harness’s explanation."
              : "No public event was recorded for this ply. Select another move to inspect its explanation."}</p>
          </div>
        )}
      </section>

      <section className="trace-timeline" aria-labelledby="decision-trace-heading">
        <header className="section-heading">
          <div>
            <h2 id="decision-trace-heading"><ListTree size={17} aria-hidden="true" /> Decision trace</h2>
            <p>Public events · graph traces in LangSmith</p>
          </div>
          <span>{events.length} events</span>
        </header>
        <div className="trace-filter" role="group" aria-label="Filter decision trace">
          <button type="button" aria-pressed={filter === "moves"} onClick={() => setFilter("moves")}>
            Moves <span>{moveCount}</span>
          </button>
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
            All events <span>{events.length}</span>
          </button>
        </div>
        {timelineGroups.length === 0 ? (
          <div className="trace-empty">
            <ListTree size={24} aria-hidden="true" />
            <h3>{events.length === 0 ? "No events yet" : "No moves recorded yet"}</h3>
            <p>{events.length === 0
              ? "Public decisions will appear here as the match progresses."
              : "Switch to All events to inspect planning and match updates."}</p>
          </div>
        ) : (
          <ol className="trace-list" ref={listRef} aria-label={filter === "moves" ? "Recorded moves" : "Decision trace events"}>
            {timelineGroups.map((group) => (
              <li className={`trace-group ${group.ply === activePly ? "trace-group--active" : ""}`} data-ply={group.ply} key={group.ply}>
                <div className="trace-group-heading">
                  <span>{group.ply === 0 ? "Initial position" : `Ply ${group.ply}`}</span>
                  {group.ply === activePly ? <span>Selected</span> : null}
                </div>
                <ol className="trace-group-events">
                  {group.events.map((event) => (
                    <li className="trace-item" key={event.id}>
                      <button
                        className={`trace-event ${event.ply === activePly ? "trace-event--active" : ""}`}
                        type="button"
                        aria-current={event.ply === activePly ? "step" : undefined}
                        aria-label={`Inspect ply ${event.ply}: ${event.summary}. ${event.status}.`}
                        onClick={() => onSelectPly(event.ply)}
                      >
                        <span className={`trace-marker trace-marker--${event.status}`}><StatusIcon status={event.status} /></span>
                        <span className="trace-copy">
                          <span className="trace-meta"><span>{event.player}</span><span>{phaseLabels[event.phase]}</span><span>{event.status}</span></span>
                          <strong>{event.summary}</strong>
                        </span>
                      </button>
                      <details className="trace-row-details">
                        <summary>Full event <ChevronDown size={13} aria-hidden="true" /></summary>
                        <div className="event-details-body">
                          <p>{event.detail || "No additional detail was recorded for this event."}</p>
                          <EventMetadata event={event} />
                        </div>
                      </details>
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ol>
        )}
      </section>
    </aside>
  );
}
