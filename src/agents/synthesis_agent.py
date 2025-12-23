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

from ..tools.log_parser import ParsedError
from .triage_agent import TriageResult
from .research_agent import ResearchResult
from ..graph.state import DebuggingBrief, FixSuggestion
from ..utils.llm import get_llm
from ..utils.shared_utils import extract_json_from_text
from ..prompts import SYNTHESIS_SYSTEM_PROMPT, SYNTHESIS_USER_PROMPT
from ..constants import BEDROCK_MODEL_ID






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
        
        data = extract_json_from_text(response_text)
        
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

