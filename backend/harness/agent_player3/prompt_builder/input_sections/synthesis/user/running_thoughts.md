# Running Thoughts

## Working Notes

These are the last accepted notes. Replace them through the next native
`agent_step.running_thoughts` argument, together with the next tool batch.

{% if working_notes %}
{{ working_notes }}
{% else %}
No working notes yet. Begin with the Vulnerabilities assessment.

Vulnerabilities: Not assessed.

Opportunities: Not assessed.

Synthesis: Pending both assessments. Top-line candidate: None yet.
{% endif %}

{% if latest_results %}
## Latest Tool Batch

{% for result in latest_results -%}
- `{{ result.tool }}`: {% if result.ok %}Accepted{% else %}Rejected{% endif %}. {{ result.result_summary }}
{% endfor %}
{% endif %}
