# agentplatform (Python)

Call one of your agents from your own code. Standard library only, Python 3.9+. Not published yet; install from the repo folder:

    pip install ./sdk/python

## Use

```python
import os
from agentplatform import Agent, AgentError

agent = Agent(api_key=os.environ["AGENT_API_KEY"], base_url="http://localhost:8000")
try:
    result = agent.run("What can you do?")
    print(result["reply"])
except AgentError as e:
    print(e.status, e.code, e.message, e.retry_after)
```

`run` returns the response as a dict (`id`, `agent_id`, `reply`, `sources`, `tools_used`, `duration_ms`). A failed call raises `AgentError` with `status`, `code`, `message` and `retry_after` (seconds from the `Retry-After` header on a 429, otherwise `None`). The package does not retry. The timeout is 200 seconds.

## Keep the key secret

Read the key from an environment variable or a secret store. Never commit it, put it in a web page, or ship it in a mobile app.
