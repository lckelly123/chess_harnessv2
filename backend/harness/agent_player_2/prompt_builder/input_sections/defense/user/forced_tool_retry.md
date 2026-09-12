# Forced Tool Call Retry

Your previous phase input remains in effect. Your active reasoning from the previous pass is provided below for context:

{{ fence }}text
{{ previous_output }}
{{ fence }}

{% if correction %}
Required protocol correction: {{ correction }}

{% endif %}
Do not continue reasoning. Call exactly one available tool now using the required tag:

<agent_tool_call>
{"tool":"tool_name","arguments":{}}
</agent_tool_call>

Output nothing after the closing tag.
