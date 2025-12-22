"""
This file is for Github Actions log fetcher
- Authenticate with github
- fetch failed logs from repo
- download and save raw log files.
"""

import os
import zipfile
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from github import Github, Auth, GithubException
from github.WorkflowRun import WorkflowRun

load_dotenv()

GITHUB_TOKEN : Optional[str] = os.getenv("GITHUB_ACCESS_TOKEN")

# default o/p directory for logs
OUTPUT_DIR = Path("output")


# helper functions 

def ensure_output_dir() -> Path : 
    """Ensure output directory exists."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR

def validate_token() -> None :
    """Validate that the GitHub token is set."""
    if not GITHUB_TOKEN :
        raise ValueError("GITHUB_ACCESS_TOKEN is not set in environment variables.")
    
# Main 

def get_github_client() -> Github:
    """Get authenticated Github client."""
    validate_token()
    auth = Auth.Token(GITHUB_TOKEN)
    client = Github(auth=auth)
    
    try:
        user = client.get_user()
        print(f"Authenticated as : {user.login}")
    except Exception as e : 
        raise ValueError(f"Auth failed : {e.data.get('message', str(e))}")
    
    return client

def get_latest_workflow_run(repo_name : str) -> Optional[WorkflowRun]:
    """
    Fetch the most recent workflow run from a repository.
    
    OPTIMIZED: Gets ONLY the latest run, doesn't iterate through all.
    
    Args:
        repo_name: Repository in "owner/repo" format
        
    Returns:
        WorkflowRun: The latest run (could be success or failure)
        None: If no workflow runs exist
    """
    
    client = get_github_client()
    
    try:
        repo = client.get_repo(repo_name)
    except GithubException as e :
        if e.status == 404:
            raise ValueError(f"Repository '{repo_name}' not found. Check the name and your access.")
        raise ValueError(f"GitHub API error: {e.data.get('message', str(e))}")
    
    workflow_runs = repo.get_workflow_runs(status="completed")
    print("Searching for failed workflow runs......")
    
    try:
        latest_run = next(iter(workflow_runs))
    except StopIteration:
        print("ℹ️  No workflow runs found in this repository.")
        return None
    
    return latest_run

def download_worflow_logs(run : WorkflowRun, output_filename: str = "build_log.txt") -> Path:
    """Download logs for a given workflow run and save to output file.
    
    Args:
        run (WorkflowRun): The workflow run to fetch logs for.
        output_filename (str): The name of the output log file.
        
    Returns:
        Path : Path to saved file
        
    How GitHub logs work:
    1. Logs are provided as a ZIP file containing multiple log files
    2. Each job in the workflow has its own log file
    3. We extract and combine them into a single readable file
    """
    
    ensure_output_dir()
    output_path = OUTPUT_DIR / output_filename
    print(f"Downloading logs for run ID {run.id}...")
    
    # Get the logs url
    logs_url = run.logs_url
    
    # Download the logs zip file.    
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    response = requests.get(logs_url, headers=headers, stream=True)
    
    if response.status_code != 200:
        raise RuntimeError(
            f"❌ Failed to download logs. Status: {response.status_code}\n"
            f"This might happen if logs have expired (GitHub keeps them for 90 days)."
        )
    
    # process zip file.
    
    combined_logs = []
    
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            print(f"   Found {len(zip_file.namelist())} log files in archive")
            
            for filename in sorted(zip_file.namelist()):
                # Read each log file
                with zip_file.open(filename) as log_file:
                    content = log_file.read().decode("utf-8", errors="replace")
                    
                    # Adding a header to identify which job this is from
                    combined_logs.append(f"\n{'='*80}")
                    combined_logs.append(f"📄 LOG FILE: {filename}")
                    combined_logs.append(f"{'='*80}\n")
                    combined_logs.append(content)
        
    except zipfile.BadZipFile:
        # Sometimes GitHub returns plain text instead of ZIP
        combined_logs.append(response.text)
        
    full_log_content = "\n".join(combined_logs)
    output_path.write_text(full_log_content, encoding="utf-8")
    
    # Calculate some stats... just to check the size and count
    line_count = full_log_content.count("\n")
    file_size_kb = len(full_log_content.encode("utf-8")) / 1024
    
    print(f"Logs saved to: {output_path.absolute()}")
    print(f"Size: {file_size_kb:.1f} KB ({line_count} lines)")
    
    return output_path
    
    
# Main execution func

def fetch_failed_build_logs(repo_name : str) -> Optional[Path]:
    """ 
    Main function: Fetch logs from the latest failed build.
    
    This is the primary interface for this module. It:
    1. Finds the latest failed workflow run
    2. Downloads the logs
    3. Saves them to a file
    
    Args:
        repo_name: Repository in "owner/repo" format
        
    Returns:
        Path to the log file, or None if no failures found
    """
    
    latest_run  = get_latest_workflow_run(repo_name=repo_name)
    
    if not latest_run :
        return None
    
    if latest_run.conclusion == "success":
        print("Your CI/CD pipeline is healthy. Nothing to analyze.")
        return None
    
    elif latest_run.conclusion == "failure":
        print("Build failed! Proceeding to download logs for analysis...")
        
        log_path = download_worflow_logs(latest_run)
        return log_path
    
    else:
        print(f"\n⚠️  Build conclusion is '{latest_run.conclusion}' (not a failure).")
        print("   No analysis needed.")
        return None
    
if __name__ == "__main__":
    
    TEST_REPO = "Yasshu55/Test-repo"
    
    try:
        result = fetch_failed_build_logs(TEST_REPO)
        
        if result:
            print(f"🎉 Success! Check the log file at: {result}")
        else:
            print("ℹ️  No failures to analyze. Try a repo with failed CI runs.")
            
    except ValueError as e:
        print(f"\n{e}")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        raise

    
    