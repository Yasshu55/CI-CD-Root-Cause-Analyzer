"""
log_parser.py - CI/CD Log Parser

This module extracts structured error information from raw GitHub Actions logs.
It identifies error types, extracts stack traces, and prepares data for AI analysis.

Part of the CI/CD Root Cause Analyzer project.

Key Features:
- Regex-based pattern matching for common error types
- Support for Python, Node.js, and generic errors
- Pydantic models for type-safe structured output
- Noise reduction (removes timestamps, groups irrelevant info)
"""

import re
from pathlib import Path
from typing import Optional
from enum import Enum

from pydantic import BaseModel, Field


# ENUMS AND CONSTANTS

class ErrorCategory(str, Enum):
    """
    Classification categories for CI/CD errors.
    
    Why use Enum?
    - Type safety: Only these values are allowed
    - IDE autocomplete: Easy to discover valid options
    - Documentation: Self-documenting code
    """
    DEPENDENCY = "dependency"           # Missing modules, packages
    SYNTAX = "syntax"                   # Syntax errors in code
    TEST_FAILURE = "test_failure"       # Failed test assertions
    CONFIGURATION = "configuration"     # Config/environment issues
    BUILD = "build"                     # Compilation/build errors
    RUNTIME = "runtime"                 # Runtime exceptions
    NETWORK = "network"                 # Network/API failures
    PERMISSION = "permission"           # Permission denied errors
    TIMEOUT = "timeout"                 # Timeout errors
    UNKNOWN = "unknown"                 # Cannot classify

# PYDANTIC MODELS (Structured Output)

class StackFrame(BaseModel):
    """Represents a single frame in a stack trace."""
    file: Optional[str] = None
    line_number: Optional[int] = None
    function: Optional[str] = None
    code: Optional[str] = None


class ParsedError(BaseModel):
    """
    Structured representation of an error extracted from logs.
    
    This model is the OUTPUT of our parser and INPUT to our AI agents.
    Having a well-defined schema makes the entire pipeline more reliable.
    """
    # Core error information
    error_type: str = Field(
        description="The Python/JS exception type (e.g., 'ModuleNotFoundError')"
    )
    error_message: str = Field(
        description="The actual error message"
    )
    error_category: ErrorCategory = Field(
        default=ErrorCategory.UNKNOWN,
        description="High-level classification of the error"
    )
    
    # Context
    failed_step: Optional[str] = Field(
        default=None,
        description="The GitHub Actions step that failed"
    )
    exit_code: Optional[int] = Field(
        default=None,
        description="Process exit code (usually 1 for errors)"
    )
    
    # Stack trace
    stack_trace: list[str] = Field(
        default_factory=list,
        description="Lines of the stack trace"
    )
    stack_frames: list[StackFrame] = Field(
        default_factory=list,
        description="Parsed stack trace frames (if available)"
    )
    
    # Raw context (useful for AI)
    relevant_lines: list[str] = Field(
        default_factory=list,
        description="Other relevant log lines around the error"
    )
    raw_error_block: str = Field(
        default="",
        description="The complete raw error block from logs"
    )


class LogParseResult(BaseModel):
    """
    Complete result of parsing a log file.
    
    Contains all errors found plus metadata about the parse operation.
    """
    # Parsing status
    success: bool = Field(
        description="Whether parsing completed successfully"
    )
    
    # Errors found
    errors: list[ParsedError] = Field(
        default_factory=list,
        description="List of all errors found in the log"
    )
    primary_error: Optional[ParsedError] = Field(
        default=None,
        description="The main/root error (usually the first one)"
    )
    
    # Metadata
    total_lines: int = Field(
        default=0,
        description="Total lines in the log file"
    )
    error_count: int = Field(
        default=0,
        description="Number of errors detected"
    )
    
    # Summary (useful for quick display)
    summary: str = Field(
        default="",
        description="One-line summary of what went wrong"
    )


# REGEX PATTERNS

class LogPatterns:
    """
    Centralized regex patterns for log parsing.
    
    Why a separate class?
    - Single source of truth for all patterns
    - Easy to add new patterns for different languages
    - Testable in isolation
    
    Regex Crash Course:
    - r"..." = raw string (backslashes work properly)
    - ^ = start of line
    - $ = end of line
    - .* = any characters (greedy)
    - .*? = any characters (non-greedy/lazy)
    - (?P<name>...) = named capture group
    - \d+ = one or more digits
    """
    
    # GitHub Actions timestamp pattern
    # Example: 2025-12-19T06:33:34.9138563Z
    TIMESTAMP = re.compile(
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z\s*'
    )
    
    # GitHub Actions special markers
    GH_ERROR = re.compile(r'##\[error\](.+)$', re.MULTILINE)
    GH_GROUP = re.compile(r'##\[group\](.+)$', re.MULTILINE)
    GH_ENDGROUP = re.compile(r'##\[endgroup\]')
    
    # Exit code pattern
    # Example: "Process completed with exit code 1"
    EXIT_CODE = re.compile(
        r'(?:Process completed with exit code|exit code|Exit code)[:\s]+(\d+)',
        re.IGNORECASE
    )
    
    # Python Traceback
    PYTHON_TRACEBACK_START = re.compile(r'Traceback \(most recent call last\):')
    
    # Python stack frame
    # Example: File "/path/to/file.py", line 42, in function_name
    PYTHON_STACK_FRAME = re.compile(
        r'File ["\'](?P<file>[^"\']+)["\'],\s*line (?P<line>\d+)(?:,\s*in (?P<function>\w+))?'
    )
    
    # Python error types (common ones)
    PYTHON_ERROR = re.compile(
        r'^(?P<type>(?:ModuleNotFoundError|ImportError|SyntaxError|IndentationError|'
        r'TypeError|ValueError|KeyError|AttributeError|NameError|FileNotFoundError|'
        r'RuntimeError|ZeroDivisionError|IndexError|AssertionError|Exception|'
        r'OSError|IOError|PermissionError|ConnectionError|TimeoutError))\s*:\s*(?P<message>.+)$',
        re.MULTILINE
    )
    
    # Node.js / npm errors
    NPM_ERROR = re.compile(r'^npm ERR!\s*(.+)$', re.MULTILINE)
    NODE_MODULE_ERROR = re.compile(
        r"Cannot find module ['\"]([^'\"]+)['\"]",
        re.IGNORECASE
    )
    
    # Generic error patterns
    GENERIC_ERROR = re.compile(
        r'^(?:Error|ERROR|error):\s*(.+)$',
        re.MULTILINE
    )
    
    # Test failure patterns (pytest, jest, etc.)
    PYTEST_FAILED = re.compile(r'FAILED\s+(\S+)', re.MULTILINE)
    ASSERTION_ERROR = re.compile(r'AssertionError:\s*(.+)$', re.MULTILINE)
    
    # Failed step name (from GitHub Actions)
    # Example: "Run npm test" or "Run python -c ..."
    FAILED_STEP = re.compile(
        r'##\[group\]Run (.+?)(?:\n|##\[endgroup\])',
        re.DOTALL
    )

# HELPER FUNCTIONS

def remove_timestamps(log_content: str) -> str:
    """
    Remove GitHub Actions timestamps from log lines.
    
    Why remove timestamps?
    - Reduces noise for pattern matching
    - Makes logs more readable
    - Timestamps aren't useful for error analysis
    
    Before: "2025-12-19T06:33:34.9138563Z Error: something failed"
    After:  "Error: something failed"
    """
    lines = log_content.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # Remove timestamp prefix if present
        cleaned = LogPatterns.TIMESTAMP.sub('', line)
        cleaned_lines.append(cleaned)
    
    return '\n'.join(cleaned_lines)


def classify_error(error_type: str, error_message: str) -> ErrorCategory:
    """
    Classify an error into a high-level category.
    
    This classification helps our AI agents understand the nature
    of the problem without analyzing the full error details.
    
    Args:
        error_type: The exception type (e.g., "ModuleNotFoundError")
        error_message: The error message
        
    Returns:
        ErrorCategory enum value
    """
    error_type_lower = error_type.lower()
    message_lower = error_message.lower()
    
    # Dependency errors
    if any(x in error_type_lower for x in ['modulenotfound', 'import', 'module']):
        return ErrorCategory.DEPENDENCY
    if 'cannot find module' in message_lower:
        return ErrorCategory.DEPENDENCY
    if 'no module named' in message_lower:
        return ErrorCategory.DEPENDENCY
    if 'npm err' in message_lower:
        return ErrorCategory.DEPENDENCY
    
    # Syntax errors
    if any(x in error_type_lower for x in ['syntax', 'indentation']):
        return ErrorCategory.SYNTAX
    
    # Test failures
    if 'assertion' in error_type_lower:
        return ErrorCategory.TEST_FAILURE
    if 'failed' in message_lower and 'test' in message_lower:
        return ErrorCategory.TEST_FAILURE
    
    # Permission errors
    if 'permission' in error_type_lower or 'permission denied' in message_lower:
        return ErrorCategory.PERMISSION
    
    # Network errors
    if any(x in error_type_lower for x in ['connection', 'timeout', 'network']):
        return ErrorCategory.NETWORK
    if any(x in message_lower for x in ['connection refused', 'network', 'timeout']):
        return ErrorCategory.NETWORK
    
    # File errors
    if 'filenotfound' in error_type_lower:
        return ErrorCategory.CONFIGURATION
    
    # Runtime errors
    if any(x in error_type_lower for x in ['type', 'value', 'key', 'attribute', 'name', 'index']):
        return ErrorCategory.RUNTIME
    
    return ErrorCategory.UNKNOWN


def extract_python_stack_trace(log_content: str) -> tuple[list[str], list[StackFrame]]:
    """
    Extract Python stack trace from log content.
    
    Returns:
        Tuple of (raw stack trace lines, parsed stack frames)
    """
    stack_lines = []
    stack_frames = []
    
    # Find traceback start
    match = LogPatterns.PYTHON_TRACEBACK_START.search(log_content)
    if not match:
        return stack_lines, stack_frames
    
    # Get content after "Traceback (most recent call last):"
    start_pos = match.end()
    lines = log_content[start_pos:].split('\n')
    
    in_traceback = True
    for line in lines:
        stripped = line.strip()
        
        if not stripped:
            continue
            
        # Check if we've hit the actual error line (end of traceback)
        if LogPatterns.PYTHON_ERROR.match(stripped):
            break
            
        # Check if this looks like a stack frame
        frame_match = LogPatterns.PYTHON_STACK_FRAME.search(stripped)
        if frame_match:
            stack_lines.append(stripped)
            stack_frames.append(StackFrame(
                file=frame_match.group('file'),
                line_number=int(frame_match.group('line')),
                function=frame_match.group('function')
            ))
        elif stripped.startswith(('File ', '  ')):
            # Code context line or continuation
            stack_lines.append(stripped)
            if stack_frames and not stripped.startswith('File '):
                # This is the code line for the previous frame
                stack_frames[-1].code = stripped
    
    return stack_lines, stack_frames

# MAIN PARSER CLASS

class LogParser:
    """
    Main parser class for CI/CD build logs.
    
    Usage:
        parser = LogParser()
        result = parser.parse_file("output/build_log.txt")
        print(result.primary_error)
    """
    
    def __init__(self):
        """Initialize the parser."""
        self.patterns = LogPatterns()
    
    def parse_file(self, file_path: str | Path) -> LogParseResult:
        """
        Parse a log file and extract structured error information.
        
        Args:
            file_path: Path to the log file
            
        Returns:
            LogParseResult containing all extracted information
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            return LogParseResult(
                success=False,
                summary=f"Log file not found: {file_path}"
            )
        
        log_content = file_path.read_text(encoding='utf-8', errors='replace')
        return self.parse_content(log_content)
    
    def parse_content(self, log_content: str) -> LogParseResult:
        """
        Parse log content string and extract structured error information.
        
        This is the main parsing method. It:
        1. Cleans the log content
        2. Extracts all errors
        3. Classifies and structures them
        4. Returns a comprehensive result
        """
        total_lines = log_content.count('\n') + 1
        
        # Clean the logs (remove timestamps for easier parsing)
        cleaned_content = remove_timestamps(log_content)
        
        errors: list[ParsedError] = []
        
        # STEP 1: Extract GitHub Actions ##[error] markers
        gh_errors = LogPatterns.GH_ERROR.findall(cleaned_content)
        exit_code_match = LogPatterns.EXIT_CODE.search(cleaned_content)
        exit_code = int(exit_code_match.group(1)) if exit_code_match else None
        
        # STEP 2: Find Python errors
        python_error_matches = list(LogPatterns.PYTHON_ERROR.finditer(cleaned_content))
        
        for match in python_error_matches:
            error_type = match.group('type')
            error_message = match.group('message').strip()
            
            # Extract stack trace for this error
            # Look backwards from the error to find the traceback
            error_start = match.start()
            preceding_content = cleaned_content[:error_start]
            stack_lines, stack_frames = extract_python_stack_trace(preceding_content)
            
            # Find the failed step (if available)
            failed_step = self._find_failed_step(cleaned_content, error_start)
            
            # Create the raw error block (for AI context)
            raw_block = self._extract_error_block(cleaned_content, error_start)
            
            errors.append(ParsedError(
                error_type=error_type,
                error_message=error_message,
                error_category=classify_error(error_type, error_message),
                failed_step=failed_step,
                exit_code=exit_code,
                stack_trace=stack_lines,
                stack_frames=stack_frames,
                raw_error_block=raw_block
            ))
        
        # STEP 3: Find npm/Node.js errors (if no Python errors found)
        if not errors:
            npm_errors = LogPatterns.NPM_ERROR.findall(cleaned_content)
            node_module_errors = LogPatterns.NODE_MODULE_ERROR.findall(cleaned_content)
            
            for module_name in node_module_errors:
                errors.append(ParsedError(
                    error_type="ModuleNotFoundError",
                    error_message=f"Cannot find module '{module_name}'",
                    error_category=ErrorCategory.DEPENDENCY,
                    exit_code=exit_code
                ))
            
            if npm_errors and not errors:
                # Combine npm errors into one
                errors.append(ParsedError(
                    error_type="NpmError",
                    error_message=npm_errors[0] if npm_errors else "npm installation failed",
                    error_category=ErrorCategory.DEPENDENCY,
                    exit_code=exit_code,
                    relevant_lines=npm_errors[:10]  # Keep first 10 npm error lines
                ))
        
        # STEP 4: Find generic errors (if nothing else found)
        if not errors:
            generic_errors = LogPatterns.GENERIC_ERROR.findall(cleaned_content)
            
            for error_msg in generic_errors[:3]:  # Limit to first 3
                errors.append(ParsedError(
                    error_type="Error",
                    error_message=error_msg.strip(),
                    error_category=ErrorCategory.UNKNOWN,
                    exit_code=exit_code
                ))
        
        # STEP 5: Fallback - use GitHub ##[error] markers
        if not errors and gh_errors:
            for gh_error in gh_errors:
                # Skip generic "Process completed with exit code" errors
                if 'Process completed with exit code' in gh_error:
                    continue
                    
                errors.append(ParsedError(
                    error_type="GitHubActionsError",
                    error_message=gh_error.strip(),
                    error_category=ErrorCategory.UNKNOWN,
                    exit_code=exit_code
                ))
        
        # STEP 6: Create result
        primary_error = errors[0] if errors else None
        
        # Generate summary
        if primary_error:
            summary = f"{primary_error.error_type}: {primary_error.error_message[:100]}"
        else:
            summary = "No specific error identified (check raw logs)"
        
        return LogParseResult(
            success=True,
            errors=errors,
            primary_error=primary_error,
            total_lines=total_lines,
            error_count=len(errors),
            summary=summary
        )
    
    def _find_failed_step(self, content: str, error_position: int) -> Optional[str]:
        """
        Find the GitHub Actions step name that contains the error.
        
        Looks backwards from the error position to find the most recent
        ##[group]Run ... marker.
        """
        preceding = content[:error_position]
        
        # Find all "Run X" groups before this error
        groups = LogPatterns.FAILED_STEP.findall(preceding)
        
        if groups:
            # Return the most recent one (last in list)
            return groups[-1].strip().split('\n')[0]
        
        return None
    
    def _extract_error_block(
        self, 
        content: str, 
        error_position: int,
        context_lines: int = 10
    ) -> str:
        """
        Extract a block of content around the error for context.
        
        Provides surrounding lines that might help AI understand the error.
        """
        lines = content.split('\n')
        
        # Find which line the error is on
        char_count = 0
        error_line_idx = 0
        
        for i, line in enumerate(lines):
            char_count += len(line) + 1  # +1 for newline
            if char_count >= error_position:
                error_line_idx = i
                break
        
        # Get context lines before and after
        start_idx = max(0, error_line_idx - context_lines)
        end_idx = min(len(lines), error_line_idx + context_lines + 1)
        
        return '\n'.join(lines[start_idx:end_idx])


# CONVENIENCE FUNCTIONS

def parse_log_file(file_path: str | Path) -> LogParseResult:
    """
    Convenience function to parse a log file.
    
    Usage:
        result = parse_log_file("output/build_log.txt")
        print(result.summary)
    """
    parser = LogParser()
    return parser.parse_file(file_path)


def parse_log_content(content: str) -> LogParseResult:
    """
    Convenience function to parse log content directly.
    
    Usage:
        result = parse_log_content(log_string)
        print(result.primary_error)
    """
    parser = LogParser()
    return parser.parse_content(content)



if __name__ == "__main__":
    """
    Test the log parser with the output from Phase 1.
    """
    from pathlib import Path
    
    print("\n" + "="*60)
    print("🔍 CI/CD Root Cause Analyzer - Log Parser")
    print("="*60 + "\n")
    
    # Path to the log file from Phase 1
    log_file = Path("output/build_log.txt")
    
    if not log_file.exists():
        print(f"❌ Log file not found: {log_file}")
        print("   Please run github_loader.py first (Phase 1)")
        exit(1)
    
    print(f"📂 Parsing: {log_file}")
    print("-" * 40)
    
    # Parse the log file
    result = parse_log_file(log_file)

    print(f"\n📊 Parse Results:")
    print(f"   Total lines analyzed: {result.total_lines}")
    print(f"   Errors found: {result.error_count}")
    print(f"   Parse successful: {result.success}")
    
    if result.primary_error:
        error = result.primary_error
        print(f"\n🎯 Primary Error:")
        print(f"   Type: {error.error_type}")
        print(f"   Category: {error.error_category.value}")
        print(f"   Message: {error.error_message}")
        
        if error.failed_step:
            print(f"   Failed Step: {error.failed_step}")
        
        if error.exit_code:
            print(f"   Exit Code: {error.exit_code}")
        
        if error.stack_trace:
            print(f"\n📚 Stack Trace ({len(error.stack_trace)} frames):")
            for i, line in enumerate(error.stack_trace[:5]):  # Show first 5
                print(f"   {i+1}. {line}")
            if len(error.stack_trace) > 5:
                print(f"   ... and {len(error.stack_trace) - 5} more frames")
    
    print(f"\n📝 Summary: {result.summary}")
    
    # Also show raw error block for debugging
    if result.primary_error and result.primary_error.raw_error_block:
        print(f"\n📜 Raw Error Context (for AI analysis):")
        print("-" * 40)
        print(result.primary_error.raw_error_block[:500])  # First 500 chars
        if len(result.primary_error.raw_error_block) > 500:
            print("... [truncated]")
    
    print("\n" + "="*60)
    print("✅ Phase 2 Complete! Error data is structured and ready.")
    print("="*60 + "\n")
    
    # Export to JSON for verification
    output_json = Path("output/parsed_error.json")
    output_json.write_text(result.model_dump_json(indent=2))
    print(f"💾 Exported to: {output_json}")