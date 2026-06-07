"""
Code Evaluator Module.

Provides a secure, multi-layered sandboxed execution environment for untrusted Python code.
Defenses include static AST analysis, regex-based obfuscation detection, OS-level resource
limits, privilege dropping, and strict time/memory constraints.
"""

import ast
import logging
import os
import re
import resource
import subprocess
import tempfile
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Security Constants & Blocklists
# -----------------------------------------------------------------------------

BLOCKED_MODULES: Set[str] = {
    "os", "sys", "subprocess", "shutil", "pathlib", "platform", "sysconfig", 
    "posix", "nt", "importlib", "runpy", "code", "codeop", "compileall", 
    "py_compile", "socket", "http", "urllib", "requests", "ftplib", "smtplib", 
    "poplib", "imaplib", "xmlrpc", "asyncio", "aiohttp", "httplib2", 
    "socketserver", "ssl", "io", "tempfile", "glob", "fnmatch", "fileinput", 
    "ctypes", "gc", "inspect", "dis", "traceback", "linecache", "tokenize", 
    "symtable", "signal", "multiprocessing", "threading", "concurrent", 
    "_thread", "resource", "pickle", "shelve", "marshal", "copyreg", 
    "webbrowser", "antigravity", "turtle", "tkinter", "builtins",
}

BLOCKED_BUILTINS: Set[str] = {
    "exec", "eval", "compile", "__import__", "open", "input", "breakpoint", 
    "exit", "quit", "globals", "locals", "vars", "dir", "getattr", "setattr", 
    "delattr", "memoryview", "type",
}

BLOCKED_ATTRIBUTES: Set[str] = {
    "__subclasses__", "__bases__", "__mro__", "__globals__", "__builtins__", 
    "__code__", "__closure__", "__func__", "__self__", "__dict__", "__class__", 
    "__module__", "__loader__", "__spec__", "__import__", "__file__", 
    "__cached__", "__path__",
}

# Pre-compiled regex patterns for detecting obfuscated sandbox escape attempts
BLOCKED_PATTERNS: List[re.Pattern] = [
    re.compile(pattern, re.IGNORECASE) for pattern in (
        r"__import__\s*\(",
        r"__subclasses__\s*\(",
        r"__globals__",
        r"__builtins__",
        r"chr\s*\(\s*\d+\s*\)\s*\+\s*chr\s*\(",  # chr() concatenation chaining
        r"getattr\s*\(",
        r"\\x[0-9a-fA-F]{2}",                    # Byte string literal execution
        r"/etc/|/proc/|/sys/|/dev/",             # Sensitive file access
        r"os\.system\s*\(",
        r"os\.popen\s*\(",
        r"subprocess",
    )
]

# -----------------------------------------------------------------------------
# Static Analysis
# -----------------------------------------------------------------------------

class SecurityNodeVisitor(ast.NodeVisitor):
    """
    AST Visitor to strictly validate Python source code.
    Traverses the syntax tree to intercept blocked imports, builtins, and attributes.
    """

    def __init__(self) -> None:
        self.violations: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module_root = alias.name.split(".")[0]
            if module_root in BLOCKED_MODULES:
                self.violations.append(f"Blocked import: module '{module_root}' is restricted")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            module_root = node.module.split(".")[0]
            if module_root in BLOCKED_MODULES:
                self.violations.append(f"Blocked from-import: module '{module_root}' is restricted")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func_name = self._get_call_name(node)
        if func_name and func_name in BLOCKED_BUILTINS:
            self.violations.append(f"Blocked builtin call: '{func_name}()' is restricted")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in BLOCKED_ATTRIBUTES:
            self.violations.append(f"Blocked attribute access: '.{node.attr}' is restricted")
        self.generic_visit(node)

    @staticmethod
    def _get_call_name(node: ast.Call) -> Optional[str]:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None


class CodeValidator:
    """Validates source code through AST traversal and regex pattern matching."""

    @classmethod
    def validate(cls, code: str) -> List[str]:
        """
        Executes all static checks against the provided code.
        
        Args:
            code: The user-submitted Python source code.
            
        Returns:
            A list of string violation descriptions. Empty if safe.
        """
        violations: List[str] = []
        violations.extend(cls._ast_analysis(code))
        violations.extend(cls._regex_scan(code))
        return violations

    @staticmethod
    def _ast_analysis(code: str) -> List[str]:
        try:
            tree = ast.parse(code)
            visitor = SecurityNodeVisitor()
            visitor.visit(tree)
            return visitor.violations
        except SyntaxError:
            return []

    @staticmethod
    def _regex_scan(code: str) -> List[str]:
        violations: List[str] = []
        for pattern in BLOCKED_PATTERNS:
            match = pattern.search(code)
            if match:
                snippet = match.group(0)[:40]
                violations.append(f"Blocked pattern detected: '{snippet}'")
        return violations

# -----------------------------------------------------------------------------
# OS Sandbox Configuration
# -----------------------------------------------------------------------------

class SandboxConfig:
    """Defines operating system limits enforced via resource.setrlimit."""

    CPU_TIME_LIMIT: int = 5                  # CPU time (seconds)
    WALL_TIME_LIMIT: int = 7                 # Wall-clock timeout (seconds)
    MEMORY_LIMIT: int = 256 * 1024 * 1024    # Virtual memory (256 MB)
    FILE_SIZE_LIMIT: int = 1 * 1024 * 1024   # File write limit (1 MB)
    PROCESS_LIMIT: int = 0                   # No fork/exec (blocks network & fork bombs)
    
    DROP_TO_UID: int = 65534                 # 'nobody' user ID
    DROP_TO_GID: int = 65534                 # 'nobody' group ID

    @classmethod
    def apply_limits(cls) -> None:
        """
        Closure executed inside the forked subprocess before exec().
        Applies memory, CPU, process, and file limits, then drops privileges.
        """
        resource.setrlimit(resource.RLIMIT_CPU, (cls.CPU_TIME_LIMIT, cls.CPU_TIME_LIMIT))
        resource.setrlimit(resource.RLIMIT_AS, (cls.MEMORY_LIMIT, cls.MEMORY_LIMIT))
        resource.setrlimit(resource.RLIMIT_FSIZE, (cls.FILE_SIZE_LIMIT, cls.FILE_SIZE_LIMIT))
        resource.setrlimit(resource.RLIMIT_NPROC, (cls.PROCESS_LIMIT, cls.PROCESS_LIMIT))

        if os.getuid() == 0:
            try:
                os.setgid(cls.DROP_TO_GID)
                os.setuid(cls.DROP_TO_UID)
            except OSError:
                pass


# -----------------------------------------------------------------------------
# Execution Engine
# -----------------------------------------------------------------------------

class CodeEvaluator:
    """Orchestrates secure code evaluation against test cases."""

    @classmethod
    def evaluate(cls, code: str, test_cases: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Evaluates the user code inside a strictly sandboxed environment.
        
        Args:
            code: The Python source code to evaluate.
            test_cases: List of dictionaries containing 'input' and 'expected_output'.
            
        Returns:
            A dictionary containing the execution status, metrics, and details.
        """
        violations = CodeValidator.validate(code)
        if violations:
            return cls._build_blocked_response(violations, len(test_cases))

        results: Dict[str, Any] = {
            "status": "Accepted",
            "total_tests": len(test_cases),
            "passed_tests": 0,
            "avg_time_ms": 0.0,
            "max_memory_kb": 0,
            "details": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            os.chmod(temp_dir, 0o700)
            file_path = os.path.join(temp_dir, "solution.py")
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(code)
            os.chmod(file_path, 0o444)

            total_time, max_mem = 0.0, 0
            
            for idx, tc in enumerate(test_cases):
                tc_result = cls._run_single_test(
                    file_path, 
                    tc.get("input", ""), 
                    tc.get("expected_output", "").strip(), 
                    idx + 1
                )
                
                results["details"].append(tc_result)
                
                if tc_result["status"] == "Passed":
                    results["passed_tests"] += 1
                    total_time += tc_result.get("time_ms", 0.0)
                    max_mem = max(max_mem, tc_result.get("memory_kb", 0))
                else:
                    results["status"] = tc_result["status"]
                    break

        if results["passed_tests"] > 0:
            results["avg_time_ms"] = round(total_time / results["passed_tests"], 2)
        results["max_memory_kb"] = max_mem

        return results

    @classmethod
    def _run_single_test(cls, file_path: str, input_data: str, expected_output: str, test_number: int) -> Dict[str, Any]:
        """Executes a single test case using the OS sandbox limits."""
        cmd = ["/usr/bin/time", "-f", "%M", "python3", file_path]
        start_time = time.monotonic()

        try:
            process = subprocess.run(
                cmd,
                input=input_data.encode("utf-8"),
                capture_output=True,
                timeout=SandboxConfig.WALL_TIME_LIMIT,
                preexec_fn=SandboxConfig.apply_limits,
                cwd=tempfile.gettempdir(),
            )
            
            exec_time_ms = (time.monotonic() - start_time) * 1000
            stdout = process.stdout.decode("utf-8", errors="replace").strip()
            stderr = process.stderr.decode("utf-8", errors="replace").strip()

            mem_kb, stderr = cls._extract_memory_metric(stderr)

            if process.returncode != 0:
                return {
                    "test_case": test_number,
                    "status": "Runtime Error",
                    "error": cls._sanitize_error(stderr),
                    "time_ms": round(exec_time_ms, 2),
                    "memory_kb": mem_kb,
                }

            if stdout == expected_output:
                return {
                    "test_case": test_number,
                    "status": "Passed",
                    "time_ms": round(exec_time_ms, 2),
                    "memory_kb": mem_kb,
                }
            
            return {
                "test_case": test_number,
                "status": "Wrong Answer",
                "expected": expected_output,
                "actual": stdout,
                "time_ms": round(exec_time_ms, 2),
                "memory_kb": mem_kb,
            }

        except subprocess.TimeoutExpired:
            return {
                "test_case": test_number,
                "status": "Time Limit Exceeded",
                "error": f"Execution exceeded {SandboxConfig.WALL_TIME_LIMIT}s limit",
            }
        except MemoryError:
            return {
                "test_case": test_number,
                "status": "Memory Limit Exceeded",
                "error": f"Exceeded {SandboxConfig.MEMORY_LIMIT // (1024*1024)}MB limit",
            }
        except Exception as e:
            logger.error(f"Sandbox execution error: {e}", exc_info=True)
            return {
                "test_case": test_number,
                "status": "System Error",
                "error": "Internal evaluation error.",
            }

    @staticmethod
    def _extract_memory_metric(stderr: str) -> Tuple[int, str]:
        """Extracts the max RSS memory reported by /usr/bin/time."""
        mem_kb = 0
        stderr_lines = stderr.split("\n")
        if stderr_lines:
            try:
                mem_kb = int(stderr_lines[-1].strip())
                stderr = "\n".join(stderr_lines[:-1]).strip()
            except ValueError:
                pass
        return mem_kb, stderr

    @staticmethod
    def _sanitize_error(stderr: str) -> str:
        """Removes server-side file paths from stack traces to prevent info leaks."""
        if not stderr:
            return "Runtime error occurred"

        sanitized = re.sub(r'File ".*?/solution\.py"', 'File "solution.py"', stderr)
        sanitized = re.sub(r"/tmp/[a-zA-Z0-9_]+/", "", sanitized)
        sanitized = re.sub(r"/home/[a-zA-Z0-9_]+/[^\s\"']*", "<redacted>", sanitized)
        
        return sanitized[:1000] + "\n... (truncated)" if len(sanitized) > 1000 else sanitized

    @staticmethod
    def _build_blocked_response(violations: List[str], total_tests: int) -> Dict[str, Any]:
        """Constructs a standardized response when static analysis blocks execution."""
        return {
            "status": "Blocked",
            "reason": "Security violation detected",
            "violations": violations[:5], 
            "total_tests": total_tests,
            "passed_tests": 0,
            "avg_time_ms": 0.0,
            "max_memory_kb": 0,
            "details": [],
        }

