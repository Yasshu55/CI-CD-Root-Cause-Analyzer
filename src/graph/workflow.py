"""
workflow.py - Hybrid Supervisor Pattern (Minimal LLM calls)
"""

import time
from datetime import datetime
from typing import Literal
from pathlib import Path

from langgraph.graph import StateGraph, START, END
from dotenv import load_dotenv

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.graph.state import (
    GraphState, 
    WorkflowPhase,
    create_initial_state,
)
from src.tools.github_loader import fetch_failed_build_logs
from src.tools.log_parser import parse_log_file
from src.agents.triage_agent import TriageAgent
from src.agents.research_agent import ResearchAgent
from src.agents.synthesis_agent import SynthesisAgent

load_dotenv()

# Track failures
failure_counts = {}
MAX_FAILURES = 3
DELAY_BETWEEN_LLM_CALLS = 5  # seconds


def hybrid_decide(state: GraphState) -> str:
    """
    Hybrid supervisor: Logic for obvious cases, no LLM needed.
    This reduces LLM calls from 9+ to just 3 (the agents themselves).
    """
    global failure_counts
    
    # Check if we've failed too many times on same step
    current_step = None
    
    if state.raw_log_content is None:
        current_step = "ingest"
    elif state.primary_error is None:
        current_step = "parse"
    elif state.triage_result is None:
        current_step = "triage"
    elif state.research_result is None:
        current_step = "research"
    elif state.debugging_brief is None:
        current_step = "synthesize"
    else:
        return "FINISH"
    
    # Check failure count
    if failure_counts.get(current_step, 0) >= MAX_FAILURES:
        print(f"[SUPERVISOR] {current_step} failed {MAX_FAILURES} times. Giving up.")
        return "FINISH"
    
    print(f"[SUPERVISOR] Decision: {current_step}")
    return current_step


def supervisor_node(state: GraphState) -> dict:
    """Supervisor using logic-based decisions."""
    decision = hybrid_decide(state)
    return {
        "next_action": decision,
        "messages": [f"Supervisor: {decision}"]
    }


def ingest_node(state: GraphState) -> dict:
    """Fetch build logs."""
    print("\n[INGEST] Fetching build logs...")
    
    try:
        log_path = fetch_failed_build_logs(state.repo_name)
        
        if log_path is None:
            failure_counts["ingest"] = failure_counts.get("ingest", 0) + 1
            return {
                "error_message": "No failed builds found",
                "messages": ["Ingest: No failed builds"]
            }
        
        log_content = log_path.read_text(encoding='utf-8', errors='replace')
        failure_counts["ingest"] = 0  # Reset on success
        
        return {
            "raw_log_content": log_content,
            "log_file_path": str(log_path),
            "current_phase": WorkflowPhase.PARSING,
            "error_message": None,
            "messages": [f"Ingest: OK ({len(log_content)} chars)"]
        }
    except Exception as e:
        failure_counts["ingest"] = failure_counts.get("ingest", 0) + 1
        return {"error_message": str(e), "messages": [f"Ingest error: {e}"]}


def parse_node(state: GraphState) -> dict:
    """Parse logs."""
    print("\n[PARSE] Parsing logs...")
    
    try:
        result = parse_log_file(state.log_file_path)
        
        if not result.primary_error:
            failure_counts["parse"] = failure_counts.get("parse", 0) + 1
            return {
                "error_message": "No errors in logs",
                "messages": ["Parse: No errors found"]
            }
        
        failure_counts["parse"] = 0
        return {
            "parse_result": result,
            "primary_error": result.primary_error,
            "current_phase": WorkflowPhase.TRIAGING,
            "error_message": None,
            "messages": [f"Parse: Found {result.error_count} error(s)"]
        }
    except Exception as e:
        failure_counts["parse"] = failure_counts.get("parse", 0) + 1
        return {"error_message": str(e), "messages": [f"Parse error: {e}"]}


def triage_node(state: GraphState) -> dict:
    """Triage with delay and error handling."""
    print("\n[TRIAGE] Analyzing error...")
    print(f"[Rate Limit] Waiting {DELAY_BETWEEN_LLM_CALLS}s before LLM call...")
    time.sleep(DELAY_BETWEEN_LLM_CALLS)
    
    try:
        agent = TriageAgent()
        result = agent.analyze(state.primary_error)
        failure_counts["triage"] = 0
        
        return {
            "triage_result": result,
            "current_phase": WorkflowPhase.RESEARCHING,
            "error_message": None,
            "messages": [f"Triage: {result.severity.value}"]
        }
    except Exception as e:
        failure_counts["triage"] = failure_counts.get("triage", 0) + 1
        print(f"[TRIAGE] Failed (attempt {failure_counts['triage']}/{MAX_FAILURES}): {e}")
        return {"error_message": str(e), "messages": [f"Triage error: {e}"]}


def research_node(state: GraphState) -> dict:
    """Research with delay and error handling."""
    print("\n[RESEARCH] Finding solutions...")
    print(f"[Rate Limit] Waiting {DELAY_BETWEEN_LLM_CALLS}s before LLM call...")
    time.sleep(DELAY_BETWEEN_LLM_CALLS)
    
    try:
        agent = ResearchAgent(repo_name=state.repo_name)
        result = agent.research(state.triage_result, state.primary_error)
        failure_counts["research"] = 0
        
        return {
            "research_result": result,
            "current_phase": WorkflowPhase.SYNTHESIZING,
            "error_message": None,
            "messages": [f"Research: {len(result.solutions)} solutions"]
        }
    except Exception as e:
        failure_counts["research"] = failure_counts.get("research", 0) + 1
        print(f"[RESEARCH] Failed (attempt {failure_counts['research']}/{MAX_FAILURES}): {e}")
        return {"error_message": str(e), "messages": [f"Research error: {e}"]}


def synthesize_node(state: GraphState) -> dict:
    """Synthesize with delay and error handling."""
    print("\n[SYNTHESIZE] Creating debugging brief...")
    print(f"[Rate Limit] Waiting {DELAY_BETWEEN_LLM_CALLS}s before LLM call...")
    time.sleep(DELAY_BETWEEN_LLM_CALLS)
    
    try:
        agent = SynthesisAgent()
        brief = agent.synthesize(
            state.primary_error,
            state.triage_result,
            state.research_result,
            state.repo_name
        )
        failure_counts["synthesize"] = 0
        
        return {
            "debugging_brief": brief,
            "current_phase": WorkflowPhase.COMPLETED,
            "completed_at": datetime.now(),
            "error_message": None,
            "messages": [f"Synthesize: {len(brief.fix_suggestions)} fixes"]
        }
    except Exception as e:
        failure_counts["synthesize"] = failure_counts.get("synthesize", 0) + 1
        print(f"[SYNTHESIZE] Failed (attempt {failure_counts['synthesize']}/{MAX_FAILURES}): {e}")
        return {"error_message": str(e), "messages": [f"Synthesize error: {e}"]}


def route_from_supervisor(state: GraphState) -> Literal[
    "ingest", "parse", "triage", "research", "synthesize", "__end__"
]:
    """Route based on supervisor decision."""
    decision = state.next_action
    
    if decision == "FINISH":
        return "__end__"
    elif decision in ["ingest", "parse", "triage", "research", "synthesize"]:
        return decision
    return "__end__"


def create_workflow() -> StateGraph:
    """Create the workflow graph."""
    workflow = StateGraph(GraphState)
    
    workflow.add_node("supervisor", supervisor_node)
    workflow.add_node("ingest", ingest_node)
    workflow.add_node("parse", parse_node)
    workflow.add_node("triage", triage_node)
    workflow.add_node("research", research_node)
    workflow.add_node("synthesize", synthesize_node)
    
    workflow.add_edge(START, "supervisor")
    
    workflow.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "ingest": "ingest",
            "parse": "parse",
            "triage": "triage",
            "research": "research",
            "synthesize": "synthesize",
            "__end__": END
        }
    )
    
    workflow.add_edge("ingest", "supervisor")
    workflow.add_edge("parse", "supervisor")
    workflow.add_edge("triage", "supervisor")
    workflow.add_edge("research", "supervisor")
    workflow.add_edge("synthesize", "supervisor")
    
    return workflow.compile()


def run_analysis(repo_name: str) -> GraphState:
    """Run analysis."""
    global failure_counts
    failure_counts = {}  # Reset
    
    print("\n" + "="*60)
    print("CI/CD ROOT CAUSE ANALYZER")
    print("="*60)
    print(f"Repository: {repo_name}")
    print(f"Max retries per step: {MAX_FAILURES}")
    print(f"Delay between LLM calls: {DELAY_BETWEEN_LLM_CALLS}s")
    print("="*60)
    
    initial_state = create_initial_state(repo_name)
    workflow = create_workflow()
    
    final_state = workflow.invoke(initial_state)
    
    if isinstance(final_state, dict):
        final_state = GraphState(**final_state)
    
    print("\n" + "="*60)
    print("COMPLETE")
    print("="*60)
    
    return final_state


if __name__ == "__main__":
    TEST_REPO = "Yasshu55/Test-repo"
    
    try:
        final_state = run_analysis(TEST_REPO)
        
        if final_state.debugging_brief:
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            
            md_path = output_dir / "debugging_brief.md"
            md_path.write_text(
                final_state.debugging_brief.to_markdown(), 
                encoding='utf-8'
            )
            print(f"\nSaved: {md_path}")
        else:
            print("\nNo brief generated.")
            if final_state.error_message:
                print(f"Error: {final_state.error_message}")
            
    except Exception as e:
        print(f"\nFailed: {e}")