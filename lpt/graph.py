import logging
import subprocess
import sys
from typing import Set, Tuple

logger = logging.getLogger("lpt.graph")


def get_afters(service: str) -> Set[str]:
    try:
        proc = subprocess.run(
            ["systemctl", "show", "-P", "After", service],
            check=True,
            capture_output=True,
            text=True,
        )
        afters = set(proc.stdout.strip().split(" "))
        try:
            afters.remove("")
        except KeyError:
            pass
        return afters
    except subprocess.CalledProcessError as error:
        print(f"failed to read service list for: {service} {error}", file=sys.stderr)
        return set()


def verify_usage(service: str) -> bool:
    try:
        subprocess.run(
            ["systemctl", "status", service], check=True, capture_output=True, text=True
        )
    except subprocess.CalledProcessError as error:
        print(f"failed to verify service list for: {service} {error}", file=sys.stderr)
        return False
    return True


def walk_dependencies(service: str) -> Set[Tuple[str, str]]:
    deps = set()
    seen = set()

    def _walk_dependencies(service: str) -> None:
        if service in seen:
            return
        seen.add(service)

        for dep in get_afters(service):
            if not verify_usage(dep):
                continue
            deps.add((service, dep))
            _walk_dependencies(dep)

    _walk_dependencies(service)
    return deps


def generate_dependency_digraph(service: str) -> str:
    deps = walk_dependencies(service)
    lines = [f'digraph "{service}" {{', "  rankdir=LR;"]
    for s1, s2 in sorted(deps):
        lines.append(f'  "{s1}"->"{s2}" [color="green"];')
    lines.append("}")
    return "\n".join(lines)
