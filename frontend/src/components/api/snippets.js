// Code samples for the API page and docs/agent-api.md (keep docs/agent-api.md in sync by hand).
// Every sample reads AGENT_API_KEY from the environment; String.raw keeps the backslashes.
const MESSAGE = 'What can you do?'
const TICK = '`' // Go struct tags need a backtick, which a template literal can't hold

export function snippets(baseUrl) {
  const url = `${baseUrl}/v1/run`
  return [
    {
      id: 'python',
      label: 'Python',
      code: String.raw`# With the package: pip install ./sdk/python
import os
from agentplatform import Agent, AgentError

agent = Agent(api_key=os.environ["AGENT_API_KEY"], base_url="${baseUrl}")
try:
    result = agent.run("${MESSAGE}")
    print(result["reply"])
except AgentError as e:
    print(e.code, e.message)

# The same call over plain HTTP: pip install requests
import requests

response = requests.post(
    "${url}",
    headers={"Authorization": "Bearer " + os.environ["AGENT_API_KEY"]},
    json={"message": "${MESSAGE}"},
    timeout=200,
)
if response.ok:
    print(response.json()["reply"])
else:
    detail = response.json()["detail"]
    print(detail["code"], detail["message"])
`,
    },
    {
      id: 'javascript',
      label: 'JavaScript',
      code: String.raw`// With the package (an ES module, e.g. run.mjs): npm install ./sdk/typescript
import { Agent, AgentError } from 'agentplatform'

const agent = new Agent({ apiKey: process.env.AGENT_API_KEY, baseUrl: '${baseUrl}' })
try {
  const result = await agent.run('${MESSAGE}')
  console.log(result.reply)
} catch (err) {
  if (!(err instanceof AgentError)) throw err
  console.log(err.code, err.message)
}

// The same call over plain HTTP
const response = await fetch('${url}', {
  method: 'POST',
  headers: {
    Authorization: 'Bearer ' + process.env.AGENT_API_KEY,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ message: '${MESSAGE}' }),
})
const data = await response.json()
if (response.ok) {
  console.log(data.reply)
} else {
  console.log(data.detail.code, data.detail.message)
}
`,
    },
    {
      id: 'typescript',
      label: 'TypeScript',
      code: String.raw`// With the package: npm install ./sdk/typescript
import { Agent, AgentError } from 'agentplatform'

const agent = new Agent({ apiKey: process.env.AGENT_API_KEY!, baseUrl: '${baseUrl}' })
try {
  const result = await agent.run('${MESSAGE}')
  console.log(result.reply)
} catch (err) {
  if (!(err instanceof AgentError)) throw err
  console.log(err.code, err.message)
}

// The same call over plain HTTP
const response = await fetch('${url}', {
  method: 'POST',
  headers: {
    Authorization: 'Bearer ' + process.env.AGENT_API_KEY,
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({ message: '${MESSAGE}' }),
})
const data = (await response.json()) as { reply?: string; detail?: { code: string; message: string } }
if (response.ok) {
  console.log(data.reply)
} else {
  console.log(data.detail?.code, data.detail?.message)
}
`,
    },
    {
      id: 'node',
      label: 'Node.js',
      code: String.raw`// A CommonJS script (run.js). The package is an ES module, so it is loaded with import().
async function main() {
  const { Agent, AgentError } = await import('agentplatform')

  const agent = new Agent({ apiKey: process.env.AGENT_API_KEY, baseUrl: '${baseUrl}' })
  try {
    const result = await agent.run('${MESSAGE}')
    console.log(result.reply)
  } catch (err) {
    if (!(err instanceof AgentError)) throw err
    console.log(err.code, err.message)
  }

  // The same call over plain HTTP (Node 18 or newer)
  const response = await fetch('${url}', {
    method: 'POST',
    headers: {
      Authorization: 'Bearer ' + process.env.AGENT_API_KEY,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ message: '${MESSAGE}' }),
  })
  const data = await response.json()
  if (response.ok) {
    console.log(data.reply)
  } else {
    console.log(data.detail.code, data.detail.message)
  }
}

main()
`,
    },
    {
      id: 'php',
      label: 'PHP',
      code: String.raw`<?php
// Needs the cURL extension.
$ch = curl_init('${url}');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_HTTPHEADER => [
        'Authorization: Bearer ' . getenv('AGENT_API_KEY'),
        'Content-Type: application/json',
    ],
    CURLOPT_POSTFIELDS => json_encode(['message' => '${MESSAGE}']),
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
`,
    },
    {
      id: 'java',
      label: 'Java',
      code: String.raw`// Java 11 or newer. Java has no JSON parser built in, so this prints the raw text of a field
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
        HttpRequest request = HttpRequest.newBuilder(URI.create("${url}"))
            .timeout(Duration.ofSeconds(200))
            .header("Authorization", "Bearer " + System.getenv("AGENT_API_KEY"))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString("{\"message\": \"${MESSAGE}\"}"))
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
`,
    },
    {
      id: 'go',
      label: 'Go',
      code: String.raw`package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"
)

type result struct {
	Reply  string ${TICK}json:"reply"${TICK}
	Detail struct {
		Code    string ${TICK}json:"code"${TICK}
		Message string ${TICK}json:"message"${TICK}
	} ${TICK}json:"detail"${TICK}
}

func main() {
	body, _ := json.Marshal(map[string]string{"message": "${MESSAGE}"})
	req, err := http.NewRequest("POST", "${url}", bytes.NewReader(body))
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
`,
    },
    {
      id: 'csharp',
      label: 'C#',
      code: String.raw`using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(200) };
using var request = new HttpRequestMessage(HttpMethod.Post, "${url}");
request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", Environment.GetEnvironmentVariable("AGENT_API_KEY"));
request.Content = new StringContent(
    JsonSerializer.Serialize(new { message = "${MESSAGE}" }),
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
`,
    },
    {
      id: 'curl',
      label: 'cURL',
      code: String.raw`curl -sS -X POST "${url}" \
  -H "Authorization: Bearer $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "${MESSAGE}"}'

# 200: {"id": "...", "reply": "...", "sources": [], "tools_used": [], "duration_ms": 1234}
# Other statuses: {"detail": {"code": "...", "message": "..."}}
`,
    },
  ]
}
