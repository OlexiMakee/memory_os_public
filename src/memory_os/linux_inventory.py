"""Linux/Ubuntu inventory integration for Memory OS.

The collector is deliberately read-only. It records host facts that help local
agents answer operational questions without re-scanning the whole machine.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

from memory_os.core.config import MemoryOSConfig
from memory_os.core.models import MemoryEdge, MemoryNode
from memory_os.core.repository import MemoryRepository
from memory_os.core.storage import FileSystemMemoryStorage


DOMAIN = "linux_inventory"
HOST_ID_PREFIX = "host"
EVIDENCE = ["agent_context/linux_inventory/latest.json"]


@dataclass
class LinuxFact:
    id: str
    kind: str
    summary: str
    tags: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    related: list[str] = field(default_factory=list)

    def to_node(self) -> MemoryNode:
        return MemoryNode(
            id=self.id,
            type="fact",
            summary=self.summary,
            evidence=EVIDENCE,
            status="verified",
            freshness="observed",
            trust="verified",
            domain=DOMAIN,
            related_nodes=self.related,
            tags=["linux", "ubuntu", self.kind, DOMAIN, *self.tags],
        )


@dataclass
class LinuxInventory:
    generated_at: str
    host_id: str
    facts: list[LinuxFact]
    issues: list[dict[str, Any]] = field(default_factory=list)
    commands: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "host_id": self.host_id,
            "facts": [asdict(f) for f in self.facts],
            "issues": self.issues,
            "commands": self.commands,
        }


class LinuxInventoryCollector:
    def __init__(self, root: Path | None = None, timeout: float = 5.0):
        self.root = root or Path.cwd()
        self.timeout = timeout
        self.commands: dict[str, dict[str, Any]] = {}
        self.issues: list[dict[str, Any]] = []
        self.hostname = socket.gethostname() or "localhost"
        self.host_id = f"{HOST_ID_PREFIX}:{safe_id(self.hostname)}"

    def collect(self) -> LinuxInventory:
        facts: list[LinuxFact] = [
            LinuxFact(self.host_id, "host", f"Linux host `{self.hostname}`", ["host"], {"hostname": self.hostname}),
        ]
        import sys
        if sys.platform != "linux":
            self.issues.append({"severity": "info", "message": f"linux_inventory skipped: platform is {sys.platform}"})
            return LinuxInventory(now_iso(), self.host_id, facts, self.issues, self.commands)
        facts.extend(self._collect_os())
        facts.extend(self._collect_hardware())
        facts.extend(self._collect_packages())
        facts.extend(self._collect_binaries())
        facts.extend(self._collect_services())
        facts.extend(self._collect_containers())
        facts.extend(self._collect_ollama())
        facts.extend(self._collect_gpu())
        facts.extend(self._collect_network())
        facts.extend(self._collect_repos())
        facts.extend(self._collect_models())
        facts.extend(self._collect_des())
        return LinuxInventory(now_iso(), self.host_id, facts, self.issues, self.commands)

    def _run(self, name: str, argv: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str] | None:
        if not argv or shutil.which(argv[0]) is None:
            self.commands[name] = {"argv": argv, "available": False, "returncode": None, "stdout": "", "stderr": ""}
            return None
        try:
            cp = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
            )
        except Exception as exc:
            self.commands[name] = {
                "argv": argv,
                "available": True,
                "returncode": None,
                "stdout": "",
                "stderr": str(exc),
            }
            return None
        self.commands[name] = {
            "argv": argv,
            "available": True,
            "returncode": cp.returncode,
            "stdout": cp.stdout[:20000],
            "stderr": cp.stderr[:4000],
        }
        return cp

    def _collect_os(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        os_release = parse_os_release(Path("/etc/os-release"))
        if os_release:
            pretty = os_release.get("PRETTY_NAME") or os_release.get("NAME") or "Linux"
            facts.append(LinuxFact("os:linux", "os", pretty, ["os"], os_release, [self.host_id]))
        facts.append(
            LinuxFact(
                f"kernel:{safe_id(platform.release())}",
                "kernel",
                f"Kernel {platform.release()}",
                ["kernel"],
                {"release": platform.release(), "version": platform.version(), "machine": platform.machine()},
                [self.host_id],
            )
        )
        return facts

    def _collect_hardware(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        cp = self._run("lscpu", ["lscpu"])
        if cp and cp.returncode == 0:
            data = parse_key_value_lines(cp.stdout)
            model = data.get("Model name", "unknown CPU")
            facts.append(LinuxFact(f"cpu:{safe_id(model)}", "cpu", model, ["cpu"], data, [self.host_id]))
        meminfo = parse_meminfo(Path("/proc/meminfo"))
        if meminfo:
            gib = round(meminfo.get("MemTotal", 0) / 1024 / 1024, 1)
            facts.append(LinuxFact("memory:system", "memory", f"System memory {gib} GiB", ["ram"], meminfo, [self.host_id]))
        cp = self._run("df", ["df", "-hT"])
        if cp and cp.returncode == 0:
            for row in parse_table(cp.stdout):
                mount = row.get("Mounted on")
                if not mount:
                    continue
                fs_id = f"fs:{safe_id(mount)}"
                facts.append(LinuxFact(fs_id, "filesystem", f"{mount}: {row.get('Size')} {row.get('Type')}", ["disk"], row, [self.host_id]))
        return facts

    def _collect_packages(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        cp = self._run("apt-mark showmanual", ["apt-mark", "showmanual"], timeout=8)
        if cp and cp.returncode == 0:
            packages = sorted(p.strip() for p in cp.stdout.splitlines() if p.strip())
            facts.append(
                LinuxFact(
                    "pkgset:apt:manual",
                    "package_set",
                    f"APT manual package set: {len(packages)} packages",
                    ["apt", "packages"],
                    {"manager": "apt", "packages": packages},
                    [self.host_id],
                )
            )
            for pkg in packages[:300]:
                facts.append(LinuxFact(f"pkg:apt:{safe_id(pkg)}", "package", f"APT package `{pkg}` is manually installed", ["apt"], {"name": pkg}, [self.host_id]))
        cp = self._run("dpkg query", ["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], timeout=10)
        if cp and cp.returncode == 0:
            installed = []
            for line in cp.stdout.splitlines():
                name, _, version = line.partition("\t")
                if name:
                    installed.append({"name": name, "version": version})
            facts.append(
                LinuxFact(
                    "pkgset:dpkg:installed",
                    "package_set",
                    f"DPKG installed package set: {len(installed)} packages",
                    ["dpkg", "packages"],
                    {"manager": "dpkg", "packages": installed[:2000], "truncated": len(installed) > 2000},
                    [self.host_id],
                )
            )
        return facts

    def _collect_binaries(self) -> list[LinuxFact]:
        names = [
            "codex",
            "claude",
            "agy",
            "tmux",
            "tmux-dashboard",
            "docker",
            "ollama",
            "python3",
            "uv",
            "git",
            "cargo",
            "rustc",
            "node",
            "npm",
            "nvidia-smi",
            "nvtop",
            "htop",
        ]
        facts: list[LinuxFact] = []
        for name in names:
            path = shutil.which(name)
            if not path:
                facts.append(LinuxFact(f"binary:{safe_id(name)}", "binary", f"Binary `{name}` is not in PATH", ["missing"], {"name": name, "path": None}, [self.host_id]))
                continue
            version = self._binary_version(name)
            facts.append(
                LinuxFact(
                    f"binary:{safe_id(name)}",
                    "binary",
                    f"Binary `{name}` is available at {path}",
                    ["binary"],
                    {"name": name, "path": path, "version": version},
                    [self.host_id],
                )
            )
        return facts

    def _binary_version(self, name: str) -> str:
        version_args = {
            "python3": ["python3", "--version"],
            "uv": ["uv", "--version"],
            "git": ["git", "--version"],
            "cargo": ["cargo", "--version"],
            "rustc": ["rustc", "--version"],
            "docker": ["docker", "--version"],
            "codex": ["codex", "--version"],
            "claude": ["claude", "--version"],
            "agy": ["agy", "--version"],
            "node": ["node", "--version"],
            "npm": ["npm", "--version"],
        }
        argv = version_args.get(name)
        if not argv:
            return ""
        cp = self._run(f"{name} version", argv, timeout=3)
        if not cp:
            return ""
        return (cp.stdout or cp.stderr).strip().splitlines()[0][:240] if (cp.stdout or cp.stderr).strip() else ""

    def _collect_services(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        cp = self._run("systemctl user list-units", ["systemctl", "--user", "list-units", "--type=service", "--all", "--no-pager"], timeout=5)
        if cp and cp.returncode == 0:
            for line in cp.stdout.splitlines():
                parts = line.split()
                if not parts or not parts[0].endswith(".service"):
                    continue
                name = parts[0]
                facts.append(LinuxFact(f"service:systemd:user:{safe_id(name)}", "service", f"User service `{name}`: {' '.join(parts[1:4])}", ["systemd", "user"], {"line": line}, [self.host_id]))
        for name in ("memory-os-ui.service", "memory-os-daemon.service"):
            cp = self._run(f"systemctl user status {name}", ["systemctl", "--user", "is-active", name], timeout=3)
            state = cp.stdout.strip() if cp and cp.stdout.strip() else "unknown"
            facts.append(LinuxFact(f"service:systemd:user:{safe_id(name)}", "service", f"Memory OS user service `{name}` is {state}", ["memory_os", "systemd"], {"state": state}, [self.host_id]))
        return facts

    def _collect_containers(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        cp = self._run("docker ps", ["docker", "ps", "--format", "{{json .}}"], timeout=6)
        if not cp or cp.returncode != 0:
            if cp and "permission denied" in cp.stderr.lower():
                self.issues.append({"id": "issue:docker-permission", "summary": "Docker socket is not readable by this user without elevated access."})
            return facts
        for line in cp.stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            name = item.get("Names") or item.get("Name") or item.get("ID", "container")
            facts.append(LinuxFact(f"container:docker:{safe_id(name)}", "container", f"Docker container `{name}`: {item.get('Image')} {item.get('Status')}", ["docker"], item, [self.host_id]))
        return facts

    def _collect_ollama(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        import os
        ollama_base = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
        api_url = f"{ollama_base}/api/tags"
        host_label = ollama_base.removeprefix("http://").removeprefix("https://")
        try:
            with urllib.request.urlopen(api_url, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            self.issues.append({"id": "issue:ollama-api", "summary": f"Ollama API at {host_label} is not reachable: {exc}"})
            return facts
        facts.append(LinuxFact(f"service:ollama:http:{host_label}", "service", f"Ollama API is reachable on {host_label}", ["ollama", "llm"], {"url": ollama_base}, [self.host_id]))
        for model in data.get("models", []):
            name = model.get("name") or model.get("model")
            if not name:
                continue
            details = model.get("details", {})
            summary = f"Ollama model `{name}`: {details.get('parameter_size', 'unknown size')} {details.get('quantization_level', '')}".strip()
            facts.append(LinuxFact(f"model:ollama:{safe_id(name)}", "model", summary, ["ollama", "llm"], model, [f"service:ollama:http:{host_label}"]))
        return facts

    def _collect_gpu(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        
        # 1. PCI scanning
        cp = self._run("lspci display", ["lspci"], timeout=5)
        gpus = []
        if cp and cp.returncode == 0:
            for line in cp.stdout.splitlines():
                if any(token in line.lower() for token in ("vga", "3d controller", "display controller", "nvidia")):
                    facts.append(LinuxFact(f"gpu:pci:{safe_id(line)}", "gpu", line, ["gpu", "pci"], {"lspci": line}, [self.host_id]))
                    gpus.append(line)

        # 2. Nvidia SMI parsing
        driver_version = None
        cuda_version = None
        
        cp = self._run("nvidia-smi", ["nvidia-smi"], timeout=5)
        if cp and cp.returncode == 0:
            driver_match = re.search(r"Driver Version:\s*([0-9.]+)", cp.stdout)
            if driver_match:
                driver_version = driver_match.group(1)
            cuda_match = re.search(r"CUDA Version:\s*([0-9.]+)", cp.stdout)
            if cuda_match:
                cuda_version = cuda_match.group(1)
            
            summary = f"NVIDIA GPU (Driver: {driver_version or 'unknown'}, CUDA: {cuda_version or 'unknown'})"
            facts.append(LinuxFact(
                "gpu:nvidia:smi",
                "gpu",
                summary,
                ["gpu", "nvidia", "cuda"],
                {
                    "nvidia_smi_available": True,
                    "driver_version": driver_version,
                    "cuda_version": cuda_version,
                    "raw_output": cp.stdout[:2000]
                },
                [self.host_id]
            ))
        else:
            has_nvidia_gpu = any("nvidia" in gpu.lower() for gpu in gpus)
            if has_nvidia_gpu:
                stderr = cp.stderr.strip() if cp else "nvidia-smi not available"
                self.issues.append({"id": "issue:nvidia-smi", "summary": f"nvidia-smi is not healthy: {stderr[:300]}"})
                facts.append(LinuxFact("issue:nvidia-smi", "issue", f"nvidia-smi is not healthy: {stderr[:180]}", ["gpu", "issue"], {"stderr": stderr}, [self.host_id]))

        # 3. NVCC check
        nvcc_version = None
        nvcc_cp = self._run("nvcc version", ["nvcc", "--version"], timeout=5)
        if nvcc_cp and nvcc_cp.returncode == 0:
            nvcc_match = re.search(r"release\s*([0-9.]+)", nvcc_cp.stdout)
            if nvcc_match:
                nvcc_version = nvcc_match.group(1)
            facts.append(LinuxFact(
                "gpu:cuda:nvcc",
                "gpu",
                f"CUDA Compiler (NVCC: {nvcc_version})",
                ["gpu", "cuda", "nvcc"],
                {"nvcc_version": nvcc_version, "raw_output": nvcc_cp.stdout[:1000]},
                [self.host_id]
            ))

        # 4. Vulkan check
        vulkan_active = False
        vulkan_summary = "Vulkan is not functional"
        vulkan_info_output = ""
        
        vulkaninfo_path = shutil.which("vulkaninfo")
        if vulkaninfo_path:
            vulkan_cp = self._run("vulkaninfo", [vulkaninfo_path, "--summary"], timeout=5)
            if not vulkan_cp or vulkan_cp.returncode != 0:
                vulkan_cp = self._run("vulkaninfo", [vulkaninfo_path], timeout=5)
                
            if vulkan_cp and vulkan_cp.returncode == 0:
                vulkan_active = True
                vulkan_summary = "Vulkan is active and functional"
                vulkan_info_output = vulkan_cp.stdout[:2000]
            else:
                vulkan_summary = "Vulkan driver is present but returned error"
                vulkan_info_output = vulkan_cp.stderr[:1000] if vulkan_cp else "vulkaninfo call failed"

        facts.append(LinuxFact(
            "gpu:vulkan:info",
            "gpu",
            vulkan_summary,
            ["gpu", "vulkan"],
            {
                "vulkaninfo_installed": (vulkaninfo_path is not None),
                "vulkan_active": vulkan_active,
                "detail": vulkan_summary,
                "raw_output": vulkan_info_output
            },
            [self.host_id]
        ))

        return facts

    def _collect_network(self) -> list[LinuxFact]:
        cp = self._run("ss listening", ["ss", "-lntup"], timeout=5)
        facts: list[LinuxFact] = []
        if cp and cp.returncode == 0:
            for line in cp.stdout.splitlines():
                if "LISTEN" not in line:
                    continue
                parts = line.split()
                local = next((p for p in parts if ":" in p and not p.startswith("*")), "")
                if local:
                    facts.append(LinuxFact(f"port:{safe_id(local)}", "port", f"Listening socket {local}", ["network", "port"], {"line": line, "local": local}, [self.host_id]))
        return facts

    def _collect_repos(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        roots = [Path.home() / "dev", Path.home() / "Projects"]
        for base in roots:
            if not base.exists():
                continue
            for git_dir in list(base.glob("*/*/.git")) + list(base.glob("*/.git")):
                repo = git_dir.parent
                facts.append(LinuxFact(f"repo:{safe_id(str(repo))}", "repo", f"Git repository at {repo}", ["repo", "git"], {"path": str(repo)}, [self.host_id]))
        return facts

    def _collect_models(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        base = Path.home() / "models"
        if not base.exists():
            return facts
        for file in base.rglob("*.gguf"):
            try:
                size = file.stat().st_size
            except OSError:
                size = 0
            facts.append(LinuxFact(f"model:gguf:{safe_id(file.name)}", "model", f"GGUF model file `{file.name}`", ["gguf", "llm"], {"path": str(file), "size_bytes": size}, [self.host_id]))
        return facts

    def _collect_des(self) -> list[LinuxFact]:
        facts: list[LinuxFact] = []
        # Scan xsessions and wayland-sessions for desktop environments
        de_list = []
        for path in [Path("/usr/share/xsessions"), Path("/usr/share/wayland-sessions")]:
            if path.exists() and path.is_dir():
                for entry in path.iterdir():
                    if entry.suffix == ".desktop":
                        name = entry.stem.lower()
                        if name not in de_list:
                            de_list.append(name)
        
        # Scan installed display managers
        dms = []
        for dm in ["sddm", "gdm3", "lightdm"]:
            if shutil.which(dm) or Path(f"/usr/sbin/{dm}").exists():
                dms.append(dm)
        
        # Detect active display server & default systemd target
        active_display = None
        if os.environ.get("WAYLAND_DISPLAY"):
            active_display = "wayland"
        elif os.environ.get("DISPLAY"):
            active_display = "x11"

        default_target = "unknown"
        if shutil.which("systemctl") is not None:
            try:
                res = subprocess.run(["systemctl", "get-default"], capture_output=True, text=True, timeout=1.0)
                if res.returncode == 0:
                    default_target = res.stdout.strip()
            except Exception as _e:
                import sys as _sys
                print(f'Ignored exception: {_e}', file=_sys.stderr)

        facts.append(
            LinuxFact(
                "desktop_environments:host",
                "desktop_environments",
                f"Desktop environments: {', '.join(de_list) if de_list else 'none detected'} ({active_display or 'no active display'}, boot: {default_target})",
                ["de", "wm", "desktop"],
                {
                    "installed_des": de_list,
                    "installed_dms": dms,
                    "active_display": active_display,
                    "display_env": os.environ.get("DISPLAY"),
                    "wayland_display_env": os.environ.get("WAYLAND_DISPLAY"),
                    "default_boot_target": default_target,
                },
                [self.host_id]
            )
        )
        return facts


def sync_inventory_to_memory(config: MemoryOSConfig, inventory: LinuxInventory) -> dict[str, Any]:
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    all_nodes = repo.get_local_nodes()
    stale_inventory_ids = {node.id for node in all_nodes if node.domain == DOMAIN}
    existing = {node.id: node for node in all_nodes if node.domain != DOMAIN}
    nodes = list(existing.values()) + [fact.to_node() for fact in inventory.facts]
    valid_node_ids = {node.id for node in nodes}
    repo.replace_nodes(nodes)

    existing_edges = [
        edge for edge in repo.get_edges()
        if edge.domain != DOMAIN and edge.source not in stale_inventory_ids and edge.target not in stale_inventory_ids
        and edge.source in valid_node_ids and edge.target in valid_node_ids
    ]
    edges = existing_edges + build_edges(inventory)
    repo.replace_edges(edges)

    return {"nodes_upserted": len(inventory.facts), "edges_upserted": len(edges) - len(existing_edges), "issues": len(inventory.issues)}


def build_edges(inventory: LinuxInventory) -> list[MemoryEdge]:
    edges: list[MemoryEdge] = []
    for fact in inventory.facts:
        if fact.id == inventory.host_id:
            continue
        related = fact.related or [inventory.host_id]
        for source in related:
            edges.append(
                MemoryEdge(
                    source=source,
                    target=fact.id,
                    type="contains",
                    domain=DOMAIN,
                    confidence=1.0,
                    evidence=EVIDENCE,
                    reason="Observed by Linux inventory collector.",
                )
            )
    return edges


def write_snapshot(config: MemoryOSConfig, inventory: LinuxInventory) -> Path:
    path = config.root_dir / "agent_context" / "linux_inventory" / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(inventory.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def query_inventory(config: MemoryOSConfig, query: str, limit: int = 25) -> list[dict[str, Any]]:
    q = query.lower()
    repo = MemoryRepository(FileSystemMemoryStorage(), config)
    matches = []
    for node in repo.get_nodes():
        if node.domain != DOMAIN:
            continue
        haystack = " ".join([node.id, node.summary, " ".join(node.tags)]).lower()
        if q in haystack:
            matches.append(node.to_dict())
    return matches[:limit]


def render_inventory_text(inventory: LinuxInventory) -> str:
    by_kind: dict[str, int] = {}
    for fact in inventory.facts:
        by_kind[fact.kind] = by_kind.get(fact.kind, 0) + 1
    lines = [
        f"Linux inventory for {inventory.host_id}",
        f"Generated: {inventory.generated_at}",
        f"Facts: {len(inventory.facts)}",
        "Kinds: " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())),
    ]
    if inventory.issues:
        lines.append("")
        lines.append("Issues:")
        lines.extend(f"- {item['id']}: {item['summary']}" for item in inventory.issues)
    return "\n".join(lines)


def safe_id(value: str) -> str:
    out = []
    for ch in value.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in ("-", "_", ".", ":"):
            out.append(ch)
        else:
            out.append("-")
    return "".join(out).strip("-")[:180] or "unknown"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_os_release(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        data[key] = value.strip().strip('"')
    return data


def parse_key_value_lines(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()
    return data


def parse_meminfo(path: Path) -> dict[str, int]:
    data: dict[str, int] = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        key, _, rest = line.partition(":")
        value = rest.strip().split()[0] if rest.strip() else "0"
        try:
            data[key] = int(value)
        except ValueError:
            pass
    return data


def parse_table(text: str) -> list[dict[str, str]]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    headers = lines[0].split()
    if headers[-2:] == ["Mounted", "on"]:
        headers = headers[:-2] + ["Mounted on"]
    rows = []
    for line in lines[1:]:
        parts = line.split(None, len(headers) - 1)
        if len(parts) == len(headers):
            rows.append(dict(zip(headers, parts)))
    return rows


def installed_sudo_guidance() -> list[str]:
    return [
        "To install the host Ollama CLI, run: curl -fsSL https://ollama.com/install.sh | sh",
        "To allow non-root Docker reads, run: sudo usermod -aG docker $USER, then log out and back in.",
        "To install Memory OS user services, run: bash scripts/install_systemd_user_services.sh --enable",
    ]
