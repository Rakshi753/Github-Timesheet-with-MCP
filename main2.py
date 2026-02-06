import asyncio
import sys
import os
import json
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

load_dotenv()

# --- HELPER: Load Config ---
def load_server_params(server_name: str) -> StdioServerParameters:
    with open("server_config.json", "r") as f:
        config = json.load(f)
    srv_cfg = config["mcpServers"][server_name]
    env_vars = os.environ.copy()
    if "env" in srv_cfg:
        for k, v in srv_cfg["env"].items():
            if v.startswith("${"): env_vars[k] = os.getenv(v[2:-1], "")
            else: env_vars[k] = v
    return StdioServerParameters(command=srv_cfg["command"], args=srv_cfg["args"], env=env_vars)

async def run_jira_flow():
    print("============================================")
    print("   🔵 Jira Data Fetcher (Standalone)        ")
    print("============================================")

    # 1. Inputs (To match existing Excel file)
    print("\n⚠️  Enter the SAME details used for GitHub to find the correct Excel file.")
    username = input("GitHub Username: ").strip()
    repo_name = input("GitHub Repo Name (owner/repo): ").strip()
    
    if not username or not repo_name: return

    # Jira Specific Input
    jira_project = input("Jira Project Key (e.g., SP): ").strip()
    if not jira_project: return

    # Reconstruct Filename
    safe_repo = repo_name.replace("/", "_")
    target_filename = f"{username}_{safe_repo}_report.xlsx"
    print(f"\n📂 Target Excel File: {target_filename}")

    async with AsyncExitStack() as stack:
        # --- CONNECT TO JIRA SERVER ---
        print("   ... Connecting to Jira Tool...")
        jira_params = load_server_params("jira-tool")
        jr_r, jr_w = await stack.enter_async_context(stdio_client(jira_params))
        jr_sess = await stack.enter_async_context(ClientSession(jr_r, jr_w))
        await jr_sess.initialize()

        # --- CONNECT TO EXCEL SERVER ---
        print("   ... Connecting to Excel Tool...")
        ex_params = load_server_params("excel-tool")
        ex_r, ex_w = await stack.enter_async_context(stdio_client(ex_params))
        ex_sess = await stack.enter_async_context(ClientSession(ex_r, ex_w))
        await ex_sess.initialize()

        # 1. Fetch Jira Data
        print(f"   ... Fetching issues from Project: {jira_project}")
        res = await jr_sess.call_tool("fetch_jira_issues", {"project_key": jira_project})
        data = json.loads(res.content[0].text)

        if "error" in data:
            print(f"❌ Error: {data['error']}")
            return

        issues = data.get("jira_issues", [])
        print(f"   ✅ Found {len(issues)} active issues/worklogs.")

        # 2. Save to Excel
        if issues:
            print("   ... Appending to 'Jira_Activity' sheet...")
            save_res = await ex_sess.call_tool("save_jira_data_to_excel", {
                "jira_data": issues,
                "filename": target_filename
            })
            print(f"   🎉 Success! Updated file: {save_res.content[0].text}")
        else:
            print("   ⚠️  No recent activity found in Jira.")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_jira_flow())