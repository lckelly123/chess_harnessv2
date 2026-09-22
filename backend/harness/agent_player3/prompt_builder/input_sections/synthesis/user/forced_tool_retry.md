# Native Tool Call Retry

The previous response did not produce an executable native `agent_step`.
No chess actions or Working Notes from that response were accepted. Use the
current rendered board, Tested Lines, and last accepted notes as your evidence.

{% if correction %}
Required correction: {{ correction }}

{% endif %}
Call the native `agent_step` function with a complete `running_thoughts`
replacement and a non-empty `tool_calls` array. Preserve the Vulnerabilities,
Opportunities, and Synthesis workflow; keep untested or rejected continuations
unresolved. Do not print a tool call or invent its result. Wait for the actual
function result before proceeding.
