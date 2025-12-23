"""
synthesis_agent.py - CI/CD Synthesis Agent

This agent takes all previous analysis and generates the final
Debugging Brief with 3 actionable fix suggestions.

THE FINAL PIECE:
- Combines triage analysis + research findings
- Uses Claude to synthesize everything
- Outputs a beautiful, actionable debugging brief

This is where we transform raw data into ACTIONABLE INSIGHTS.
"""

import os
import json
import re
from datetime import datetime
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.tools.log_parser import ParsedError
from src.agents.triage_agent import TriageResult
from src.agents.research_agent import ResearchResult
from src.graph.state import DebuggingBrief, FixSuggestion
from src.utils.llm import get_llm


load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"



SYNTHESIS_SYSTEM_PROMPT = """You are an expert CI/CD debugging assistant creating a comprehensive debugging brief.

Your job is to synthesize all analysis into a clear, actionable report that a developer can use to fix their build failure.

IMPORTANT GUIDELINES:
1. Be specific and actionable - vague suggestions are useless
2. Prioritize fixes by likelihood of success and ease of implementation
3. Include actual code/commands when possible
4. Reference the actual error and affected files
5. Keep explanations concise but complete

You must provide EXACTLY 3 fix suggestions, ranked by priority."""


SYNTHESIS_USER_PROMPT = """Create a debugging brief for this CI/CD failure.

## Error Information
- **Type:** {error_type}
- **Message:** {error_message}
- **Failed Step:** {failed_step}

## Triage Analysis
- **Severity:** {severity}
- **Root Cause:** {root_cause}
- **Detailed Analysis:** {root_cause_detailed}
- **Affected Files:** {affected_files}
- **Category:** {error_category}

## Research Findings
### Web Research
{web_findings}

### Suggested Solutions from Research
{research_solutions}

### Relevant URLs
{relevant_urls}

## Your Task

Generate a JSON response with the debugging brief. Include EXACTLY 3 fix suggestions.

IMPORTANT: 
- Use double quotes for all strings
- Escape special characters properly
- No trailing commas
- No markdown code blocks in JSON string values

{{
    "title": "Short descriptive title of the issue",
    "root_cause_summary": "One paragraph explaining what went wrong in simple terms",
    "root_cause_detailed": "Technical explanation of the root cause",
    "fix_suggestions": [
        {{
            "priority": 1,
            "title": "Most likely fix",
            "description": "What this fix does and why it should work",
            "implementation_steps": [
                "Step 1: Specific action",
                "Step 2: Specific action",
                "Step 3: Specific action"
            ],
            "code_example": "actual code or command if applicable (or null)",
            "confidence": 0.0 to 1.0,
            "source": "where this fix came from"
        }},
        {{
            "priority": 2,
            "title": "Second fix option",
            "description": "...",
            "implementation_steps": ["..."],
            "code_example": null,
            "confidence": 0.0 to 1.0,
            "source": "..."
        }},
        {{
            "priority": 3,
            "title": "Third fix option",
            "description": "...",
            "implementation_steps": ["..."],
            "code_example": null,
            "confidence": 0.0 to 1.0,
            "source": "..."
        }}
    ],
    "research_summary": "Brief summary of what web research revealed",
    "confidence_score": 0.0 to 1.0
}}

Respond with ONLY the JSON object."""

# HELPER FUNCTIONS

def clean_json_response(text: str) -> str:
    """Clean LLM response for JSON parsing."""
    text = text.strip()
    
    # Remove markdown code blocks
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    
    # Remove trailing commas
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    
    return text.strip()


def extract_json(text: str) -> Optional[dict]:
    """Extract JSON from text with multiple strategies."""
    # Strategy 1: Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Clean and parse
    try:
        cleaned = clean_json_response(text)
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: Find JSON object
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(clean_json_response(match.group()))
    except (json.JSONDecodeError, AttributeError):
        pass
    
    return None


# SYNTHESIS AGENT

class SynthesisAgent:
    """
    Agent that synthesizes all analysis into a final Debugging Brief.
    
    This is the final agent in our pipeline. It takes:
    - ParsedError (from parser)
    - TriageResult (from triage agent)
    - ResearchResult (from research agent)
    
    And produces:
    - DebuggingBrief (the final output)
    
    Usage:
        agent = SynthesisAgent()
        brief = agent.synthesize(parsed_error, triage_result, research_result, "owner/repo")
    """
    
    def __init__(self, model_id: str = BEDROCK_MODEL_ID):
        """Initialize the Synthesis Agent."""
        self.model_id = model_id
        self.llm = self._create_llm()
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", SYNTHESIS_SYSTEM_PROMPT),
            ("human", SYNTHESIS_USER_PROMPT)
        ])
        print("✅ Synthesis Agent initialized!")
    
    def _create_llm(self) -> ChatBedrock:
        print(f"Using shared Claude instance")
        return get_llm()
    
    def _format_prompt_variables(
        self,
        parsed_error: ParsedError,
        triage_result: TriageResult,
        research_result: ResearchResult
    ) -> dict:
        """Format all data for the prompt."""
        
        # Format web findings
        web_findings = "\n".join([
            f"- {finding}" for finding in research_result.web_findings[:5]
        ]) if research_result.web_findings else "No web findings available."
        
        # Format research solutions
        research_solutions = []
        for sol in research_result.solutions[:3]:
            research_solutions.append(f"- **{sol.title}** (confidence: {sol.confidence:.0%})")
            research_solutions.append(f"  {sol.description}")
        research_solutions_str = "\n".join(research_solutions) if research_solutions else "No solutions from research."
        
        # Format URLs
        relevant_urls = "\n".join([
            f"- {url}" for url in research_result.relevant_urls[:5]
        ]) if research_result.relevant_urls else "No relevant URLs found."
        
        return {
            "error_type": parsed_error.error_type,
            "error_message": parsed_error.error_message[:300],
            "failed_step": parsed_error.failed_step or "Unknown",
            "severity": triage_result.severity.value,
            "root_cause": triage_result.root_cause,
            "root_cause_detailed": triage_result.root_cause_detailed[:500],
            "affected_files": ", ".join(triage_result.affected_files) if triage_result.affected_files else "Unknown",
            "error_category": triage_result.error_category_refined.value,
            "web_findings": web_findings,
            "research_solutions": research_solutions_str,
            "relevant_urls": relevant_urls
        }
    
    def _parse_response(
        self,
        response_text: str,
        parsed_error: ParsedError,
        triage_result: TriageResult,
        research_result: ResearchResult,
        repo_name: Optional[str]
    ) -> DebuggingBrief:
        """Parse LLM response into DebuggingBrief."""
        
        data = extract_json(response_text)
        
        if not data:
            print("⚠️ Could not parse synthesis response, using fallback")
            return self._create_fallback_brief(
                parsed_error, triage_result, research_result, repo_name
            )
        
        fix_suggestions = []
        for fix_data in data.get("fix_suggestions", []):
            try:
                fix_suggestions.append(FixSuggestion(
                    priority=fix_data.get("priority", len(fix_suggestions) + 1),
                    title=fix_data.get("title", "Fix suggestion"),
                    description=fix_data.get("description", ""),
                    implementation_steps=fix_data.get("implementation_steps", []),
                    code_example=fix_data.get("code_example"),
                    confidence=float(fix_data.get("confidence", 0.5)),
                    source=fix_data.get("source", "ai_synthesis")
                ))
            except Exception as e:
                print(f"   ⚠️ Could not parse fix suggestion: {e}")
        
        if not fix_suggestions:
            fix_suggestions = self._create_fallback_suggestions(triage_result, research_result)
        
        return DebuggingBrief(
            title=data.get("title", f"{parsed_error.error_type}: {parsed_error.error_message[:50]}"),
            repository=repo_name,
            error_type=parsed_error.error_type,
            error_message=parsed_error.error_message,
            error_category=triage_result.error_category_refined.value,
            severity=triage_result.severity.value,
            root_cause_summary=data.get("root_cause_summary", triage_result.root_cause),
            root_cause_detailed=data.get("root_cause_detailed", triage_result.root_cause_detailed),
            affected_files=triage_result.affected_files,
            affected_components=triage_result.affected_components,
            fix_suggestions=fix_suggestions,
            relevant_links=research_result.relevant_urls[:5],
            research_summary=data.get("research_summary"),
            confidence_score=float(data.get("confidence_score", triage_result.confidence_score))
        )
    
    def _create_fallback_suggestions(
        self,
        triage_result: TriageResult,
        research_result: ResearchResult
    ) -> list[FixSuggestion]:
        """Create fallback suggestions from triage and research."""
        suggestions = []
        
        # From triage immediate suggestions
        for i, suggestion in enumerate(triage_result.immediate_suggestions[:2]):
            suggestions.append(FixSuggestion(
                priority=i + 1,
                title=f"Suggestion {i + 1}",
                description=suggestion,
                implementation_steps=[suggestion],
                confidence=0.7,
                source="triage_agent"
            ))
        
        # From research solutions
        for sol in research_result.solutions[:1]:
            suggestions.append(FixSuggestion(
                priority=len(suggestions) + 1,
                title=sol.title,
                description=sol.description,
                implementation_steps=sol.steps,
                confidence=sol.confidence,
                source="research_agent"
            ))
        
        return suggestions[:3]  # Ensure max 3
    
    def _create_fallback_brief(
        self,
        parsed_error: ParsedError,
        triage_result: TriageResult,
        research_result: ResearchResult,
        repo_name: Optional[str]
    ) -> DebuggingBrief:
        """Create a fallback brief when LLM parsing fails."""
        return DebuggingBrief(
            title=f"{parsed_error.error_type}: {parsed_error.error_message[:50]}",
            repository=repo_name,
            error_type=parsed_error.error_type,
            error_message=parsed_error.error_message,
            error_category=triage_result.error_category_refined.value,
            severity=triage_result.severity.value,
            root_cause_summary=triage_result.root_cause,
            root_cause_detailed=triage_result.root_cause_detailed,
            affected_files=triage_result.affected_files,
            affected_components=triage_result.affected_components,
            fix_suggestions=self._create_fallback_suggestions(triage_result, research_result),
            relevant_links=research_result.relevant_urls[:5],
            confidence_score=triage_result.confidence_score
        )
    
    def synthesize(
        self,
        parsed_error: ParsedError,
        triage_result: TriageResult,
        research_result: ResearchResult,
        repo_name: Optional[str] = None
    ) -> DebuggingBrief:
        """
        Synthesize all analysis into a final Debugging Brief.
        
        This is the main entry point for the Synthesis Agent.
        
        Args:
            parsed_error: The parsed error from log parser
            triage_result: AI triage analysis
            research_result: Web research and code analysis
            repo_name: Repository name for context
            
        Returns:
            DebuggingBrief with actionable fix suggestions
        """
        print("\n" + "="*60)
        print("📝 SYNTHESIS AGENT - Generating Debugging Brief")
        print("="*60)
        
        start_time = datetime.now()
        
        prompt_vars = self._format_prompt_variables(
            parsed_error, triage_result, research_result
        )
        
        print("\n🔄 Sending to Claude for synthesis...")

        chain = self.prompt | self.llm
        response = chain.invoke(prompt_vars)
        
        print("✅ Received response from Claude")
        
        brief = self._parse_response(
            response.content,
            parsed_error,
            triage_result,
            research_result,
            repo_name
        )
        
        end_time = datetime.now()
        brief.analysis_duration_seconds = (end_time - start_time).total_seconds()
        
        self._display_brief(brief)
        
        return brief
    
    def _display_brief(self, brief: DebuggingBrief) -> None:
        """Display the debugging brief summary."""
        print("\n" + "="*60)
        print("📋 DEBUGGING BRIEF GENERATED")
        print("="*60)
        
        print(f"\n📌 Title: {brief.title}")
        print(f"⚠️ Severity: {brief.severity}")
        print(f"🎯 Root Cause: {brief.root_cause_summary[:100]}...")
        
        print(f"\n💡 Fix Suggestions ({len(brief.fix_suggestions)}):")
        for fix in brief.fix_suggestions:
            print(f"   {fix.priority}. {fix.title} (confidence: {fix.confidence:.0%})")
        
        print(f"\n📊 Overall Confidence: {brief.confidence_score:.0%}")



# SCRIPT ENTRY POINT

if __name__ == "__main__":
    """Test the Synthesis Agent with outputs from previous phases."""
    
    print("\n" + "="*60)
    print("🔧 CI/CD Root Cause Analyzer - Synthesis Agent")
    print("="*60 + "\n")
    
    # Load previous outputs
    parsed_error_path = Path("output/parsed_error.json")
    triage_result_path = Path("output/triage_result.json")
    research_result_path = Path("output/research_result.json")
    
    for path in [parsed_error_path, triage_result_path, research_result_path]:
        if not path.exists():
            print(f"❌ Required file not found: {path}")
            print("   Please run previous phases first")
            exit(1)
    
    # Load the data
    print("📂 Loading inputs from previous phases...")
    
    with open(parsed_error_path) as f:
        parsed_data = json.load(f)
    
    with open(triage_result_path) as f:
        triage_data = json.load(f)
    
    with open(research_result_path) as f:
        research_data = json.load(f)
    
    parsed_error = ParsedError(**parsed_data["primary_error"])
    triage_result = TriageResult(**triage_data)
    research_result = ResearchResult(**research_data)
    
    print(f"✅ Loaded error: {parsed_error.error_type}")
    print(f"✅ Loaded triage: {triage_result.severity.value} severity")
    print(f"✅ Loaded research: {len(research_result.solutions)} solutions")
    
    REPO_NAME = "Yasshu55/Test-repo"
    
    try:
        agent = SynthesisAgent()
        brief = agent.synthesize(
            parsed_error,
            triage_result,
            research_result,
            REPO_NAME
        )
        
        # Save JSON result
        json_path = Path("output/debugging_brief.json")
        json_path.write_text(brief.model_dump_json(indent=2))
        print(f"\n💾 JSON saved to: {json_path}")
        
        # Save Markdown result
        md_path = Path("output/debugging_brief.md")
        md_path.write_text(brief.to_markdown(), encoding='utf-8')
        print(f"💾 Markdown saved to: {md_path}")
        
        # Print preview
        print("\n" + "="*60)
        print("📄 MARKDOWN PREVIEW")
        print("="*60)
        print(brief.to_markdown()[:2000])
        if len(brief.to_markdown()) > 2000:
            print("\n... [truncated - see full file]")
        
        print("\n" + "="*60)
        print("✅ Phase 5 Complete! Synthesis Agent working!")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ Error during synthesis: {e}")
        import traceback
        traceback.print_exc()