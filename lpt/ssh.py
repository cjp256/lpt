import dataclasses
import logging
import shlex
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple, Union

import paramiko

logger = logging.getLogger("lpt.ssh")


@dataclasses.dataclass
class SSH:
    user: str
    host: str
    client: Optional[paramiko.SSHClient] = None
    proxy_client: Optional[paramiko.SSHClient] = None
    proxy_host: Optional[str] = None
    proxy_user: Optional[str] = None
    proxy_sock = None

    def connect(self) -> None:
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

            self.proxy_sock = transport.open_channel(
                "direct-tcpip", (self.host, 22), ("", 0)
            )

        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        logger.debug(
            "connecting to ssh server (host=%s, user=%s)", self.host, self.user
        )
        self.client.connect(
            hostname=self.host, username=self.user, sock=self.proxy_sock
        )
        logger.debug("connected to ssh server (host=%s, user=%s)", self.host, self.user)

    def fetch(self, remote_path: Path, local_path: Path, as_sudo: bool = False) -> None:
        cmd = ["cat", str(remote_path)]
        if as_sudo:
            cmd.insert(0, "sudo")

        stdout, _, _ = self.run(cmd, capture_output=True, check=True)
        assert isinstance(stdout, bytes)
        local_path.write_bytes(stdout)

    def run(
        self,
        cmd: List[str],
        *,
        capture_output: bool = False,
        check: bool = False,
        text: bool = False
    ) -> Tuple[Union[bytes, str, None], Union[bytes, str, None], int]:
        stderr_out = b""
        stdout_out = b""
        cmd_string = shlex.join(cmd)

        assert self.client
        _, stdout, stderr = self.client.exec_command(cmd_string)
        returncode = stdout.channel.recv_exit_status()

        if check and returncode != 0:
            raise subprocess.CalledProcessError(
                returncode, cmd_string, stdout_out, stderr_out
            )

        if not capture_output:
            return None, None, returncode

        while True:
            stderr_read = stderr.read()
            if stderr_read:
                stderr_out += stderr_read

            stdout_read = stdout.read()
            if stdout_read:
                stdout_out += stdout_read

            if not stderr_read and not stdout_read:
                break

        if text:
            return (
                stdout_out.decode(encoding="utf-8", errors="strict"),
                stderr_out.decode(encoding="utf-8", errors="strict"),
                returncode,
            )

        return (stdout_out, stderr_out, returncode)
