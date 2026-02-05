import asyncio
import sys
import os
from dotenv import load_dotenv
from src.client import build_graph

load_dotenv()

async def main():
    print("============================================")
    print("   🤖 Unified Timesheet Agent (Git + Jira)  ")
    print("============================================")
    
    if not os.getenv("GROQ_API_KEY"): return print("❌ Error: Missing GROQ_API_KEY")

    # Inputs
    user = input("\nGitHub Username: ").strip()
    repo = input("GitHub Repo (owner/repo): ").strip()
    jira_proj = input("Jira Project Key (Leave empty to skip): ").strip()
    
    if not user or not repo: return

    app = build_graph()
    initial_state = {
        "username": user, 
        "repo_name": repo, 
        "jira_project": jira_proj, # Pass to graph
        "filter_days": 7
    }
    
    try:
        result = await app.ainvoke(initial_state)
        
        print("\n" + "="*40)
        print("       📝 FINAL UNIFIED REPORT       ")
        print("="*40 + "\n")
        
        if result.get("final_timesheet"):
            print(result["final_timesheet"])
            
    except Exception as e:
        print(f"\n❌ Execution Error: {e}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main()) 