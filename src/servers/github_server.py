import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from github import Github
from fastmcp import FastMCP

# Initialize Server
mcp = FastMCP("github-server")

load_dotenv()

@mcp.tool()
def fetch_github_activity(repo_name: str, username: str, days_lookback: int = 730) -> str:
    """
    Scans all branches of a GitHub repository to find commits by a specific user.
    Returns a JSON string containing the commit history.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return json.dumps({"error": "Server Error: GITHUB_TOKEN missing in environment"})

    try:
        g = Github(token)
        if "/" not in repo_name:
            repo_name = f"{username}/{repo_name}"
            
        repo = g.get_repo(repo_name)
        start_date = datetime.now() - timedelta(days=days_lookback)
        
        data_package = {"user_commits": [], "main_commits": []}
        seen_hashes = set()
        
        # 1. Scan All Branches
        branches = list(repo.get_branches())
        
        for branch in branches:
            try:
                commits = repo.get_commits(sha=branch.name, since=start_date)
                for commit in commits:
                    sha = commit.sha
                    if sha in seen_hashes: continue
                    seen_hashes.add(sha)
                    
                    # Fuzzy Author Matching
                    is_target = False
                    if commit.author and commit.author.login.lower() == username.lower():
                        is_target = True
                    elif username.lower() in commit.commit.author.name.lower():
                        is_target = True
                    
                    if is_target:
                        data_package["user_commits"].append({
                            "date": commit.commit.author.date.strftime("%Y-%m-%d"),
                            "author": commit.commit.author.name,
                            "message": commit.commit.message,
                            "sha": sha[:7],
                            "branch_context": branch.name
                        })
            except Exception:
                continue 

        # 2. Get Main Context
        try:
            main_commits = repo.get_commits(sha=repo.default_branch, since=start_date)
            for commit in main_commits:
                data_package["main_commits"].append({
                    "date": commit.commit.author.date.strftime("%Y-%m-%d"),
                    "author": commit.commit.author.name,
                    "message": commit.commit.message,
                    "sha": commit.sha[:7]
                })
        except:
            pass
            
        return json.dumps(data_package, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run()