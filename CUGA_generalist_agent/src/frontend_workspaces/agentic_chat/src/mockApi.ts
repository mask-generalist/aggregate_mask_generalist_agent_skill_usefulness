declare const FAKE_STREAM: boolean | undefined;
const USE_FAKE_STREAM = typeof FAKE_STREAM !== "undefined" ? !!FAKE_STREAM : !!(globalThis as any).FAKE_STREAM;

const mockWorkspaceTree = {
  tree: [
    {
      name: "src",
      path: "/workspace/src",
      type: "directory" as const,
      children: [
        {
          name: "main.py",
          path: "/workspace/src/main.py",
          type: "file" as const,
        },
        {
          name: "utils.py",
          path: "/workspace/src/utils.py",
          type: "file" as const,
        },
        {
          name: "config.json",
          path: "/workspace/src/config.json",
          type: "file" as const,
        },
      ],
    },
    {
      name: "data",
      path: "/workspace/data",
      type: "directory" as const,
      children: [
        {
          name: "accounts.csv",
          path: "/workspace/data/accounts.csv",
          type: "file" as const,
        },
        {
          name: "contacts.txt",
          path: "/workspace/data/contacts.txt",
          type: "file" as const,
        },
      ],
    },
    {
      name: "README.md",
      path: "/workspace/README.md",
      type: "file" as const,
    },
    {
      name: "requirements.txt",
      path: "/workspace/requirements.txt",
      type: "file" as const,
    },
  ],
};

const mockFileContents: Record<string, string> = {
  "/workspace/src/main.py": `# Main Application Entry Point
import asyncio
from utils import get_accounts, process_data

async def main():
    """Main application function"""
    print("Starting application...")
    accounts = await get_accounts()
    results = process_data(accounts)
    print(f"Processed {len(results)} accounts")
    return results

if __name__ == "__main__":
    asyncio.run(main())
`,
  "/workspace/src/utils.py": `# Utility Functions
from typing import List, Dict, Any

async def get_accounts() -> List[Dict[str, Any]]:
    """Fetch accounts from the API"""
    # Mock implementation
    return [
        {"name": "Acme Corp", "revenue": 1000000},
        {"name": "Tech Innovations", "revenue": 750000},
        {"name": "Global Solutions", "revenue": 500000},
    ]

def process_data(accounts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process account data"""
    return sorted(accounts, key=lambda x: x["revenue"], reverse=True)
`,
  "/workspace/src/config.json": `{
  "api": {
    "endpoint": "https://api.example.com",
    "timeout": 30,
    "retry_count": 3
  },
  "database": {
    "host": "localhost",
    "port": 5432,
    "name": "crm_db"
  },
  "features": {
    "enable_caching": true,
    "enable_analytics": true,
    "max_concurrent_requests": 10
  }
}`,
  "/workspace/data/accounts.csv": `name,state,revenue,industry
Acme Corporation,New York,1000000,Technology
Tech Innovations Ltd.,California,750000,Software
Global Solutions Inc.,Texas,500000,Consulting
Pioneer Investments,Massachusetts,450000,Finance
Sunrise Industries,Florida,300000,Manufacturing`,
  "/workspace/data/contacts.txt": `John Doe - john.doe@acme.com - CEO
Jane Smith - jane.smith@techinnovations.com - CTO
Bob Johnson - bob.johnson@globalsolutions.com - VP Sales
Alice Williams - alice.williams@pioneer.com - Director
Charlie Brown - charlie.brown@sunrise.com - Manager`,
  "/workspace/README.md": `# Workspace Project

This is a sample workspace containing various files created by the agent.

## Structure

- \`src/\` - Source code files
  - \`main.py\` - Main application entry point
  - \`utils.py\` - Utility functions
  - \`config.json\` - Configuration settings

- \`data/\` - Data files
  - \`accounts.csv\` - Account information
  - \`contacts.txt\` - Contact details

## Usage

Run the main application:

\`\`\`bash
python src/main.py
\`\`\`

## Requirements

See \`requirements.txt\` for Python dependencies.
`,
  "/workspace/requirements.txt": `aiohttp==3.9.1
requests==2.31.0
pandas==2.1.4
pydantic==2.5.3
python-dotenv==1.0.0
fastapi==0.109.0
uvicorn==0.27.0
`,
};

const originalFetch = window.fetch;

function setupMockApi() {
  if (!USE_FAKE_STREAM) {
    return;
  }

  console.log("🎭 Mock API initialized - intercepting workspace API calls");

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;

    // Intercept workspace tree API
    if (url.includes("/api/workspace/tree")) {
    //   console.log("🎭 Mock: Returning workspace tree");
      await delay(300);
      return new Response(JSON.stringify(mockWorkspaceTree), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Intercept workspace file content API
    if (url.includes("/api/workspace/file")) {
      const urlObj = new URL(url, window.location.origin);
      const path = urlObj.searchParams.get("path");
      console.log("🎭 Mock: Returning file content for", path);
      
      await delay(200);
      
      if (path && mockFileContents[path]) {
        return new Response(
          JSON.stringify({ content: mockFileContents[path] }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      } else {
        return new Response(
          JSON.stringify({ error: "File not found" }),
          {
            status: 404,
            headers: { "Content-Type": "application/json" },
          }
        );
      }
    }

    // Intercept workspace file download API
    if (url.includes("/api/workspace/download")) {
      const urlObj = new URL(url, window.location.origin);
      const path = urlObj.searchParams.get("path");
      console.log("🎭 Mock: Returning file download for", path);
      
      await delay(200);
      
      if (path && mockFileContents[path]) {
        const blob = new Blob([mockFileContents[path]], { type: "text/plain" });
        return new Response(blob, {
          status: 200,
          headers: {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": `attachment; filename="${path.split("/").pop()}"`,
          },
        });
      } else {
        return new Response(
          JSON.stringify({ error: "File not found" }),
          {
            status: 404,
            headers: { "Content-Type": "application/json" },
          }
        );
      }
    }

    // Intercept config API endpoints
    if (url.includes("/api/config/")) {
      console.log("🎭 Mock: Returning config response for", url);
      await delay(200);
      
      // Return empty config for all config endpoints
      const configType = url.split("/api/config/")[1];
      const mockConfigs: Record<string, any> = {
        memory: {
          enableMemory: true,
          memoryType: "both",
          contextWindow: 4096,
          maxMemoryItems: 100,
          semanticSearch: true,
          autoSummarization: true,
        },
        knowledge: {
          sources: [],
          embeddingModel: "text-embedding-3-small",
          chunkSize: 1000,
          chunkOverlap: 200,
        },
        tools: {
          mcpServers: {},
          services: [],
        },
        subagents: {
          mode: "supervisor",
          subAgents: [],
          supervisorStrategy: "adaptive",
          availableTools: [],
        },
        model: {
          provider: "anthropic",
          model: "claude-3-5-sonnet-20241022",
          temperature: 0.7,
          maxTokens: 4096,
          topP: 1.0,
        },
        policies: {
          enablePolicies: true,
          intentPolicies: [],
          sopPolicies: [],
          subAgentPolicies: [],
          appPolicies: [],
          strictMode: false,
          logViolations: true,
        },
      };
      
      if (init?.method === "POST") {
        // Save config (just return success)
        return new Response(JSON.stringify({ success: true }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      } else {
        // Get config
        const config = mockConfigs[configType] || {};
        return new Response(JSON.stringify(config), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
    }

    // For all other requests, use the original fetch
    return originalFetch(input, init);
  };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Initialize mock API if FAKE_STREAM is enabled
if (USE_FAKE_STREAM) {
  setupMockApi();
}

export { setupMockApi, USE_FAKE_STREAM };

