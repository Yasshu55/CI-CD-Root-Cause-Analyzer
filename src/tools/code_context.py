"""
code_context.py - GitHub Code Context Fetcher

This module fetches relevant code files from a GitHub repository
to provide context for debugging CI/CD failures.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from github import Github, Auth, GithubException

load_dotenv()
GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")


class CodeFile(BaseModel):
    """Represents a file from the repository."""
    path: str = Field(description="File path in the repository")
    content: str = Field(description="File content (may be truncated)")
    size_bytes: int = Field(description="File size in bytes")
    truncated: bool = Field(
        default=False,
        description="Whether content was truncated due to size"
    )


class RepoContext(BaseModel):
    """Context gathered from a repository."""
    repo_name: str = Field(description="Repository name (owner/repo)")
    files: list[CodeFile] = Field(default_factory=list)
    structure: list[str] = Field(
        default_factory=list,
        description="List of file paths in the repo"
    )
    readme_content: Optional[str] = Field(
        default=None,
        description="README content if available"
    )
    requirements: Optional[str] = Field(
        default=None,
        description="requirements.txt content if available"
    )
    workflow_files: list[CodeFile] = Field(
        default_factory=list,
        description="GitHub Actions workflow files"
    )



class CodeContextFetcher:
    """
    Fetches code context from a GitHub repository.
    
    This provides the Research Agent with relevant code files
    to understand the project structure and find the error source.
    
    Usage:
        fetcher = CodeContextFetcher("owner/repo")
        context = fetcher.get_context()
        print(context.requirements)
    """
    
    # Maximum file size to fetch (100KB)
    MAX_FILE_SIZE = 100 * 1024
    
    # Maximum content length to keep (for LLM context limits)
    MAX_CONTENT_LENGTH = 10000

    PRIORITY_FILES = [
        "requirements.txt",
        "setup.py",
        "pyproject.toml",
        "package.json",
        "Pipfile",
        "poetry.lock",
        "README.md",
        "README.rst",
        ".python-version",
        "runtime.txt",
        "Dockerfile",
        "docker-compose.yml",
    ]
    
    def __init__(self, repo_name: str):

        if not GITHUB_ACCESS_TOKEN:
            raise ValueError("GITHUB_ACCESS_TOKEN not found in environment")
        
        self.repo_name = repo_name
        auth = Auth.Token(GITHUB_ACCESS_TOKEN)
        self.github = Github(auth=auth)
        
        try:
            self.repo = self.github.get_repo(repo_name)
            print(f" Connected to repository: {repo_name}")
        except GithubException as e:
            raise ValueError(f" Could not access repository: {e}")
    
    def get_file_content(self, file_path: str) -> Optional[CodeFile]:
        """
        Fetch content of a specific file.
        
        Args:
            file_path: Path to the file in the repository
            
        Returns:
            CodeFile with content, or None if file doesn't exist
        """
        try:
            file_content = self.repo.get_contents(file_path)
            
            # Check if it's a file (not a directory)
            if file_content.type != "file":
                return None
            
            if file_content.size > self.MAX_FILE_SIZE:
                print(f"  File too large, skipping: {file_path}")
                return None
            
            try:
                content = file_content.decoded_content.decode("utf-8")
            except UnicodeDecodeError:
                print(f" Binary file, skipping: {file_path}")
                return None
            
            truncated = False
            if len(content) > self.MAX_CONTENT_LENGTH:
                content = content[:self.MAX_CONTENT_LENGTH] + "\n\n... [truncated]"
                truncated = True
            
            return CodeFile(
                path=file_path,
                content=content,
                size_bytes=file_content.size,
                truncated=truncated
            )
            
        except GithubException as e:
            if e.status == 404:
                return None
            print(f" Error fetching {file_path}: {e}")
            return None
    
    def get_directory_structure(self, path: str = "", max_depth: int = 3) -> list[str]:
        """
        Get the directory structure of the repository.
        
        Args:
            path: Starting path
            max_depth: Maximum recursion depth
            
        Returns:
            List of file paths
        """
        if max_depth <= 0:
            return []
        
        files = []
        
        try:
            contents = self.repo.get_contents(path)
            
            for content in contents:
                if content.type == "file":
                    files.append(content.path)
                elif content.type == "dir":
                    skip_dirs = [
                        "node_modules", ".git", "__pycache__", ".venv",
                        "venv", "dist", "build", ".tox", ".pytest_cache",
                        ".mypy_cache", "htmlcov", ".eggs", "*.egg-info"
                    ]
                    
                    if not any(skip in content.path for skip in skip_dirs):
                        files.append(content.path + "/")
                        files.extend(
                            self.get_directory_structure(content.path, max_depth - 1)
                        )
                        
        except GithubException as e:
            print(f" Error reading directory {path}: {e}")
        
        return files
    
    def get_workflow_files(self) -> list[CodeFile]:
        """
        Fetch GitHub Actions workflow files.
        
        These are crucial for debugging CI/CD failures.
        """
        workflow_files = []
        workflow_path = ".github/workflows"
        
        try:
            contents = self.repo.get_contents(workflow_path)
            
            for content in contents:
                if content.type == "file" and content.path.endswith((".yml", ".yaml")):
                    file = self.get_file_content(content.path)
                    if file:
                        workflow_files.append(file)
                        print(f"  Found workflow: {content.path}")
                        
        except GithubException:
            print(f"   No workflow files found in {workflow_path}")
        
        return workflow_files
    
    def get_context(
        self,
        include_structure: bool = True,
        include_priority_files: bool = True,
        additional_files: list[str] = None
    ) -> RepoContext:
        """
        Gather comprehensive context from the repository.
        
        This is the main method that collects all relevant information.
        
        Args:
            include_structure: Whether to fetch directory structure
            include_priority_files: Whether to fetch priority files
            additional_files: Extra files to fetch
            
        Returns:
            RepoContext with all gathered information
        """
        print(f"\n Gathering context from: {self.repo_name}")
        print("-" * 40)
        
        files = []
        structure = []
        readme_content = None
        requirements = None
        
        if include_structure:
            print(" Fetching directory structure...")
            structure = self.get_directory_structure(max_depth=2)
            print(f"   Found {len(structure)} items")
        
        # Get priority files
        if include_priority_files:
            print("Fetching priority files...")
            for file_path in self.PRIORITY_FILES:
                file = self.get_file_content(file_path)
                if file:
                    files.append(file)
                    print(f"   ✓ {file_path}")
                    
                    # Special handling
                    if "readme" in file_path.lower():
                        readme_content = file.content
                    elif file_path == "requirements.txt":
                        requirements = file.content
        
        if additional_files:
            print("Fetching additional files...")
            for file_path in additional_files:
                file = self.get_file_content(file_path)
                if file:
                    files.append(file)
                    print(f"   ✓ {file_path}")
        
        print("Fetching workflow files...")
        workflow_files = self.get_workflow_files()
        
        context = RepoContext(
            repo_name=self.repo_name,
            files=files,
            structure=structure,
            readme_content=readme_content,
            requirements=requirements,
            workflow_files=workflow_files
        )
        
        print(f"\n Context gathered:")
        print(f"   - {len(files)} code files")
        print(f"   - {len(workflow_files)} workflow files")
        print(f"   - {len(structure)} items in structure")
        
        return context


if __name__ == "__main__":
    """Test the code context fetcher."""
    
    print("\n" + "="*60)
    print("🔧 CI/CD Root Cause Analyzer - Code Context Test")
    print("="*60 + "\n")
    
    TEST_REPO = "Yasshu55/Test-repo" 
    
    try:
        fetcher = CodeContextFetcher(TEST_REPO)
        context = fetcher.get_context()
        
        print("\n" + "="*60)
        print("Context Summary")
        print("="*60)
        
        if context.requirements:
            print(f"\n requirements.txt:")
            print("-" * 30)
            print(context.requirements[:500])
        
        if context.workflow_files:
            print(f"\n Workflow files:")
            print("-" * 30)
            for wf in context.workflow_files:
                print(f"\n{wf.path}:")
                print(wf.content[:300])
        
        print("\n" + "="*60)
        print("Code Context Test Complete!")
        print("="*60 + "\n")
        
    except ValueError as e:
        print(f"\n{e}")
    except Exception as e:
        print(f"\n Error: {e}")
        raise