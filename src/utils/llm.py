"""
llm.py - Shared LLM instance with rate limiting

Prevents throttling by:
1. Single shared LLM instance
2. Delay between calls
3. Retry with exponential backoff
"""

import os
import time
from functools import wraps
from dotenv import load_dotenv
from langchain_aws import ChatBedrock

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"

MIN_DELAY_BETWEEN_CALLS = 2  # seconds
MAX_RETRIES = 3
BACKOFF_FACTOR = 2

_last_call_time = 0
_llm_instance = None


def get_llm() -> ChatBedrock:
    """Get shared LLM instance (singleton)."""
    global _llm_instance
    
    if _llm_instance is None:
        _llm_instance = ChatBedrock(
            model_id=BEDROCK_MODEL_ID,
            region_name=AWS_REGION,
            model_kwargs={
                "temperature": 0.1,
                "max_tokens": 2000,
            }
        )
    
    return _llm_instance


def rate_limited_invoke(chain, input_vars: dict, max_retries: int = MAX_RETRIES):
    """
    Invoke LLM chain with rate limiting and retry.
    
    Args:
        chain: LangChain chain to invoke
        input_vars: Variables for the chain
        max_retries: Max retry attempts
        
    Returns:
        Chain response
    """
    global _last_call_time
    
    # Ensure minimum delay between calls
    elapsed = time.time() - _last_call_time
    if elapsed < MIN_DELAY_BETWEEN_CALLS:
        wait_time = MIN_DELAY_BETWEEN_CALLS - elapsed
        print(f"[Rate Limit] Waiting {wait_time:.1f}s...")
        time.sleep(wait_time)
    
    # Retry with exponential backoff
    for attempt in range(max_retries + 1):
        try:
            _last_call_time = time.time()
            return chain.invoke(input_vars)
            
        except Exception as e:
            error_str = str(e).lower()
            
            # Check if it's a throttling error
            if "throttling" in error_str or "too many requests" in error_str:
                if attempt < max_retries:
                    wait_time = BACKOFF_FACTOR ** (attempt + 1)
                    print(f"[Rate Limit] Throttled. Retry {attempt + 1}/{max_retries} in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
            
            # Not a throttling error or max retries exceeded
            raise
    
    raise Exception("Max retries exceeded")