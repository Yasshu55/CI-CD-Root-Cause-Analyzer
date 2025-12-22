"""
state.py - Shared State for LangGraph Workflow
"""

from datetime import datetime
from enum import Enum
from typing import Optional, Annotated
from pydantic import BaseModel, Field, ConfigDict
import operator

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.tools.log_parser import ParsedError, LogParseResult
from src.agents.triage_agent import TriageResult
from src.agents.research_agent import ResearchResult


# ENUMS

class WorkflowPhase(str, Enum):
    """
    Tracks which phase the workflow is currently in.
    
    This helps the supervisor know what to do next.
    """
    INITIALIZED = "initialized"
    INGESTING = "ingesting"
    PARSING = "parsing"
    TRIAGING = "triaging"
    RESEARCHING = "researching"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentDecision(str, Enum):
    """
    Possible decisions from the supervisor.
    
    Used for conditional routing in the graph.
    """
    CONTINUE_TO_TRIAGE = "continue_to_triage"
    CONTINUE_TO_RESEARCH = "continue_to_research"
    CONTINUE_TO_SYNTHESIS = "continue_to_synthesis"
    FINISH = "finish"
    ABORT = "abort"


# DEBUGGING BRIEF MODEL

class FixSuggestion(BaseModel):
    """A single fix suggestion in the debugging brief."""
    priority: int = Field(description="Priority rank (1 = highest)")
    title: str = Field(description="Short title for the fix")
    description: str = Field(description="Detailed explanation")
    implementation_steps: list[str] = Field(
        default_factory=list,
        description="Step-by-step implementation guide"
    )
    code_example: Optional[str] = Field(
        default=None,
        description="Code snippet if applicable"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="How confident we are this will work"
    )
    source: str = Field(
        default="ai_analysis",
        description="Where this suggestion came from"
    )


class DebuggingBrief(BaseModel):
    """
    The final output: A structured debugging brief.
    
    This is what the user sees - a comprehensive report with
    actionable fix suggestions.
    """
    # Header
    title: str = Field(description="Brief title summarizing the issue")
    generated_at: datetime = Field(default_factory=datetime.now)
    repository: Optional[str] = Field(default=None)
    workflow_run_id: Optional[int] = Field(default=None)
    
    error_type: str = Field(description="The type of error encountered")
    error_message: str = Field(description="The error message")
    error_category: str = Field(description="High-level category")
    severity: str = Field(description="Severity assessment")

    root_cause_summary: str = Field(
        description="One-paragraph explanation of what went wrong"
    )
    root_cause_detailed: str = Field(
        description="Detailed technical explanation"
    )
    affected_files: list[str] = Field(default_factory=list)
    affected_components: list[str] = Field(default_factory=list)
    
    fix_suggestions: list[FixSuggestion] = Field(
        default_factory=list,
        description="Ranked list of fix suggestions (aim for 3)"
    )
    
    relevant_links: list[str] = Field(
        default_factory=list,
        description="Helpful documentation/Stack Overflow links"
    )
    research_summary: Optional[str] = Field(
        default=None,
        description="Summary of web research findings"
    )
    
    confidence_score: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="Overall confidence in the analysis"
    )
    analysis_duration_seconds: Optional[float] = Field(default=None)
    
    def to_markdown(self) -> str:
        """
        Convert the debugging brief to a beautiful markdown document.
        
        This is what gets saved as the final output.
        """
        md = []
        
        # Header
        md.append(f"# 🔧 CI/CD Debugging Brief")
        md.append(f"\n**{self.title}**\n")
        md.append(f"Generated: {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if self.repository:
            md.append(f"Repository: `{self.repository}`")
        md.append("")
        
        # Severity Badge
        severity_emoji = {
            "critical": "🔴",
            "high": "🟠", 
            "medium": "🟡",
            "low": "🟢"
        }.get(self.severity.lower(), "⚪")
        md.append(f"## {severity_emoji} Severity: {self.severity.upper()}\n")
        
        # Error Summary
        md.append("## 📋 Error Summary\n")
        md.append(f"| Field | Value |")
        md.append(f"|-------|-------|")
        md.append(f"| **Type** | `{self.error_type}` |")
        md.append(f"| **Category** | {self.error_category} |")
        md.append(f"| **Message** | {self.error_message[:100]}{'...' if len(self.error_message) > 100 else ''} |")
        md.append("")
        
        # Root Cause
        md.append("## 🎯 Root Cause Analysis\n")
        md.append(f"### Summary\n{self.root_cause_summary}\n")
        md.append(f"### Detailed Explanation\n{self.root_cause_detailed}\n")
        
        if self.affected_files:
            md.append("### Affected Files")
            for f in self.affected_files[:5]:
                md.append(f"- `{f}`")
            md.append("")
        
        # Fix Suggestions (THE MAIN VALUE)
        md.append("## 💡 Fix Suggestions\n")
        
        for i, fix in enumerate(self.fix_suggestions, 1):
            confidence_bar = "█" * int(fix.confidence * 10) + "░" * (10 - int(fix.confidence * 10))
            md.append(f"### Fix #{i}: {fix.title}")
            md.append(f"**Confidence:** [{confidence_bar}] {fix.confidence:.0%}\n")
            md.append(f"{fix.description}\n")
            
            if fix.implementation_steps:
                md.append("**Steps:**")
                for j, step in enumerate(fix.implementation_steps, 1):
                    md.append(f"{j}. {step}")
                md.append("")
            
            if fix.code_example:
                md.append("**Code Example:**")
                md.append(f"```python\n{fix.code_example}\n```")
                md.append("")
        
        # Relevant Links
        if self.relevant_links:
            md.append("## 🔗 Helpful Resources\n")
            for link in self.relevant_links[:5]:
                md.append(f"- {link}")
            md.append("")
        
        # Footer
        md.append("---")
        md.append(f"*Analysis confidence: {self.confidence_score:.0%}*")
        if self.analysis_duration_seconds:
            md.append(f"*Analysis completed in {self.analysis_duration_seconds:.1f}s*")
        
        return "\n".join(md)


# MAIN GRAPH STATE

class GraphState(BaseModel):
    """
    The central state object for the LangGraph workflow.
    
    This is THE most important class in the project. It:
    1. Holds all data as it flows through the pipeline
    2. Gets updated by each agent
    3. Enables routing decisions by the supervisor
    
    FLOW:
    ─────
    [Input] → Ingest → Parse → Triage → Research → Synthesize → [Output]
       │                                                              │
       └──────────────► GraphState (updated at each step) ◄──────────┘
    """
    
    # ── Input Configuration 
    repo_name: str = Field(
        description="GitHub repository to analyze (owner/repo format)"
    )
    
    # ── Raw Data (from ingestion) 
    raw_log_content: Optional[str] = Field(
        default=None,
        description="Raw build log content"
    )
    log_file_path: Optional[str] = Field(
        default=None,
        description="Path to the saved log file"
    )
    workflow_run_id: Optional[int] = Field(
        default=None,
        description="GitHub Actions workflow run ID"
    )
    
    # ── Parsed Data (from parser) 
    parse_result: Optional[LogParseResult] = Field(
        default=None,
        description="Full parse result including all errors"
    )
    primary_error: Optional[ParsedError] = Field(
        default=None,
        description="The main error to analyze"
    )
    
    # ── Triage Results (from triage agent) 
    triage_result: Optional[TriageResult] = Field(
        default=None,
        description="AI triage analysis"
    )
    
    # ── Research Results (from research agent) 
    research_result: Optional[ResearchResult] = Field(
        default=None,
        description="Web research and code analysis"
    )
    
    # ── Final Output (from synthesis agent)
    debugging_brief: Optional[DebuggingBrief] = Field(
        default=None,
        description="The final debugging brief"
    )
    
    # ── Workflow Control 
    current_phase: WorkflowPhase = Field(
        default=WorkflowPhase.INITIALIZED,
        description="Current phase of the workflow"
    )
    next_action: Optional[AgentDecision] = Field(
        default=None,
        description="What the supervisor decided to do next"
    )
    
    # ── Logging & Debugging 
    messages: Annotated[list[str], operator.add] = Field(
        default_factory=list,
        description="Log of actions taken (audit trail)"
    )
    
    # ── Error Handling 
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if workflow fails"
    )
    
    # ── Timing
    started_at: Optional[datetime] = Field(
        default=None,
        description="When the workflow started"
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="When the workflow completed"
    )
    
    model_config = ConfigDict(arbitrary_types_allowed=True)



def create_initial_state(repo_name: str) -> GraphState:
    """
    Create the initial state to start the workflow.
    
    Usage:
        state = create_initial_state("owner/repo")
        # Pass to LangGraph
    """
    return GraphState(
        repo_name=repo_name,
        current_phase=WorkflowPhase.INITIALIZED,
        started_at=datetime.now(),
        messages=[f"Workflow initialized for repository: {repo_name}"]
    )


def get_state_summary(state: GraphState) -> str:
    """
    Get a human-readable summary of the current state.
    
    Useful for debugging and logging.
    """
    summary = [
        f"📊 State Summary",
        f"   Repository: {state.repo_name}",
        f"   Phase: {state.current_phase.value}",
        f"   Has parsed error: {state.primary_error is not None}",
        f"   Has triage: {state.triage_result is not None}",
        f"   Has research: {state.research_result is not None}",
        f"   Has brief: {state.debugging_brief is not None}",
        f"   Messages: {len(state.messages)}",
    ]
    
    if state.error_message:
        summary.append(f"   ⚠️ Error: {state.error_message}")
    
    return "\n".join(summary)



if __name__ == "__main__":
    """Test the state models."""
    
    print("\n" + "="*60)
    print("🔧 CI/CD Root Cause Analyzer - State Models Test")
    print("="*60 + "\n")
    
    # Test creating initial state
    state = create_initial_state("Yasshu55/Test-repo")
    print(get_state_summary(state))
    
    # Test DebuggingBrief
    print("\n" + "-"*40)
    print("Testing DebuggingBrief model...")
    
    brief = DebuggingBrief(
        title="ModuleNotFoundError: No module named 'requests'",
        repository="Yasshu55/Test-repo",
        error_type="ModuleNotFoundError",
        error_message="No module named 'requests'",
        error_category="dependency",
        severity="high",
        root_cause_summary="The 'requests' package is not installed in the CI environment.",
        root_cause_detailed="The GitHub Actions workflow does not install project dependencies before running tests.",
        affected_files=["requirements.txt", ".github/workflows/test.yml"],
        fix_suggestions=[
            FixSuggestion(
                priority=1,
                title="Add pip install step to workflow",
                description="Add a step to install dependencies from requirements.txt",
                implementation_steps=[
                    "Open .github/workflows/test.yml",
                    "Add 'pip install -r requirements.txt' before test step",
                    "Commit and push changes"
                ],
                confidence=0.95,
                source="ai_analysis"
            ),
            FixSuggestion(
                priority=2,
                title="Add 'requests' to requirements.txt",
                description="Ensure the requests package is listed in requirements.txt",
                implementation_steps=[
                    "Open requirements.txt",
                    "Add line: requests>=2.28.0",
                    "Commit and push"
                ],
                confidence=0.85,
                source="web_research"
            )
        ],
        relevant_links=[
            "https://docs.github.com/en/actions/using-workflows",
            "https://pip.pypa.io/en/stable/user_guide/"
        ],
        confidence_score=0.9
    )
    
    print("\n📄 Generated Markdown Preview:")
    print("-"*40)
    markdown = brief.to_markdown()
    print(markdown[:1500] + "\n...[truncated]")
    
    # Save sample output
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    
    sample_path = output_dir / "sample_debugging_brief.md"
    sample_path.write_text(markdown, encoding='utf-8')
    print(f"\n💾 Sample brief saved to: {sample_path}")
    
    print("\n" + "="*60)
    print("✅ State Models Test Complete!")
    print("="*60 + "\n")