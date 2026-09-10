"use client";

import { FormEvent, useMemo, useState } from "react";

type TraceItem = {
  type: string;
  text?: string;
  name?: string;
  capability?: string;
  args?: Record<string, unknown>;
  result?: string | null;
  is_error?: boolean;
  order?: number;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  trace?: TraceItem[];
};

const TOOL_GROUPS = [
  "Directory",
  "Weather",
  "Flights",
  "Hotels",
  "Activities",
  "Cost",
] as const;

const DEFAULT_TOOLS = [
  { id: "get_airport_code", group: "Directory", label: "get_airport_code" },
  { id: "list_districts", group: "Directory", label: "list_districts" },
  { id: "get_district", group: "Directory", label: "get_district" },
  { id: "get_currency", group: "Directory", label: "get_currency" },
  { id: "get_weather", group: "Weather", label: "get_weather" },
  { id: "get_climate_average", group: "Weather", label: "get_climate_average" },
  { id: "get_flight", group: "Flights", label: "get_flight" },
  { id: "list_hotels", group: "Hotels", label: "list_hotels" },
  { id: "list_activities", group: "Activities", label: "list_activities" },
  { id: "get_trip_cost", group: "Cost", label: "get_trip_cost" },
  { id: "get_exchange_rate", group: "Cost", label: "get_exchange_rate" },
  { id: "calculator", group: "Cost", label: "calculator" },
] as const;

const initialEnabled = {
  get_airport_code: true,
  list_districts: true,
  get_district: true,
  get_currency: true,
  get_weather: true,
  get_climate_average: false,
  get_flight: true,
  list_hotels: true,
  list_activities: true,
  get_trip_cost: false,
  get_exchange_rate: true,
  calculator: true,
} as const;

const COBA_MARK = (
  <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M7 18.5L12 3L17 18.5H7Z" stroke="#F4C447" strokeWidth="1.65" strokeLinejoin="round" />
    <path d="M10 13.5H14" stroke="#F4C447" strokeWidth="1.65" strokeLinecap="round" />
    <path d="M8.5 9.5L12 6.2L15.5 9.5" stroke="#F4C447" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

export default function Home() {
  const [enabled, setEnabled] = useState<Record<string, boolean>>(initialEnabled);
  const [question, setQuestion] = useState("Plan a 3-day trip to Paris with food and art");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const toolGroups = useMemo(() => {
    return TOOL_GROUPS.map((group) => ({
      group,
      items: DEFAULT_TOOLS.filter((t) => t.group === group),
    }));
  }, []);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || loading) return;

    const nextUserMessage: Message = { role: "user", content: trimmed };
    setMessages((prev) => [...prev, nextUserMessage]);
    setLoading(true);
    setError("");

    try {
      const enabledIds = Object.entries(enabled)
        .filter(([, value]) => value)
        .map(([key]) => key);

      const response = await fetch("http://localhost:8000/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: trimmed,
          enabled_tools: enabledIds,
        }),
      });

      if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
      }

      const data = await response.json();
      const assistantMessage: Message = {
        role: "assistant",
        content: data.answer || "No answer returned.",
        trace: Array.isArray(data.trace) ? data.trace : [],
      };
      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
      setQuestion("");
    }
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="app-header-inner">
          <div className="header-mark">{COBA_MARK}</div>
          <h1>Travel Agent</h1>
        </div>
      </header>

      <div className="workspace">
        <section className="panel chat-panel">
          <div className="chat-scroll">
            {messages.length === 0 ? (
              <div className="empty-state">
                Type a travel question below. The agent will use whatever tools are enabled on the right.
              </div>
            ) : null}

            {messages.map((msg, index) => (
              <div key={`${msg.role}-${index}`} className={`message ${msg.role}`}>
                <div className="bubble">{msg.content}</div>

                {msg.role === "assistant" && msg.trace && msg.trace.length > 0 ? (
                  <div className="trace-box">
                    <h4>Trace</h4>
                    {msg.trace.map((item, traceIndex) => {
                      if (item.type === "reasoning") {
                        return (
                          <div key={`${item.type}-${traceIndex}`} className="trace-item">
                            <strong>Reasoning</strong>
                            {item.text}
                          </div>
                        );
                      }

                      return (
                        <div key={`${item.type}-${traceIndex}`} className="trace-item">
                          <strong>
                            Tool: {item.name} {item.order ? `#${item.order}` : ""}
                          </strong>
                          {item.capability ? `Capability: ${item.capability}` : null}
                          {item.args && Object.keys(item.args).length > 0 ? (
                            <div style={{ marginTop: 4 }}>
                              Args: {JSON.stringify(item.args)}
                            </div>
                          ) : null}
                          {item.result ? (
                            <div style={{ marginTop: 4 }}>
                              Result: {String(item.result)}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            ))}

            {loading ? (
              <div className="message assistant">
                <div className="bubble">The agent is working…</div>
              </div>
            ) : null}
          </div>

          <form onSubmit={handleSubmit} className="compose">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ask your own travel question…"
            />
            <button className="primary-button" type="submit" disabled={loading || !question.trim()}>
              {loading ? "Thinking..." : "Ask"}
            </button>
          </form>

          {error ? <div className="error-banner">{error}</div> : null}
        </section>

        <aside className="panel tool-panel">
          {toolGroups.map(({ group, items }) => (
            <div key={group} className="tool-group">
              <div className="group-label">{group}</div>
              <div className="tool-list">
                {items.map((tool) => (
                  <label key={tool.id} className="tool-card">
                    <input
                      type="checkbox"
                      checked={!!enabled[tool.id]}
                      onChange={() =>
                        setEnabled((prev) => ({
                          ...prev,
                          [tool.id]: !prev[tool.id],
                        }))
                      }
                    />
                    <div className="tool-card-content">
                      <div className="tool-name">{tool.label}</div>
                      <div className="tool-description">
                        {tool.id === "get_airport_code" && "Convert a city to the correct airport code."}
                        {tool.id === "list_districts" && "Find the districts that belong to a city."}
                        {tool.id === "get_district" && "Map a district back to its city and transfer time."}
                        {tool.id === "get_currency" && "Check which currency local prices use."}
                        {tool.id === "get_weather" && "Look up the current temperature for a city."}
                        {tool.id === "get_climate_average" && "Historical climate average, not current conditions."}
                        {tool.id === "get_flight" && "Get round-trip airfare and travel duration."}
                        {tool.id === "list_hotels" && "List hotels and nightly prices in a district."}
                        {tool.id === "list_activities" && "List activities and prices in a district."}
                        {tool.id === "get_trip_cost" && "Convenience bundle that can mislead by bundling assumptions."}
                        {tool.id === "get_exchange_rate" && "Convert local prices into EUR for comparison."}
                        {tool.id === "calculator" && "Mandatory arithmetic tool for all numeric calculations."}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </aside>
      </div>
    </main>
  );
}
