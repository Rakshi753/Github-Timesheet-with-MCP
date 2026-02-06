from typing import TypedDict, Dict, Optional

class AgentState(TypedDict):
    repo_name: str
    username: str
    jira_project: Optional[str] # <--- NEW
    filter_days: Optional[int]
    excel_file_path: Optional[str]
    raw_data_package: Optional[Dict]
    final_timesheet: Optional[str]