# src/servers/jira_server.py
import os
import json
from dotenv import load_dotenv
from jira import JIRA
from fastmcp import FastMCP

mcp = FastMCP("jira-server")
load_dotenv()

@mcp.tool()
def fetch_jira_issues(project_key: str, days_lookback: int = 30) -> str:
    url = os.getenv("JIRA_URL")
    email = os.getenv("JIRA_EMAIL")
    token = os.getenv("JIRA_API_TOKEN")

    if not (url and email and token):
        return json.dumps({"error": "Missing Jira Credentials"})

    try:
        jira = JIRA(server=url, basic_auth=(email, token))
        
        # Added project, timeoriginalestimate, aggregatetimespent, issuetype
        jql = f'project = {project_key} AND (assignee = currentUser() OR worklogAuthor = currentUser()) AND updated >= -{days_lookback}d ORDER BY updated DESC'
        issues = jira.search_issues(jql, maxResults=50, fields="summary,description,status,priority,updated,project,timeoriginalestimate,aggregatetimespent,issuetype,worklog")
        
        data = []
        for issue in issues:
            worklogs = jira.worklogs(issue.id)
            user_worklogs = []
            for wl in worklogs:
                user_worklogs.append({
                    "date": wl.started[:10], 
                    "time_spent": wl.timeSpentSeconds / 3600 if hasattr(wl, 'timeSpentSeconds') else 0, # Convert to hours
                    "comment": getattr(wl, 'comment', '')
                })

            desc = issue.fields.description if issue.fields.description else ""
            
            # Safe extraction of time data
            orig_est = issue.fields.timeoriginalestimate / 3600 if issue.fields.timeoriginalestimate else 0
            time_spent_total = issue.fields.aggregatetimespent / 3600 if issue.fields.aggregatetimespent else 0

            data.append({
                "key": issue.key,
                "project_name": issue.fields.project.name,
                "summary": issue.fields.summary,
                "description": desc,
                "type": issue.fields.issuetype.name,
                "status": issue.fields.status.name,
                "original_estimate": orig_est,
                "total_spent": time_spent_total,
                "worklogs": user_worklogs
            })
            
        return json.dumps({"jira_issues": data}, default=str)

    except Exception as e:
        return json.dumps({"error": f"Jira Error: {str(e)}"})
if __name__ == "__main__":
    mcp.run()