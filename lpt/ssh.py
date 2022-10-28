import dataclasses
import logging
import shlex
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Union

import paramiko

logger = logging.getLogger("lpt.ssh")


class SystemReadyTimeout(Exception):
    def __init__(self, status: str) -> None:
        self.status = status


@dataclasses.dataclass
class SSH:
    user: str
    host: str
    client: Optional[paramiko.SSHClient] = None
    proxy_client: Optional[paramiko.SSHClient] = None
    proxy_host: Optional[str] = None
    proxy_user: Optional[str] = None
    proxy_sock = None
    private_key: Optional[Path] = None

    def connect(self) -> None:
        if self.private_key:
            pkey = paramiko.RSAKey.from_private_key_file(str(self.private_key))
        else:
            pkey = None

        if not self.client:
            self.client = paramiko.SSHClient()

        if self.proxy_host:
            self.proxy_client = paramiko.SSHClient()
            self.proxy_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            logger.debug(
                "connecting to proxy ssh server (proxy_host=%s, proxy_user=%s)",
                self.proxy_host,
                self.proxy_user,
            )
            self.proxy_client.connect(
                hostname=self.proxy_host, username=self.proxy_user
            )
            logger.debug(
                "connected to proxy ssh server (proxy_host=%s, proxy_user=%s)",
                self.proxy_host,
                self.proxy_user,
            )

            transport = self.proxy_client.get_transport()
            if not transport:
                raise RuntimeError("unable to open transport")

            logger.debug("opening transport channel to %s...", self.host)
            self.proxy_sock = transport.open_channel(
                "direct-tcpip", (self.host, 22), ("", 0)
            )

        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        logger.debug(
            "connecting to ssh server (host=%s, user=%s)", self.host, self.user
        )
        self.client.connect(
            hostname=self.host,
            username=self.user,
            sock=self.proxy_sock,
            pkey=pkey,
        )
        logger.debug("connected to ssh server (host=%s, user=%s)", self.host, self.user)

    def connect_with_retries(self, attempts: int = 300, sleep: float = 1.0) -> None:
        while attempts > 0:
            attempts -= 1
            try:
                self.connect()
                return
            except paramiko.ssh_exception.AuthenticationException as exc:
                logger.debug("failed auth: %r", exc)
            except paramiko.ssh_exception.NoValidConnectionsError as exc:
                logger.debug("failed to connect: %r", exc)
            except paramiko.ssh_exception.SSHException as exc:
                logger.debug("failed to connect: %r", exc)

            time.sleep(sleep)

    def fetch(self, remote_path: Path, local_path: Path) -> None:
        cmd = ["cat", str(remote_path)]

        proc = self.run(cmd, capture_output=True, check=False)
        if proc.returncode != 0:
            logger.debug("falling back to fetching %r with sudo...", remote_path)
            cmd.insert(0, "sudo")
            try:
                proc = self.run(cmd, capture_output=True, check=True)
            except subprocess.CalledProcessError as exc:
                logger.debug("failed to fetch file %r: %r", remote_path, exc)
                raise FileNotFoundError(2, "No such file or directory") from exc

        assert isinstance(proc.stdout, bytes)
        local_path.write_bytes(proc.stdout)

    def run(
        self,
        cmd: List[str],
        *,
        capture_output: bool = False,
        check: bool = False,
        text: bool = False
    ) -> subprocess.CompletedProcess:
        stderr_out: Union[bytes, str, None] = b""
        stdout_out: Union[bytes, str, None] = b""
        cmd_string = shlex.join(cmd)

        assert self.client

        logger.debug("running command: %r", cmd_string)
        stdin, stdout, stderr = self.client.exec_command(cmd_string)
        stdin.close()

        while True:
            assert isinstance(stderr_out, bytes)
            assert isinstance(stdout_out, bytes)

            logger.debug("reading stdout")
            stdout_read = stdout.read()
            if stdout_read:
                stdout_out += stdout_read
            logger.debug("read %d bytes from stdout", len(stdout_read))

            logger.debug("reading stderr")
            stderr_read = stderr.read()
            if stderr_read:
                stderr_out += stderr_read
            logger.debug("read %d bytes from stderr", len(stderr_read))

            if not stdout_read and not stderr_read:
                break

        logger.debug("output read")

        returncode = stdout.channel.recv_exit_status()
        logger.debug("command returned: %r", returncode)
        if check and returncode != 0:
            raise subprocess.CalledProcessError(
                returncode, cmd_string, stdout_out, stderr_out
            )

        if not capture_output:
            stdout_out = None
            stderr_out = None

        if text:
            assert isinstance(stderr_out, bytes)
            assert isinstance(stdout_out, bytes)
            stdout_out = stdout_out.decode(encoding="utf-8", errors="strict")
            stderr_out = stderr_out.decode(encoding="utf-8", errors="strict")

        return subprocess.CompletedProcess(cmd, returncode, stdout_out, stderr_out)

    def wait_for_system_ready(self, *, attempts: int = 300, sleep: float = 1.0) -> str:
        cmd = ["systemctl", "is-system-running"]

        logger.debug("waiting for system ready...")
        for _ in range(attempts):
            proc = self.run(cmd, capture_output=True, check=False, text=True)
            status = proc.stdout.strip()

            if status == "degraded":
                logger.warning("system ready, but degraded")
                return status

            if status == "running":
                logger.debug("system ready")
                return status

            logger.debug("system status: %s (rc=%d)", status, proc.returncode)
            time.sleep(sleep)

        logger.error("timed out waiting for system ready: %r", status)
        raise SystemReadyTimeout(status)
