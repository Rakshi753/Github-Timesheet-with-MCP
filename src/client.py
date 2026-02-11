import os
import json
import asyncio
import httpx
from datetime import datetime, timedelta
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack
from rich.console import Console

from src.state import AgentState

load_dotenv()
console = Console()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.1,
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    convert_system_message_to_human=True
)

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

async def batch_enrich_commits(commits):
    if not commits: return []
    enriched = []
    batch_size = 10
    
    console.log(f"[dim]Enriching {len(commits)} GitHub commits...[/dim]")
    
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

async def github_node(state: AgentState):
    with console.status("[bold blue]Fetching GitHub Data...[/bold blue]", spinner="dots"):
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
            if commit_count > 0:
                console.print(f"   [green]✔ Found {commit_count} GitHub commits[/green]")
                raw_data["user_commits"] = await batch_enrich_commits(raw_data["user_commits"])
            else:
                console.print("   [yellow]⚠ No commits found (check username/author name)[/yellow]")

            filename = f"{state['username']}_{state['repo_name'].replace('/', '_')}_report.xlsx"
            res = await ex_sess.call_tool("save_github_data_to_excel", {
                "user_commits": raw_data.get("user_commits", []),
                "main_commits": raw_data.get("main_commits", []),
                "filename": filename
            })
            
            return {"excel_file_path": res.content[0].text}

async def jira_node(state: AgentState):
    jira_proj = state.get("jira_project")
    if not jira_proj: return {}

    with console.status(f"[bold blue]Fetching Jira Data ({jira_proj})...[/bold blue]", spinner="dots"):
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
            
            if issues:
                console.print(f"   [green]✔ Found {len(issues)} Jira items[/green]")
                if path:
                    await ex_sess.call_tool("save_jira_data_to_excel", {
                        "jira_data": issues, "filename": os.path.basename(path)
                    })
    return {}

async def reporter_node(state: AgentState):
    path = state.get("excel_file_path")
    if not path: return {"final_timesheet": "Failed."}

    async with AsyncExitStack() as stack:
        ex_params = load_server_params("excel-tool")
        r, w = await stack.enter_async_context(stdio_client(ex_params))
        sess = await stack.enter_async_context(ClientSession(r, w))
        await sess.initialize()

        res = await sess.call_tool("get_data_date_range", {"file_path": path})
        range_str = res.content[0].text.replace('|', ' to ')
        
        console.rule("[bold]Configuration[/bold]")
        console.print(f"[cyan]Data Log Available:[/cyan] {range_str}")
        
        start_input = console.input("   [bold green]👉 Enter Start Date (YYYY-MM-DD): [/bold green]").strip()
        days_input = console.input("   [bold green]👉 Enter Number of Days [Default: 5]: [/bold green]").strip()
        num_days = int(days_input) if days_input.isdigit() else 5
        
        try:
            start_dt = datetime.strptime(start_input, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=num_days - 1)
            targets = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]
            target_str = ", ".join(targets)
        except: return {"final_timesheet": "❌ Invalid Date."}

        with console.status("[bold magenta]Synthesizing Unified Narrative...[/bold magenta]", spinner="earth"):
            res = await sess.call_tool("read_unified_date_range", {
                "file_path": path, "start_date": start_input, "end_date": end_dt.strftime('%Y-%m-%d')
            })
            context = res.content[0].text
            
            system_prompt = f"""
            You are an Expert Corporate Timesheet Generator.
            
            TASK: Create a timesheet for these {num_days} TARGET DATES: {target_str}
            
            SOURCE DATA (COMBINED):
            {context}
            
            CRITICAL RULES:
            1. **Strictly ONE row per date.**
            2. **Consolidate:** Merge multiple items into ONE professional sentence.
            3. **Spread Work:** If a date is empty, infer reasonable continuation tasks (Research, Planning) from neighbors.
            4. **Source:** Tag as [GitHub], [Jira], or [GitHub + Jira].
            
            OUTPUT FORMAT:
            
            | Date | Category | Consolidated Description | Source |
            | :--- | :--- | :--- | :--- |
            ... (table rows) ...

            ### 📝 Executive Summary
            [Write exactly 1 high-quality, professional sentence summarizing the value delivered this week.]
            """
            
            res = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content="Generate Report.")])
            
    return {"final_timesheet": res.content}

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