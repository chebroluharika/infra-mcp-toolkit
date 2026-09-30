# Docs Agent Data

Place your product documentation here. The docs agent uses RAG (FAISS + sentence-transformers)
to search across your docs and answer questions.

## Setup
1. Drop your documentation files (markdown, JSON, HTML) into `docs_raw/`
2. Run `python ai_agents/docs_agent/tools/scraper.py` to index them
3. The FAISS index will be built automatically into `faiss_index/`

The `docs_index.json` and `faiss_index/` are auto-generated and excluded from git.
