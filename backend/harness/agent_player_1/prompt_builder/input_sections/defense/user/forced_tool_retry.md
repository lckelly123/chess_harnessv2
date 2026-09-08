{% if forced_tool_retry.active %}
# Forced Tool Call Retry

The original phase input is unchanged. Your active reasoning from the previous pass is provided below for context:

{{ forced_tool_retry.fence }}text
{{ forced_tool_retry.previous_output }}
{{ forced_tool_retry.fence }}

Do not continue reasoning. Call exactly one available tool now using the required tag:

<agent_tool_call>
{"tool":"tool_name","arguments":{}}
</agent_tool_call>

Output nothing after the closing tag.
{% endif %}
