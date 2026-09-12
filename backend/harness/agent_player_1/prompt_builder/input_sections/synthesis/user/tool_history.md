# Tool History

{% if entries %}
{% for entry in entries %}
## {{ loop.index }}. `{{ entry.tool }}`

Justification: {{ entry.justification }}

Input:

```json
{{ entry.arguments_json }}
```

{% if entry.status %}
Status: {{ entry.status }}

{% endif %}
{% if entry.result_summary %}
Result summary: {{ entry.result_summary }}

{% endif %}
{% endfor %}
{% else %}
No tool calls yet.
{% endif %}
