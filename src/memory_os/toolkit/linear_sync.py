import os
import re
import json
import urllib.request
from pathlib import Path
from memory_os.core.logger import get_logger

logger = get_logger(__name__)

LINEAR_GRAPHQL_URL = "https://api.linear.app/graphql"

def get_linear_team_id(api_key: str) -> str:
    query = """
    query {
      teams {
        nodes {
          id
        }
      }
    }
    """
    data = execute_graphql(api_key, query)
    teams = data.get("data", {}).get("teams", {}).get("nodes", [])
    if not teams:
        raise ValueError("No teams found in Linear workspace.")
    return teams[0]["id"]

def get_linear_issues(api_key: str) -> dict:
    query = """
    query($after: String) {
      issues(after: $after) {
        nodes {
          id
          title
          state {
            type
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """
    issues = []
    has_next_page = True
    after_cursor = None
    
    while has_next_page:
        variables = {}
        if after_cursor:
            variables["after"] = after_cursor
        data = execute_graphql(api_key, query, variables)
        if not data or not isinstance(data, dict):
            break
        data_body = data.get("data")
        if not data_body or not isinstance(data_body, dict):
            break
        issues_data = data_body.get("issues")
        if not issues_data or not isinstance(issues_data, dict):
            break
        nodes = issues_data.get("nodes", [])
        issues.extend(nodes)
        
        page_info = issues_data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        after_cursor = page_info.get("endCursor")
        
    return {issue["title"].strip(): issue for issue in issues if isinstance(issue, dict) and "title" in issue}

def create_linear_issue(api_key: str, team_id: str, title: str):
    query = """
    mutation IssueCreate($title: String!, $teamId: String!) {
      issueCreate(input: { title: $title, teamId: $teamId }) {
        issue {
          id
          title
        }
      }
    }
    """
    variables = {"title": title, "teamId": team_id}
    execute_graphql(api_key, query, variables)

def execute_graphql(api_key: str, query: str, variables: dict = None) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Authorization": api_key
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
        
    req = urllib.request.Request(
        LINEAR_GRAPHQL_URL, 
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        logger.error(f"Linear API error: {e.read().decode('utf-8')}")
        raise

def sync_roadmap_with_linear(root_dir: Path):
    api_key = os.environ.get("LINEAR_API_KEY")
    if not api_key:
        logger.error("LINEAR_API_KEY is not set in environment. Skipping sync.")
        return False
        
    roadmap_path = root_dir / "agent_context" / "GLOBAL_ROADMAP.md"
    if not roadmap_path.exists():
        logger.error(f"{roadmap_path} not found.")
        return False
        
    logger.info("Syncing roadmap with Linear...")
    
    try:
        team_id = get_linear_team_id(api_key)
        existing_issues = get_linear_issues(api_key)
    except Exception as e:
        logger.error(f"Failed to communicate with Linear API: {e}")
        return False
        
    with open(roadmap_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    task_pattern = re.compile(r"^(\s*)-\s+\[([ xX])\]\s+(.*?)\s*$")
    
    updated_lines = []
    created_count = 0
    updated_count = 0
    
    for line in lines:
        match = task_pattern.match(line)
        if match:
            indent = match.group(1)
            checked = match.group(2).lower() == 'x'
            title = match.group(3)
            
            # Remove bolding or formatting from title for matching
            clean_title = re.sub(r'[*_`]', '', title).strip()
            
            if clean_title in existing_issues:
                # Task exists in Linear, sync state
                issue = existing_issues[clean_title]
                is_completed_in_linear = issue.get("state", {}).get("type") in ["completed", "canceled"]
                
                if is_completed_in_linear and not checked:
                    # Mark as checked in markdown
                    updated_lines.append(f"{indent}- [x] {title}\n")
                    updated_count += 1
                elif not is_completed_in_linear and checked:
                    # Mark as unchecked in markdown
                    updated_lines.append(f"{indent}- [ ] {title}\n")
                    updated_count += 1
                else:
                    updated_lines.append(line)
            else:
                # Task does not exist in Linear, create it
                logger.info(f"Creating Linear issue: {clean_title}")
                try:
                    create_linear_issue(api_key, team_id, clean_title)
                    created_count += 1
                except Exception as e:
                    logger.error(f"Failed to create issue '{clean_title}': {e}")
                updated_lines.append(line)
        else:
            updated_lines.append(line)
            
    if updated_count > 0:
        with open(roadmap_path, "w", encoding="utf-8") as f:
            f.writelines(updated_lines)
            
    logger.info(f"Linear sync complete. Created {created_count} issues, updated {updated_count} statuses.")
    return True
