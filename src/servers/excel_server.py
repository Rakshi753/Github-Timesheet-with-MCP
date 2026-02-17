from fastmcp import FastMCP
import pandas as pd
import os
import json
from typing import List, Dict

mcp = FastMCP("excel-server")

@mcp.tool()
def save_github_data_to_excel(user_commits: List[Dict], filename: str) -> str:
    """Saves Global GitHub data."""
    df_user = pd.DataFrame(user_commits)
    
    # Ensure columns exist
    if not df_user.empty:
        cols = ["date", "repo", "author", "message", "ai_summary", "sha"]
        if "ai_summary" not in df_user.columns: df_user["ai_summary"] = ""
        existing_cols = [c for c in cols if c in df_user.columns]
        df_user = df_user[existing_cols]

    file_path = os.path.abspath(filename)
    try:
        # Create fresh file or overwrite existing
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            if not df_user.empty:
                df_user.to_excel(writer, sheet_name="GitHub_Activity", index=False)
            else:
                pd.DataFrame({"Status": ["No Data"]}).to_excel(writer, sheet_name="GitHub_Activity")
        return file_path
    except Exception as e:
        return f"Error: {e}"

@mcp.tool()
def save_jira_data_to_excel(jira_data: List[Dict], filename: str) -> str:
    """Appends Jira data."""
    if not jira_data: return "No Jira data."
    
    rows = []
    for issue in jira_data:
        desc = issue.get("description", "")
        proj_name = issue.get("project_name", "")
        proj_key = issue.get("key", "").split('-')[0]
        final_project = proj_name if proj_name else proj_key

        if issue["worklogs"]:
            for wl in issue["worklogs"]:
                rows.append({
                    "Date": wl["date"],
                    "Key": issue["key"],
                    "Project": final_project, 
                    "Summary": issue["summary"],
                    "Description": desc,
                    "Time Spent": wl["time_spent"]
                })
        else:
            rows.append({
                "Date": issue["last_updated"],
                "Key": issue["key"],
                "Project": final_project,
                "Summary": issue["summary"],
                "Description": desc,
                "Time Spent": issue.get("total_spent", 0)
            })

    df = pd.DataFrame(rows)
    file_path = os.path.abspath(filename)
    
    try:
        with pd.ExcelWriter(file_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            df.to_excel(writer, sheet_name="Jira_Activity", index=False)
        return file_path
    except Exception as e:
        return f"Error saving Jira: {e}"

@mcp.tool()
def get_data_date_range(file_path: str) -> str:
    if not os.path.exists(file_path): return "Error: File not found"
    all_dates = []
    try:
        df_git = pd.read_excel(file_path, sheet_name="GitHub_Activity")
        all_dates.extend(pd.to_datetime(df_git['date']).tolist())
    except: pass
    try:
        df_jira = pd.read_excel(file_path, sheet_name="Jira_Activity")
        all_dates.extend(pd.to_datetime(df_jira['Date']).tolist())
    except: pass
    
    if not all_dates: return "No date data available"
    return f"{min(all_dates).strftime('%Y-%m-%d')}|{max(all_dates).strftime('%Y-%m-%d')}"

@mcp.tool()
def read_unified_date_range(file_path: str, start_date: str, end_date: str) -> str:
    combined_context = ""
    
    # GitHub
    try:
        df_git = pd.read_excel(file_path, sheet_name="GitHub_Activity")
        df_git['date'] = pd.to_datetime(df_git['date'])
        mask = (df_git['date'] >= start_date) & (df_git['date'] <= end_date)
        git_filtered = df_git.loc[mask].sort_values('date')
        
        if not git_filtered.empty:
            git_filtered['date'] = git_filtered['date'].dt.strftime('%Y-%m-%d')
            combined_context += "### GITHUB ACTIVITY:\n"
            combined_context += git_filtered[["date", "repo", "ai_summary"]].to_markdown(index=False)
            combined_context += "\n\n"
    except: pass

    # Jira
    try:
        df_jira = pd.read_excel(file_path, sheet_name="Jira_Activity")
        df_jira['Date'] = pd.to_datetime(df_jira['Date'])
        # Get RECENT Jira items for gap filling context
        mask = (df_jira['Date'] >= start_date) & (df_jira['Date'] <= end_date)
        jira_filtered = df_jira.loc[mask].sort_values('Date')
        
        if not jira_filtered.empty:
            jira_filtered['Date'] = jira_filtered['Date'].dt.strftime('%Y-%m-%d')
            jira_filtered['Description'] = jira_filtered['Description'].fillna("").astype(str).apply(lambda x: x[:200].replace('\n', ' '))
            combined_context += "### JIRA ACTIVITY:\n"
            combined_context += jira_filtered[["Date", "Project", "Key", "Summary", "Description"]].to_markdown(index=False)
        else:
            # Fallback: Fetch last 3 items for context
            last_3 = df_jira.sort_values('Date', ascending=False).head(3)
            if not last_3.empty:
                last_3['Date'] = last_3['Date'].dt.strftime('%Y-%m-%d')
                last_3['Description'] = last_3['Description'].fillna("").astype(str).apply(lambda x: x[:200].replace('\n', ' '))
                combined_context += "\n### RECENT (PAST) JIRA CONTEXT (For Gap Filling Only):\n"
                combined_context += last_3[["Date", "Project", "Key", "Summary", "Description"]].to_markdown(index=False)
    except: pass
        
    return combined_context

@mcp.tool()
def generate_final_timesheet(
    ai_enrichment_json: str, 
    employee_id: str, 
    employee_name: str, 
    source_file_path: str,
    start_date: str,
    num_days: int
) -> str:
    """
    Generates Timesheet by merging Source Data (Excel) with AI Descriptions (JSON).
    """
    try:
        # 1. Parse AI Enrichment Data (Date -> {Desc, Remarks})
        try:
            ai_data = json.loads(ai_enrichment_json)
        except:
            ai_data = {}

        # 2. Load Source Data
        xls = pd.ExcelFile(source_file_path)
        
        # Load GitHub
        if "GitHub_Activity" in xls.sheet_names:
            df_gh = pd.read_excel(xls, "GitHub_Activity")
            # Normalize Date
            if 'date' in df_gh.columns:
                df_gh['date'] = pd.to_datetime(df_gh['date']).dt.strftime('%Y-%m-%d')
        else:
            df_gh = pd.DataFrame(columns=['date', 'message'])

        # Load Jira
        if "Jira_Activity" in xls.sheet_names:
            df_jr = pd.read_excel(xls, "Jira_Activity")
            # Normalize Date (Handle 'Date' or 'created' or 'last_updated')
            date_col = next((c for c in ['Date', 'created', 'last_updated'] if c in df_jr.columns), None)
            if date_col:
                df_jr['date'] = pd.to_datetime(df_jr[date_col]).dt.strftime('%Y-%m-%d')
            else:
                df_jr['date'] = []
        else:
            df_jr = pd.DataFrame(columns=['date', 'Summary', 'Project'])

        # 3. Generate Rows for Every Target Date
        start_dt = pd.to_datetime(start_date)
        target_dates = [(start_dt + pd.Timedelta(days=i)).strftime("%Y-%m-%d") for i in range(num_days)]
        
        final_rows = []

        for d in target_dates:
            # Filter Data for this Date
            gh_day = df_gh[df_gh['date'] == d] if not df_gh.empty else pd.DataFrame()
            jr_day = df_jr[df_jr['date'] == d] if not df_jr.empty else pd.DataFrame()
            
            # --- INTELLIGENT MERGING LOGIC ---
            
            # A. Determine Project & Task Summary
            project = "Internal Development"
            task_summary = "General Development"
            jira_hours = 0

            if not jr_day.empty:
                # Prefer Jira Data
                row = jr_day.iloc[0]
                project = row.get('Project', row.get('project_name', "Internal Development"))
                task_summary = row.get('Summary', "General Development")
                # Sum time spent if available
                if 'Time Spent' in jr_day.columns:
                    jira_hours = jr_day['Time Spent'].sum()
            elif not gh_day.empty:
                # Fallback to GitHub
                msg = gh_day.iloc[0]['message']
                task_summary = f"Code Implementation: {msg[:50]}..."

            # B. Get AI Content (Description & Remarks)
            # We look up the date in the JSON passed from Client
            ai_entry = ai_data.get(d, {})
            description = ai_entry.get("description", f"Performed {task_summary.lower()}.")
            remarks = ai_entry.get("remarks", "Completed assigned tasks.")

            # Construct Row
            final_rows.append({
                "Employee": employee_id,
                "Employee Name": employee_name,
                "Date": d,
                "Project": project,
                "Activity / Process / Transaction": "Development",
                "Task": task_summary,
                "Task Description": description, # FROM AI
                "Authorized Hours": 4, "Authorized Units": 3, "UOM": "a", "Billable": "yes",
                "Site": "Onsite", "Role": "Software Engineer", "Location": "chennai",
                "Authorizer Remarks": "good", "Work Item": "001", "Analysis Code": "nice",
                "Remarks": remarks, # FROM AI
                "Status": "done",
                "Booked Hours": 8, "Booked Units": 3,
                "Planned Hours": jira_hours,
                "Balance Hours": 0
            })

        # 4. Save to Excel
        df_final = pd.DataFrame(final_rows)
        with pd.ExcelWriter(source_file_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
            df_final.to_excel(writer, sheet_name="Final_Timesheet", index=False)
            
        # Optional: Save copy
        new_path = source_file_path.replace(".xlsx", "_Final_Timesheet.xlsx")
        df_final.to_excel(new_path, index=False)
        return new_path

    except Exception as e:
        import traceback
        return f"Error: {e}\n{traceback.format_exc()}"


if __name__ == "__main__":
    mcp.run()