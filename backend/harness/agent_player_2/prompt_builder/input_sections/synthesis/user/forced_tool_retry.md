# Forced Tool Call Retry

Your current synthesis input remains in effect. Your active reasoning from the previous pass is provided below for context:

{{ fence }}text
{{ previous_output }}
{{ fence }}

{% if correction %}
Required protocol correction: {{ correction }}

{% endif %}
Do not continue reasoning. Return a complete replacement for Working Notes,
preserving the current findings and progress through Vulnerabilities,
Opportunities, and Synthesis. Carry corrections already identified in the
previous reasoning into the notes, dependent conclusions, and `annotate_branch`
calls for affected annotations. Leave an unfinished assessment as `Not assessed`
and the top-line candidate unset until both assessments meet the completion
standards in Analysis Workflow. Keep any conclusion that depends on an unplayed
or rejected move unresolved. Then emit at least one available tool in the
required JSON array:

<running_thoughts>
Vulnerabilities: Current findings or Not assessed.

Opportunities: Current findings or Not assessed.

Synthesis: Current comparison. Top-line candidate: the leading move and why,
or None yet.
</running_thoughts>

<agent_tool_calls>
[
  {"tool":"tool_name","arguments":{}}
]
</agent_tool_calls>

Output nothing after the closing tag.
