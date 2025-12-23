"""
test_runner.py - Centralized Test Runner

Replaces all the scattered __main__ blocks with organized tests.
Run individual components or full integration tests.
"""

import sys
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.tools.log_parser import parse_log_file
from src.tools.github_loader import fetch_failed_build_logs
from src.tools.tavily_search import TavilySearchTool
from src.tools.code_context import CodeContextFetcher
from src.agents.triage_agent import TriageAgent
from src.agents.research_agent import ResearchAgent
from src.agents.synthesis_agent import SynthesisAgent
from src.graph.workflow import run_analysis
from src.utils.shared_utils import ensure_output_dir


def test_github_loader(repo_name: str = "Yasshu55/Test-repo"):
    """Test GitHub log fetching."""
    print("\n" + "="*60)
    print("🔧 Testing GitHub Loader")
    print("="*60)
    
    try:
        result = fetch_failed_build_logs(repo_name)
        if result:
            print(f"✅ Success! Log saved to: {result}")
            return result
        else:
            print("ℹ️ No failures found")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_log_parser(log_file: Optional[Path] = None):
    """Test log parsing."""
    print("\n" + "="*60)
    print("🔧 Testing Log Parser")
    print("="*60)
    
    if not log_file:
        log_file = Path("output/build_log.txt")
    
    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        return None
    
    try:
        result = parse_log_file(log_file)
        print(f"✅ Parsed {result.error_count} errors")
        if result.primary_error:
            print(f"Primary error: {result.primary_error.error_type}")
        return result
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_triage_agent():
    """Test triage agent."""
    print("\n" + "="*60)
    print("🔧 Testing Triage Agent")
    print("="*60)
    
    # Load parsed error
    import json
    parsed_error_path = Path("output/parsed_error.json")
    
    if not parsed_error_path.exists():
        print("❌ Need parsed error file. Run log parser first.")
        return None
    
    try:
        with open(parsed_error_path) as f:
            data = json.load(f)
        
        from src.tools.log_parser import ParsedError
        parsed_error = ParsedError(**data["primary_error"])
        
        agent = TriageAgent()
        result = agent.analyze(parsed_error)
        
        print(f"✅ Triage complete. Severity: {result.severity}")
        return result
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_research_agent(repo_name: str = "Yasshu55/Test-repo"):
    """Test research agent."""
    print("\n" + "="*60)
    print("🔧 Testing Research Agent")
    print("="*60)
    
    # Load triage result
    import json
    triage_path = Path("output/triage_result.json")
    parsed_error_path = Path("output/parsed_error.json")
    
    if not triage_path.exists() or not parsed_error_path.exists():
        print("❌ Need triage and parsed error files")
        return None
    
    try:
        with open(triage_path) as f:
            triage_data = json.load(f)
        with open(parsed_error_path) as f:
            parsed_data = json.load(f)
        
        from src.tools.log_parser import ParsedError
        from src.agents.triage_agent import TriageResult
        
        parsed_error = ParsedError(**parsed_data["primary_error"])
        triage_result = TriageResult(**triage_data)
        
        agent = ResearchAgent(repo_name=repo_name)
        result = agent.research(triage_result, parsed_error)
        
        print(f"✅ Research complete. Found {len(result.solutions)} solutions")
        return result
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_synthesis_agent(repo_name: str = "Yasshu55/Test-repo"):
    """Test synthesis agent."""
    print("\n" + "="*60)
    print("🔧 Testing Synthesis Agent")
    print("="*60)
    
    # Load all previous results
    import json
    files = {
        "parsed_error": Path("output/parsed_error.json"),
        "triage_result": Path("output/triage_result.json"),
        "research_result": Path("output/research_result.json")
    }
    
    for name, path in files.items():
        if not path.exists():
            print(f"❌ Missing {name} file: {path}")
            return None
    
    try:
        # Load data
        with open(files["parsed_error"]) as f:
            parsed_data = json.load(f)
        with open(files["triage_result"]) as f:
            triage_data = json.load(f)
        with open(files["research_result"]) as f:
            research_data = json.load(f)
        
        # Convert to models
        from src.tools.log_parser import ParsedError
        from src.agents.triage_agent import TriageResult
        from src.agents.research_agent import ResearchResult
        
        parsed_error = ParsedError(**parsed_data["primary_error"])
        triage_result = TriageResult(**triage_data)
        research_result = ResearchResult(**research_data)
        
        # Run synthesis
        agent = SynthesisAgent()
        brief = agent.synthesize(parsed_error, triage_result, research_result, repo_name)
        
        print(f"✅ Synthesis complete. Generated {len(brief.fix_suggestions)} fixes")
        return brief
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def test_full_workflow(repo_name: str = "Yasshu55/Test-repo"):
    """Test complete workflow."""
    print("\n" + "="*60)
    print("🔧 Testing Full Workflow")
    print("="*60)
    
    try:
        final_state = run_analysis(repo_name)
        
        if final_state.debugging_brief:
            print("✅ Full workflow complete!")
            return final_state
        else:
            print("❌ Workflow failed")
            return None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def main():
    """Main test runner with menu."""
    print("\n" + "="*60)
    print("🧪 CI/CD Root Cause Analyzer - Test Runner")
    print("="*60)
    
    tests = {
        "1": ("GitHub Loader", test_github_loader),
        "2": ("Log Parser", test_log_parser),
        "3": ("Triage Agent", test_triage_agent),
        "4": ("Research Agent", test_research_agent),
        "5": ("Synthesis Agent", test_synthesis_agent),
        "6": ("Full Workflow", test_full_workflow),
    }
    
    print("\nAvailable Tests:")
    for key, (name, _) in tests.items():
        print(f"  {key}. {name}")
    print("  q. Quit")
    
    while True:
        choice = input("\nSelect test (1-6, q): ").strip().lower()
        
        if choice == 'q':
            break
        elif choice in tests:
            name, test_func = tests[choice]
            print(f"\n🚀 Running {name}...")
            
            # Ensure output directory exists
            ensure_output_dir()
            
            result = test_func()
            
            if result:
                print(f"✅ {name} completed successfully")
            else:
                print(f"❌ {name} failed")
        else:
            print("Invalid choice. Try again.")
    
    print("\n👋 Test runner finished.")


if __name__ == "__main__":
    main()