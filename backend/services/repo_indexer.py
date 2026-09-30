"""
Repository Indexer Service (Patched for large repos)
==========================

Indexes a GitHub repository into FAISS for code context retrieval.

Features:
- Fetches file tree via GitHub API
- Parses Python files using AST (functions, classes, docstrings, imports)
- Builds a dependency graph (who imports whom)
- Stores code chunks in FAISS for semantic search

Usage:
    indexer = RepoIndexer()
    stats = await indexer.index_repo("your-org", "client")
    context = await indexer.get_file_context("src/auth/session_manager.py")
    deps = indexer.get_dependencies("src/auth/session_manager.py")
"""

import ast
import logging
import os
import pickle
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# Rate limit wait time (seconds)
RATE_LIMIT_WAIT = 60

# Add ai_agents to path for shared imports
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ai_agents_dir = os.path.join(_project_root, "ai_agents")
if _ai_agents_dir not in sys.path:
    sys.path.insert(0, _ai_agents_dir)

from core.embeddings import EmbeddingProvider, get_embedding_provider
from core.vector_store import FAISSVectorStore, SearchResult

# Index storage paths
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
REPO_INDEX_DIR = os.path.join(DATA_DIR, "repo_faiss_index")
DEP_GRAPH_PATH = os.path.join(DATA_DIR, "repo_dep_graph.pkl")

# File extensions to index
INDEXABLE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".java", ".cpp", ".hpp", ".c", ".h", ".cc", ".cxx"}

# Max file size to parse (skip very large files)
MAX_FILE_SIZE = 100_000  # 100KB


class RepoIndexer:
    """
    Indexes a GitHub repository into FAISS for code context retrieval.

    Parses Python files using AST to extract functions, classes, docstrings,
    and import relationships. Stores code chunks in FAISS for semantic search.
    """

    def __init__(
        self,
        embeddings: Optional[EmbeddingProvider] = None,
        index_path: str = REPO_INDEX_DIR,
        dep_graph_path: str = DEP_GRAPH_PATH,
    ):
        self._embeddings = embeddings
        self._store = FAISSVectorStore(index_path=index_path)
        self._index_path = index_path
        self._dep_graph_path = dep_graph_path
        self._dep_graph: Dict[str, Any] = {
            "forward_imports": {},
            "reverse_imports": {},
        }
        self._last_indexed: Optional[str] = None
        self._indexed_repo: Optional[str] = None

        # Try to load existing index + dep graph
        if self._store.load():
            logger.info("RepoIndexer: loaded existing index (%d vectors)", self._store.size)
        self._load_dep_graph()

    def _get_embeddings(self) -> EmbeddingProvider:
        """Lazy-load embedding provider."""
        if self._embeddings is None:
            self._embeddings = get_embedding_provider(
                provider="ollama",
                model=os.getenv("EMBEDDING_MODEL", "qwen3-embedding"),
                base_url=os.getenv("EMBEDDING_BASE_URL", ""),
                api_key=os.getenv("EMBEDDING_API_KEY", ""),
            )
        return self._embeddings

    def _load_dep_graph(self):
        """Load dependency graph from disk."""
        if os.path.exists(self._dep_graph_path):
            try:
                with open(self._dep_graph_path, "rb") as f:
                    self._dep_graph = pickle.load(f)
                logger.info(
                    "RepoIndexer: loaded dep graph (%d files)",
                    len(self._dep_graph.get("forward_imports", {})),
                )
            except Exception as e:
                logger.warning("RepoIndexer: failed to load dep graph: %s", e)

    def _save_dep_graph(self):
        """Save dependency graph to disk."""
        os.makedirs(os.path.dirname(self._dep_graph_path), exist_ok=True)
        with open(self._dep_graph_path, "wb") as f:
            pickle.dump(self._dep_graph, f)

    async def _fetch_directory_contents(
        self,
        client: httpx.AsyncClient,
        owner: str,
        repo: str,
        path: str,
        branch: str,
        headers: Dict[str, str],
        retries: int = 3,
    ) -> List[Dict]:
        """Fetch contents of a single directory using Contents API."""
        import asyncio

        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        if branch:
            url += f"?ref={branch}"

        for attempt in range(retries):
            try:
                response = await client.get(url, headers=headers)

                if response.status_code == 403:
                    reset_time = response.headers.get("X-RateLimit-Reset")
                    if reset_time:
                        wait_time = max(int(reset_time) - int(datetime.now().timestamp()), 1)
                        wait_time = min(wait_time, 60)
                    else:
                        wait_time = 60
                    logger.warning(f"[RepoIndexer] Rate limited. Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue

                if response.status_code == 404:
                    return []
                if response.status_code != 200:
                    logger.warning(f"[RepoIndexer] Error fetching {path}: {response.status_code}")
                    return []
                return response.json()
            except Exception as e:
                logger.warning(f"[RepoIndexer] Exception fetching {path}: {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(2**attempt)
        return []

    async def _fetch_file_tree_recursive(
        self, owner: str, repo: str, branch: str = "main", max_files: int = 100000
    ) -> List[Dict]:
        """Recursively fetch file tree using Contents API (handles large repos)."""
        import asyncio

        github_token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if github_token:
            headers["Authorization"] = f"token {github_token}"

        files = []
        dirs_to_process = [""]
        processed_dirs = set()

        skip_dirs = {
            "node_modules",
            ".git",
            "__pycache__",
            ".pytest_cache",
            "venv",
            "env",
            ".venv",
            "build",
            "dist",
            ".eggs",
            ".tox",
            ".mypy_cache",
            ".coverage",
            "htmlcov",
            "vendor",
            "third_party",
            "thirdparty",
            "external",
            ".idea",
            ".vscode",
            ".vs",
            "cmake-build-debug",
            "cmake-build-release",
            "debug",
            "release",
            "x64",
            "x86",
        }

        async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
            while dirs_to_process and len(files) < max_files:
                current_dir = dirs_to_process.pop(0)

                if current_dir in processed_dirs:
                    continue
                processed_dirs.add(current_dir)

                contents = await self._fetch_directory_contents(client, owner, repo, current_dir, branch, headers)

                if not isinstance(contents, list):
                    continue

                for item in contents:
                    item_type = item.get("type")
                    item_path = item.get("path", "")

                    if item_type == "dir":
                        dir_name = os.path.basename(item_path).lower()
                        if dir_name not in skip_dirs and not dir_name.startswith("."):
                            dirs_to_process.append(item_path)
                    elif item_type == "file":
                        ext = os.path.splitext(item_path)[1]
                        if ext in INDEXABLE_EXTENSIONS:
                            size = item.get("size", 0)
                            if size <= MAX_FILE_SIZE:
                                files.append({"path": item_path, "size": size, "sha": item.get("sha")})
                                if len(files) % 1000 == 0:
                                    logger.info(f"[RepoIndexer] Found {len(files)} files so far...")

                if len(processed_dirs) % 100 == 0:
                    await asyncio.sleep(0.5)

        logger.info(f"[RepoIndexer] Total files found: {len(files)}")
        return files

    async def _fetch_file_tree(
        self, owner: str, repo: str, branch: str = "main", max_files: int = 100000
    ) -> List[Dict]:
        """Fetch the file tree from GitHub API (handles truncation for large repos)."""
        github_token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github.v3+json"}
        if github_token:
            headers["Authorization"] = f"token {github_token}"

        url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"

        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                raise RuntimeError(f"GitHub API error ({response.status_code}): {response.text[:200]}")
            data = response.json()

        # Check if truncated - use recursive Contents API instead
        if data.get("truncated", False):
            logger.info("[RepoIndexer] Tree API truncated, using recursive Contents API...")
            return await self._fetch_file_tree_recursive(owner, repo, branch, max_files)

        files = []
        for item in data.get("tree", []):
            if item.get("type") != "blob":
                continue
            path = item.get("path", "")
            ext = os.path.splitext(path)[1]
            if ext in INDEXABLE_EXTENSIONS:
                size = item.get("size", 0)
                if size <= MAX_FILE_SIZE:
                    files.append({"path": path, "size": size, "sha": item.get("sha")})

        return files[:max_files]

    async def _fetch_file_content(self, owner: str, repo: str, path: str) -> Optional[str]:
        """Fetch a single file's content from GitHub."""
        github_token = os.getenv("GITHUB_TOKEN", "")
        headers = {"Accept": "application/vnd.github.v3.raw"}
        if github_token:
            headers["Authorization"] = f"token {github_token}"

        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                return response.text
        return None

    def _parse_python_file(self, content: str, file_path: str) -> List[Dict]:
        """
        Parse a Python file using AST to extract functions, classes, docstrings.

        Returns a list of code chunks, each representing a function or class.
        """
        chunks = []
        imports = []

        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Return a single chunk for the whole file if parsing fails
            return [
                {
                    "type": "file",
                    "name": file_path,
                    "docstring": "",
                    "signature": "",
                    "imports": [],
                    "line_start": 1,
                    "line_end": content.count("\n") + 1,
                }
            ]

        # Extract imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.append(module)

        # Extract module-level docstring
        module_docstring = ast.get_docstring(tree) or ""

        # Add file-level chunk
        chunks.append(
            {
                "type": "module",
                "name": file_path,
                "docstring": module_docstring[:500],
                "signature": f"module {os.path.basename(file_path)}",
                "imports": imports,
                "line_start": 1,
                "line_end": content.count("\n") + 1,
            }
        )

        # Extract functions and classes
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                docstring = ast.get_docstring(node) or ""
                args = [a.arg for a in node.args.args if a.arg != "self"]
                sig = f"def {node.name}({', '.join(args)})"
                if isinstance(node, ast.AsyncFunctionDef):
                    sig = f"async {sig}"

                chunks.append(
                    {
                        "type": "function",
                        "name": node.name,
                        "docstring": docstring[:500],
                        "signature": sig,
                        "imports": [],
                        "line_start": node.lineno,
                        "line_end": node.end_lineno or node.lineno,
                    }
                )

            elif isinstance(node, ast.ClassDef):
                docstring = ast.get_docstring(node) or ""
                bases = []
                for base in node.bases:
                    if isinstance(base, ast.Name):
                        bases.append(base.id)
                    elif isinstance(base, ast.Attribute):
                        bases.append(f"{ast.dump(base)}")

                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(item.name)

                sig = f"class {node.name}"
                if bases:
                    sig += f"({', '.join(bases)})"

                chunks.append(
                    {
                        "type": "class",
                        "name": node.name,
                        "docstring": docstring[:500],
                        "signature": sig,
                        "methods": methods,
                        "imports": [],
                        "line_start": node.lineno,
                        "line_end": node.end_lineno or node.lineno,
                    }
                )

        return chunks

    def _parse_cpp_file(self, content: str, file_path: str) -> List[Dict]:
        """
        Parse a C/C++ file using regex to extract functions, classes, and comments.

        This is a simplified parser that extracts:
        - Function signatures (returnType functionName(args))
        - Class/struct definitions
        - Multi-line comments (/** ... */ style for documentation)
        - Single-line comments above functions

        Returns a list of code chunks.
        """
        import re

        chunks = []
        lines = content.split("\n")

        # Add file-level chunk with any top comment
        top_comment = ""
        for line in lines[:20]:
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                top_comment += stripped.lstrip("/*/ ") + " "
            elif stripped and not stripped.startswith("#"):
                break

        chunks.append(
            {
                "type": "module",
                "name": file_path,
                "docstring": top_comment[:500].strip(),
                "signature": f"file {os.path.basename(file_path)}",
                "imports": [],
                "line_start": 1,
                "line_end": len(lines),
            }
        )

        # Regex patterns for C++ constructs
        # Function pattern: returnType functionName(args) { or ;
        func_pattern = re.compile(
            r"^[\s]*((?:virtual\s+|static\s+|inline\s+|explicit\s+|constexpr\s+)*"
            r"(?:[\w:*&<>]+\s+)+)"  # return type
            r"([\w~]+)\s*"  # function name
            r"\(([^)]*)\)\s*"  # parameters
            r"(?:const\s*)?(?:override\s*)?(?:final\s*)?"  # qualifiers
            r"(?:\{|;|$)",  # body start or declaration
            re.MULTILINE,
        )

        # Class/struct pattern
        class_pattern = re.compile(
            r"^[\s]*(class|struct)\s+([\w]+)\s*(?::\s*(?:public|private|protected)\s+[\w:]+)?", re.MULTILINE
        )

        # Extract classes/structs
        for match in class_pattern.finditer(content):
            class_type = match.group(1)
            class_name = match.group(2)
            line_num = content[: match.start()].count("\n") + 1

            # Try to get preceding comment
            preceding_lines = content[: match.start()].split("\n")[-5:]
            docstring = ""
            for line in preceding_lines:
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    docstring += stripped.lstrip("/*/ ") + " "

            chunks.append(
                {
                    "type": "class",
                    "name": class_name,
                    "docstring": docstring[:500].strip(),
                    "signature": f"{class_type} {class_name}",
                    "imports": [],
                    "line_start": line_num,
                    "line_end": line_num + 10,  # Approximate
                }
            )

        # Extract functions (skip common false positives)
        skip_keywords = {"if", "else", "while", "for", "switch", "catch", "return", "sizeof", "typeof"}
        for match in func_pattern.finditer(content):
            return_type = match.group(1).strip()
            func_name = match.group(2)
            params = match.group(3).strip()

            # Skip control flow statements and macros
            if func_name.lower() in skip_keywords:
                continue
            if func_name.startswith("_") and func_name.isupper():
                continue  # Likely a macro

            line_num = content[: match.start()].count("\n") + 1

            # Try to get preceding comment
            preceding_lines = content[: match.start()].split("\n")[-5:]
            docstring = ""
            for line in preceding_lines:
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    docstring += stripped.lstrip("/*/ ") + " "

            sig = f"{return_type} {func_name}({params})"
            chunks.append(
                {
                    "type": "function",
                    "name": func_name,
                    "docstring": docstring[:500].strip(),
                    "signature": sig[:200],
                    "imports": [],
                    "line_start": line_num,
                    "line_end": line_num + 20,  # Approximate
                }
            )

        return chunks if len(chunks) > 1 else [chunks[0]]  # Return at least the file chunk

    def _build_embedding_text(self, chunk: Dict, file_path: str) -> str:
        """Build the text to embed for a code chunk."""
        parts = [f"File: {file_path}"]

        if chunk.get("signature"):
            parts.append(chunk["signature"])
        if chunk.get("docstring"):
            parts.append(chunk["docstring"])
        if chunk.get("methods"):
            parts.append(f"Methods: {', '.join(chunk['methods'])}")
        if chunk.get("imports"):
            parts.append(f"Imports: {', '.join(chunk['imports'][:10])}")

        return ". ".join(parts)

    async def index_repo(
        self,
        owner: str,
        repo: str,
        branch: str = "main",
        force: bool = False,
        max_files: int = 500,
        path_filter: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Index a GitHub repository into FAISS.

        Args:
            owner: Repository owner
            repo: Repository name
            branch: Branch to index
            force: If True, re-index even if already indexed
            max_files: Maximum number of files to index
            path_filter: Optional callable(path: str) -> bool to filter files.
                         Only files where path_filter(path) is True will be indexed.
                         If None, all files matching INDEXABLE_EXTENSIONS are indexed.

        Returns:
            Dict with indexing statistics
        """
        repo_key = f"{owner}/{repo}:{branch}"

        if not force and self._indexed_repo == repo_key and self._store.size > 0:
            return {
                "status": "already_indexed",
                "repo": repo_key,
                "total_vectors": self._store.size,
                "last_indexed": self._last_indexed,
            }

        logger.info("RepoIndexer: starting index for %s", repo_key)

        # Clear existing
        self._store.clear()
        self._dep_graph = {"forward_imports": {}, "reverse_imports": {}}

        # Fetch file tree (pass max_files for recursive fetch)
        files = await self._fetch_file_tree(owner, repo, branch, max_files=max_files)
        if path_filter:
            files = [f for f in files if path_filter(f["path"])]
        files = files[:max_files]

        logger.info("RepoIndexer: found %d indexable files in %s", len(files), repo_key)

        all_chunks = []
        all_texts = []
        files_processed = 0

        for file_info in files:
            file_path = file_info["path"]

            try:
                content = await self._fetch_file_content(owner, repo, file_path)
                if not content:
                    continue

                files_processed += 1

                # Parse based on extension
                ext = os.path.splitext(file_path)[1]
                if ext == ".py":
                    code_chunks = self._parse_python_file(content, file_path)
                elif ext in {".cpp", ".hpp", ".c", ".h", ".cc", ".cxx"}:
                    code_chunks = self._parse_cpp_file(content, file_path)
                else:
                    # For other files, create a single chunk with file content summary
                    lines = content.split("\n")
                    code_chunks = [
                        {
                            "type": "file",
                            "name": file_path,
                            "docstring": "\n".join(lines[:20]),
                            "signature": f"file {os.path.basename(file_path)} ({len(lines)} lines)",
                            "imports": [],
                            "line_start": 1,
                            "line_end": len(lines),
                        }
                    ]

                # Build dependency graph from imports
                for chunk in code_chunks:
                    if chunk.get("imports"):
                        self._dep_graph["forward_imports"][file_path] = chunk["imports"]
                        for imp in chunk["imports"]:
                            if imp not in self._dep_graph["reverse_imports"]:
                                self._dep_graph["reverse_imports"][imp] = []
                            if file_path not in self._dep_graph["reverse_imports"][imp]:
                                self._dep_graph["reverse_imports"][imp].append(file_path)

                # Build FAISS chunks
                for i, chunk in enumerate(code_chunks):
                    embed_text = self._build_embedding_text(chunk, file_path)
                    chunk_id = f"REPO-{file_path}-{chunk['type']}-{i}"

                    faiss_chunk = {
                        "chunk_id": chunk_id,
                        "content": embed_text,
                        "file_path": file_path,
                        "chunk_type": chunk["type"],
                        "name": chunk.get("name", ""),
                        "docstring": chunk.get("docstring", ""),
                        "signature": chunk.get("signature", ""),
                        "methods": chunk.get("methods", []),
                        "imports": chunk.get("imports", []),
                        "line_start": chunk.get("line_start", 0),
                        "line_end": chunk.get("line_end", 0),
                        "source_url": f"https://github.com/{owner}/{repo}/blob/{branch}/{file_path}",
                        "source_title": file_path,
                    }

                    all_chunks.append(faiss_chunk)
                    all_texts.append(embed_text)

                if files_processed % 50 == 0:
                    logger.info("RepoIndexer: processed %d/%d files", files_processed, len(files))

            except Exception as e:
                logger.warning("RepoIndexer: failed to process %s: %s", file_path, e)
                continue

        if not all_chunks:
            return {
                "status": "no_files_indexed",
                "repo": repo_key,
                "files_found": len(files),
                "indexed": 0,
            }

        # Embed all texts
        logger.info("RepoIndexer: embedding %d code chunks...", len(all_texts))
        embeddings = await self._get_embeddings().embed_texts(all_texts)

        # Add to FAISS
        await self._store.add_documents(all_chunks, embeddings)

        # Save to disk
        self._store.save()
        self._save_dep_graph()
        self._last_indexed = datetime.now().isoformat()
        self._indexed_repo = repo_key

        stats = {
            "status": "success",
            "repo": repo_key,
            "files_found": len(files),
            "files_processed": files_processed,
            "total_chunks": len(all_chunks),
            "total_vectors": self._store.size,
            "dep_graph_files": len(self._dep_graph["forward_imports"]),
            "index_path": self._index_path,
            "last_indexed": self._last_indexed,
        }

        logger.info("RepoIndexer: indexing complete — %s", stats)
        return stats

    async def get_file_context(self, file_path: str, top_k: int = 5) -> List[SearchResult]:
        """
        Get context for a specific file from the index.

        Args:
            file_path: Path to the file in the repo
            top_k: Number of chunks to return

        Returns:
            List of SearchResult for that file
        """
        if self._store.size == 0:
            return []

        query_embedding = await self._get_embeddings().embed_query(f"File: {file_path}")

        # Filter to only chunks from this file
        results = await self._store.search_with_filter(
            query_embedding=query_embedding,
            top_k=top_k,
            filter_fn=lambda meta: meta.get("file_path") == file_path,
        )

        return results

    def get_dependencies(self, file_path: str) -> Dict[str, List[str]]:
        """
        Get dependency information for a file.

        Args:
            file_path: Path to the file

        Returns:
            Dict with 'imports' (what this file imports) and
            'imported_by' (what imports this file)
        """
        # Normalize path for matching
        imports = self._dep_graph.get("forward_imports", {}).get(file_path, [])

        # Check reverse imports by file path and module name
        imported_by = []
        file_module = file_path.replace("/", ".").replace(".py", "")
        file_stem = os.path.splitext(os.path.basename(file_path))[0]

        for key, dependents in self._dep_graph.get("reverse_imports", {}).items():
            if key == file_path or key == file_module or key.endswith(f".{file_stem}"):
                imported_by.extend(dependents)

        return {
            "imports": imports,
            "imported_by": list(set(imported_by)),
        }

    async def search(self, query: str, top_k: int = 10) -> List[SearchResult]:
        """Search for code chunks matching a query."""
        if self._store.size == 0:
            return []

        query_embedding = await self._get_embeddings().embed_query(query)
        return await self._store.hybrid_search(
            query=query,
            query_embedding=query_embedding,
            top_k=top_k,
            semantic_weight=0.6,
            keyword_weight=0.4,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get indexer statistics."""
        return {
            "total_vectors": self._store.size,
            "indexed_repo": self._indexed_repo,
            "last_indexed": self._last_indexed,
            "dep_graph_files": len(self._dep_graph.get("forward_imports", {})),
            "index_path": self._index_path,
        }


# Singleton
_repo_indexer: Optional[RepoIndexer] = None


def get_repo_indexer() -> RepoIndexer:
    """Get singleton RepoIndexer instance."""
    global _repo_indexer
    if _repo_indexer is None:
        _repo_indexer = RepoIndexer()
    return _repo_indexer
