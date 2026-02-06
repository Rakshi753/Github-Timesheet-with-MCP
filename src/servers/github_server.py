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
    Uses fuzzy matching to handle differences between GitHub username and Git author name.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return json.dumps({"error": "Server Error: GITHUB_TOKEN missing in environment"})

    try:
        g = Github(token)
        # Handle cases where user provides "owner/repo" or just "repo"
        if "/" not in repo_name:
            repo_name = f"{username}/{repo_name}"
            
        repo = g.get_repo(repo_name)
        start_date = datetime.now() - timedelta(days=days_lookback)
        
        data_package = {"user_commits": [], "main_commits": []}
        seen_hashes = set()
        
        # 1. Scan All Branches
        # We assume the user might be working on feature branches not yet merged.
        branches = list(repo.get_branches())
        
        for branch in branches:
            try:
                commits = repo.get_commits(sha=branch.name, since=start_date)
                for c in commits:
                    if c.sha in seen_hashes: continue
                    seen_hashes.add(c.sha)
                    
                    # --- IMPROVED MATCHING LOGIC ---
                    is_match = False
                    
                    # Check 1: Strict Match on GitHub Username (Login)
                    # This works if the commit is linked to a GitHub account
                    if c.author and c.author.login.lower() == username.lower():
                        is_match = True
                    
                    # Check 2: Loose Match on Git Author Name (The name in local git config)
                    # This handles cases where "Rakshi753" (GitHub) != "Rakshith L" (Local Git)
                    elif c.commit.author.name:
                        author_name = c.commit.author.name.lower()
                        target_user = username.lower()
                        
                        # Logic: Is the username inside the real name? OR Real name inside username?
                        if target_user in author_name or author_name in target_user:
                            is_match = True
                    
                    if is_match:
                        data_package["user_commits"].append({
                            "date": c.commit.author.date.strftime("%Y-%m-%d"),
                            "author": c.commit.author.name,
                            "message": c.commit.message,
                            "sha": c.sha[:7],
                            "branch_context": branch.name
                        })
            except Exception:
                # Skip branches that are protected or empty
                continue 

        # 2. Get Main Context (Commit history of the main branch for reference)
        try:
            main_commits = repo.get_commits(sha=repo.default_branch, since=start_date)
            for c in main_commits:
                data_package["main_commits"].append({
                    "date": c.commit.author.date.strftime("%Y-%m-%d"),
                    "author": c.commit.author.name,
                    "message": c.commit.message,
                    "sha": c.sha[:7]
                })
        except:
            pass
            
        return json.dumps(data_package, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)})

if __name__ == "__main__":
    mcp.run()