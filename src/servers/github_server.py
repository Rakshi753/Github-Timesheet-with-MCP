import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from github import Github
from fastmcp import FastMCP

mcp = FastMCP("github-server")

load_dotenv()

@mcp.tool()
def fetch_global_github_activity(username: str, days_lookback: int = 15) -> str:
    """
    Searches for commits by the user across ALL repositories (Global Search).
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return json.dumps({"error": "Server Error: GITHUB_TOKEN missing"})

    try:
        g = Github(token)
        
        # Calculate start date for the search query
        start_date = (datetime.now() - timedelta(days=days_lookback)).strftime('%Y-%m-%d')
        
        # SEARCH QUERY: author:username date:>YYYY-MM-DD
        query = f"author:{username} committer-date:>{start_date}"
        
        commits = g.search_commits(query=query, sort='committer-date', order='desc')
        
        data_package = {"user_commits": []}
        seen_hashes = set()
        
        # Limit to last 50 commits to prevent timeouts
        for c in commits[:50]:
            if c.sha in seen_hashes: continue
            seen_hashes.add(c.sha)
            
            repo_name = c.repository.name
            # Try to get branch name if possible, otherwise generic
            branch = "main" 
            
            data_package["user_commits"].append({
                "date": c.commit.author.date.strftime("%Y-%m-%d"),
                "author": c.commit.author.name,
                "message": c.commit.message,
                "repo": repo_name, # <--- Capture Repo Name per commit
                "sha": c.sha[:7],
                "branch_context": branch
            })
            
        return json.dumps(data_package, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run()