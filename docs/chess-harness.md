# chess_harness response retries

The main `chess_harness` (`agent-player-2-langgraph-v1`) retries rejected model
responses with the exact captured system/developer instructions and dynamic
input. Reasoning effort and output allowance stay at their normal values. Failed
output, notes, and correction messages are never appended to the next input.
This applies to its LM Studio, Unsloth, OpenAI, and Codex training paths.

`max_response_retries` defaults to **10 additional attempts per input**: the
initial attempt plus up to ten retries. An accepted tool batch resets the retry
counter and builds the next input from the committed state. The overall
100-model-call limit, tool budget, queue timeout, and cancellation still apply.
Malformed output, incomplete responses, invalid arguments, and rejected chess
actions use this retry policy. Provider/transport failures propagate immediately.

Every tool's arguments and chess-state requirements are validated before any tool
in that response executes. A rejected batch executes no tools and leaves the
canonical board, scratchboard, tested lines, annotations, working notes, latest
results, and history unchanged. An accepted batch commits its results and notes
together. Rejected proposals do not consume the executed-tool budget.

Each attempt remains a separate saved model pass with its exact input/output and
failure reason. Proposed tools in a rejected response remain unexecuted in the
trace. Rejections are also logged by the backend, including exhaustion of the
retry allowance. Legacy and alternate harness retry policies are unchanged.
