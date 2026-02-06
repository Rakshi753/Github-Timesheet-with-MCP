import os
import json
from dotenv import load_dotenv
from jira import JIRA
from fastmcp import FastMCP

mcp = FastMCP("jira-server")
load_dotenv()

@mcp.tool()
def fetch_jira_issues(project_key: str, days_lookback: int = 30) -> str:
    """
    Fetches Jira issues and worklogs for the current user in a specific project.
    """
    # 1. Auth
    url = os.getenv("JIRA_URL")
    email = os.getenv("JIRA_EMAIL")
    token = os.getenv("JIRA_API_TOKEN")

    if not (url and email and token):
        return json.dumps({"error": "Missing Jira Credentials in .env"})

    try:
        # 2. Connect
        jira = JIRA(server=url, basic_auth=(email, token))
        
        # 3. Search (JQL)
        # Find issues in PROJECT updated recently where I am Assignee OR Worklog Author
        jql = f'project = {project_key} AND (assignee = currentUser() OR worklogAuthor = currentUser()) AND updated >= -{days_lookback}d ORDER BY updated DESC'
        
        issues = jira.search_issues(jql, maxResults=50, fields="summary,status,priority,updated,created,assignee,worklog")
        
        data = []
        
        for issue in issues:
            # Get Worklogs (Time spent)
            worklogs = jira.worklogs(issue.id)
            user_worklogs = []
            for wl in worklogs:
                # Filter strictly for the API user if possible, or just grab all for context
                # For simplicity, we grab time spent
                user_worklogs.append({
                    "date": wl.started[:10], # "2023-10-05"
                    "time_spent": wl.timeSpent,
                    "comment": getattr(wl, 'comment', '')
                })

            data.append({
                "key": issue.key,
                "summary": issue.fields.summary,
                "status": issue.fields.status.name,
                "priority": issue.fields.priority.name,
                "last_updated": issue.fields.updated[:10],
                "worklogs": user_worklogs,
                "url": f"{url}/browse/{issue.key}"
            })
            
        return json.dumps({"jira_issues": data}, default=str)

    except Exception as e:
        return json.dumps({"error": f"Jira Error: {str(e)}"})

if __name__ == "__main__":
    mcp.run()