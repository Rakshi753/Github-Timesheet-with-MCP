from typing import TypedDict, Dict, Optional

class AgentState(TypedDict):
    repo_name: str
    username: str
    filter_days: Optional[int]
    
    # Internal Data passed between nodes
    excel_file_path: Optional[str]
    raw_data_package: Optional[Dict]
    
    # Final Output
    final_timesheet: Optional[str]