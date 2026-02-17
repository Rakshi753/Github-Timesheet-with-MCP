import os
import json
import asyncio
import re
import warnings
from datetime import datetime, timedelta


import httpx
from httpx import Client, AsyncClient

def patched_client_init(self, *args, **kwargs):
    kwargs['verify'] = False
    return Client._original_init(self, *args, **kwargs)

def patched_async_client_init(self, *args, **kwargs):
    kwargs['verify'] = False
    return AsyncClient._original_init(self, *args, **kwargs)

if not getattr(Client, "_original_init", None):
    Client._original_init = Client.__init__
    Client.__init__ = patched_client_init

if not getattr(AsyncClient, "_original_init", None):
    AsyncClient._original_init = AsyncClient.__init__
    AsyncClient.__init__ = patched_async_client_init

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langchain_groq import ChatGroq 
from langchain_core.messages import SystemMessage, HumanMessage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from contextlib import AsyncExitStack
from rich.console import Console

from src.state import AgentState

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
load_dotenv()
console = Console()

llm = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.1,
    groq_api_key=os.getenv("GROQ_API_KEY")
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
    batch_size = 20 
    
    console.log(f"[dim]Enriching {len(commits)} GitHub commits...[/dim]")
    
    for i in range(0, len(commits), batch_size):
        batch = commits[i:i+batch_size]
        batch_text = "\n".join([f"{idx+1}. {c['message']}" for idx, c in enumerate(batch)])
        prompt = "Rewrite each git commit message into a single, professional, past-tense sentence. Return ONLY the numbered list."
        try:
            res = await llm.ainvoke([SystemMessage(content=prompt), HumanMessage(content=batch_text)])
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
    """Fetches Global GitHub Activity (All Repos)."""
    with console.status("[bold blue]Scanning Global GitHub Activity...[/bold blue]", spinner="dots"):
        async with AsyncExitStack() as stack:
            gh_params = load_server_params("github-tool")
            gh_r, gh_w = await stack.enter_async_context(stdio_client(gh_params))
            gh_sess = await stack.enter_async_context(ClientSession(gh_r, gh_w))
            await gh_sess.initialize()

            ex_params = load_server_params("excel-tool")
            ex_r, ex_w = await stack.enter_async_context(stdio_client(ex_params))
            ex_sess = await stack.enter_async_context(ClientSession(ex_r, ex_w))
            await ex_sess.initialize()

            # Global Search - No repo name needed
            res = await gh_sess.call_tool("fetch_global_github_activity", {
                "username": state["username"]
            })
            raw_data = json.loads(res.content[0].text)
            
            commit_count = len(raw_data.get("user_commits", []))
            if commit_count > 0:
                console.print(f"   [green]✔ Found {commit_count} commits across all repos[/green]")
                raw_data["user_commits"] = await batch_enrich_commits(raw_data["user_commits"])
            else:
                console.print("   [yellow]⚠ No commits found[/yellow]")
            
            filename = f"{state['username']}_Timesheet_Report.xlsx"
            res = await ex_sess.call_tool("save_github_data_to_excel", {
                "user_commits": raw_data.get("user_commits", []),
                "filename": filename
            })
            
            return {"excel_file_path": res.content[0].text}

async def jira_node(state: AgentState):
    """Fetches Jira Data and Appends to Excel."""
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
    """
    Lightweight Reporter: Fetches Context -> Asks AI for Text -> Calls Excel Server to Merge.
    """
    path = state.get("excel_file_path")
    if not path or not os.path.exists(path):
        return {"final_timesheet": "Failed."}

    # 1. Collect User Input (Terminal Interactive)
    # We do this here so the LLM knows the exact dates
    try:
        async with AsyncExitStack() as stack:
            # Setup connections
            ex_params = load_server_params("excel-tool")
            r, w = await stack.enter_async_context(stdio_client(ex_params))
            sess = await stack.enter_async_context(ClientSession(r, w))
            await sess.initialize()

            # Get Date Range from File for suggestion
            res = await sess.call_tool("get_data_date_range", {"file_path": path})
            range_str = res.content[0].text.replace('|', ' to ')

            console.rule("[bold]Timesheet Configuration[/bold]")
            console.print(f"[cyan]Data Available:[/cyan] {range_str}")
            
            emp_id = console.input("   [bold green]🆔 Employee ID: [/bold green]").strip()
            emp_name = console.input("   [bold green]👤 Employee Name: [/bold green]").strip()
            start_input = console.input("   [bold green]📅 Start Date (YYYY-MM-DD): [/bold green]").strip()
            days_input = console.input("   [bold green]⏳ Number of Days [5]: [/bold green]").strip()
            num_days = int(days_input) if days_input.isdigit() else 5
            
            # Calculate Target Dates
            start_dt = datetime.strptime(start_input, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=num_days - 1)
            target_dates = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]

            # 2. Get Context (Read logs from Excel)
            with console.status("[bold magenta]Reading Context...[/bold magenta]", spinner="earth"):
                res = await sess.call_tool("read_unified_date_range", {
                    "file_path": path, "start_date": start_input, "end_date": end_dt.strftime('%Y-%m-%d')
                })
                context = res.content[0].text
                
                # 3. Lean Prompt (Only Description & Remarks)
                sys_msg = f"""
                You are a Corporate Timesheet Assistant.
                
                TARGET DATES: {target_dates}
                
                ACTIVITY LOGS:
                {context}
                
                INSTRUCTIONS:
                For EACH target date in the list, write:
                1. "Description": A professional, past-tense paragraph summarizing the work based on the logs. If no log, invent a generic "Maintenance and review" description.
                2. "Remarks": A single high-level sentence about the value delivered.
                
                OUTPUT FORMAT (Strict Pipe-Separated):
                Date|Description|Remarks
                
                Example:
                2026-02-02|Refactored the API module.|Improved API stability.
                """
                
                human_msg = "Generate the pipe-separated list now. One line per date."
                
                # 4. AI Generation
                ai_res = await llm.ainvoke([SystemMessage(content=sys_msg), HumanMessage(content=human_msg)])
                raw_lines = ai_res.content.strip().split('\n')
                
                # 5. Parse into Map (Date -> Data)
                enrichment_map = {}
                for line in raw_lines:
                    parts = line.split('|')
                    if len(parts) >= 3:
                        d = parts[0].strip()
                        enrichment_map[d] = {
                            "description": parts[1].strip(),
                            "remarks": parts[2].strip()
                        }
                
                # Send just the AI text to the tool
                json_payload = json.dumps(enrichment_map)

            # 6. Call Excel Server to Merge & Save
            console.log("[bold cyan]Merging Data & Saving...[/bold cyan]")
            
            final_res = await sess.call_tool("generate_final_timesheet", {
                "ai_enrichment_json": json_payload,
                "employee_id": emp_id,
                "employee_name": emp_name,
                "source_file_path": path,
                "start_date": start_input,
                "num_days": num_days
            })
            
            result_text = final_res.content[0].text
            if "Error" in result_text:
                 console.print(f"[bold red]❌ Error:[/bold red] {result_text}")
                 return {"final_timesheet": "Failed."}
                 
            console.print(f"[bold green]✔ Success![/bold green] Saved to: {result_text}")
            return {"final_timesheet": result_text}

    except Exception as e:
        import traceback
        console.print(f"[bold red]❌ Detailed Error:[/bold red] {e}")
        console.print(traceback.format_exc())
        return {"final_timesheet": "Failed."}

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