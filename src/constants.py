"""
constants.py - Shared Constants for CI/CD Root Cause Analyzer

Centralized configuration to eliminate duplication across modules.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# AWS/Bedrock Configuration
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"

# GitHub Configuration  
GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")

# Tavily Configuration
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

# Rate Limiting
DELAY_BETWEEN_LLM_CALLS = 3  # seconds
MAX_FAILURES = 3  # max retries per workflow step
MIN_DELAY_BETWEEN_CALLS = 2  # seconds for LLM rate limiting
MAX_RETRIES = 3
BACKOFF_FACTOR = 2

# File Size Limits
MAX_FILE_SIZE = 100 * 1024  # 100KB
MAX_CONTENT_LENGTH = 10000  # for LLM context

# Output Configuration
DEFAULT_OUTPUT_DIR = "output"

# Priority Files for Code Context
PRIORITY_FILES = [
    "requirements.txt",
    "setup.py", 
    "pyproject.toml",
    "package.json",
    "Pipfile",
    "poetry.lock",
    "README.md",
    "README.rst",
    ".python-version",
    "runtime.txt",
    "Dockerfile",
    "docker-compose.yml",
]