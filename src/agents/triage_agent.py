"""
triage_agent.py - CI/CD Error Triage Agent

This agent analyzes parsed CI/CD errors and provides:
- Severity assessment
- Root cause hypothesis
- Initial fix suggestions
- Determination of whether further research is needed

Uses Claude via AWS Bedrock for intelligent analysis.
"""

import os
import json
from typing import Optional
from enum import Enum

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from langchain_aws import ChatBedrock
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from src.tools.log_parser import ParsedError, LogParseResult, ErrorCategory

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"



# ENUMS and Models

class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class RefinedErrorCategory(str, Enum):
    
    # Dependency issues
    MISSING_PACCKAGE = "missing_package"
    VERSION_CONFLICT = "version_conflict"
    INCOMPATIBLE_DEPENDENCY = "incompatible_dependency"
    
    # Code issues
    SYNTAX_ERROR = "syntax_error"
    TYPE_ERROR = "type_error"
    IMPORT_ERROR = "import_error"
    
    # Test Issues
    ASSERTION_FAILURE = "assertion_failure"
    TEST_TIMEOUT = "test_timeout"
    FIXTURE_ERROR = "fixture_error"

    # Configuration/Env Issues
    MISSING_ENV_VAR = "missing_env_var"
    INVALID_CONFIG = "invalid_config"
    MISSING_FILE = "missing_file"
    
    # Infra issues
    NETWORK_ERROR = "network_error"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_LIMIT = "resource_limit"
    
    # other
    UNKNOWN = "unknown"
    
class TriageResult(BaseModel):
    severity : Severity = Field(description="How Urgent is this error?")
    severity_reasoning : str = Field(description="Wgy this severity lvl was choosen")
    root_cause: str = Field(description="One sentence description of the root cause")
    root_cause_detailed : str = Field(description="Detailed explanation of what went wrong and why")
    error_category_refined: RefinedErrorCategory = Field(description="Specific category after AI analysis")
    affected_files : list[str] = Field( 
        default_factory=list, 
        description="List of files likely involved in the error"
    )
    affected_components: list[str] = Field(
        default_factory=list,
        description="System components affected (e.g., 'database', 'auth', 'api')"
    )
    immediate_suggestions: list[str] = Field(description="3-5 actionable fix suggestions")
    requires_research: bool = Field(description="Does this need web research for solutions?")
    research_queries: list[str] = Field(
        default_factory=list,
        description="Suggested search queries if research is needed"
    )
    confidence_score: float = Field(
        ge=0.0, le=1.0,
        description="How confident the AI is in this analysis (0-1)"
    )
    
TRIAGE_SYSTEM_PROMPT = """You are an expert CI/CD debugging assistant. Your job is to analyze build failures and provide actionable insights.

You have deep expertise in:
- Python, Node.js, and common programming languages
- Package managers (pip, npm, yarn, poetry)
- CI/CD systems (GitHub Actions, Jenkins, GitLab CI)
- Common error patterns and their solutions

When analyzing an error, you should:
1. Identify the root cause (not just the symptom)
2. Assess the severity based on impact
3. Provide specific, actionable fix suggestions
4. Determine if web research would help find solutions

Be concise but thorough. Focus on actionable insights."""


TRIAGE_USER_PROMPT = """Analyze this CI/CD build failure and provide a structured diagnosis.

## Error Information

**Error Type:** {error_type}
**Error Message:** {error_message}
**Error Category:** {error_category}
**Failed Step:** {failed_step}
**Exit Code:** {exit_code}

## Stack Trace
{stack_trace}

## Raw Error Context
{raw_error_block}

## Your Task

Provide a JSON response with the following structure:
{{
    "severity": "critical|high|medium|low",
    "severity_reasoning": "Why this severity level",
    "root_cause": "One sentence root cause",
    "root_cause_detailed": "Detailed explanation",
    "error_category_refined": "specific_category",
    "affected_files": ["file1.py", "file2.py"],
    "affected_components": ["component1", "component2"],
    "immediate_suggestions": [
        "First suggestion",
        "Second suggestion",
        "Third suggestion"
    ],
    "requires_research": true/false,
    "research_queries": ["search query 1", "search query 2"],
    "confidence_score": 0.0-1.0
}}

For error_category_refined, use one of:
- missing_package, version_conflict, incompatible_dependency
- syntax_error, type_error, import_error
- assertion_failure, test_timeout, fixture_error
- missing_env_var, invalid_config, missing_file
- network_error, permission_denied, resource_limit
- unknown

Respond ONLY with the JSON object, no additional text."""


class TriageAgent: 
    """
    AI-powered agent for triaging CI/CD errors.
    
    This agent takes a parsed error and uses Claude to:
    1. Assess severity
    2. Identify root cause
    3. Suggest immediate fixes
    4. Determine if research is needed
    
    Usage:
        agent = TriageAgent()
        result = agent.analyze(parsed_error)
        print(result.root_cause)
    """

    def __init__(self, model_id : str = BEDROCK_MODEL_ID):
        self.model_id = model_id
        self.llm = self._create_llm()
        self.prompt = self._create_prompt()
    
    def _create_llm(self) -> ChatBedrock:
        if not os.getenv("AWS_ACCESS_KEY_ID"):
            raise ValueError(
                "AWS_ACCESS_KEY_ID not found in environment.\n"
                "Please set up your AWS credentials in .env file."
            )
        print(f"Initializing Claude via Bedrock ({self.model_id}")
        
        llm = ChatBedrock(
            model_id=self.model_id,
            provider="anthropic",
            region_name=AWS_REGION,
            model_kwargs={
                "temperature": 0.1,
                "max_tokens": 2000,
            }
        )
        
        print("Claude initialized successfully!")
        return llm
    
    def _create_prompt(self) -> ChatPromptTemplate:
        
        return ChatPromptTemplate.from_messages([
            ("system", TRIAGE_SYSTEM_PROMPT),
            ("human", TRIAGE_USER_PROMPT)
        ])
        
    def _format_error_for_prompt(self, error: ParsedError) -> dict:
        """
        Format a ParsedError into prompt variables.
        
        This bridges our Pydantic model to the prompt template.
        """
        print("Formatting error for prompt...")
        
        return {
            "error_type": error.error_type,
            "error_message": error.error_message,
            "error_category": error.error_category.value if error.error_category else "unknown",
            "failed_step": error.failed_step or "Unknown",
            "exit_code": error.exit_code or "Unknown",
            "stack_trace": "\n".join(error.stack_trace) if error.stack_trace else "No stack trace available",
            "raw_error_block": error.raw_error_block[:2000] if error.raw_error_block else "No additional context"
        }
    
    def _parse_llm_response(self, response_text: str) -> TriageResult:
        try:
            cleaned = response_text.strip()
            
             # Remove ```json and ``` if present
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
                
            cleaned = cleaned.strip()
            
            data = json.loads(cleaned)
            
            return TriageResult(**data)
            
        except json.JSONDecodeError as e:
            print(f"Failed to parse LLM response as JSON: {e}")
            print(f"Response was: {response_text[:200]}...")
            
            return TriageResult(
                severity=Severity.MEDIUM,
                severity_reasoning="Could not parse AI response",
                root_cause="Analysis failed - please review logs manually",
                root_cause_detailed=f"The AI response could not be parsed: {response_text[:500]}",
                error_category_refined=RefinedErrorCategory.UNKNOWN,
                immediate_suggestions=["Review the raw logs manually"],
                requires_research=True,
                research_queries=["CI/CD build failure debugging"],
                confidence_score=0.0
            )
        
        except Exception as e:
            print(f"Error creating TriageResult: {e}")
            raise
        
    def analyze(self, error : ParsedError) -> TriageResult:
        """ Main entry point
        Args:
            error: ParsedError from the log parser
        Returns:
            TriageResult with severity, root cause, and suggestions
        """
        
        print("TRIAGE AGENT - Analyzing Error")
        
        prompts_vars = self._format_error_for_prompt(error)
        print("Formatted!")
        chain = self.prompt | self.llm
        
        print("\n Sending to claude for analysis..")
        response = chain.invoke(prompts_vars)
        print("\n Recieved res from claude")
        
        result = self._parse_llm_response(response.content)
        
        return result


if __name__ == "__main__":
    """
    Test the Triage Agent with the parsed error from Phase 2.
    """
    
    print("\n" + "="*60)
    print("CI/CD Root Cause Analyzer - Triage Agent")
    print("="*60 + "\n")
    
    parsed_error_path = Path("output/parsed_error.json")
    
    if not parsed_error_path.exists():
        print(f"Parsed error file not found: {parsed_error_path}")
        print("Please run log_parser.py first (Phase 2)")
        exit(1)
    
    print(f"Loading parsed error from: {parsed_error_path}")
    
    with open(parsed_error_path) as f:
        data = json.load(f)
    
    if not data.get("primary_error"):
        print("No primary error in parsed data")
        exit(1)

    primary_error_data = data["primary_error"]
    parsed_error = ParsedError(**primary_error_data)
    
    print(f"✅ Loaded error: {parsed_error.error_type}")
    
    try:
        agent = TriageAgent()
        result = agent.analyze(parsed_error)
        
        # Save the result
        output_path = Path("output/triage_result.json")
        output_path.write_text(result.model_dump_json(indent=2))
        
        print("Phase 3 Complete! Triage analysis saved.")
        print(f"\n Results saved to: {output_path}")
        
    except Exception as e:
        print("\n❌ Error during triage:")
        print(e)
        raise
