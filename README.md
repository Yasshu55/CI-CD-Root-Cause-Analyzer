# CI/CD Root Cause Analyzer

AI-powered multi-agent system that analyzes failed CI/CD builds and suggests fixes.

## Features

- Fetches failed GitHub Actions logs
- Extracts and classifies errors
- Researches solutions via web search
- Generates debugging brief with 3 actionable fixes

## Architecture

Uses LangGraph Supervisor-Worker pattern:

- Supervisor: Orchestrates workflow
- Triage Agent: Classifies errors
- Research Agent: Finds solutions
- Synthesis Agent: Creates final report

## Tech Stack

- Python 3.11
- LangGraph
- Claude 3.5 Sonnet (AWS Bedrock)
- Tavily API
- PyGithub

## Usage

```bash
python -m src.main owner/repo
```
