"""
workflow.py - LangGraph Workflow for CI/CD Root Cause Analyzer

This module creates the main workflow graph that orchestrates
all agents using the Supervisor-Worker pattern.

FLOW:
    START -> ingest -> parse -> triage -> research -> synthesize -> END
    
Each node is a function that:
1. Receives the current state
2. Does its work (calls tools/agents)
3. Returns state updates (partial dict)
"""

from datetime import datetime
from typing import Literal
from pathlib import Path

from langgraph.graph import StateGraph, START, END

# Import state
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.graph.state import (
    GraphState, 
    WorkflowPhase, 
    AgentDecision,
    create_initial_state,
    DebuggingBrief
)

# Import tools
from src.tools.github_loader import fetch_failed_build_logs
from src.tools.log_parser import parse_log_file

# Import agents
from src.agents.triage_agent import TriageAgent
from src.agents.research_agent import ResearchAgent
from src.agents.synthesis_agent import SynthesisAgent


def ingest_node(state: GraphState) -> dict:
    """
    Node 1: Fetch failed build logs from GitHub.
    
    Reuses: github_loader.py
    """
    print("\n[INGEST NODE] Fetching build logs...")
    
    try:
        log_path = fetch_failed_build_logs(state.repo_name)
        
        if log_path is None:
            return {
                "current_phase": WorkflowPhase.FAILED,
                "error_message": "No failed builds found or build succeeded",
                "messages": ["Ingest: No failed builds to analyze"]
            }
        
        log_content = log_path.read_text(encoding='utf-8', errors='replace')
        
        return {
            "raw_log_content": log_content,
            "log_file_path": str(log_path),
            "current_phase": WorkflowPhase.PARSING,
            "messages": [f"Ingest: Fetched logs ({len(log_content)} chars)"]
        }
        
    except Exception as e:
        return {
            "current_phase": WorkflowPhase.FAILED,
            "error_message": f"Ingest failed: {str(e)}",
            "messages": [f"Ingest: Error - {str(e)}"]
        }


def parse_node(state: GraphState) -> dict:
    """
    Node 2: Parse logs to extract structured error info.
    
    Reuses: log_parser.py
    """
    print("\n[PARSE NODE] Parsing logs...")
    
    try:
        if not state.log_file_path:
            return {
                "current_phase": WorkflowPhase.FAILED,
                "error_message": "No log file to parse",
                "messages": ["Parse: No log file available"]
            }
        
        result = parse_log_file(state.log_file_path)
        
        if not result.primary_error:
            return {
                "current_phase": WorkflowPhase.FAILED,
                "error_message": "No errors found in logs",
                "messages": ["Parse: No errors detected in logs"]
            }
        
        return {
            "parse_result": result,
            "primary_error": result.primary_error,
            "current_phase": WorkflowPhase.TRIAGING,
            "messages": [f"Parse: Found {result.error_count} error(s)"]
        }
        
    except Exception as e:
        return {
            "current_phase": WorkflowPhase.FAILED,
            "error_message": f"Parse failed: {str(e)}",
            "messages": [f"Parse: Error - {str(e)}"]
        }


def triage_node(state: GraphState) -> dict:
    """
    Node 3: AI-powered error triage.
    
    Reuses: triage_agent.py
    """
    print("\n[TRIAGE NODE] Analyzing error...")
    
    try:
        if not state.primary_error:
            return {
                "current_phase": WorkflowPhase.FAILED,
                "error_message": "No error to triage",
                "messages": ["Triage: No error available"]
            }
        
        agent = TriageAgent()
        result = agent.analyze(state.primary_error)
        
        return {
            "triage_result": result,
            "current_phase": WorkflowPhase.RESEARCHING,
            "messages": [f"Triage: {result.severity.value} severity - {result.root_cause[:50]}..."]
        }
        
    except Exception as e:
        return {
            "current_phase": WorkflowPhase.FAILED,
            "error_message": f"Triage failed: {str(e)}",
            "messages": [f"Triage: Error - {str(e)}"]
        }


def research_node(state: GraphState) -> dict:
    """
    Node 4: Web research and code context analysis.
    
    Reuses: research_agent.py
    """
    print("\n[RESEARCH NODE] Researching solutions...")
    
    try:
        if not state.triage_result or not state.primary_error:
            return {
                "current_phase": WorkflowPhase.FAILED,
                "error_message": "Missing triage or error data",
                "messages": ["Research: Missing required data"]
            }
        
        agent = ResearchAgent(repo_name=state.repo_name)
        result = agent.research(state.triage_result, state.primary_error)
        
        return {
            "research_result": result,
            "current_phase": WorkflowPhase.SYNTHESIZING,
            "messages": [f"Research: Found {len(result.solutions)} solutions"]
        }
        
    except Exception as e:
        return {
            "current_phase": WorkflowPhase.FAILED,
            "error_message": f"Research failed: {str(e)}",
            "messages": [f"Research: Error - {str(e)}"]
        }


def synthesize_node(state: GraphState) -> dict:
    """
    Node 5: Generate final debugging brief.
    
    Reuses: synthesis_agent.py
    """
    print("\n[SYNTHESIS NODE] Generating debugging brief...")
    
    try:
        if not all([state.primary_error, state.triage_result, state.research_result]):
            return {
                "current_phase": WorkflowPhase.FAILED,
                "error_message": "Missing data for synthesis",
                "messages": ["Synthesis: Missing required data"]
            }
        
        agent = SynthesisAgent()
        brief = agent.synthesize(
            state.primary_error,
            state.triage_result,
            state.research_result,
            state.repo_name
        )
        
        return {
            "debugging_brief": brief,
            "current_phase": WorkflowPhase.COMPLETED,
            "completed_at": datetime.now(),
            "messages": [f"Synthesis: Generated brief with {len(brief.fix_suggestions)} fixes"]
        }
        
    except Exception as e:
        return {
            "current_phase": WorkflowPhase.FAILED,
            "error_message": f"Synthesis failed: {str(e)}",
            "messages": [f"Synthesis: Error - {str(e)}"]
        }


# ROUTING FUNCTIONS

def should_continue(state: GraphState) -> Literal["continue", "end"]:
    """
    Supervisor decision: continue to next node or end workflow.
    
    This is called after each node to decide routing.
    """
    if state.current_phase == WorkflowPhase.FAILED:
        return "end"
    if state.current_phase == WorkflowPhase.COMPLETED:
        return "end"
    return "continue"


def route_after_ingest(state: GraphState) -> Literal["parse", "end"]:
    """Route after ingest node."""
    if state.current_phase == WorkflowPhase.FAILED:
        return "end"
    return "parse"


def route_after_parse(state: GraphState) -> Literal["triage", "end"]:
    """Route after parse node."""
    if state.current_phase == WorkflowPhase.FAILED:
        return "end"
    return "triage"


def route_after_triage(state: GraphState) -> Literal["research", "end"]:
    """Route after triage node."""
    if state.current_phase == WorkflowPhase.FAILED:
        return "end"
    return "research"


def route_after_research(state: GraphState) -> Literal["synthesize", "end"]:
    """Route after research node."""
    if state.current_phase == WorkflowPhase.FAILED:
        return "end"
    return "synthesize"


# GRAPH BUILDER

def create_workflow() -> StateGraph:
    """
    Create the LangGraph workflow.
    
    Returns a compiled graph ready to run.
    """
    workflow = StateGraph(GraphState)
    
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("parse", parse_node)
    workflow.add_node("triage", triage_node)
    workflow.add_node("research", research_node)
    workflow.add_node("synthesize", synthesize_node)
    
    workflow.add_edge(START, "ingest")
    
    workflow.add_conditional_edges(
        "ingest",
        route_after_ingest,
        {"parse": "parse", "end": END}
    )
    
    workflow.add_conditional_edges(
        "parse",
        route_after_parse,
        {"triage": "triage", "end": END}
    )
    
    workflow.add_conditional_edges(
        "triage",
        route_after_triage,
        {"research": "research", "end": END}
    )
    
    workflow.add_conditional_edges(
        "research",
        route_after_research,
        {"synthesize": "synthesize", "end": END}
    )
    
    workflow.add_edge("synthesize", END)
    
    return workflow.compile()



def run_analysis(repo_name: str) -> GraphState:
    """
    Run the full CI/CD analysis workflow.
    
    Args:
        repo_name: GitHub repository in "owner/repo" format
        
    Returns:
        Final GraphState with debugging_brief
    """
    print("\n" + "="*60)
    print("CI/CD ROOT CAUSE ANALYZER")
    print("="*60)
    print(f"Repository: {repo_name}")
    print("="*60)
    
    initial_state = create_initial_state(repo_name)
    
    workflow = create_workflow()
    
    print("\nStarting workflow...")
    final_state = workflow.invoke(initial_state)
    
    if isinstance(final_state, dict):
        final_state = GraphState(**final_state)
    
    print("\n" + "="*60)
    print("WORKFLOW COMPLETE")
    print("="*60)
    print(f"Final Phase: {final_state.current_phase.value}")
    
    if final_state.error_message:
        print(f"Error: {final_state.error_message}")
    
    if final_state.messages:
        print("\nWorkflow Log:")
        for msg in final_state.messages:
            print(f"  - {msg}")
    
    return final_state



if __name__ == "__main__":
    """Test the workflow."""
    
    TEST_REPO = "Yasshu55/Test-repo"
    
    try:
        final_state = run_analysis(TEST_REPO)
        
        if final_state.debugging_brief:
            # Save outputs
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            
            # Save markdown
            md_path = output_dir / "debugging_brief.md"
            md_path.write_text(
                final_state.debugging_brief.to_markdown(), 
                encoding='utf-8'
            )
            print(f"\nSaved: {md_path}")
            
            # Save JSON
            json_path = output_dir / "debugging_brief.json"
            json_path.write_text(
                final_state.debugging_brief.model_dump_json(indent=2),
                encoding='utf-8'
            )
            print(f"Saved: {json_path}")
            
            print("\nPhase 6 Complete!")
        else:
            print("\nNo debugging brief generated.")
            print("Check the error message above.")
            
    except Exception as e:
        print(f"\nWorkflow failed: {e}")
        import traceback
        traceback.print_exc()