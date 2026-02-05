from fastmcp import FastMCP
import pandas as pd
import os
from datetime import datetime, timedelta
from typing import List, Dict

mcp = FastMCP("excel-server")

@mcp.tool()
def save_github_data_to_excel(user_commits: List[Dict], main_commits: List[Dict], filename: str) -> str:
    """Saves data to Excel with 'ai_summary' column."""
    df_user = pd.DataFrame(user_commits)
    if not df_user.empty:
        cols = ["date", "author", "message", "branch_context", "ai_summary", "sha"]
        if "ai_summary" not in df_user.columns: df_user["ai_summary"] = ""
        df_user = df_user[[c for c in cols if c in df_user.columns]]
    
    df_main = pd.DataFrame(main_commits)
    if not df_main.empty:
        cols = ["date", "author", "message", "sha"]
        df_main = df_main[[c for c in cols if c in df_main.columns]]

    file_path = os.path.abspath(filename)
    try:
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            written = False
            if not df_user.empty:
                df_user.to_excel(writer, sheet_name="Target_User_Activity", index=False)
                written = True
            if not df_main.empty:
                df_main.to_excel(writer, sheet_name="Main_Branch_Log", index=False)
                written = True
            if not written:
                pd.DataFrame({"Status": ["No Data"]}).to_excel(writer, sheet_name="No_Data_Found")
        return file_path
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
def get_data_date_range(file_path: str) -> str:
    """
    Returns the date range from EITHER GitHub or Jira data (or both).
    """
    if not os.path.exists(file_path): return "Error: File not found"
    
    all_dates = []
    
    # 1. Try GitHub Dates
    try:
        df_git = pd.read_excel(file_path, sheet_name="Target_User_Activity")
        if not df_git.empty and 'date' in df_git.columns:
            all_dates.extend(pd.to_datetime(df_git['date']).tolist())
    except:
        pass # Sheet might not exist
        
    # 2. Try Jira Dates
    try:
        df_jira = pd.read_excel(file_path, sheet_name="Jira_Activity")
        if not df_jira.empty and 'Date' in df_jira.columns:
            all_dates.extend(pd.to_datetime(df_jira['Date']).tolist())
    except:
        pass # Sheet might not exist

    if not all_dates:
        return "No date data available"
        
    # Calculate Range
    min_date = min(all_dates).strftime('%Y-%m-%d')
    max_date = max(all_dates).strftime('%Y-%m-%d')
    return f"{min_date}|{max_date}"

@mcp.tool()
def read_unified_date_range(file_path: str, start_date: str, end_date: str) -> str:
    """
    Reads BOTH GitHub and Jira sheets for the specific date range.
    Returns a combined Markdown string.
    """
    if not os.path.exists(file_path): return "Error: File not found"
    
    combined_context = ""
    
    # 1. Read GitHub Data
    try:
        df_git = pd.read_excel(file_path, sheet_name="Target_User_Activity")
        df_git['date'] = pd.to_datetime(df_git['date'])
        mask = (df_git['date'] >= start_date) & (df_git['date'] <= end_date)
        git_filtered = df_git.loc[mask].sort_values('date')
        
        if not git_filtered.empty:
            git_filtered['date'] = git_filtered['date'].dt.strftime('%Y-%m-%d')
            col = "ai_summary" if "ai_summary" in git_filtered.columns else "message"
            # Add Source Tag
            git_filtered['source'] = "[GitHub]"
            combined_context += "### GITHUB ACTIVITY:\n"
            combined_context += git_filtered[["date", "source", "branch_context", col]].to_markdown(index=False)
            combined_context += "\n\n"
    except:
        combined_context += "No GitHub data found.\n\n"

    # 2. Read Jira Data
    try:
        df_jira = pd.read_excel(file_path, sheet_name="Jira_Activity")
        # Ensure column names match what we saved (Date, Key, Summary, etc.)
        df_jira['Date'] = pd.to_datetime(df_jira['Date'])
        mask = (df_jira['Date'] >= start_date) & (df_jira['Date'] <= end_date)
        jira_filtered = df_jira.loc[mask].sort_values('Date')
        
        if not jira_filtered.empty:
            jira_filtered['Date'] = jira_filtered['Date'].dt.strftime('%Y-%m-%d')
            # Add Source Tag
            jira_filtered['Source'] = "[Jira]"
            combined_context += "### JIRA ACTIVITY:\n"
            # Select relevant columns: Date, Source, Key, Summary, Status
            combined_context += jira_filtered[["Date", "Source", "Key", "Summary", "Details"]].to_markdown(index=False)
            combined_context += "\n\n"
    except:
        combined_context += "No Jira data found.\n"
        
    return combined_context if combined_context.strip() else "No activity found in either source."
    

@mcp.tool()
def save_jira_data_to_excel(jira_data: List[Dict], filename: str) -> str:
    """
    Appends Jira data to a new sheet 'Jira_Activity' in the existing Excel file.
    Creates the file if it doesn't exist.
    """
    if not jira_data: return "No Jira data to save."
    
    # Flatten the data for Excel (One row per issue)
    rows = []
    for issue in jira_data:
        # If there are worklogs, create a row for each worklog (more detailed)
        if issue["worklogs"]:
            for wl in issue["worklogs"]:
                rows.append({
                    "Date": wl["date"],
                    "Key": issue["key"],
                    "Type": "Worklog",
                    "Summary": issue["summary"],
                    "Status": issue["status"],
                    "Time Spent": wl["time_spent"],
                    "Details": wl["comment"] or "Logged time",
                    "URL": issue["url"]
                })
        else:
            # Just the issue status
            rows.append({
                "Date": issue["last_updated"],
                "Key": issue["key"],
                "Type": "Issue Update",
                "Summary": issue["summary"],
                "Status": issue["status"],
                "Time Spent": "",
                "Details": "Status update",
                "URL": issue["url"]
            })

    df = pd.DataFrame(rows)
    file_path = os.path.abspath(filename)
    
    try:
        # Check if file exists to decide mode
        mode = 'a' if os.path.exists(file_path) else 'w'
        if_sheet_exists = 'replace' if mode == 'a' else None
        
        with pd.ExcelWriter(file_path, engine='openpyxl', mode=mode, if_sheet_exists=if_sheet_exists) as writer:
            df.to_excel(writer, sheet_name="Jira_Activity", index=False)
            
        return file_path
    except Exception as e:
        return f"Error saving Jira sheet: {e}"
if __name__ == "__main__":
    mcp.run()