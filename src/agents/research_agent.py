"""
research_agent.py - CI/CD Research Agent 

This agent performs research to find solutions for CI/CD failures:
1. Searches the web using Tavily for solutions
2. Fetches relevant code context from the repository
3. Uses Claude to synthesize findings into actionable solutions

- Robust JSON parsing with multiple fallback strategies
- Better handling of LLM response quirks
- Generates queries even when triage says not needed
"""

import os
import json
import re
from typing import Optional
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate

from ..tools.tavily_search import TavilySearchTool, SearchResponse
from ..tools.code_context import CodeContextFetcher, RepoContext
from ..tools.log_parser import ParsedError
from .triage_agent import TriageResult

from ..utils.llm import get_llm
from ..utils.shared_utils import parse_llm_json_response
from ..prompts import RESEARCH_SYNTHESIS_PROMPT
from ..constants import BEDROCK_MODEL_ID
from ..utils.shared_utils import extract_json_from_text


class SolutionCandidate(BaseModel):
    """A potential solution found during research."""
    title: str = Field(description="Short title for the solution")
    description: str = Field(description="What this solution does")
    steps: list[str] = Field(default_factory=list, description="Step-by-step implementation")
    source: str = Field(default="research", description="Where this solution came from")
    confidence: float = Field(
        default=0.5,
        ge=0.0, le=1.0,
        description="How confident we are this will work"
    )
    code_changes: Optional[str] = Field(
        default=None,
        description="Suggested code changes if applicable"
    )


class ResearchResult(BaseModel):
    """Complete result from the Research Agent."""
    error_summary: str = Field(description="Brief summary of the error")
    research_completed: bool = Field(
        default=True,
        description="Whether research was performed"
    )
    web_searches_performed: int = Field(default=0)
    web_findings: list[str] = Field(
        default_factory=list,
        description="Key findings from web search"
    )
    relevant_urls: list[str] = Field(
        default_factory=list,
        description="URLs that might be helpful"
    )
    repo_analyzed: Optional[str] = Field(
        default=None,
        description="Repository that was analyzed"
    )
    relevant_files: list[str] = Field(
        default_factory=list,
        description="Files relevant to the error"
    )
    code_observations: list[str] = Field(
        default_factory=list,
        description="Observations from code analysis"
    )
    solutions: list[SolutionCandidate] = Field(
        default_factory=list,
        description="Ranked list of solution candidates"
    )
    primary_recommendation: Optional[str] = Field(
        default=None,
        description="The single best recommendation"
    )
    raw_llm_response: Optional[str] = Field(
        default=None,
        description="Raw LLM response for debugging"
    )


RESEARCH_SYNTHESIS_PROMPT = """You are a CI/CD debugging expert. Analyze the research findings and provide solutions.

## Error Details
- Type: {error_type}
- Message: {error_message}
- Root Cause: {root_cause}

## Web Research Summary
{web_findings}

## Repository Context
Repository: {repo_name}
Files Found: {relevant_files}

Requirements.txt content:
{requirements_content}

Workflow file content:
{workflow_content}

## Instructions

Based on the above, provide your analysis as a JSON object. Be careful to:
1. Use double quotes for all strings
2. Escape any special characters in strings
3. Do NOT include trailing commas
4. Do NOT include code blocks with backticks inside JSON strings

Respond with ONLY this JSON structure:

{{
    "web_findings_summary": [
        "Finding 1 from web search",
        "Finding 2 from web search"
    ],
    "code_observations": [
        "Observation 1 about the code",
        "Observation 2 about the code"
    ],
    "solutions": [
        {{
            "title": "Solution Title",
            "description": "Brief description of the solution",
            "steps": [
                "Step 1: Do this",
                "Step 2: Then do this",
                "Step 3: Finally do this"
            ],
            "source": "web research or code analysis",
            "confidence": 0.85
        }}
    ],
    "primary_recommendation": "The single most important action to take"
}}

Provide 2-3 practical solutions. Respond ONLY with valid JSON, no other text."""

# JSON PARSING UTILITIES
def clean_json_string(text: str) -> str:
    """
    Clean a string to make it valid JSON.
    
    Handles common LLM JSON issues:
    - Markdown code blocks
    - Trailing commas
    - Single quotes
    - Unescaped newlines in strings
    """
    text = text.strip()
    
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    
    text = text.strip()
    
    # Remove trailing commas before } or ], This regex finds commas followed by whitespace and then } or ]
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    
    return text


def parse_llm_json_response(response_text: str) -> dict:
    """
    Parse LLM response as JSON with robust error handling.
    
    Returns a valid dict or a fallback structure.
    """
    result = extract_json_from_text(response_text)
    
    if result:
        return result
    
    print(f"  Could not parse JSON. Response preview: {response_text[:300]}...")
    
    return {
        "web_findings_summary": ["Could not parse AI response - see raw data"],
        "code_observations": [],
        "solutions": [],
        "primary_recommendation": "Manual review required - AI response parsing failed"
    }


# RESEARCH AGENT CLASS

class ResearchAgent:
    """
    AI-powered agent for researching CI/CD error solutions.
    
    This agent:
    1. Searches the web for solutions using Tavily
    2. Fetches relevant code from the repository
    3. Uses Claude to synthesize findings into actionable solutions
    
    Usage:
        agent = ResearchAgent(repo_name="owner/repo")
        result = agent.research(triage_result, parsed_error)
    """
    
    def __init__(
        self,
        repo_name: Optional[str] = None,
        model_id: str = BEDROCK_MODEL_ID
    ):
        """
        Initialize the Research Agent.
        
        Args:
            repo_name: GitHub repository to analyze (owner/repo)
            model_id: Bedrock model ID for synthesis
        """
        self.repo_name = repo_name
        self.model_id = model_id
        
        self.search_tool = TavilySearchTool()
        self.code_fetcher = None
        if repo_name:
            try:
                self.code_fetcher = CodeContextFetcher(repo_name)
            except Exception as e:
                print(f"Could not connect to repo: {e}")
        
        self.llm = self._create_llm()
        self.prompt = ChatPromptTemplate.from_messages([
            ("human", RESEARCH_SYNTHESIS_PROMPT)
        ])
    
    def _create_llm(self) -> ChatBedrock:
        print(f"Using shared Claude instance")
        return get_llm()
    
    def _generate_search_queries(
        self,
        triage_result: TriageResult,
        parsed_error: ParsedError
    ) -> list[str]:
        """
        Generate search queries for web research.
        
        Always generates queries, even if triage says not needed.
        """
        queries = []
        
        # Use triage-provided queries if available
        if triage_result.research_queries:
            queries.extend(triage_result.research_queries)
        
        # Always generate basic queries based on error
        error_short = parsed_error.error_message[:50].replace("'", "").replace('"', '')
        
        queries.extend([
            f"{parsed_error.error_type} {error_short} fix",
            f"GitHub Actions {parsed_error.error_type} solution",
            f"Python {parsed_error.error_type} how to fix"
        ])
        
        # Add category-specific queries
        if triage_result.error_category_refined:
            category = triage_result.error_category_refined.value
            queries.append(f"CI/CD {category} error solution")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_queries = []
        for q in queries:
            q_lower = q.lower().strip()
            if q_lower not in seen and len(q_lower) > 10:
                seen.add(q_lower)
                unique_queries.append(q)
        
        return unique_queries[:3]  # Limit to 3 queries
    
    def _perform_web_research(
        self,
        triage_result: TriageResult,
        parsed_error: ParsedError
    ) -> list[SearchResponse]:
        """
        Perform web searches based on triage findings.
        
        Returns:
            List of SearchResponse objects
        """
        print("\nPerforming Web Research...")
        print("-" * 40)
        
        queries = self._generate_search_queries(triage_result, parsed_error)
        
        print(f"Generated {len(queries)} search queries:")
        for q in queries:
            print(f"• {q}")
        
        return self.search_tool.search_multiple(queries, max_results_per_query=3)
    
    def _gather_code_context(self) -> Optional[RepoContext]:
        """
        Gather code context from the repository.
        """
        if not self.code_fetcher:
            print(" No repository configured, skipping code context")
            return None
        
        print("\n Gathering Code Context...")
        print("-" * 40)
        
        return self.code_fetcher.get_context()
    
    def _format_web_findings(self, search_responses: list[SearchResponse]) -> str:
        """Format web search results for the LLM prompt."""
        formatted = []
        
        for response in search_responses:
            formatted.append(f"\nSearch Query: {response.query}")
            
            if response.answer:
                formatted.append(f"Summary: {response.answer}")
            
            for i, result in enumerate(response.results, 1):
                formatted.append(f"\nResult {i}: {result.title}")
                formatted.append(f"URL: {result.url}")
                # Limit content length and clean it
                content = result.content[:400].replace('\n', ' ').strip()
                formatted.append(f"Content: {content}")
        
        return "\n".join(formatted) if formatted else "No web findings available."
    
    def _synthesize_findings(
        self,
        parsed_error: ParsedError,
        triage_result: TriageResult,
        web_findings_text: str,
        code_context: Optional[RepoContext]
    ) -> tuple[dict, str]:
        """
        Use Claude to synthesize findings into solutions.
        
        Returns:
            Tuple of (parsed dict, raw response text)
        """
        print("\n Synthesizing findings with Claude...")
        print("-" * 40)
        
        requirements_content = "No requirements.txt found"
        workflow_content = "No workflow files found"
        relevant_files = []
        
        if code_context:
            if code_context.requirements:
                requirements_content = code_context.requirements[:800]
            
            if code_context.workflow_files:
                wf_content = []
                for wf in code_context.workflow_files[:2]:
                    content = wf.content[:600].replace('`', "'")  # Replace backticks
                    wf_content.append(f"File: {wf.path}\n{content}")
                workflow_content = "\n\n".join(wf_content)
            
            relevant_files = [f.path for f in code_context.files]
        
        prompt_vars = {
            "error_type": parsed_error.error_type,
            "error_message": parsed_error.error_message[:200],
            "root_cause": triage_result.root_cause,
            "web_findings": web_findings_text[:3000],  # Limit size
            "repo_name": self.repo_name or "Not specified",
            "relevant_files": ", ".join(relevant_files) if relevant_files else "None found",
            "requirements_content": requirements_content,
            "workflow_content": workflow_content
        }
        
        chain = self.prompt | self.llm
        response = chain.invoke(prompt_vars)
        
        raw_response = response.content
        parsed = parse_llm_json_response(raw_response)
        
        return parsed, raw_response
    
    def research(
        self,
        triage_result: TriageResult,
        parsed_error: ParsedError
    ) -> ResearchResult:
        """
        Perform comprehensive research on the error.
        
        This is the main entry point for the Research Agent.
        """
        print("\n" + "="*60)
        print(" RESEARCH AGENT - Finding Solutions")
        print("="*60)
        
        print(f"\n Researching: {parsed_error.error_type}")
        print(f"   Root cause: {triage_result.root_cause[:60]}...")
        
        # Step 1: Web Research
        search_responses = self._perform_web_research(triage_result, parsed_error)
        web_findings_text = self._format_web_findings(search_responses)
        
        # Step 2: Code Context
        code_context = self._gather_code_context()
        
        # Step 3: Synthesize
        synthesis, raw_response = self._synthesize_findings(
            parsed_error, triage_result, web_findings_text, code_context
        )
        
        # Build relevant URLs from search results
        relevant_urls = []
        for response in search_responses:
            for result in response.results[:2]:
                if result.url:
                    relevant_urls.append(result.url)
        
        # Build solutions from synthesis
        solutions = []
        for sol_data in synthesis.get("solutions", []):
            try:
                solutions.append(SolutionCandidate(
                    title=sol_data.get("title", "Solution"),
                    description=sol_data.get("description", ""),
                    steps=sol_data.get("steps", []),
                    source=sol_data.get("source", "research"),
                    confidence=float(sol_data.get("confidence", 0.5)),
                    code_changes=sol_data.get("code_changes")
                ))
            except Exception as e:
                print(f"     Could not parse solution: {e}")
        
        # If no solutions from LLM, create fallback from triage suggestions
        if not solutions and triage_result.immediate_suggestions:
            print("    Using triage suggestions as fallback solutions")
            for i, suggestion in enumerate(triage_result.immediate_suggestions[:3]):
                solutions.append(SolutionCandidate(
                    title=f"Suggestion {i+1}",
                    description=suggestion,
                    steps=[suggestion],
                    source="triage_agent",
                    confidence=0.7
                ))
        
        result = ResearchResult(
            error_summary=f"{parsed_error.error_type}: {parsed_error.error_message[:100]}",
            research_completed=True,
            web_searches_performed=len(search_responses),
            web_findings=synthesis.get("web_findings_summary", []),
            relevant_urls=relevant_urls[:6],
            repo_analyzed=self.repo_name,
            relevant_files=[f.path for f in code_context.files] if code_context else [],
            code_observations=synthesis.get("code_observations", []),
            solutions=solutions,
            primary_recommendation=synthesis.get("primary_recommendation"),
            raw_llm_response=raw_response[:1000] if raw_response else None  # For debugging
        )
        
        return result


