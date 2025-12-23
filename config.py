"""
config.py - Project Configuration

Centralized configuration management for the CI/CD Root Cause Analyzer.
"""

from pathlib import Path
from typing import Dict, Any
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class Config:
    """Main configuration class."""
    
    # Project Info
    PROJECT_NAME = "CI/CD Root Cause Analyzer"
    VERSION = "1.0.0"
    
    # Directories
    PROJECT_ROOT = Path(__file__).parent
    SRC_DIR = PROJECT_ROOT / "src"
    OUTPUT_DIR = PROJECT_ROOT / "output"
    TESTS_DIR = PROJECT_ROOT / "tests"
    
    # AWS Configuration
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"
    
    # API Keys
    GITHUB_ACCESS_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
    
    # Rate Limiting
    DELAY_BETWEEN_LLM_CALLS = 3
    MAX_FAILURES_PER_STEP = 3
    MIN_DELAY_BETWEEN_CALLS = 2
    MAX_RETRIES = 3
    BACKOFF_FACTOR = 2
    
    # File Processing
    MAX_FILE_SIZE = 100 * 1024  # 100KB
    MAX_CONTENT_LENGTH = 10000
    MAX_LOG_LINES = 50000
    
    # Default Repository for Testing
    DEFAULT_TEST_REPO = "Yasshu55/Test-repo"
    
    # Logging Configuration
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    @classmethod
    def validate(cls) -> Dict[str, Any]:
        """Validate configuration and return status."""
        issues = []
        
        if not cls.GITHUB_ACCESS_TOKEN:
            issues.append("GITHUB_ACCESS_TOKEN not set")
        
        if not cls.TAVILY_API_KEY:
            issues.append("TAVILY_API_KEY not set")
        
        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "config": {
                "aws_region": cls.AWS_REGION,
                "model_id": cls.BEDROCK_MODEL_ID,
                "has_github_token": bool(cls.GITHUB_ACCESS_TOKEN),
                "has_tavily_key": bool(cls.TAVILY_API_KEY),
            }
        }
    
    @classmethod
    def ensure_directories(cls):
        """Ensure all required directories exist."""
        for dir_path in [cls.OUTPUT_DIR, cls.TESTS_DIR]:
            dir_path.mkdir(parents=True, exist_ok=True)


# Create global config instance
config = Config()

# Validate on import
validation = config.validate()
if not validation["valid"]:
    print("⚠️ Configuration Issues:")
    for issue in validation["issues"]:
        print(f"  - {issue}")
    print("Please check your .env file")