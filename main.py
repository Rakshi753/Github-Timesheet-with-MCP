import asyncio
import sys
import os
from dotenv import load_dotenv
from src.client import build_graph

load_dotenv()

async def main():
    print("============================================")
    print("   🤖 MCP Agent: Enrich -> Save -> Report   ")
    print("============================================")
    
    if not os.getenv("GROQ_API_KEY"):
        print("❌ Error: GROQ_API_KEY missing.")
        return

    user = input("\nGitHub Username: ").strip()
    repo = input("Repository (owner/repo): ").strip()
    
    if not user or not repo: return

    app = build_graph()
    initial_state = {
        "username": user, 
        "repo_name": repo, 
        "filter_days": 7 
    }
    
    try:
        result = await app.ainvoke(initial_state)
        
        print("\n" + "="*40)
        print("       📝 FINAL OUTPUT       ")
        print("="*40 + "\n")
        
        if result.get("final_timesheet"):
            print(result["final_timesheet"])
            
    except Exception as e:
        print(f"\n❌ Execution Error: {e}")

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())