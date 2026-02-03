from fastmcp import FastMCP
import pandas as pd
import os
from datetime import datetime, timedelta
from typing import List, Dict

mcp = FastMCP("excel-server")

@mcp.tool()
def save_github_data_to_excel(user_commits: List[Dict], main_commits: List[Dict], filename: str) -> str:
    """Saves data to Excel with 'ai_summary' column."""
    # ... (Same saving logic as before) ...
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
    Returns the First Push Date and Latest Push Date found in the Excel file.
    Format: "YYYY-MM-DD to YYYY-MM-DD"
    """
    if not os.path.exists(file_path): return "Error: File not found"
    try:
        df = pd.read_excel(file_path, sheet_name="Target_User_Activity")
        if df.empty: return "No data found"
        
        df['date'] = pd.to_datetime(df['date'])
        min_date = df['date'].min().strftime('%Y-%m-%d')
        max_date = df['date'].max().strftime('%Y-%m-%d')
        return f"{min_date}|{max_date}"
    except:
        return "No date data available"

@mcp.tool()
def read_specific_date_range(file_path: str, start_date: str, end_date: str) -> str:
    """
    Reads Excel and returns commits ONLY for the specific date range (Inclusive).
    """
    if not os.path.exists(file_path): return "Error: File not found"
    try:
        df = pd.read_excel(file_path, sheet_name="Target_User_Activity")
        df['date'] = pd.to_datetime(df['date'])
        
        # Filter Range
        mask = (df['date'] >= start_date) & (df['date'] <= end_date)
        filtered = df.loc[mask].sort_values('date')
        
        if filtered.empty: return "No commits found in this specific 5-day window."
        
        filtered['date'] = filtered['date'].dt.strftime('%Y-%m-%d')
        
        # Return AI Summary if available
        if "ai_summary" in filtered.columns:
            return filtered[["date", "branch_context", "ai_summary"]].to_markdown(index=False)
        else:
            return filtered[["date", "branch_context", "message"]].to_markdown(index=False)
    except Exception as e:
        return f"Error reading range: {str(e)}"

if __name__ == "__main__":
    mcp.run()