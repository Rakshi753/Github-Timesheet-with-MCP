import asyncio
import sys
import os
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from src.client import build_graph

load_dotenv()
console = Console()

async def main():
    console.clear()
    console.print(Panel.fit(
        "[bold cyan]🤖 MCP Timesheet Agent[/bold cyan]\n[dim]Powered by Gemini 2.0 Flash[/dim]",
        border_style="cyan"
    ))
    
    if not os.getenv("GOOGLE_API_KEY"): 
        return console.print("[bold red]❌ Error: Missing GOOGLE_API_KEY[/bold red]")

    # Inputs
    user = console.input("[bold]GitHub Username:[/bold] ").strip()
    repo = console.input("[bold]GitHub Repo (owner/repo):[/bold] ").strip()
    jira_proj = console.input("[bold]Jira Project Key (Optional):[/bold] ").strip()
    
    if not user or not repo: return

    app = build_graph()
    initial_state = {
        "username": user, 
        "repo_name": repo, 
        "jira_project": jira_proj,
        "filter_days": 7
    }
    
    try:
        result = await app.ainvoke(initial_state)
        
        if result.get("final_timesheet"):
            console.print("\n")
            console.print(Panel(
                Markdown(result["final_timesheet"]),
                title="[bold green]Generated Timesheet[/bold green]",
                border_style="green",
                expand=False
            ))
            console.print(f"[dim]File saved successfully.[/dim]")
            
    except Exception as e:
        console.print(f"\n[bold red]❌ Execution Error:[/bold red] {e}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())