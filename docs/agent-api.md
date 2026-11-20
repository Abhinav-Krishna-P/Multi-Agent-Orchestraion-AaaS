# Agent API

Call a live agent from your own program. Each call runs the agent once with the message you send and returns its reply.

## Create a key

Open the API page, pick the agent, and choose **Create key**. The full key (it starts with `cap_`) is shown once. You won't see it again: keep it secret, like a password. Each agent can have up to 10 active keys; revoke a key on the same page to stop it working at once.

Keep the key on your server. Never put it in browser or mobile-app code. The samples below read it from the `AGENT_API_KEY` environment variable.

## The call

`POST {base URL}/v1/run`

| Header | Value |
| --- | --- |
| `Authorization` | `Bearer <your key>` |
| `Content-Type` | `application/json` |

Body: `{"message": "..."}`. The message is required and may be 1 to 8,000 characters.

## The response

`200`:

```json
{
  "id": "...",
  "agent_id": "...",
  "reply": "...",
  "sources": [],
  "tools_used": [{"name": "...", "ok": true, "result": {"kind": "..."}}],
  "duration_ms": 1234
}
```

`sources` lists the knowledge-base pages the answer used; an item is `{"document_name": "...", "page": 3, "excerpt": "..."}` (`page` is null for documents without pages). `tools_used` lists the tools the agent called; `result` is an object describing what the tool did, or null when it has nothing to show. An item has `overridden`, a list of the argument names whose values were removed, when a destination was not named in your message (see Recipients).

## Errors

Every error has the body `{"detail": {"code": "...", "message": "..."}}`.

| Status | Code | Meaning |
| --- | --- | --- |
| 401 | `invalid_api_key` | The key is missing, unknown or revoked. |
| 409 | `agent_not_live` | The agent is not live. |
| 409 | `no_llm_key` | The agent has no model key to run with. |
| 422 | `invalid_request` | The message is missing, empty or longer than 8,000 characters. |
| 429 | `rate_limited` | Too many calls this minute. The `Retry-After` header says how many seconds to wait. |
| 502 | `agent_failed` | The run failed or took too long. |

## Limits

- Message: 8,000 characters.
- Calls per minute, per agent: 60 by default; set 1 to 600 on the API page. Without Redis the count is per server process.
- A run stops after 180 seconds (502 `agent_failed`).

## Actions

Calls through the API run the agent's actions (sending email, posting to a channel and so on) automatically, without asking. The **Actions through the API** setting on the API page is on by default; turn it off to let API calls answer without using actions.

## Recipients

An email address, channel or other destination is used only if it appears in the caller's own message. Any other destination the model chooses is removed, and the call shows it as `overridden` in `tools_used`.

## Packages

Both are in this repository and not yet published; the name `agentplatform` may change before they are.

- Python (3.9+, standard library only): `pip install ./sdk/python`, then `from agentplatform import Agent`. `Agent(api_key=..., base_url=...)`, `agent.run("...")` returns a dict.
- TypeScript and JavaScript (built-in `fetch`): `npm install ./sdk/typescript`, then `import { Agent, AgentError } from 'agentplatform'`. `new Agent({ apiKey, baseUrl })`, `await agent.run('...')`.

A failed call raises `AgentError` with `status`, `code`, `message` and the retry delay (`retry_after` in Python, `retryAfter` in TypeScript). The packages do not retry.

## Samples

These use `http://localhost:8000` as the base URL; on the API page they use your own.

### Python

```python
# With the package: pip install ./sdk/python
import os
from agentplatform import Agent, AgentError

agent = Agent(api_key=os.environ["AGENT_API_KEY"], base_url="http://localhost:8000")
try:
    result = agent.run("What can you do?")
    print(result["reply"])
except AgentError as e:
    print(e.code, e.message)

# The same call over plain HTTP: pip install requests
import requests

response = requests.post(
    "http://localhost:8000/v1/run",
    headers={"Authorization": "Bearer " + os.environ["AGENT_API_KEY"]},
    json={"message": "What can you do?"},
    timeout=200,
)
if response.ok:
    print(response.json()["reply"])
else:
    detail = response.json()["detail"]
    print(detail["code"], detail["message"])
```

### JavaScript

```js
// With the package (an ES module, e.g. run.mjs): npm install ./sdk/typescript
import { Agent, AgentError } from 'agentplatform'

const agent = new Agent({ apiKey: process.env.AGENT_API_KEY, baseUrl: 'http://localhost:8000' })
try {
  const result = await agent.run('What can you do?')
  console.log(result.reply)
} catch (err) {
  if (!(err instanceof AgentError)) throw err
  console.log(err.code, err.message)
}

// The same call over plain HTTP
const response = await fetch('http://localhost:8000/v1/run', {
  method: 'POST',
  headers: {
    Authorization: 'Bearer ' + process.env.AGENT_API_KEY,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ message: 'What can you do?' }),
})
const data = await response.json()
if (response.ok) {
  console.log(data.reply)
} else {
  console.log(data.detail.code, data.detail.message)
}
```

### TypeScript

```ts
// With the package: npm install ./sdk/typescript
import { Agent, AgentError } from 'agentplatform'

const agent = new Agent({ apiKey: process.env.AGENT_API_KEY!, baseUrl: 'http://localhost:8000' })
try {
  const result = await agent.run('What can you do?')
  console.log(result.reply)
} catch (err) {
  if (!(err instanceof AgentError)) throw err
  console.log(err.code, err.message)
}

// The same call over plain HTTP
const response = await fetch('http://localhost:8000/v1/run', {
  method: 'POST',
  headers: {
    Authorization: 'Bearer ' + process.env.AGENT_API_KEY,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ message: 'What can you do?' }),
})
const data = (await response.json()) as { reply?: string; detail?: { code: string; message: string } }
if (response.ok) {
  console.log(data.reply)
} else {
  console.log(data.detail?.code, data.detail?.message)
}
```

### Node.js

```js
// A CommonJS script (run.js). The package is an ES module, so it is loaded with import().
async function main() {
  const { Agent, AgentError } = await import('agentplatform')

  const agent = new Agent({ apiKey: process.env.AGENT_API_KEY, baseUrl: 'http://localhost:8000' })
  try {
    const result = await agent.run('What can you do?')
    console.log(result.reply)
  } catch (err) {
    if (!(err instanceof AgentError)) throw err
    console.log(err.code, err.message)
  }

  // The same call over plain HTTP (Node 18 or newer)
  const response = await fetch('http://localhost:8000/v1/run', {
    method: 'POST',
    headers: {
      Authorization: 'Bearer ' + process.env.AGENT_API_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message: 'What can you do?' }),
  })
  const data = await response.json()
  if (response.ok) {
    console.log(data.reply)
  } else {
    console.log(data.detail.code, data.detail.message)
  }
}

main()
```

### PHP

```php
<?php
// Needs the cURL extension.
$ch = curl_init('http://localhost:8000/v1/run');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_HTTPHEADER => [
        'Authorization: Bearer ' . getenv('AGENT_API_KEY'),
        'Content-Type: application/json',
    ],
    CURLOPT_POSTFIELDS => json_encode(['message' => 'What can you do?']),
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT => 200,
]);
$body = curl_exec($ch);
if ($body === false) {
    fwrite(STDERR, curl_error($ch) . "\n");
    exit(1);
}
$status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

$data = json_decode($body, true);
if ($status >= 200 && $status < 300) {
    echo $data['reply'], "\n";
} else {
    echo $data['detail']['code'], ' ', $data['detail']['message'], "\n";
}
```

### Java

```java
// Java 11 or newer. Java has no JSON parser built in, so this prints the raw text of a field
// (escape sequences left as they are); use a JSON library such as Jackson in real code.
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class Main {
    static String field(String json, String name) {
        Matcher m = Pattern.compile("\"" + name + "\"\\s*:\\s*\"((?:[^\"\\\\]|\\\\.)*)\"").matcher(json);
        return m.find() ? m.group(1) : "";
    }

    public static void main(String[] args) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://localhost:8000/v1/run"))
            .timeout(Duration.ofSeconds(200))
            .header("Authorization", "Bearer " + System.getenv("AGENT_API_KEY"))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString("{\"message\": \"What can you do?\"}"))
            .build();
        HttpResponse<String> response = HttpClient.newHttpClient()
            .send(request, HttpResponse.BodyHandlers.ofString());

        String body = response.body();
        if (response.statusCode() >= 200 && response.statusCode() < 300) {
            System.out.println(field(body, "reply"));
        } else {
            System.out.println(field(body, "code") + " " + field(body, "message"));
        }
    }
}
```

### Go

```go
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"
)

type result struct {
	Reply  string `json:"reply"`
	Detail struct {
		Code    string `json:"code"`
		Message string `json:"message"`
	} `json:"detail"`
}

func main() {
	body, _ := json.Marshal(map[string]string{"message": "What can you do?"})
	req, err := http.NewRequest("POST", "http://localhost:8000/v1/run", bytes.NewReader(body))
	if err != nil {
		panic(err)
	}
	req.Header.Set("Authorization", "Bearer "+os.Getenv("AGENT_API_KEY"))
	req.Header.Set("Content-Type", "application/json")

	client := &http.Client{Timeout: 200 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()

	var data result
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		panic(err)
	}
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		fmt.Println(data.Reply)
	} else {
		fmt.Println(data.Detail.Code, data.Detail.Message)
	}
}
```

### C#

```csharp
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(200) };
using var request = new HttpRequestMessage(HttpMethod.Post, "http://localhost:8000/v1/run");
request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", Environment.GetEnvironmentVariable("AGENT_API_KEY"));
request.Content = new StringContent(
    JsonSerializer.Serialize(new { message = "What can you do?" }),
    Encoding.UTF8,
    "application/json");

using var response = await client.SendAsync(request);
using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
if (response.IsSuccessStatusCode)
{
    Console.WriteLine(json.RootElement.GetProperty("reply").GetString());
}
else
{
    var detail = json.RootElement.GetProperty("detail");
    Console.WriteLine(detail.GetProperty("code").GetString() + " " + detail.GetProperty("message").GetString());
}
```

### cURL

```bash
curl -sS -X POST "http://localhost:8000/v1/run" \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "What can you do?"}'

# 200: {"id": "...", "reply": "...", "sources": [], "tools_used": [], "duration_ms": 1234}
# Other statuses: {"detail": {"code": "...", "message": "..."}}
```

## Call log

The API page lists recent calls: time, outcome, duration, message, reply, tools used and sources. Rejected calls (401, 422, 429) are not logged. Calls of a revoked key stay in the log.
