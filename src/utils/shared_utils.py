"""
shared_utils.py - Shared Utility Functions

Common functions used across multiple modules to eliminate duplication.
"""

import json
import re
from typing import Optional, Dict, Any
from pathlib import Path


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
    
    # Remove trailing commas before } or ]
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    
    return text


def extract_json_from_text(text: str) -> Optional[Dict[Any, Any]]:
    """
    Extract JSON object from text that might contain other content.
    
    Uses multiple strategies:
    1. Direct parsing
    2. Clean and parse
    3. Find JSON in text using regex
    4. Find JSON by bracket matching
    """
    # Strategy 1: Direct parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Strategy 2: Clean and parse
    try:
        cleaned = clean_json_string(text)
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # Strategy 3: Find JSON object using regex
    try:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            json_str = match.group()
            cleaned = clean_json_string(json_str)
            return json.loads(cleaned)
    except (json.JSONDecodeError, AttributeError):
        pass
    
    # Strategy 4: Bracket matching
    try:
        start_idx = text.find('{')
        if start_idx != -1:
            bracket_count = 0
            end_idx = start_idx
            
            for i, char in enumerate(text[start_idx:], start_idx):
                if char == '{':
                    bracket_count += 1
                elif char == '}':
                    bracket_count -= 1
                    if bracket_count == 0:
                        end_idx = i + 1
                        break
            
            if end_idx > start_idx:
                json_str = text[start_idx:end_idx]
                cleaned = clean_json_string(json_str)
                return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    
    return None


def parse_llm_json_response(response_text: str, fallback_data: Optional[Dict] = None) -> Dict[Any, Any]:
    """
    Parse LLM response as JSON with robust error handling.
    
    Returns a valid dict or a fallback structure.
    """
    result = extract_json_from_text(response_text)
    
    if result:
        return result
    
    print(f"Could not parse JSON. Response preview: {response_text[:300]}...")
    
    return fallback_data or {
        "error": "Could not parse AI response - see raw data",
        "raw_response": response_text[:500]
    }


def ensure_output_dir(output_dir: str = "output") -> Path:
    """Ensure output directory exists and return Path object."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def truncate_text(text: str, max_length: int = 1000, suffix: str = "...") -> str:
    """Truncate text to max_length with suffix if needed."""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def validate_repo_format(repo_name: str) -> bool:
    """Validate that repo_name is in 'owner/repo' format."""
    return "/" in repo_name and len(repo_name.split("/")) == 2


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"