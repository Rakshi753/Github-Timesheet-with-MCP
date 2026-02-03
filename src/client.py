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

# --- HELPER: Batch Enrichment ---
async def batch_enrich_commits(commits):
    """Sends batches of commit messages to LLM for summarization."""
    if not commits: return []
    enriched = []
    batch_size = 10
    
    print(f"   ... Enriching {len(commits)} commits (Generating summaries)...")
    
    for i in range(0, len(commits), batch_size):
        batch = commits[i:i+batch_size]
        batch_text = "\n".join([f"{idx+1}. {c['message']}" for idx, c in enumerate(batch)])
        
        prompt = """
        Rewrite each git commit message into a single, professional, past-tense sentence describing the work.
        Return ONLY the numbered list.
        """
        try:
            res = llm.invoke([SystemMessage(content=prompt), HumanMessage(content=batch_text)])
            lines = res.content.strip().split('\n')
            for idx, commit in enumerate(batch):
                summary = commit['message']
                if idx < len(lines):
                    clean_line = lines[idx].split(". ", 1)[-1].strip()
                    if len(clean_line) > 5: summary = clean_line
                commit['ai_summary'] = summary
                enriched.append(commit)
        except:
            for commit in batch:
                commit['ai_summary'] = commit['message']
                enriched.append(commit)
                
    return enriched

# --- NODES ---

async def orchestrator_node(state: AgentState):
    print(f"--- [Orchestrator] Starting workflow for {state['repo_name']} ---")
    
    async with AsyncExitStack() as stack:
        gh_params = load_server_params("github-tool")
        gh_read, gh_write = await stack.enter_async_context(stdio_client(gh_params))
        gh_session = await stack.enter_async_context(ClientSession(gh_read, gh_write))
        await gh_session.initialize()

        ex_params = load_server_params("excel-tool")
        ex_read, ex_write = await stack.enter_async_context(stdio_client(ex_params))
        ex_session = await stack.enter_async_context(ClientSession(ex_read, ex_write))
        await ex_session.initialize()

        # 1. Fetch
        print("   ... Fetching raw data from GitHub...")
        gh_result = await gh_session.call_tool("fetch_github_activity", {
            "repo_name": state["repo_name"], "username": state["username"]
        })
        raw_data = json.loads(gh_result.content[0].text)
        if "error" in raw_data: return {"raw_data_package": raw_data}

        # 2. Enrich
        user_commits = raw_data.get("user_commits", [])
        if user_commits:
            print(f"   ℹ️  Found {len(user_commits)} commits.")
            if len(user_commits) > 0:
                print("   ... Running LLM Enrichment for Excel (Professional Summaries)...")
                raw_data["user_commits"] = await batch_enrich_commits(user_commits)

        # 3. Save
        filename = f"{state['username']}_report.xlsx"
        print(f"   ... Saving enriched data to {filename}")
        save_result = await ex_session.call_tool("save_github_data_to_excel", {
            "user_commits": raw_data["user_commits"],
            "main_commits": raw_data["main_commits"],
            "filename": filename
        })
        
        return {"excel_file_path": save_result.content[0].text, "raw_data_package": raw_data}

async def reporter_node(state: AgentState):
    path = state.get("excel_file_path")
    if not path or "Error" in path: return {"final_timesheet": "Failed."}

    async with AsyncExitStack() as stack:
        ex_params = load_server_params("excel-tool")
        read, write = await stack.enter_async_context(stdio_client(ex_params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        
        # 1. Get Range
        range_result = await session.call_tool("get_data_date_range", {"file_path": path})
        range_str = range_result.content[0].text
        
        if "|" not in range_str: return {"final_timesheet": "No date data."}
        min_date, max_date = range_str.split("|")
        
        print(f"\n   ✅ Data Available From: {min_date} to {max_date}")

        # DISPLAY TABLE
        print("\n   📜 AVAILABLE ACTIVITY LOG:")
        print("   " + "="*60)
        table_result = await session.call_tool("read_excel_summary", {
            "file_path": path, "days_filter": 3650
        })
        print(table_result.content[0].text)
        print("   " + "="*60 + "\n")

        print("   The system will pool all tasks and spread them across 5 days.")
        start_input = input(f"   👉 Enter Start Date (YYYY-MM-DD): ").strip()
        
        try:
            start_dt = datetime.strptime(start_input, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=4)
            end_input = end_dt.strftime("%Y-%m-%d")
            # List of 5 target days
            target_dates = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
            target_dates_str = ", ".join(target_dates)
        except ValueError:
            return {"final_timesheet": "❌ Invalid Date Format."}

        # 2. Fetch Specific Range Data
        print(f"   ... Fetching context for {start_input} to {end_input}...")
        read_result = await session.call_tool("read_specific_date_range", {
            "file_path": path,
            "start_date": start_input,
            "end_date": end_input
        })
        context = read_result.content[0].text

    # 3. Generate "Work Spreading" Report
    print("   ... Synthesizing Smooth 5-Day Narrative...")
    
    # --- THIS PROMPT IS THE KEY FIX ---
    system_prompt = f"""
    You are an Expert Timesheet Generator.
    
    TASK: Create a 5-day timesheet for these TARGET DATES: 
    {target_dates_str}
    
    SOURCE DATA (POOL OF WORK):
    {context}
    
    INSTRUCTIONS (WORK SPREADING):
    1. Analyze all the work items in the SOURCE DATA.
    2. **IGNORE the specific dates** in the Source Data. Treat the work as a "Pool of Tasks" completed this week.
    3. Distribute this work logically across the 5 TARGET DATES to simulate continuous progress.
    4. **Spread the load:** If Day 1 had 5 commits and Day 2 had 0, move some tasks from Day 1 to Day 2.
    5. Ensure every TARGET DATE has a unique, professional entry.
    6. Maintain the chronological order of tasks (don't put the final polish before the initial setup).
    
    OUTPUT FORMAT (Markdown Table):
    | Date | Category | Consolidated Description | Branch |
    | :--- | :--- | :--- | :--- |
    """
    
    res = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content="Start Generating.")])
    return {"final_timesheet": res.content}

def build_graph():
    wf = StateGraph(AgentState)
    wf.add_node("orchestrator", orchestrator_node)
    wf.add_node("reporter", reporter_node)
    wf.set_entry_point("orchestrator")
    wf.add_edge("orchestrator", "reporter")
    wf.add_edge("reporter", END)
    return wf.compile()