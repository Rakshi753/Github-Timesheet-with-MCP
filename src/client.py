import os
import json
import asyncio
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack

from src.state import AgentState

load_dotenv()

# Setup LLM
http_client = httpx.Client(verify=False)
llm = ChatGroq(
    model="llama-3.1-8b-instant", 
    temperature=0.1, 
    api_key=os.getenv("GROQ_API_KEY"),
    http_client=http_client
)

# --- HELPER: Load Config ---
def load_server_params(server_name: str) -> StdioServerParameters:
    with open("server_config.json", "r") as f:
        config = json.load(f)
    if server_name not in config["mcpServers"]:
        raise ValueError(f"Server '{server_name}' not found")
    srv_cfg = config["mcpServers"][server_name]
    env_vars = os.environ.copy()
    if "env" in srv_cfg:
        for k, v in srv_cfg["env"].items():
            if v.startswith("${") and v.endswith("}"):
                env_vars[k] = os.getenv(v[2:-1], "")
            else:
                env_vars[k] = v
    return StdioServerParameters(command=srv_cfg["command"], args=srv_cfg["args"], env=env_vars)

# --- HELPER: Batch Enrichment (GitHub) ---
async def batch_enrich_commits(commits):
    if not commits: return []
    enriched = []
    batch_size = 10
    print(f"   ... Enriching {len(commits)} GitHub commits...")
    
    for i in range(0, len(commits), batch_size):
        batch = commits[i:i+batch_size]
        batch_text = "\n".join([f"{idx+1}. {c['message']}" for idx, c in enumerate(batch)])
        prompt = "Rewrite each git commit message into a single, professional, past-tense sentence. Return ONLY the numbered list."
        try:
            res = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=batch_text)])
            lines = res.content.strip().split('\n')
            for idx, commit in enumerate(batch):
                summary = commit['message']
                if idx < len(lines):
                    clean = lines[idx].split(". ", 1)[-1].strip()
                    if len(clean) > 5: summary = clean
                commit['ai_summary'] = summary
                enriched.append(commit)
        except:
            for commit in batch:
                commit['ai_summary'] = commit['message']
                enriched.append(commit)
    return enriched

# --- NODE 1: GITHUB FETCH ---
async def github_node(state: AgentState):
    print(f"--- [1/3] Fetching GitHub Data ({state['repo_name']}) ---")
    
    async with AsyncExitStack() as stack:
        gh_params = load_server_params("github-tool")
        gh_r, gh_w = await stack.enter_async_context(stdio_client(gh_params))
        gh_sess = await stack.enter_async_context(ClientSession(gh_r, gh_w))
        await gh_sess.initialize()

        ex_params = load_server_params("excel-tool")
        ex_r, ex_w = await stack.enter_async_context(stdio_client(ex_params))
        ex_sess = await stack.enter_async_context(ClientSession(ex_r, ex_w))
        await ex_sess.initialize()

        res = await gh_sess.call_tool("fetch_github_activity", {
            "repo_name": state["repo_name"], "username": state["username"]
        })
        raw_data = json.loads(res.content[0].text)

        commit_count = len(raw_data.get("user_commits", []))
        print(f"   ℹ️  Found {commit_count} GitHub commits.")
        
        if commit_count == 0:
            print("   ⚠️  Warning: 0 Commits found! Check if your local Git Name matches your GitHub Username.")

        if raw_data.get("user_commits"):
            raw_data["user_commits"] = await batch_enrich_commits(raw_data["user_commits"])

        filename = f"{state['username']}_{state['repo_name'].replace('/', '_')}_report.xlsx"
        res = await ex_sess.call_tool("save_github_data_to_excel", {
            "user_commits": raw_data.get("user_commits", []),
            "main_commits": raw_data.get("main_commits", []),
            "filename": filename
        })
        
        path = res.content[0].text
        print(f"   ✅ GitHub data saved to: {path}")
        return {"excel_file_path": path}

# --- NODE 2: JIRA FETCH ---
async def jira_node(state: AgentState):
    jira_proj = state.get("jira_project")
    if not jira_proj: 
        print("--- [2/3] Skipping Jira (No Project Key) ---")
        return {}

    print(f"--- [2/3] Fetching Jira Data ({jira_proj}) ---")
    path = state.get("excel_file_path")

    async with AsyncExitStack() as stack:
        jr_params = load_server_params("jira-tool")
        jr_r, jr_w = await stack.enter_async_context(stdio_client(jr_params))
        jr_sess = await stack.enter_async_context(ClientSession(jr_r, jr_w))
        await jr_sess.initialize()

        ex_params = load_server_params("excel-tool")
        ex_r, ex_w = await stack.enter_async_context(stdio_client(ex_params))
        ex_sess = await stack.enter_async_context(ClientSession(ex_r, ex_w))
        await ex_sess.initialize()

        res = await jr_sess.call_tool("fetch_jira_issues", {"project_key": jira_proj})
        data = json.loads(res.content[0].text)
        issues = data.get("jira_issues", [])
        print(f"   ℹ️  Found {len(issues)} Jira items.")

        if issues and path:
            await ex_sess.call_tool("save_jira_data_to_excel", {
                "jira_data": issues, "filename": os.path.basename(path)
            })
            print("   ✅ Jira data appended to Excel.")
        
    return {}

# --- NODE 3: REPORTER ---
async def reporter_node(state: AgentState):
    print("--- [3/3] Generating Unified Report ---")
    path = state.get("excel_file_path")
    if not path: return {"final_timesheet": "Failed."}

    async with AsyncExitStack() as stack:
        ex_params = load_server_params("excel-tool")
        r, w = await stack.enter_async_context(stdio_client(ex_params))
        sess = await stack.enter_async_context(ClientSession(r, w))
        await sess.initialize()

        res = await sess.call_tool("get_data_date_range", {"file_path": path})
        range_str = res.content[0].text
        
        print(f"\n   ✅ Data Available in Log: {range_str.replace('|', ' to ')}")
        print("   The system will merge GitHub (Code) and Jira (Plans) into one narrative.")
        
        # --- NEW INPUT LOGIC ---
        start_input = input(f"   👉 Enter Start Date (YYYY-MM-DD): ").strip()
        days_input = input(f"   👉 Enter Number of Days [Default: 5]: ").strip()
        num_days = int(days_input) if days_input.isdigit() else 5
        
        try:
            start_dt = datetime.strptime(start_input, "%Y-%m-%d")
            # Calculate End Date based on Num Days
            end_dt = start_dt + timedelta(days=num_days - 1)
            targets = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]
            target_str = ", ".join(targets)
        except: return {"final_timesheet": "❌ Invalid Date."}

        print(f"   ... Reading context for {start_input} to {end_dt.strftime('%Y-%m-%d')}...")
        res = await sess.call_tool("read_unified_date_range", {
            "file_path": path, "start_date": start_input, "end_date": end_dt.strftime('%Y-%m-%d')
        })
        context = res.content[0].text

    print(f"   ... Synthesizing Unified {num_days}-Day Narrative...")
    
    # --- UPDATED PROMPT ---
    system_prompt = f"""
    You are an Expert Corporate Timesheet Generator.
    
    TASK: Create a timesheet for these {num_days} TARGET DATES: {target_str}
    
    SOURCE DATA (COMBINED):
    {context}
    
    CRITICAL RULES:
    1. **Strictly ONE row per date.** Do not create multiple rows for the same date. 
    2. **Consolidate:** If a day has multiple GitHub commits or Jira items, merge them into ONE rich, professional sentence.
       - BAD: "Fixed bug. Also updated UI."
       - GOOD: "Resolved authentication bugs and optimized the frontend dashboard UI for better user experience."
    3. **Spread Work:** If a target date has no data, infer logical work (e.g., "Research", "Planning", "Testing") from adjacent days to fill the gap.
    4. **Source:** Tag sources as "GitHub", "Jira", or "Both".
    
    OUTPUT FORMAT:
    
    | Date | Category | Consolidated Description | Source |
    | :--- | :--- | :--- | :--- |
    ... (table rows) ...

    ### Timesheet Summary
    [Write exactly 1 or 2 high-quality, professional sentences summarizing the entire period. Do not list bullet points or daily stats. Focus on value delivered.]
    """
    
    res = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content="Generate Report.")])
    return {"final_timesheet": res.content}

# --- GRAPH ---
def build_graph():
    wf = StateGraph(AgentState)
    wf.add_node("github", github_node)
    wf.add_node("jira", jira_node)
    wf.add_node("reporter", reporter_node)
    
    wf.set_entry_point("github")
    wf.add_edge("github", "jira")
    wf.add_edge("jira", "reporter")
    wf.add_edge("reporter", END)
    
    return wf.compile()