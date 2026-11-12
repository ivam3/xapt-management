"""Core APT service used by the Xapt graphical interface.

The module deliberately keeps all package-manager access in one place.  The UI
never builds a shell command and never reads APT output directly, which makes
cancellation, logging and testing much easier.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass
class Package:
    name: str
    version: str = ""
    architecture: str = ""
    status: str = ""
    summary: str = ""
    section: str = ""


@dataclass
class CommandResult:
    command: list[str]
    returncode: int
    output: str
    cancelled: bool = False


@dataclass
class StreamEvent:
    kind: str
    text: str = ""
    result: CommandResult | None = None


class AptError(RuntimeError):
    """Raised when APT cannot be started or returns an unexpected error."""


class AptService:
    """Small, thread-safe wrapper around the APT command-line tools."""

    def __init__(self, apt_binary: str | None = None) -> None:
        prefix = os.environ.get("PREFIX", "").strip()
        system_apt = os.path.join(prefix, "bin", "apt") if prefix else ""
        if apt_binary:
            self.apt = apt_binary
        elif system_apt and os.path.exists(system_apt):
            # Prefer the real APT binary over command wrappers in ~/.local/bin.
            self.apt = system_apt
        else:
            self.apt = shutil.which("apt") or "apt"
        system_apt_cache = os.path.join(prefix, "bin", "apt-cache") if prefix else ""
        self.apt_cache = (
            system_apt_cache
            if system_apt_cache and os.path.exists(system_apt_cache)
            else (shutil.which("apt-cache") or "apt-cache")
        )
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._cancel = threading.Event()

    # ------------------------------------------------------------------
    # Process helpers
    # ------------------------------------------------------------------
    def cancel(self) -> None:
        """Ask the active APT process to stop."""
        with self._lock:
            self._cancel.set()
            process = self._process
        if process and process.poll() is None:
            self._terminate_process(process)

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        """Terminate the APT process group, including child dpkg processes."""
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("DEBIAN_FRONTEND", "noninteractive")
        env.setdefault("APT_LISTCHANGES_FRONTEND", "none")
        env.setdefault("LANG", "C")
        env.setdefault("LC_ALL", "C")
        return env

    def _run(
        self,
        args: Iterable[str],
        *,
        timeout: int | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> CommandResult:
        command = [self.apt, *args]
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise AptError("Another APT operation is already running.")
            self._cancel.clear()
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._environment(),
                start_new_session=True,
            )
            self._process = process

        lines: list[str] = []
        cancelled = False
        try:
            assert process.stdout is not None
            for line in process.stdout:
                lines.append(line)
                if on_line is not None:
                    on_line(line.rstrip("\n"))
                if self._cancel.is_set():
                    cancelled = True
                    break
            if cancelled and process.poll() is None:
                self._terminate_process(process)
            try:
                returncode = process.wait(timeout=timeout or 2)
            except subprocess.TimeoutExpired:
                process.kill()
                returncode = process.wait(timeout=2)
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
        return CommandResult(command, returncode, "".join(lines), cancelled)

    def _run_capture(self, args: Iterable[str]) -> str:
        result = self._run(args)
        if result.returncode != 0:
            detail = result.output.strip() or f"exit code {result.returncode}"
            raise AptError(detail)
        return result.output

    # ------------------------------------------------------------------
    # Read-only queries
    # ------------------------------------------------------------------
    def list_packages(self) -> list[Package]:
        """Return packages known to APT with their installed/upgradable state."""
        try:
            output = self._run_capture(["list"])
        except AptError:
            # `apt list` is not available in a few minimal images; dpkg-query is.
            return self.list_installed()

        packages: dict[str, Package] = {}
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith(("Listing...", "WARNING:", "N:")):
                continue
            match = re.match(
                r"^(?P<name>[^/\s]+)/(?P<repo>\S+)\s+(?P<version>\S+)\s+(?P<arch>\S+)"
                r"(?P<rest>.*)$",
                line,
            )
            if not match:
                continue
            name = match.group("name")
            rest = match.group("rest")
            status = ""
            if "upgradable" in rest:
                status = "upgradable"
            elif "[installed" in rest:
                status = "installed"
            packages[name] = Package(
                name=name,
                version=match.group("version"),
                architecture=match.group("arch"),
                status=status,
            )
        return sorted(packages.values(), key=lambda pkg: pkg.name.lower())

    def list_installed(self) -> list[Package]:
        dpkg = shutil.which("dpkg-query")
        if not dpkg:
            return []
        command = [
            dpkg,
            "-W",
            "-f=${Package}\t${Version}\t${Architecture}\t${Status}\t${binary:Summary}\n",
        ]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=self._environment(),
            check=False,
        )
        packages = []
        for line in result.stdout.splitlines():
            parts = line.split("\t", 4)
            if len(parts) < 4 or "installed" not in parts[3]:
                continue
            packages.append(
                Package(
                    name=parts[0],
                    version=parts[1],
                    architecture=parts[2],
                    status="installed",
                    summary=parts[4] if len(parts) > 4 else "",
                )
            )
        return sorted(packages, key=lambda pkg: pkg.name.lower())

    def list_upgradable(self) -> list[Package]:
        try:
            output = self._run_capture(["list", "--upgradable"])
        except AptError:
            return [pkg for pkg in self.list_packages() if pkg.status == "upgradable"]
        packages = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith(("Listing...", "WARNING:", "N:")):
                continue
            match = re.match(r"^([^/\s]+)/(\S+)\s+(\S+)\s+(\S+)", line)
            if match:
                packages.append(
                    Package(
                        name=match.group(1),
                        version=match.group(3),
                        architecture=match.group(4),
                        status="upgradable",
                    )
                )
        return sorted(packages, key=lambda pkg: pkg.name.lower())

    def search(self, query: str) -> list[Package]:
        query = query.strip()
        if not query:
            return []
        try:
            output = self._run_capture(["search", query])
        except AptError:
            return []
        packages = []
        for line in output.splitlines():
            if " - " not in line:
                continue
            name, summary = line.split(" - ", 1)
            name = name.strip()
            if not name or " " in name:
                continue
            packages.append(Package(name=name, summary=summary.strip()))
        return packages

    def details(self, name: str) -> dict[str, str]:
        """Return the first `apt-cache show` stanza for *name*."""
        result = subprocess.run(
            [self.apt_cache, "show", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=self._environment(),
            check=False,
        )
        if result.returncode != 0:
            raise AptError(result.stdout.strip() or f"apt-cache exited with {result.returncode}")
        output = result.stdout
        stanza: dict[str, str] = {}
        current_key = ""
        for line in output.splitlines():
            if not line.strip():
                if stanza:
                    break
                continue
            if line[0].isspace():
                if current_key:
                    stanza[current_key] += "\n" + line.strip()
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                current_key = key.strip()
                stanza[current_key] = value.strip()
        return stanza

    def dependencies(self, name: str) -> str:
        detail = self.details(name)
        return detail.get("Depends", "No dependency information available.")

    def files(self, name: str) -> str:
        dpkg = shutil.which("dpkg")
        if not dpkg:
            return "dpkg is not available."
        result = subprocess.run(
            [dpkg, "-L", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=self._environment(),
            check=False,
        )
        return result.stdout.strip() or "No file list available (package is not installed)."

    # ------------------------------------------------------------------
    # Mutating operations
    # ------------------------------------------------------------------
    def update(self, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["update"], on_line=on_line)

    def upgrade(self, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["upgrade", "-y"], on_line=on_line)

    def install(self, name: str, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["install", "-y", name], on_line=on_line)

    def remove(self, name: str, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["remove", "-y", name], on_line=on_line)

    def purge(self, name: str, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["purge", "-y", name], on_line=on_line)

    def autoremove(self, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["autoremove", "-y"], on_line=on_line)

    def clean(self, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["clean"], on_line=on_line)

    def hold(self, name: str, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["hold", name], on_line=on_line)

    def unhold(self, name: str, on_line: Callable[[str], None] | None = None) -> CommandResult:
        return self._run(["unhold", name], on_line=on_line)
