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

## 🚀 How to Actually Use This Thing

**Local Setup** :
1. Clone this repo
2. Copy `.env.example` to `.env` 
3. Fill in your secrets (GitHub token, AWS credentials, etc.) - check `.env.example` for what you need
4. Install dependencies: `pip install -r requirements.txt`
5. Run it: `streamlit run app.py`

**Streamlit Cloud Deployment** (For the lazy, like me):
1. Fork this repo
2. Deploy to Streamlit Cloud
3. Add all your `.env` variables in the Streamlit secrets section
4. Click deploy

## Usage

```bash
python -m src.main owner/repo
```
# Final Result Images - 

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/2ee139e2-5eb1-49bb-9395-3a36aa08e959" />
<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/6a8addf4-512b-4b7f-901e-1b7057bde94c" />
<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/b711323a-e963-4b9f-bc89-029c34cff72d" />
<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/dd3c6d6e-eced-4960-8009-414fd1004b46" />
<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/8f981b42-b786-4035-8d9f-7cbeaf078f0f" />


